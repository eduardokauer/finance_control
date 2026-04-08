from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.repositories.models import Transaction
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
from app.services.ingestion import ingest_bytes
from app.services.admin import admin_dashboard_metrics, list_recent_source_files

from .helpers import is_htmx_request, render_admin, templates, trigger_admin_toast


CENT_VALUE = Decimal("0.01")
CONTROL_CENTER_URL = "/admin/operations"
INVOICE_MANAGE_URL = "/admin/credit-card-invoices/manage"
STATEMENT_MANAGE_URL = "/admin/conference/manage"
STATEMENT_URL = "/admin/conference"


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


def _render_dashboard_shell(
    request: Request,
    db: Session,
    *,
    credit_card_error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/partials/dashboard_shell.html",
        {
            "request": request,
            **_dashboard_context(db),
            "credit_card_error": credit_card_error,
        },
        status_code=status_code,
    )


def _get_source_file_period(db: Session, source_file_id: int):
    return db.execute(
        select(
            func.min(Transaction.transaction_date),
            func.max(Transaction.transaction_date),
        ).where(Transaction.source_file_id == source_file_id)
    ).one()


def _statement_manage_page_context(db: Session) -> dict:
    return {
        "recent_loads": list_recent_source_files(db, source_types=["bank_statement"], limit=10),
    }


def _validate_ofx_upload(file: UploadFile) -> None:
    if not file.filename:
        raise CreditCardBillError("Arquivo OFX obrigatorio.", status_code=422)
    if not file.filename.lower().endswith(".ofx"):
        raise CreditCardBillError("Somente arquivos .ofx sao aceitos.", status_code=422)


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


def _credit_card_invoice_manage_page_context(db: Session) -> dict:
    return {
        "credit_cards": list_credit_cards(db, active_only=True),
        "recent_loads": list_recent_source_files(db, source_types=["credit_card_bill"], limit=10),
    }


def _render_statement_manage_shell(
    request: Request,
    db: Session,
    *,
    statement_upload_error: str | None = None,
    statement_upload_result: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/partials/statement_manage_shell.html",
        {
            "request": request,
            **_statement_manage_page_context(db),
            "statement_upload_error": statement_upload_error,
            "statement_upload_result": statement_upload_result,
        },
        status_code=status_code,
    )


def _render_credit_card_invoice_manage_shell(
    request: Request,
    db: Session,
    *,
    invoice_upload_error: str | None = None,
    invoice_upload_result: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/partials/credit_card_invoices_manage_shell.html",
        {
            "request": request,
            **_credit_card_invoice_manage_page_context(db),
            "invoice_upload_error": invoice_upload_error,
            "invoice_upload_result": invoice_upload_result,
        },
        status_code=status_code,
    )


def admin_statements_manage(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    context = _statement_manage_page_context(db)
    if is_htmx_request(request):
        return _render_statement_manage_shell(request, db)
    return render_admin(request, "admin/statement_manage.html", context)

def admin_operations(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    context = _dashboard_context(db)
    if is_htmx_request(request):
        return _render_dashboard_shell(request, db)
    return render_admin(request, "admin/dashboard.html", context)


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
        if is_htmx_request(request):
            response = _render_dashboard_shell(
                request,
                db,
                credit_card_error=str(exc),
                status_code=exc.status_code if exc.status_code >= 400 else 422,
            )
            return trigger_admin_toast(response, "Nao foi possivel salvar o cartao.", level="danger")
        return render_admin(
            request,
            "admin/dashboard.html",
            {**_dashboard_context(db), "credit_card_error": str(exc)},
            status_code=exc.status_code if exc.status_code >= 400 else 422,
        )
    if is_htmx_request(request):
        response = _render_dashboard_shell(request, db)
        return trigger_admin_toast(response, "Cartao salvo.", level="success")
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
    return_to: str | None = Form(default=None),
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
        if is_htmx_request(request):
            response = _render_credit_card_invoice_manage_shell(
                request,
                db,
                invoice_upload_error="Estrutura invalida: datas do formulario estao invalidas.",
                status_code=422,
            )
            return trigger_admin_toast(response, "Nao foi possivel importar a fatura.", level="danger")
        return render_admin(
            request,
            "admin/credit_card_invoices_manage.html",
            {
                **_credit_card_invoice_manage_page_context(db),
                "invoice_upload_error": "Estrutura invalida: datas do formulario estao invalidas.",
                "return_to": return_to or INVOICE_MANAGE_URL,
            },
            status_code=422,
        )
    except CreditCardBillError as exc:
        if is_htmx_request(request):
            response = _render_credit_card_invoice_manage_shell(
                request,
                db,
                invoice_upload_error=str(exc),
                status_code=exc.status_code,
            )
            return trigger_admin_toast(response, "Nao foi possivel importar a fatura.", level="danger")
        return render_admin(
            request,
            "admin/credit_card_invoices_manage.html",
            {
                **_credit_card_invoice_manage_page_context(db),
                "invoice_upload_error": str(exc),
                "return_to": return_to or INVOICE_MANAGE_URL,
            },
            status_code=exc.status_code,
        )

    if is_htmx_request(request):
        response = _render_credit_card_invoice_manage_shell(
            request,
            db,
            invoice_upload_result={
                "message": result["message"],
                "invoice_id": result["invoice_id"],
                "imported_items": result["imported_items"],
            },
        )
        return trigger_admin_toast(response, result["message"], level="success")
    request.session["flash"] = result["message"]
    return RedirectResponse(url="/admin/credit-card-invoices", status_code=303)


async def admin_upload_bank_statement(
    request: Request,
    file: UploadFile = File(...),
    reference_id: str | None = Form(default=None),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    try:
        _validate_ofx_upload(file)
        raw_content = await file.read()
        if not raw_content:
            raise CreditCardBillError("Arquivo OFX vazio.", status_code=422)
        result = ingest_bytes(
            db=db,
            source_type="bank_statement",
            file_name=file.filename or "",
            raw_content=raw_content,
            reference_id=reference_id,
        )
    except CreditCardBillError as exc:
        if is_htmx_request(request):
            response = _render_statement_manage_shell(
                request,
                db,
                statement_upload_error=str(exc),
                status_code=exc.status_code,
            )
            return trigger_admin_toast(response, "Nao foi possivel importar o extrato.", level="danger")
        return render_admin(
            request,
            "admin/statement_manage.html",
            {
                **_statement_manage_page_context(db),
                "statement_upload_error": str(exc),
                "return_to": return_to or STATEMENT_MANAGE_URL,
            },
            status_code=exc.status_code,
        )
    except Exception as exc:
        if is_htmx_request(request):
            response = _render_statement_manage_shell(
                request,
                db,
                statement_upload_error=str(exc),
                status_code=422,
            )
            return trigger_admin_toast(response, "Nao foi possivel importar o extrato.", level="danger")
        return render_admin(
            request,
            "admin/statement_manage.html",
            {
                **_statement_manage_page_context(db),
                "statement_upload_error": str(exc),
                "return_to": return_to or STATEMENT_MANAGE_URL,
            },
            status_code=422,
        )

    period_start, period_end = _get_source_file_period(db, result["source_file_id"])
    if result["status"] == "processed" and period_start and period_end:
        from app.services.analysis import run_analysis

        run_analysis(
            db,
            period_start=period_start,
            period_end=period_end,
            trigger_source_file_id=result["source_file_id"],
        )

    if is_htmx_request(request):
        response = _render_statement_manage_shell(
            request,
            db,
            statement_upload_result={
                "message": result["message"],
                "source_file_id": result["source_file_id"],
                "period_start": period_start,
                "period_end": period_end,
            },
        )
        return trigger_admin_toast(response, result["message"], level="success")
    request.session["flash"] = result["message"]
    if period_start and period_end:
        return RedirectResponse(
            url=f"{STATEMENT_URL}?selection_mode=custom&period_start={period_start.isoformat()}&period_end={period_end.isoformat()}",
            status_code=303,
        )
    return RedirectResponse(url=return_to or STATEMENT_MANAGE_URL, status_code=303)
