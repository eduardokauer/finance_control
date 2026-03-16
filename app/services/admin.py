from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.repositories.models import AnalysisRun, CategorizationRule, Category, Transaction, TransactionAuditLog
from app.services.analysis import run_analysis
from app.services.classification import apply_transaction_classification, classify_transaction, create_audit_log
from app.utils.normalization import normalize_description

UNCATEGORIZED_NAMES = ("NÃƒÂ£o Categorizado", "NÃ£o Categorizado", "Não Categorizado")


@dataclass
class TransactionFilters:
    period_start: date
    period_end: date
    category: str | None = None
    description: str | None = None
    uncategorized_only: bool = False
    transaction_kind: str | None = None
    sort: str = "recent"


def default_closed_month(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    return previous_month_start, previous_month_end


def latest_closed_month_with_transactions(db: Session, today: date | None = None) -> tuple[date, date] | None:
    today = today or date.today()
    current_month_start = today.replace(day=1)
    latest_tx_date = db.scalar(
        select(func.max(Transaction.transaction_date)).where(Transaction.transaction_date < current_month_start)
    )
    if latest_tx_date is None:
        return None
    start = latest_tx_date.replace(day=1)
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    return start, next_month - timedelta(days=1)


def build_transaction_filters(
    *,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
    category: str | None,
    description: str | None,
    uncategorized_only: bool,
    transaction_kind: str | None,
    sort: str | None,
    default_period: tuple[date, date] | None = None,
) -> TransactionFilters:
    if month:
        year, month_value = [int(part) for part in month.split("-", 1)]
        start = date(year, month_value, 1)
        next_month = date(year + (1 if month_value == 12 else 0), 1 if month_value == 12 else month_value + 1, 1)
        end = next_month - timedelta(days=1)
    elif period_start and period_end:
        start, end = period_start, period_end
    else:
        start, end = default_period or default_closed_month()

    return TransactionFilters(
        period_start=start,
        period_end=end,
        category=category or None,
        description=description.strip() if description else None,
        uncategorized_only=uncategorized_only,
        transaction_kind=transaction_kind or None,
        sort=sort or "recent",
    )


def _base_transactions_query(filters: TransactionFilters) -> Select:
    query = select(Transaction).where(
        Transaction.transaction_date >= filters.period_start,
        Transaction.transaction_date <= filters.period_end,
    )
    if filters.category:
        query = query.where(Transaction.category == filters.category)
    if filters.description:
        query = query.where(Transaction.description_normalized.contains(normalize_description(filters.description)))
    if filters.uncategorized_only:
        query = query.where(or_(*(Transaction.category == name for name in UNCATEGORIZED_NAMES)))
    if filters.transaction_kind:
        query = query.where(Transaction.transaction_kind == filters.transaction_kind)
    return query


def list_transactions_for_admin(db: Session, filters: TransactionFilters, *, limit: int, offset: int) -> tuple[list[Transaction], int]:
    query = _base_transactions_query(filters)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    if filters.sort == "amount_desc":
        query = query.order_by(func.abs(Transaction.amount).desc(), Transaction.transaction_date.desc(), Transaction.id.desc())
    else:
        query = query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc())

    items = db.scalars(query.limit(limit).offset(offset)).all()
    return items, int(total)


def is_uncategorized_category(category: str | None) -> bool:
    return category in UNCATEGORIZED_NAMES


def resolve_reapply_classification(
    tx: Transaction,
    result: dict,
    *,
    allow_degrade_to_uncategorized: bool,
) -> dict:
    target_category = result["category"]
    degraded_to_uncategorized = (
        not allow_degrade_to_uncategorized
        and result["rule_id"] is None
        and is_uncategorized_category(target_category)
        and not is_uncategorized_category(tx.category)
    )

    if degraded_to_uncategorized:
        return {
            **result,
            "category": tx.category,
            "transaction_kind": tx.transaction_kind,
            "preserved_current": True,
            "degrade_blocked": True,
        }

    return {
        **result,
        "category": target_category,
        "transaction_kind": result["transaction_kind"],
        "preserved_current": False,
        "degrade_blocked": False,
    }


def admin_dashboard_metrics(db: Session) -> dict:
    period_start, period_end = default_closed_month()
    uncategorized_query = select(Transaction).where(
        Transaction.transaction_date >= period_start,
        Transaction.transaction_date <= period_end,
        or_(*(Transaction.category == name for name in UNCATEGORIZED_NAMES)),
    )
    uncategorized_count = db.scalar(select(func.count()).select_from(uncategorized_query.subquery())) or 0
    uncategorized_total = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.transaction_date >= period_start,
        Transaction.transaction_date <= period_end,
        or_(*(Transaction.category == name for name in UNCATEGORIZED_NAMES)),
    )) or 0
    latest_changes = db.scalars(
        select(TransactionAuditLog).order_by(TransactionAuditLog.created_at.desc(), TransactionAuditLog.id.desc()).limit(5)
    ).all()
    latest_rules = db.scalars(
        select(CategorizationRule)
        .where(CategorizationRule.is_active.is_(True))
        .order_by(CategorizationRule.updated_at.desc(), CategorizationRule.id.desc())
        .limit(5)
    ).all()
    return {
        "period_start": period_start,
        "period_end": period_end,
        "uncategorized_count": int(uncategorized_count),
        "uncategorized_total": float(uncategorized_total),
        "latest_changes": latest_changes,
        "latest_rules": latest_rules,
    }


def list_categories(db: Session) -> list[Category]:
    return db.scalars(select(Category).order_by(Category.is_active.desc(), Category.name.asc())).all()


def list_rules(db: Session) -> list[CategorizationRule]:
    return db.scalars(
        select(CategorizationRule).order_by(CategorizationRule.is_active.desc(), CategorizationRule.priority.asc(), CategorizationRule.id.asc())
    ).all()


def list_active_rules(db: Session) -> list[CategorizationRule]:
    return db.scalars(
        select(CategorizationRule)
        .where(CategorizationRule.is_active.is_(True))
        .order_by(CategorizationRule.priority.asc(), CategorizationRule.id.asc())
    ).all()


def kind_mode_from_transaction_kind(transaction_kind: str) -> str:
    return "transfer" if transaction_kind == "transfer" else "flow"


def upsert_category(db: Session, *, category_id: int | None, name: str, transaction_kind: str, is_active: bool = True) -> Category:
    category = db.get(Category, category_id) if category_id else None
    if category is None:
        category = Category(name=name, transaction_kind=transaction_kind, is_active=is_active)
        db.add(category)
    else:
        category.name = name
        category.transaction_kind = transaction_kind
        category.is_active = is_active
    db.commit()
    db.refresh(category)
    return category


def upsert_rule(
    db: Session,
    *,
    rule_id: int | None,
    pattern: str,
    rule_type: str,
    category_name: str,
    kind_mode: str,
    priority: int,
    is_active: bool = True,
) -> CategorizationRule:
    normalized_pattern = normalize_description(pattern)
    rule = db.get(CategorizationRule, rule_id) if rule_id else None
    if rule is None:
        rule = CategorizationRule(
            pattern=normalized_pattern,
            rule_type=rule_type,
            category_name=category_name,
            kind_mode=kind_mode,
            priority=priority,
            is_active=is_active,
        )
        db.add(rule)
    else:
        rule.pattern = normalized_pattern
        rule.rule_type = rule_type
        rule.category_name = category_name
        rule.kind_mode = kind_mode
        rule.priority = priority
        rule.is_active = is_active
    db.commit()
    db.refresh(rule)
    return rule


def reclassify_transactions_manual(
    db: Session,
    txs: Sequence[Transaction],
    *,
    category: str,
    transaction_kind: str,
    notes: str | None,
    origin: str,
    should_count_in_spending: bool | None = None,
) -> int:
    updated = 0
    for tx in txs:
        previous_category = tx.category
        previous_kind = tx.transaction_kind
        apply_transaction_classification(
            tx,
            category=category,
            transaction_kind=transaction_kind,
            method="manual",
            confidence=1.0,
            applied_rule="manual_override",
            rule_id=tx.categorization_rule_id,
            manual_override=True,
            notes=notes,
            should_count_in_spending=should_count_in_spending,
        )
        create_audit_log(
            db,
            tx,
            origin=origin,
            previous_category=previous_category,
            new_category=tx.category,
            previous_transaction_kind=previous_kind,
            new_transaction_kind=tx.transaction_kind,
            applied_rule_id=tx.categorization_rule_id,
            notes=notes,
        )
        updated += 1
    db.commit()
    return updated


def preview_similar_transactions(db: Session, tx: Transaction, *, match_mode: str, pattern: str) -> list[Transaction]:
    normalized_pattern = normalize_description(pattern)
    query = select(Transaction).where(Transaction.id != tx.id)
    if match_mode == "exact_normalized":
        query = query.where(Transaction.description_normalized == normalized_pattern)
    else:
        query = query.where(Transaction.description_normalized.contains(normalize_description(pattern)))
    return db.scalars(query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).limit(20)).all()


def preview_bulk_reclassification(
    db: Session,
    *,
    transaction_ids: list[int] | None = None,
    match_mode: str | None = None,
    pattern: str | None = None,
) -> list[Transaction]:
    query = select(Transaction)
    if transaction_ids:
        query = query.where(Transaction.id.in_(transaction_ids))
    elif pattern:
        normalized_pattern = normalize_description(pattern)
        if match_mode == "exact_normalized":
            query = query.where(Transaction.description_normalized == normalized_pattern)
        else:
            query = query.where(Transaction.description_normalized.contains(normalized_pattern))
    else:
        return []
    return db.scalars(query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).limit(50)).all()


def reapply_rules_for_period(
    db: Session,
    *,
    period_start: date | None,
    period_end: date | None,
    include_manual: bool,
    allow_degrade_to_uncategorized: bool = False,
    allowed_rule_ids: list[int] | None = None,
    selected_transaction_ids: list[int] | None = None,
) -> dict:
    query = select(Transaction)
    if period_start:
        query = query.where(Transaction.transaction_date >= period_start)
    if period_end:
        query = query.where(Transaction.transaction_date <= period_end)
    if not include_manual:
        query = query.where(Transaction.manual_override.is_(False))
    if selected_transaction_ids is not None:
        query = query.where(Transaction.id.in_(selected_transaction_ids))
    txs = db.scalars(query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc())).all()

    updated = 0
    for tx in txs:
        previous_category = tx.category
        previous_kind = tx.transaction_kind
        result = classify_transaction(
            db,
            tx.source_type,
            tx.description_raw,
            tx.amount,
            allowed_rule_ids=allowed_rule_ids,
        )
        resolved = resolve_reapply_classification(
            tx,
            result,
            allow_degrade_to_uncategorized=allow_degrade_to_uncategorized,
        )
        apply_transaction_classification(
            tx,
            category=resolved["category"],
            transaction_kind=resolved["transaction_kind"],
            method=resolved["method"],
            confidence=resolved["confidence"],
            applied_rule=resolved["rule"],
            rule_id=resolved["rule_id"],
            manual_override=tx.manual_override if include_manual else False,
            notes=tx.manual_notes if include_manual else None,
        )
        create_audit_log(
            db,
            tx,
            origin="admin_reapply",
            previous_category=previous_category,
            new_category=tx.category,
            previous_transaction_kind=previous_kind,
            new_transaction_kind=tx.transaction_kind,
            applied_rule_id=resolved["rule_id"],
            notes="ReaplicaÃƒÂ§ÃƒÂ£o administrativa de regras",
        )
        if previous_category != tx.category or previous_kind != tx.transaction_kind:
            updated += 1

    db.commit()
    return {"updated_count": updated, "checked_count": len(txs)}


def preview_reapply_rules(
    db: Session,
    *,
    period_start: date | None,
    period_end: date | None,
    include_manual: bool,
    allow_degrade_to_uncategorized: bool = False,
    allowed_rule_ids: list[int] | None = None,
) -> dict:
    query = select(Transaction)
    if period_start:
        query = query.where(Transaction.transaction_date >= period_start)
    if period_end:
        query = query.where(Transaction.transaction_date <= period_end)
    if not include_manual:
        query = query.where(Transaction.manual_override.is_(False))
    txs = db.scalars(query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc())).all()
    changed_items = []
    for tx in txs:
        result = classify_transaction(
            db,
            tx.source_type,
            tx.description_raw,
            tx.amount,
            allowed_rule_ids=allowed_rule_ids,
        )
        resolved = resolve_reapply_classification(
            tx,
            result,
            allow_degrade_to_uncategorized=allow_degrade_to_uncategorized,
        )
        will_change = tx.category != resolved["category"] or tx.transaction_kind != resolved["transaction_kind"]
        if not will_change:
            continue
        changed_items.append(
            {
                "transaction": tx,
                "from_category": tx.category,
                "to_category": resolved["category"],
                "from_kind": tx.transaction_kind,
                "to_kind": resolved["transaction_kind"],
                "rule_id": resolved["rule_id"],
                "rule_pattern": resolved["rule"],
                "degrade_blocked": resolved["degrade_blocked"],
                "will_change": will_change,
            }
        )
    return {
        "total_evaluated": len(txs),
        "total_changed": len(changed_items),
        "examples": changed_items,
    }


def run_analysis_for_period(db: Session, *, period_start: date, period_end: date) -> AnalysisRun:
    return run_analysis(db, period_start=period_start, period_end=period_end, trigger_source_file_id=None)


def build_pagination(total: int, *, limit: int, offset: int) -> dict:
    page = offset // limit + 1 if limit else 1
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "page": page,
        "pages": ceil(total / limit) if limit else 1,
        "has_more": offset + limit < total,
        "next_offset": offset + limit,
    }

