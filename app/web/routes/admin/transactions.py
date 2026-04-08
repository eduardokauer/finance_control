from __future__ import annotations

from datetime import date
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.repositories.models import CategorizationRule, Transaction
from app.services.admin import (
    build_pagination,
    build_transaction_filters,
    default_closed_month,
    kind_mode_from_transaction_kind,
    latest_closed_month_with_transactions,
    list_categories,
    list_transactions_for_admin,
    preview_bulk_reclassification,
    preview_similar_transactions,
    reclassify_transactions_manual,
    upsert_category,
    upsert_rule,
)
from app.services.credit_card_bills import map_conciliated_bank_payment_signals

from .helpers import is_htmx_request, render_admin, templates, trigger_admin_toast

router = APIRouter()


def _transactions_page_context(
    request: Request,
    db: Session,
    *,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
    category: str | None,
    description: str | None,
    uncategorized_only: bool,
    transaction_kind: str | None,
    sort: str | None,
    limit: int,
    offset: int,
) -> dict:
    default_period = latest_closed_month_with_transactions(db) or default_closed_month()
    filters = build_transaction_filters(
        month=month,
        period_start=period_start,
        period_end=period_end,
        category=category,
        description=description,
        uncategorized_only=uncategorized_only,
        transaction_kind=transaction_kind,
        sort=sort,
        default_period=default_period,
    )
    transactions, total = list_transactions_for_admin(db, filters, limit=limit, offset=offset)
    current_url = str(request.url)
    return {
        "filters": filters,
        "transactions": transactions,
        "pagination": build_pagination(total, limit=limit, offset=offset),
        "categories": list_categories(db),
        "current_url": current_url,
        "encoded_current_url": quote(current_url, safe=""),
        "current_path": request.url.path,
        "current_query": request.url.query,
        "bulk_actions_href": "/admin/transactions/bulk",
        "transactions_list_href": "/admin/transactions",
    }


def _transaction_detail_context(
    db: Session,
    *,
    transaction_id: int,
    return_to: str | None,
) -> dict:
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    signal = map_conciliated_bank_payment_signals(db, transaction_ids=[tx.id]).get(tx.id)
    setattr(tx, "conciliation_signal", signal)
    setattr(tx, "is_conciliated_bank_payment", signal is not None)
    return_to_value = unquote(return_to or "/admin/transactions")
    current_rule = db.get(CategorizationRule, tx.categorization_rule_id) if tx.categorization_rule_id else None
    return {
        "transaction": tx,
        "categories": list_categories(db),
        "current_rule": current_rule,
        "return_to": return_to_value,
        "encoded_return_to": quote(return_to_value, safe=""),
    }


def _render_transaction_detail_shell(
    request: Request,
    db: Session,
    *,
    transaction_id: int,
    return_to: str | None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/partials/transaction_detail_shell.html",
        {
            "request": request,
            **_transaction_detail_context(
                db,
                transaction_id=transaction_id,
                return_to=return_to,
            ),
        },
        status_code=status_code,
    )


@router.get("/transactions", response_class=HTMLResponse)
def admin_transactions(
    request: Request,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    category: str | None = None,
    description: str | None = None,
    uncategorized_only: bool = False,
    transaction_kind: str | None = None,
    sort: str | None = "recent",
    limit: int = Query(default=20, le=50),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    context = _transactions_page_context(
        request,
        db,
        month=month,
        period_start=period_start,
        period_end=period_end,
        category=category,
        description=description,
        uncategorized_only=uncategorized_only,
        transaction_kind=transaction_kind,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return render_admin(request, "admin/transactions.html", context)


@router.get("/transactions/bulk", response_class=HTMLResponse)
def admin_transactions_bulk(
    request: Request,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    category: str | None = None,
    description: str | None = None,
    uncategorized_only: bool = False,
    transaction_kind: str | None = None,
    sort: str | None = "recent",
    limit: int = Query(default=20, le=50),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    context = _transactions_page_context(
        request,
        db,
        month=month,
        period_start=period_start,
        period_end=period_end,
        category=category,
        description=description,
        uncategorized_only=uncategorized_only,
        transaction_kind=transaction_kind,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return render_admin(request, "admin/transactions_bulk.html", context)


@router.get("/transactions/{transaction_id}", response_class=HTMLResponse)
def admin_transaction_detail(
    transaction_id: int,
    request: Request,
    return_to: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    context = _transaction_detail_context(
        db,
        transaction_id=transaction_id,
        return_to=return_to,
    )
    return render_admin(request, "admin/transaction_detail.html", context)


@router.post("/transactions/{transaction_id}/preview-similar", response_class=HTMLResponse)
def admin_preview_similar(
    transaction_id: int,
    request: Request,
    pattern: str = Form(...),
    match_mode: str = Form(...),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    similar = preview_similar_transactions(db, tx, match_mode=match_mode, pattern=pattern)
    return templates.TemplateResponse(
        request,
        "admin/partials/similar_preview.html",
        {"request": request, "transactions": similar, "count": len(similar)},
    )


@router.post("/transactions/{transaction_id}/update")
def admin_update_transaction(
    transaction_id: int,
    request: Request,
    category: str = Form(...),
    transaction_kind: str = Form(...),
    notes: str | None = Form(default=None),
    return_to: str = Form("/admin/transactions"),
    rule_action: str = Form("none"),
    rule_pattern: str | None = Form(default=None),
    rule_match_mode: str = Form("contains"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    reclassify_transactions_manual(
        db,
        [tx],
        category=category,
        transaction_kind=transaction_kind,
        notes=notes,
        origin="manual_edit",
    )
    if rule_action in {"create", "update_current"} and rule_pattern:
        rule_id = tx.categorization_rule_id if rule_action == "update_current" else None
        rule = upsert_rule(
            db,
            rule_id=rule_id,
            pattern=rule_pattern,
            rule_type=rule_match_mode,
            category_name=category,
            kind_mode=kind_mode_from_transaction_kind(transaction_kind),
            source_scope="bank_statement",
            priority=0,
            is_active=True,
        )
        tx.categorization_rule_id = rule.id
        db.commit()
    resolved_return_to = unquote(return_to)
    if is_htmx_request(request):
        response = _render_transaction_detail_shell(
            request,
            db,
            transaction_id=transaction_id,
            return_to=resolved_return_to,
        )
        return trigger_admin_toast(response, "Lançamento atualizado.", level="success")
    request.session["flash"] = "Lançamento atualizado."
    return RedirectResponse(url=resolved_return_to, status_code=303)


@router.post("/transactions/{transaction_id}/quick-category")
def admin_transaction_quick_category(
    transaction_id: int,
    request: Request,
    name: str = Form(...),
    transaction_kind: str = Form(...),
    return_to: str = Form("/admin/transactions"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    category = upsert_category(
        db,
        category_id=None,
        name=name,
        transaction_kind=transaction_kind,
        is_active=True,
    )
    resolved_return_to = unquote(return_to)
    if is_htmx_request(request):
        response = _render_transaction_detail_shell(
            request,
            db,
            transaction_id=transaction_id,
            return_to=resolved_return_to,
        )
        return trigger_admin_toast(response, f"Categoria criada: {category.name}.", level="success")
    request.session["flash"] = "Categoria criada."
    return RedirectResponse(
        url=f"/admin/transactions/{transaction_id}?return_to={quote(resolved_return_to, safe='')}",
        status_code=303,
    )


@router.post("/transactions/bulk-preview", response_class=HTMLResponse)
@router.post("/transactions/bulk/preview", response_class=HTMLResponse)
def admin_bulk_preview(
    request: Request,
    selected_ids: list[int] = Form(default=[]),
    category: str = Form(...),
    transaction_kind: str = Form(...),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    txs = preview_bulk_reclassification(db, transaction_ids=selected_ids)
    return templates.TemplateResponse(
        request,
        "admin/partials/bulk_preview.html",
        {
            "request": request,
            "transactions": txs[:5],
            "count": len(txs),
            "selected_ids": selected_ids,
            "category": category,
            "transaction_kind": transaction_kind,
        },
    )


@router.post("/transactions/bulk-apply")
@router.post("/transactions/bulk/apply")
def admin_bulk_apply(
    request: Request,
    selected_ids: list[int] = Form(default=[]),
    category: str = Form(...),
    transaction_kind: str = Form(...),
    notes: str | None = Form(default=None),
    return_to: str = Form("/admin/transactions"),
    save_rule: bool = Form(False),
    rule_pattern: str | None = Form(default=None),
    rule_match_mode: str = Form("contains"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    txs = preview_bulk_reclassification(db, transaction_ids=selected_ids)
    if txs:
        reclassify_transactions_manual(
            db,
            txs,
            category=category,
            transaction_kind=transaction_kind,
            notes=notes,
            origin="bulk_reclassification",
        )
        if save_rule and rule_pattern:
            upsert_rule(
                db,
                rule_id=None,
                pattern=rule_pattern,
                rule_type=rule_match_mode,
                category_name=category,
                kind_mode=kind_mode_from_transaction_kind(transaction_kind),
                source_scope="bank_statement",
                priority=0,
                is_active=True,
            )
    request.session["flash"] = f"{len(txs)} lançamento(s) atualizados."
    return RedirectResponse(url=unquote(return_to), status_code=303)
