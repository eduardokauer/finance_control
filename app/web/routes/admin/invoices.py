from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import list_recent_source_files, resolve_analysis_period
from app.services.analysis import build_analysis_snapshot
from app.services.credit_card_bills import (
    build_credit_card_invoice_import_chart,
    CreditCardInvoiceCategoryEditError,
    CreditCardInvoiceConciliationError,
    apply_manual_credit_card_invoice_item_category_change,
    apply_manual_credit_card_invoice_item_category_rule_application,
    get_credit_card_invoice_item_category_editor,
    get_credit_card_invoice_detail,
    list_credit_cards,
    list_credit_card_invoices,
    preview_manual_credit_card_invoice_item_category_change,
    preview_manual_credit_card_invoice_item_category_rule_application,
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


def _render_invoice_item_category_editor(
    *,
    invoice_id: int,
    item_id: int,
    request: Request,
    db: Session,
    selected_category: str | None = None,
    selected_apply_mode: str = "single",
    selected_rule_pattern: str | None = None,
    selected_rule_match_mode: str = "exact_normalized",
    return_to: str | None = None,
    single_preview=None,
    base_preview=None,
    form_error: str | None = None,
    status_code: int = 200,
):
    editor = get_credit_card_invoice_item_category_editor(db, invoice_id=invoice_id, item_id=item_id)
    if editor is None:
        raise HTTPException(status_code=404, detail="Invoice item not found")
    resolved_category = selected_category or editor.item.category
    if resolved_category is None and editor.available_categories:
        resolved_category = editor.available_categories[0].name
    resolved_rule_pattern = selected_rule_pattern or editor.item.description_normalized or editor.item.description_raw
    return render_admin(
        request,
        "admin/credit_card_invoice_item_category_edit.html",
        {
            "editor": editor,
            "selected_category": resolved_category,
            "selected_apply_mode": selected_apply_mode,
            "selected_rule_pattern": resolved_rule_pattern,
            "selected_rule_match_mode": selected_rule_match_mode,
            "return_to": return_to,
            "single_preview": single_preview,
            "base_preview": base_preview,
            "form_error": form_error,
            "status_variant": _status_variant,
        },
        status_code=status_code,
    )


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
    period_start, period_end = resolve_analysis_period(
        db,
        month=None,
        period_start=None,
        period_end=None,
    )
    analysis_snapshot = build_analysis_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
    )
    return render_admin(
        request,
        "admin/credit_card_invoices.html",
        {
            "entries": entries,
            "chart_data": chart_payload,
            "invoice_category_chart": analysis_snapshot["charts"]["invoice_categories"],
            "invoice_period_label": analysis_snapshot["period"]["month_reference_label"],
            "status_variant": _status_variant,
        },
    )


def _credit_card_invoice_manage_context(db: Session) -> dict:
    return {
        "credit_cards": list_credit_cards(db, active_only=True),
        "recent_loads": list_recent_source_files(db, source_types=["credit_card_bill"], limit=10),
    }


@router.get("/credit-card-invoices/manage", response_class=HTMLResponse)
def admin_credit_card_invoice_manage(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/credit_card_invoices_manage.html",
        _credit_card_invoice_manage_context(db),
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


@router.get("/credit-card-invoices/{invoice_id}/items/{item_id}/category", response_class=HTMLResponse)
def admin_credit_card_invoice_item_category_edit(
    invoice_id: int,
    item_id: int,
    request: Request,
    return_to: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return _render_invoice_item_category_editor(
        invoice_id=invoice_id,
        item_id=item_id,
        request=request,
        db=db,
        return_to=return_to,
    )


@router.post("/credit-card-invoices/{invoice_id}/items/{item_id}/category/preview", response_class=HTMLResponse)
def admin_credit_card_invoice_item_category_preview(
    invoice_id: int,
    item_id: int,
    request: Request,
    category: str = Form(...),
    apply_mode: str = Form("single"),
    rule_pattern: str | None = Form(default=None),
    rule_match_mode: str = Form("exact_normalized"),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    try:
        if apply_mode == "base":
            base_preview = preview_manual_credit_card_invoice_item_category_rule_application(
                db,
                invoice_id=invoice_id,
                item_id=item_id,
                category_name=category,
                rule_pattern=rule_pattern or "",
                rule_type=rule_match_mode,
            )
            single_preview = None
        else:
            single_preview = preview_manual_credit_card_invoice_item_category_change(
                db,
                invoice_id=invoice_id,
                item_id=item_id,
                category_name=category,
            )
            base_preview = None
    except CreditCardInvoiceCategoryEditError as exc:
        return _render_invoice_item_category_editor(
            invoice_id=invoice_id,
            item_id=item_id,
            request=request,
            db=db,
            selected_category=category,
            selected_apply_mode=apply_mode,
            selected_rule_pattern=rule_pattern,
            selected_rule_match_mode=rule_match_mode,
            return_to=return_to,
            form_error=str(exc),
            status_code=exc.status_code,
        )
    return _render_invoice_item_category_editor(
        invoice_id=invoice_id,
        item_id=item_id,
        request=request,
        db=db,
        selected_category=category,
        selected_apply_mode=apply_mode,
        selected_rule_pattern=rule_pattern,
        selected_rule_match_mode=rule_match_mode,
        return_to=return_to,
        single_preview=single_preview,
        base_preview=base_preview,
    )


@router.post("/credit-card-invoices/{invoice_id}/items/{item_id}/category/apply")
def admin_credit_card_invoice_item_category_apply(
    invoice_id: int,
    item_id: int,
    request: Request,
    category: str = Form(...),
    apply_mode: str = Form("single"),
    rule_pattern: str | None = Form(default=None),
    rule_match_mode: str = Form("exact_normalized"),
    return_to: str | None = Form(default=None),
    confirm_apply: bool = Form(False),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    if not confirm_apply:
        return _render_invoice_item_category_editor(
            invoice_id=invoice_id,
            item_id=item_id,
            request=request,
            db=db,
            selected_category=category,
            selected_apply_mode=apply_mode,
            selected_rule_pattern=rule_pattern,
            selected_rule_match_mode=rule_match_mode,
            form_error="Confirme explicitamente a alteração antes de salvar.",
            status_code=422,
        )
    try:
        if apply_mode == "base":
            result = apply_manual_credit_card_invoice_item_category_rule_application(
                db,
                invoice_id=invoice_id,
                item_id=item_id,
                category_name=category,
                rule_pattern=rule_pattern or "",
                rule_type=rule_match_mode,
            )
        else:
            apply_manual_credit_card_invoice_item_category_change(
                db,
                invoice_id=invoice_id,
                item_id=item_id,
                category_name=category,
            )
            result = None
    except CreditCardInvoiceCategoryEditError as exc:
        return _render_invoice_item_category_editor(
            invoice_id=invoice_id,
            item_id=item_id,
            request=request,
            db=db,
            selected_category=category,
            selected_apply_mode=apply_mode,
            selected_rule_pattern=rule_pattern,
            selected_rule_match_mode=rule_match_mode,
            form_error=str(exc),
            status_code=exc.status_code,
        )

    if apply_mode == "base" and result is not None:
        request.session["flash"] = (
            f"Regra aplicada na base. {result.reapply_result['updated_count']} item(ns) existente(s) foram reavaliados."
        )
    else:
        request.session["flash"] = "Categoria do item de fatura atualizada."
    return RedirectResponse(url=f"/admin/credit-card-invoices/{invoice_id}", status_code=303)


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

    request.session["flash"] = "Conciliação atualizada."
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

    request.session["flash"] = "Vínculo de pagamento removido."
    return RedirectResponse(url=f"/admin/credit-card-invoices/{invoice_id}", status_code=303)
