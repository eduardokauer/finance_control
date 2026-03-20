from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import bearer_auth
from app.core.database import get_db
from app.repositories.models import Transaction
from app.schemas.common import IngestResponse
from app.services.ingestion import ingest_bytes

router = APIRouter(dependencies=[Depends(bearer_auth)])


def _get_source_file_period(db: Session, source_file_id: int):
    return db.execute(
        select(
            func.min(Transaction.transaction_date),
            func.max(Transaction.transaction_date),
        ).where(Transaction.source_file_id == source_file_id)
    ).one()


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
    period_start, period_end = _get_source_file_period(db, result["source_file_id"])
    result["period_start"] = period_start
    result["period_end"] = period_end
    if result['status'] == 'processed':
        from app.services.analysis import run_analysis

        analysis_run = run_analysis(
            db,
            period_start=period_start,
            period_end=period_end,
            trigger_source_file_id=result["source_file_id"],
        )
        result["analysis_run_id"] = analysis_run.id if analysis_run else None
    else:
        result["analysis_run_id"] = None
    return result
