from __future__ import annotations

from datetime import date

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.credit_card_bills import (
    CreditCardBillError,
    CreditCardBillUploadInput,
    create_credit_card,
    import_credit_card_bill,
    list_credit_cards,
)
from app.services.admin import admin_dashboard_metrics

from .helpers import render_admin


def _parse_brl_amount(raw_value: str) -> float:
    value = raw_value.strip().replace("R$", "").replace(" ", "")
    if not value:
        raise CreditCardBillError("Valor total da fatura e obrigatorio.")
    return float(value.replace(".", "").replace(",", "."))


def _dashboard_context(db: Session) -> dict:
    return {
        "metrics": admin_dashboard_metrics(db),
        "credit_cards": list_credit_cards(db),
    }


def admin_home(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
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
            {**_dashboard_context(db), "invoice_upload_error": str(exc)},
            status_code=exc.status_code if exc.status_code >= 400 else 422,
        )
    request.session["flash"] = "Cartao salvo."
    return RedirectResponse(url="/admin", status_code=303)


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
            payload=CreditCardBillUploadInput(
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
            "admin/dashboard.html",
            {**_dashboard_context(db), "invoice_upload_error": "Estrutura invalida: datas do formulario estao invalidas."},
            status_code=422,
        )
    except CreditCardBillError as exc:
        return render_admin(
            request,
            "admin/dashboard.html",
            {**_dashboard_context(db), "invoice_upload_error": str(exc)},
            status_code=exc.status_code,
        )

    request.session["flash"] = result["message"]
    return RedirectResponse(url="/admin", status_code=303)
