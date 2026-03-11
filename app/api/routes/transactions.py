from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import bearer_auth
from app.core.database import get_db
from app.repositories.models import Transaction

router = APIRouter(dependencies=[Depends(bearer_auth)])


@router.get('/transactions')
def list_transactions(
    period_start: date,
    period_end: date,
    source_type: str | None = None,
    category_name: str | None = None,
    should_count_in_spending: bool | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    query = select(Transaction).where(Transaction.transaction_date >= period_start, Transaction.transaction_date <= period_end)
    if source_type:
        query = query.where(Transaction.source_type == source_type)
    if category_name:
        query = query.where(Transaction.category == category_name)
    if should_count_in_spending is not None:
        query = query.where(Transaction.should_count_in_spending == should_count_in_spending)

    txs = db.scalars(query.order_by(Transaction.transaction_date.desc()).limit(limit).offset(offset)).all()
    return txs
