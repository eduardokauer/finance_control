from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.credit_card_bills import (
    build_credit_card_invoice_import_chart,
    CreditCardInvoiceCategoryEditError,
    CreditCardInvoiceConciliationError,
    apply_manual_credit_card_invoice_item_category_change,
    get_credit_card_invoice_item_category_editor,
    get_credit_card_invoice_detail,
    list_credit_cards,
    list_credit_card_invoices,
    preview_manual_credit_card_invoice_item_category_change,
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
    preview=None,
    form_error: str | None = None,
    status_code: int = 200,
):
    editor = get_credit_card_invoice_item_category_editor(db, invoice_id=invoice_id, item_id=item_id)
    if editor is None:
        raise HTTPException(status_code=404, detail="Invoice item not found")
    resolved_category = selected_category or editor.item.category
    if resolved_category is None and editor.available_categories:
        resolved_category = editor.available_categories[0].name
    return render_admin(
        request,
        "admin/credit_card_invoice_item_category_edit.html",
        {
            "editor": editor,
            "selected_category": resolved_category,
            "preview": preview,
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
    return render_admin(
        request,
        "admin/credit_card_invoices.html",
        {
            "entries": entries,
            "chart_data": chart_payload,
            "credit_cards": list_credit_cards(db, active_only=True),
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


@router.get("/credit-card-invoices/{invoice_id}/items/{item_id}/category", response_class=HTMLResponse)
def admin_credit_card_invoice_item_category_edit(
    invoice_id: int,
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return _render_invoice_item_category_editor(
        invoice_id=invoice_id,
        item_id=item_id,
        request=request,
        db=db,
    )


@router.post("/credit-card-invoices/{invoice_id}/items/{item_id}/category/preview", response_class=HTMLResponse)
def admin_credit_card_invoice_item_category_preview(
    invoice_id: int,
    item_id: int,
    request: Request,
    category: str = Form(...),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    try:
        preview = preview_manual_credit_card_invoice_item_category_change(
            db,
            invoice_id=invoice_id,
            item_id=item_id,
            category_name=category,
        )
    except CreditCardInvoiceCategoryEditError as exc:
        return _render_invoice_item_category_editor(
            invoice_id=invoice_id,
            item_id=item_id,
            request=request,
            db=db,
            selected_category=category,
            form_error=str(exc),
            status_code=exc.status_code,
        )
    return _render_invoice_item_category_editor(
        invoice_id=invoice_id,
        item_id=item_id,
        request=request,
        db=db,
        selected_category=category,
        preview=preview,
    )


@router.post("/credit-card-invoices/{invoice_id}/items/{item_id}/category/apply")
def admin_credit_card_invoice_item_category_apply(
    invoice_id: int,
    item_id: int,
    request: Request,
    category: str = Form(...),
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
            form_error="Confirme explicitamente a alteração antes de salvar.",
            status_code=422,
        )
    try:
        apply_manual_credit_card_invoice_item_category_change(
            db,
            invoice_id=invoice_id,
            item_id=item_id,
            category_name=category,
        )
    except CreditCardInvoiceCategoryEditError as exc:
        return _render_invoice_item_category_editor(
            invoice_id=invoice_id,
            item_id=item_id,
            request=request,
            db=db,
            selected_category=category,
            form_error=str(exc),
            status_code=exc.status_code,
        )

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
