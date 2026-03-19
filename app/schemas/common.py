from datetime import date
from typing import Any

from pydantic import BaseModel


class IngestRequest(BaseModel):
    file_name: str
    file_path: str
    reference_id: str | None = None


class IngestResponse(BaseModel):
    source_file_id: int | None = None
    invoice_id: int | None = None
    imported_items: int | None = None
    analysis_run_id: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    status: str
    message: str


class CreditCardBillIngestResponse(BaseModel):
    invoice_id: int
    imported_items: int
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


class LLMEmailAnalysisRequest(BaseModel):
    period_start: date
    period_end: date
    trigger_source_file_id: int | None = None


class LLMEmailAnalysisResponse(BaseModel):
    summary_html: str
    llm_payload: dict[str, Any]


class TransactionReclassifyFilters(BaseModel):
    transaction_ids: list[int] | None = None
    period_start: date | None = None
    period_end: date | None = None
    source_type: str | None = None
    source_file_id: int | None = None
    current_category: str | None = None
    description_contains: str | None = None


class TransactionReclassifyRequest(BaseModel):
    filters: TransactionReclassifyFilters
    category: str | None = None
    transaction_kind: str | None = None
    should_count_in_spending: bool | None = None
    notes: str | None = None


class TransactionReclassifyResponse(BaseModel):
    updated_count: int
    transaction_ids: list[int]
