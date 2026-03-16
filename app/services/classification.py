from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.repositories.models import CategorizationRule, Transaction, TransactionAuditLog
from app.services.categorization import categorize
from app.services.reconciliation import infer_transaction_kind, reconciliation_flags
from app.utils.normalization import normalize_description


def _match_rule(rule: CategorizationRule, normalized_description: str) -> bool:
    if rule.rule_type == "exact_normalized":
        return normalized_description == rule.pattern
    return rule.pattern in normalized_description


def find_matching_rule(
    db: Session,
    normalized_description: str,
    *,
    allowed_rule_ids: list[int] | None = None,
) -> CategorizationRule | None:
    query = (
        select(CategorizationRule)
        .where(CategorizationRule.is_active.is_(True))
        .order_by(CategorizationRule.priority.asc(), CategorizationRule.id.asc())
    )
    if allowed_rule_ids:
        query = query.where(CategorizationRule.id.in_(allowed_rule_ids))
    rules = db.scalars(query).all()
    for rule in rules:
        if _match_rule(rule, normalized_description):
            return rule
    return None


def _rule_transaction_kind(rule: CategorizationRule, amount: float) -> str:
    if rule.kind_mode == "transfer":
        return "transfer"
    return "income" if amount > 0 else "expense"


def classify_transaction(
    db: Session,
    source_type: str,
    description: str,
    amount: float,
    *,
    allowed_rule_ids: list[int] | None = None,
) -> dict:
    normalized = normalize_description(description)
    rule = find_matching_rule(db, normalized, allowed_rule_ids=allowed_rule_ids)
    inferred_kind = infer_transaction_kind(source_type, description, amount)

    if rule:
        return {
            "category": rule.category_name,
            "transaction_kind": _rule_transaction_kind(rule, amount),
            "method": "rule",
            "confidence": 1.0,
            "rule": rule.pattern,
            "rule_id": rule.id,
            "rule_kind_mode": rule.kind_mode,
            "normalized_description": normalized,
        }

    fallback = categorize(description, inferred_kind)
    return {
        "category": fallback["category"],
        "transaction_kind": inferred_kind,
        "method": fallback["method"],
        "confidence": fallback["confidence"],
        "rule": fallback["rule"],
        "rule_id": None,
        "rule_kind_mode": None,
        "normalized_description": normalized,
    }


def apply_transaction_classification(
    tx: Transaction,
    *,
    category: str,
    transaction_kind: str,
    method: str,
    confidence: float,
    applied_rule: str | None,
    rule_id: int | None,
    manual_override: bool,
    notes: str | None = None,
    should_count_in_spending: bool | None = None,
) -> None:
    flags = reconciliation_flags(transaction_kind)
    tx.category = category
    tx.transaction_kind = transaction_kind
    tx.categorization_method = method
    tx.categorization_confidence = confidence
    tx.applied_rule = applied_rule
    tx.categorization_rule_id = rule_id
    tx.manual_override = manual_override
    tx.manual_notes = notes
    tx.manual_updated_at = datetime.now(timezone.utc) if manual_override else tx.manual_updated_at
    tx.is_card_bill_payment = flags["is_card_bill_payment"]
    tx.is_adjustment = flags["is_adjustment"]
    tx.is_reconciled = flags["is_reconciled"]
    tx.should_count_in_spending = (
        should_count_in_spending if should_count_in_spending is not None else flags["should_count_in_spending"]
    )


def create_audit_log(
    db: Session,
    tx: Transaction,
    *,
    origin: str,
    previous_category: str | None,
    new_category: str | None,
    previous_transaction_kind: str | None,
    new_transaction_kind: str | None,
    applied_rule_id: int | None = None,
    notes: str | None = None,
) -> None:
    if previous_category == new_category and previous_transaction_kind == new_transaction_kind:
        return
    db.add(
        TransactionAuditLog(
            transaction_id=tx.id,
            origin=origin,
            previous_category=previous_category,
            new_category=new_category,
            previous_transaction_kind=previous_transaction_kind,
            new_transaction_kind=new_transaction_kind,
            applied_rule_id=applied_rule_id,
            notes=notes,
        )
    )
