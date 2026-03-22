from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.credit_card_bills import get_credit_card_invoice_detail, list_credit_card_invoices

from .helpers import render_admin

router = APIRouter()


def _status_variant(status: str) -> str:
    return {
        "imported": "ok",
        "pending_review": "warn",
        "conciliated": "ok",
        "conflict": "danger",
    }.get(status, "")


@router.get("/credit-card-invoices", response_class=HTMLResponse)
def admin_credit_card_invoice_list(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    entries = list_credit_card_invoices(db)
    return render_admin(
        request,
        "admin/credit_card_invoices.html",
        {
            "entries": entries,
            "status_variant": _status_variant,
        },
    )


@router.get("/credit-card-invoices/{invoice_id}", response_class=HTMLResponse)
def admin_credit_card_invoice_detail(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    detail = get_credit_card_invoice_detail(db, invoice_id=invoice_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return render_admin(
        request,
        "admin/credit_card_invoice_detail.html",
        {
            "detail": detail,
            "status_variant": _status_variant,
        },
    )
