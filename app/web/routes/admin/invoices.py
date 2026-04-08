from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import list_available_analysis_months, list_recent_source_files, resolve_analysis_period
from app.services.analysis import (
    build_analysis_snapshot,
    build_invoice_operational_snapshot,
    format_currency_br,
    format_date_br,
)
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

from .helpers import is_htmx_request, render_admin, templates, trigger_admin_toast

router = APIRouter()


def _status_variant(status: str) -> str:
    return {
        "imported": "ok",
        "pending_review": "warn",
        "partially_conciliated": "warn",
        "conciliated": "ok",
        "conflict": "danger",
    }.get(status, "")


def _invoice_period_context(
    db: Session,
    *,
    request: Request,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
) -> dict:
    latest_closed_start, latest_closed_end = resolve_analysis_period(
        db,
        month=None,
        period_start=None,
        period_end=None,
    )
    selected_mode = selection_mode or ("custom" if period_start and period_end else ("month" if month else "closed"))
    month_value = month or f"{latest_closed_start.year:04d}-{latest_closed_start.month:02d}"
    month_preview_start, month_preview_end = resolve_analysis_period(
        db,
        month=month_value,
        period_start=None,
        period_end=None,
    )
    if selected_mode == "month":
        resolved_start, resolved_end = month_preview_start, month_preview_end
    elif selected_mode == "custom" and period_start and period_end:
        resolved_start, resolved_end = resolve_analysis_period(
            db,
            month=None,
            period_start=period_start,
            period_end=period_end,
        )
    else:
        resolved_start, resolved_end = latest_closed_start, latest_closed_end

    latest_closed_value = f"{latest_closed_start.year:04d}-{latest_closed_start.month:02d}"
    analysis_month_options = list_available_analysis_months(db)
    latest_closed_label = next(
        (option["label"] for option in analysis_month_options if option["value"] == latest_closed_value),
        latest_closed_value,
    )
    return {
        "selection_mode": selected_mode,
        "period_start": resolved_start,
        "period_end": resolved_end,
        "month_value": month_value,
        "latest_closed_start": latest_closed_start,
        "latest_closed_end": latest_closed_end,
        "month_preview_start": month_preview_start,
        "month_preview_end": month_preview_end,
        "analysis_month_options": analysis_month_options,
        "latest_closed_label": latest_closed_label,
        "analysis_page_title": "Visão de Faturas",
        "analysis_page_intro": "Itens e faturas do período.",
        "analysis_form_action": "/admin/credit-card-invoices",
        "analysis_show_generate": False,
        "analysis_breadcrumb_items": [
            {"label": "Resumo", "href": "/admin"},
            {"label": "Visão de Faturas", "href": None},
        ],
        "analysis_back_href": "/admin",
        "analysis_context_chips": [
            {"key": "period", "label": "Período", "value": f"{format_date_br(resolved_start)} a {format_date_br(resolved_end)}"},
        ],
        "analysis_focus_banner": None,
        "analysis_global_tabs": [],
        "analysis_controls_intro": "Período global da página.",
        "analysis_extra_hidden_fields": [],
        "analysis_urls": {"return_to": str(request.url)},
        "analysis_toolbar_filters": [],
    }


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
    context = {
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
    }
    return render_admin(
        request,
        "admin/credit_card_invoice_item_category_edit.html",
        context,
        status_code=status_code,
    )


def _render_invoice_item_category_shell(
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
    return templates.TemplateResponse(
        request,
        "admin/partials/credit_card_invoice_item_category_shell.html",
        {
            "request": request,
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


def _invoice_detail_context(db: Session, *, invoice_id: int, conciliation_error: str | None = None) -> dict:
    detail = get_credit_card_invoice_detail(db, invoice_id=invoice_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {
        "detail": detail,
        "status_variant": _status_variant,
        "conciliation_error": conciliation_error,
    }


def _render_invoice_detail_shell(
    request: Request,
    db: Session,
    *,
    invoice_id: int,
    conciliation_error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/partials/credit_card_invoice_detail_shell.html",
        {
            "request": request,
            **_invoice_detail_context(
                db,
                invoice_id=invoice_id,
                conciliation_error=conciliation_error,
            ),
        },
        status_code=status_code,
    )


@router.get("/credit-card-invoices", response_class=HTMLResponse)
def admin_credit_card_invoice_list(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    card_label: str | None = None,
    category: str | None = None,
    item_type: str | None = None,
    conciliation_status: str | None = None,
    description: str | None = None,
    sort: str | None = "recent",
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    period_context = _invoice_period_context(
        db,
        request=request,
        selection_mode=selection_mode,
        month=month,
        period_start=period_start,
        period_end=period_end,
    )
    entries = [
        entry
        for entry in list_credit_card_invoices(db)
        if period_context["period_start"] <= entry.invoice.due_date <= period_context["period_end"]
    ]
    if conciliation_status:
        entries = [entry for entry in entries if entry.conciliation_status == conciliation_status]
    if card_label:
        entries = [entry for entry in entries if entry.card.card_label == card_label]
    analysis_snapshot = build_analysis_snapshot(
        db,
        period_start=period_context["period_start"],
        period_end=period_context["period_end"],
    )
    all_invoice_rows = build_invoice_operational_snapshot(
        db,
        period_start=period_context["period_start"],
        period_end=period_context["period_end"],
    )["rows"]
    invoice_rows = all_invoice_rows
    if card_label:
        invoice_rows = [row for row in invoice_rows if row["card_label"] == card_label]
    if category:
        invoice_rows = [row for row in invoice_rows if row["category"] == category]
    if item_type:
        invoice_rows = [row for row in invoice_rows if row["item_type"] == item_type]
    if conciliation_status:
        invoice_rows = [row for row in invoice_rows if row["conciliation_status"] == conciliation_status]
    if description:
        lowered_description = description.casefold()
        invoice_rows = [
            row
            for row in invoice_rows
            if lowered_description in row["description"].casefold()
            or lowered_description in (row["description_normalized"] or "").casefold()
        ]
    if sort == "amount_desc":
        invoice_rows = sorted(invoice_rows, key=lambda row: (abs(row["amount"]), row["purchase_date"], row["id"]), reverse=True)
    elif sort == "amount_asc":
        invoice_rows = sorted(invoice_rows, key=lambda row: (abs(row["amount"]), row["purchase_date"], row["id"]))
    elif sort == "description":
        invoice_rows = sorted(invoice_rows, key=lambda row: ((row["description_normalized"] or "").casefold(), row["purchase_date"], row["id"]))
    else:
        invoice_rows = sorted(invoice_rows, key=lambda row: (row["purchase_date"], row["id"]), reverse=True)

    chart_data = {
        "monthly": analysis_snapshot["charts"]["invoice_monthly"],
        "categories_monthly": analysis_snapshot["charts"]["invoice_categories_monthly"],
    }
    return render_admin(
        request,
        "admin/credit_card_invoices.html",
        {
            **period_context,
            "entries": entries,
            "invoice_rows": invoice_rows,
            "chart_data": chart_data,
            "invoice_period_label": analysis_snapshot["period"]["month_reference_label"],
            "invoice_snapshot": analysis_snapshot["invoice_month_snapshot"],
            "invoice_filters": {
                "card_label": card_label or "",
                "category": category or "",
                "item_type": item_type or "",
                "conciliation_status": conciliation_status or "",
                "description": description or "",
                "sort": sort or "recent",
            },
            "invoice_filter_options": {
                "card_labels": sorted({row["card_label"] for row in all_invoice_rows if row["card_label"]}),
                "categories": sorted({row["category"] for row in all_invoice_rows if row["category"]}),
                "item_types": sorted({row["item_type"] for row in all_invoice_rows if row["item_type"]}),
                "conciliation_statuses": sorted({row["conciliation_status"] for row in all_invoice_rows if row["conciliation_status"]}),
            },
            "invoice_stats": {
                "row_count": len(invoice_rows),
                "full_row_count": len(all_invoice_rows),
                "invoice_count": len(entries),
            },
            "format_currency_br": format_currency_br,
            "format_date_br": format_date_br,
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
    return render_admin(
        request,
        "admin/credit_card_invoice_detail.html",
        _invoice_detail_context(db, invoice_id=invoice_id),
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
    renderer = _render_invoice_item_category_shell if is_htmx_request(request) else _render_invoice_item_category_editor
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
        return renderer(
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
    return renderer(
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
    renderer = _render_invoice_item_category_shell if is_htmx_request(request) else _render_invoice_item_category_editor
    if not confirm_apply:
        return renderer(
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
        return renderer(
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
        success_message = f"Regra aplicada na base. {result.reapply_result['updated_count']} item(ns) existente(s) foram reavaliados."
    else:
        success_message = "Categoria do item de fatura atualizada."
    if is_htmx_request(request):
        response = _render_invoice_item_category_shell(
            invoice_id=invoice_id,
            item_id=item_id,
            request=request,
            db=db,
            return_to=return_to,
        )
        return trigger_admin_toast(response, success_message, level="success")
    request.session["flash"] = success_message
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
        if is_htmx_request(request):
            return _render_invoice_detail_shell(
                request,
                db,
                invoice_id=invoice_id,
                conciliation_error=str(exc),
                status_code=exc.status_code,
            )
        return render_admin(
            request,
            "admin/credit_card_invoice_detail.html",
            _invoice_detail_context(
                db,
                invoice_id=invoice_id,
                conciliation_error=str(exc),
            ),
            status_code=exc.status_code,
        )

    if is_htmx_request(request):
        response = _render_invoice_detail_shell(
            request,
            db,
            invoice_id=invoice_id,
        )
        return trigger_admin_toast(response, "Conciliação atualizada.", level="success")
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
        if is_htmx_request(request):
            return _render_invoice_detail_shell(
                request,
                db,
                invoice_id=invoice_id,
                conciliation_error=str(exc),
                status_code=exc.status_code,
            )
        return render_admin(
            request,
            "admin/credit_card_invoice_detail.html",
            _invoice_detail_context(
                db,
                invoice_id=invoice_id,
                conciliation_error=str(exc),
            ),
            status_code=exc.status_code,
        )

    if is_htmx_request(request):
        response = _render_invoice_detail_shell(
            request,
            db,
            invoice_id=invoice_id,
        )
        return trigger_admin_toast(response, "Vínculo de pagamento removido.", level="success")
    request.session["flash"] = "Vínculo de pagamento removido."
    return RedirectResponse(url=f"/admin/credit-card-invoices/{invoice_id}", status_code=303)
