from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.credit_card_bills import (
    build_credit_card_invoice_import_chart,
    CreditCardBillError,
    CreditCardBillUploadInput,
    create_credit_card,
    import_credit_card_bill,
    list_credit_cards,
    list_credit_card_invoices,
    list_recent_credit_card_invoices,
)
from app.services.admin import admin_dashboard_metrics

from .helpers import render_admin


CENT_VALUE = Decimal("0.01")
CONTROL_CENTER_URL = "/admin/operations"
ANALYSIS_HOME_URL = "/admin/analysis"


def _parse_brl_amount(raw_value: str) -> Decimal:
    value = raw_value.strip().replace("R$", "").replace(" ", "")
    if not value:
        raise CreditCardBillError("Valor total da fatura e obrigatorio.")
    try:
        return Decimal(value.replace(".", "").replace(",", ".")).quantize(CENT_VALUE, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise CreditCardBillError("Valor total da fatura e obrigatorio.") from exc


def _dashboard_context(db: Session) -> dict:
    return {
        "metrics": admin_dashboard_metrics(db),
        "credit_cards": list_credit_cards(db),
        "recent_credit_card_invoices": list_recent_credit_card_invoices(db),
    }


def _status_variant(status: str) -> str:
    return {
        "imported": "ok",
        "pending_review": "warn",
        "partially_conciliated": "warn",
        "conciliated": "ok",
        "conflict": "danger",
    }.get(status, "")


def _credit_card_invoice_page_context(db: Session) -> dict:
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
    return {
        "entries": entries,
        "chart_data": chart_payload,
        "credit_cards": list_credit_cards(db, active_only=True),
        "status_variant": _status_variant,
    }


def admin_home(_: Request, __: Session = Depends(get_db), ___: bool = Depends(require_admin_session)):
    return RedirectResponse(url=ANALYSIS_HOME_URL, status_code=303)


def admin_operations(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    return render_admin(request, "admin/dashboard.html", _dashboard_context(db))


def admin_create_credit_card(
    request: Request,
    issuer: str = Form(...),
    card_label: str = Form(...),
    card_final: str = Form(...),
    brand: str | None = Form(default=None),
    is_active: bool = Form(True),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    try:
        create_credit_card(
            db,
            issuer=issuer,
            card_label=card_label,
            card_final=card_final,
            brand=brand,
            is_active=is_active,
        )
    except CreditCardBillError as exc:
        return render_admin(
            request,
            "admin/dashboard.html",
            {**_dashboard_context(db), "credit_card_error": str(exc)},
            status_code=exc.status_code if exc.status_code >= 400 else 422,
        )
    request.session["flash"] = "Cartao salvo."
    return RedirectResponse(url=CONTROL_CENTER_URL, status_code=303)


async def admin_upload_credit_card_bill(
    request: Request,
    file: UploadFile = File(...),
    billing_month: int = Form(...),
    billing_year: int = Form(...),
    due_date: str = Form(...),
    card_id: int = Form(...),
    total_amount_brl: str = Form(...),
    closing_date: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    try:
        raw_content = await file.read()
        result = import_credit_card_bill(
            db,
            file_name=file.filename or "",
            raw_content=raw_content,
            upload_input=CreditCardBillUploadInput(
                card_id=card_id,
                billing_year=billing_year,
                billing_month=billing_month,
                due_date=date.fromisoformat(due_date),
                total_amount_brl=_parse_brl_amount(total_amount_brl),
                closing_date=date.fromisoformat(closing_date) if closing_date else None,
                notes=notes,
            ),
        )
    except ValueError:
        return render_admin(
            request,
            "admin/credit_card_invoices.html",
            {
                **_credit_card_invoice_page_context(db),
                "invoice_upload_error": "Estrutura invalida: datas do formulario estao invalidas.",
            },
            status_code=422,
        )
    except CreditCardBillError as exc:
        return render_admin(
            request,
            "admin/credit_card_invoices.html",
            {**_credit_card_invoice_page_context(db), "invoice_upload_error": str(exc)},
            status_code=exc.status_code,
        )

    request.session["flash"] = result["message"]
    return RedirectResponse(url="/admin/credit-card-invoices", status_code=303)
