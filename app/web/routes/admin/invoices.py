from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.credit_card_bills import (
    build_credit_card_invoice_import_chart,
    CreditCardInvoiceConciliationError,
    get_credit_card_invoice_detail,
    list_credit_card_invoices,
    reconcile_credit_card_invoice_bank_payments,
    unlink_credit_card_invoice_bank_payment,
)

from .helpers import render_admin

router = APIRouter()


def _status_variant(status: str) -> str:
    return {
        "imported": "ok",
        "pending_review": "warn",
        "partially_conciliated": "warn",
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
    chart_data = build_credit_card_invoice_import_chart(db)
    chart_payload = (
        {
            "month_labels": chart_data.month_labels,
            "datasets": [
                {
                    "year": dataset.year,
                    "color": dataset.color,
                    "values": dataset.values,
                }
                for dataset in chart_data.datasets
            ],
        }
        if chart_data
        else None
    )
    return render_admin(
        request,
        "admin/credit_card_invoices.html",
        {
            "entries": entries,
            "chart_data": chart_payload,
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


@router.post("/credit-card-invoices/{invoice_id}/conciliation")
def admin_credit_card_invoice_reconcile(
    invoice_id: int,
    request: Request,
    selected_transaction_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    try:
        reconcile_credit_card_invoice_bank_payments(
            db,
            invoice_id=invoice_id,
            bank_transaction_ids=selected_transaction_ids,
        )
    except CreditCardInvoiceConciliationError as exc:
        detail = get_credit_card_invoice_detail(db, invoice_id=invoice_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Invoice not found") from exc
        return render_admin(
            request,
            "admin/credit_card_invoice_detail.html",
            {
                "detail": detail,
                "status_variant": _status_variant,
                "conciliation_error": str(exc),
            },
            status_code=exc.status_code,
        )

    request.session["flash"] = "Conciliacao atualizada."
    return RedirectResponse(url=f"/admin/credit-card-invoices/{invoice_id}", status_code=303)


@router.post("/credit-card-invoices/{invoice_id}/conciliation/items/{conciliation_item_id}/unlink")
def admin_credit_card_invoice_unlink_payment(
    invoice_id: int,
    conciliation_item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    try:
        unlink_credit_card_invoice_bank_payment(
            db,
            invoice_id=invoice_id,
            conciliation_item_id=conciliation_item_id,
        )
    except CreditCardInvoiceConciliationError as exc:
        detail = get_credit_card_invoice_detail(db, invoice_id=invoice_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Invoice not found") from exc
        return render_admin(
            request,
            "admin/credit_card_invoice_detail.html",
            {
                "detail": detail,
                "status_variant": _status_variant,
                "conciliation_error": str(exc),
            },
            status_code=exc.status_code,
        )

    request.session["flash"] = "Vinculo de pagamento removido."
    return RedirectResponse(url=f"/admin/credit-card-invoices/{invoice_id}", status_code=303)
