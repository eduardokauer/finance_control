from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import bearer_auth
from app.core.database import get_db
from app.schemas.common import CreditCardBillIngestResponse
from app.services.credit_card_bills import CreditCardBillError, CreditCardBillUploadInput, import_credit_card_bill

router = APIRouter(dependencies=[Depends(bearer_auth)])


def _validate_bill_upload(file: UploadFile, raw_content: bytes) -> None:
    if not file.filename:
        raise HTTPException(status_code=422, detail="File name is required")
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="Only .csv files are accepted")
    if not raw_content:
        raise HTTPException(status_code=422, detail="Empty file")


@router.post("/ingest/credit-card-bill", response_model=CreditCardBillIngestResponse)
async def ingest_credit_card_bill(
    file: UploadFile = File(...),
    billing_month: int = Form(...),
    billing_year: int = Form(...),
    due_date: date = Form(...),
    card_id: int = Form(...),
    total_amount_brl: Decimal = Form(...),
    closing_date: date | None = Form(default=None),
    notes: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    raw_content = await file.read()
    _validate_bill_upload(file, raw_content)

    try:
        return import_credit_card_bill(
            db=db,
            file_name=file.filename,
            raw_content=raw_content,
            upload_input=CreditCardBillUploadInput(
                card_id=card_id,
                billing_year=billing_year,
                billing_month=billing_month,
                due_date=due_date,
                total_amount_brl=total_amount_brl,
                closing_date=closing_date,
                notes=notes,
            ),
        )
    except CreditCardBillError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
