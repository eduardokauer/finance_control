from datetime import datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.repositories.models import Transaction
from app.schemas.common import TransactionReclassifyRequest
from app.services.reconciliation import reconciliation_flags


def _apply_filters(query: Select, payload: TransactionReclassifyRequest) -> Select:
    filters = payload.filters
    if filters.transaction_ids:
        query = query.where(Transaction.id.in_(filters.transaction_ids))
    if filters.period_start:
        query = query.where(Transaction.transaction_date >= filters.period_start)
    if filters.period_end:
        query = query.where(Transaction.transaction_date <= filters.period_end)
    if filters.source_type:
        query = query.where(Transaction.source_type == filters.source_type)
    if filters.source_file_id:
        query = query.where(Transaction.source_file_id == filters.source_file_id)
    if filters.current_category:
        query = query.where(Transaction.category == filters.current_category)
    if filters.description_contains:
        query = query.where(Transaction.description_normalized.contains(filters.description_contains.lower()))
    return query


def reclassify_transactions(db: Session, payload: TransactionReclassifyRequest) -> dict:
    if not payload.filters.transaction_ids and not any(
        [
            payload.filters.period_start,
            payload.filters.period_end,
            payload.filters.source_type,
            payload.filters.source_file_id,
            payload.filters.current_category,
            payload.filters.description_contains,
        ]
    ):
        raise ValueError("At least one selector must be provided")

    if payload.category is None and payload.transaction_kind is None and payload.should_count_in_spending is None:
        raise ValueError("At least one reclassification field must be provided")

    query = _apply_filters(select(Transaction).order_by(Transaction.id), payload)
    txs = db.scalars(query).all()
    if not txs:
        return {"updated_count": 0, "transaction_ids": []}

    for tx in txs:
        kind = payload.transaction_kind or tx.transaction_kind
        flags = reconciliation_flags(kind)
        tx.transaction_kind = kind
        if payload.category is not None:
            tx.category = payload.category
        tx.categorization_method = "manual"
        tx.categorization_confidence = 1.0
        tx.applied_rule = "manual_override"
        tx.manual_override = True
        tx.manual_notes = payload.notes
        tx.manual_updated_at = datetime.now(timezone.utc)
        tx.is_card_bill_payment = flags["is_card_bill_payment"]
        tx.is_adjustment = flags["is_adjustment"]
        tx.is_reconciled = flags["is_reconciled"]
        tx.should_count_in_spending = (
            payload.should_count_in_spending
            if payload.should_count_in_spending is not None
            else flags["should_count_in_spending"]
        )

    db.commit()
    return {"updated_count": len(txs), "transaction_ids": [tx.id for tx in txs]}
