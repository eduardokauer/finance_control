from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import bearer_auth
from app.core.database import get_db
from app.repositories.models import Transaction
from app.schemas.common import IngestRequest, IngestResponse
from app.services.analysis import run_analysis
from app.services.ingestion import ingest_bytes, ingest_file

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
        return run_analysis(db, period_start=period_start, period_end=period_end, trigger_source_file_id=source_file_id)
    return None


def _validate_ofx_upload(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(status_code=422, detail="File name is required")
    if not file.filename.lower().endswith(".ofx"):
        raise HTTPException(status_code=422, detail="Only .ofx files are accepted")


@router.post('/ingest/bank-statement', response_model=IngestResponse)
async def ingest_bank_statement(
    file: UploadFile = File(...),
    reference_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    _validate_ofx_upload(file)
    raw_content = await file.read()
    if not raw_content:
        raise HTTPException(status_code=422, detail="Empty file")
    try:
        result = ingest_bytes(
            db=db,
            source_type="bank_statement",
            file_name=file.filename,
            raw_content=raw_content,
            reference_id=reference_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result['status'] == 'processed':
        analysis_run = _run_default_analysis(db, result['source_file_id'])
        result["analysis_run_id"] = analysis_run.id if analysis_run else None
    else:
        result["analysis_run_id"] = None
    return result


@router.post('/ingest/credit-card-bill', response_model=IngestResponse)
def ingest_credit_card_bill(payload: IngestRequest, db: Session = Depends(get_db)):
    try:
        result = ingest_file(db, 'credit_card', payload.file_name, payload.file_path, payload.reference_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result['status'] == 'processed':
        analysis_run = _run_default_analysis(db, result['source_file_id'])
        result["analysis_run_id"] = analysis_run.id if analysis_run else None
    else:
        result["analysis_run_id"] = None
    return result
