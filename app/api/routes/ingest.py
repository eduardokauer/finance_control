from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import bearer_auth
from app.core.database import get_db
from app.repositories.models import Transaction
from app.schemas.common import IngestRequest, IngestResponse
from app.services.analysis import run_analysis
from app.services.ingestion import ingest_file

router = APIRouter(dependencies=[Depends(bearer_auth)])


def _run_default_analysis(db: Session, source_file_id: int):
    period = db.execute(
        select(
            func.min(Transaction.transaction_date),
            func.max(Transaction.transaction_date),
        ).where(Transaction.source_file_id == source_file_id)
    ).one()
    period_start, period_end = period
    if period_start and period_end:
        run_analysis(db, period_start=period_start, period_end=period_end, trigger_source_file_id=source_file_id)


@router.post('/ingest/bank-statement', response_model=IngestResponse)
def ingest_bank_statement(payload: IngestRequest, db: Session = Depends(get_db)):
    try:
        result = ingest_file(db, 'bank_statement', payload.file_name, payload.file_path, payload.reference_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result['status'] == 'processed':
        _run_default_analysis(db, result['source_file_id'])
    return result


@router.post('/ingest/credit-card-bill', response_model=IngestResponse)
def ingest_credit_card_bill(payload: IngestRequest, db: Session = Depends(get_db)):
    try:
        result = ingest_file(db, 'credit_card', payload.file_name, payload.file_path, payload.reference_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result['status'] == 'processed':
        _run_default_analysis(db, result['source_file_id'])
    return result
