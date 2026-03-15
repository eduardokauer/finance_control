from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import bearer_auth
from app.core.database import get_db
from app.repositories.models import AnalysisRun
from app.schemas.common import AnalysisRunRequest, LLMEmailAnalysisRequest, LLMEmailAnalysisResponse
from app.services.analysis import run_analysis
from app.services.llm_email_analysis import build_llm_email_analysis

router = APIRouter(dependencies=[Depends(bearer_auth)])


@router.post('/analysis/run')
def create_analysis(payload: AnalysisRunRequest, db: Session = Depends(get_db)):
    return run_analysis(db, payload.period_start, payload.period_end, payload.trigger_source_file_id)


@router.post("/analysis/llm-email", response_model=LLMEmailAnalysisResponse)
def create_llm_email_analysis(payload: LLMEmailAnalysisRequest, db: Session = Depends(get_db)):
    return build_llm_email_analysis(db, payload.period_start, payload.period_end, payload.trigger_source_file_id)


@router.get('/analysis/runs')
def list_analysis_runs(db: Session = Depends(get_db)):
    return db.scalars(select(AnalysisRun).order_by(AnalysisRun.created_at.desc())).all()
