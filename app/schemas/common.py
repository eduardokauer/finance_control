from datetime import date

from pydantic import BaseModel


class IngestRequest(BaseModel):
    file_name: str
    file_path: str
    reference_id: str | None = None


class IngestResponse(BaseModel):
    source_file_id: int | None = None
    status: str
    message: str


class TransactionOut(BaseModel):
    id: int
    transaction_date: date
    source_type: str
    category: str
    amount: float
    should_count_in_spending: bool


class AnalysisRunRequest(BaseModel):
    period_start: date
    period_end: date
    trigger_source_file_id: int | None = None


class AnalysisRunOut(BaseModel):
    id: int
    period_start: date
    period_end: date
    status: str
    html_output: str
