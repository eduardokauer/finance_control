from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.admin_auth import admin_ui_enabled, require_admin_session, verify_admin_password
from app.core.config import settings
from app.core.database import get_db
from app.repositories.models import CategorizationRule, Transaction
from app.services.admin import (
    admin_dashboard_metrics,
    build_pagination,
    build_transaction_filters,
    list_categories,
    list_rules,
    list_transactions_for_admin,
    preview_bulk_reclassification,
    preview_reapply_rules,
    preview_similar_transactions,
    reapply_rules_for_period,
    reclassify_transactions_manual,
    run_analysis_for_period,
    upsert_category,
    upsert_rule,
)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
router = APIRouter(prefix="/admin", include_in_schema=False)


def _render(request: Request, template_name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request,
        template_name,
        {
            **context,
            "flash": flash,
            "admin_enabled": admin_ui_enabled(),
            "settings": settings,
        },
        status_code=status_code,
    )


@router.get("/login", response_class=HTMLResponse)
def admin_login_page(request: Request, next: str = "/admin"):
    if request.session.get("admin_authenticated"):
        return RedirectResponse(url=unquote(next or "/admin"), status_code=303)
    return _render(request, "admin/login.html", {"next": unquote(next or "/admin")})


@router.post("/login")
def admin_login(request: Request, password: str = Form(...), next: str = Form("/admin")):
    if not admin_ui_enabled():
        raise HTTPException(status_code=503, detail="Configure ADMIN_UI_PASSWORD to enable the admin UI")
    if not verify_admin_password(password):
        return _render(request, "admin/login.html", {"next": next, "error": "Senha inválida."}, status_code=401)
    request.session["admin_authenticated"] = True
    request.session["flash"] = "Login efetuado com sucesso."
    return RedirectResponse(url=next or "/admin", status_code=303)


@router.post("/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("", response_class=HTMLResponse)
def admin_home(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    return _render(request, "admin/dashboard.html", {"metrics": admin_dashboard_metrics(db)})


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
    filters = build_transaction_filters(
        month=month,
        period_start=period_start,
        period_end=period_end,
        category=category,
        description=description,
        uncategorized_only=uncategorized_only,
        transaction_kind=transaction_kind,
        sort=sort,
    )
    transactions, total = list_transactions_for_admin(db, filters, limit=limit, offset=offset)
    current_url = str(request.url)
    context = {
        "filters": filters,
        "transactions": transactions,
        "pagination": build_pagination(total, limit=limit, offset=offset),
        "categories": list_categories(db),
        "current_url": current_url,
        "encoded_current_url": quote(current_url, safe=""),
        "current_path": request.url.path,
        "current_query": request.url.query,
    }
    return _render(request, "admin/transactions.html", context)


@router.get("/transactions/{transaction_id}", response_class=HTMLResponse)
def admin_transaction_detail(
    transaction_id: int,
    request: Request,
    return_to: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return_to_value = unquote(return_to or "/admin/transactions")
    current_rule = db.get(CategorizationRule, tx.categorization_rule_id) if tx.categorization_rule_id else None
    context = {
        "transaction": tx,
        "categories": list_categories(db),
        "current_rule": current_rule,
        "return_to": return_to_value,
        "encoded_return_to": quote(return_to_value, safe=""),
    }
    return _render(request, "admin/transaction_detail.html", context)


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
            transaction_kind=transaction_kind,
            priority=0,
            is_active=True,
        )
        tx.categorization_rule_id = rule.id
        db.commit()
    request.session["flash"] = "Lançamento atualizado."
    return RedirectResponse(url=unquote(return_to), status_code=303)


@router.post("/transactions/bulk-preview", response_class=HTMLResponse)
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
                transaction_kind=transaction_kind,
                priority=0,
                is_active=True,
            )
    request.session["flash"] = f"{len(txs)} lançamento(s) atualizados."
    return RedirectResponse(url=unquote(return_to), status_code=303)


@router.get("/rules", response_class=HTMLResponse)
def admin_rules(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    return _render(request, "admin/rules.html", {"rules": list_rules(db), "categories": list_categories(db)})


@router.post("/rules")
def admin_create_rule(
    request: Request,
    pattern: str = Form(...),
    rule_type: str = Form(...),
    category_name: str = Form(...),
    transaction_kind: str = Form(...),
    priority: int = Form(0),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    upsert_rule(
        db,
        rule_id=None,
        pattern=pattern,
        rule_type=rule_type,
        category_name=category_name,
        transaction_kind=transaction_kind,
        priority=priority,
        is_active=True,
    )
    request.session["flash"] = "Regra criada."
    return RedirectResponse(url="/admin/rules", status_code=303)


@router.post("/rules/{rule_id}/update")
def admin_update_rule(
    rule_id: int,
    request: Request,
    pattern: str = Form(...),
    rule_type: str = Form(...),
    category_name: str = Form(...),
    transaction_kind: str = Form(...),
    priority: int = Form(...),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    upsert_rule(
        db,
        rule_id=rule_id,
        pattern=pattern,
        rule_type=rule_type,
        category_name=category_name,
        transaction_kind=transaction_kind,
        priority=priority,
        is_active=is_active,
    )
    request.session["flash"] = "Regra atualizada."
    return RedirectResponse(url="/admin/rules", status_code=303)


@router.post("/rules/{rule_id}/toggle")
def admin_toggle_rule(rule_id: int, request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    rule = db.get(CategorizationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.is_active = not rule.is_active
    db.commit()
    request.session["flash"] = "Status da regra atualizado."
    return RedirectResponse(url="/admin/rules", status_code=303)


@router.post("/rules/{rule_id}/delete")
def admin_delete_rule(rule_id: int, request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    rule = db.get(CategorizationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    request.session["flash"] = "Regra excluída."
    return RedirectResponse(url="/admin/rules", status_code=303)


@router.get("/categories", response_class=HTMLResponse)
def admin_categories(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    return _render(request, "admin/categories.html", {"categories": list_categories(db)})


@router.post("/categories")
def admin_create_category(
    request: Request,
    name: str = Form(...),
    transaction_kind: str = Form(...),
    is_active: bool = Form(True),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    upsert_category(db, category_id=None, name=name, transaction_kind=transaction_kind, is_active=is_active)
    request.session["flash"] = "Categoria salva."
    return RedirectResponse(url=unquote(return_to or "/admin/categories"), status_code=303)


@router.post("/categories/{category_id}/update")
def admin_update_category(
    category_id: int,
    request: Request,
    name: str = Form(...),
    transaction_kind: str = Form(...),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    upsert_category(db, category_id=category_id, name=name, transaction_kind=transaction_kind, is_active=is_active)
    request.session["flash"] = "Categoria atualizada."
    return RedirectResponse(url="/admin/categories", status_code=303)


@router.get("/reapply", response_class=HTMLResponse)
def admin_reapply_page(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    return _render(request, "admin/reapply.html", {"preview": None})


@router.post("/reapply/preview", response_class=HTMLResponse)
def admin_reapply_preview(
    request: Request,
    period_start: date = Form(...),
    period_end: date = Form(...),
    include_manual: bool = Form(False),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    preview = preview_reapply_rules(db, period_start=period_start, period_end=period_end, include_manual=include_manual)
    return templates.TemplateResponse(
        request,
        "admin/partials/reapply_preview.html",
        {
            "request": request,
            "preview": preview,
            "period_start": period_start,
            "period_end": period_end,
            "include_manual": include_manual,
        },
    )


@router.post("/reapply")
def admin_reapply(
    request: Request,
    period_start: date = Form(...),
    period_end: date = Form(...),
    include_manual: bool = Form(False),
    run_analysis_after: bool = Form(False),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    result = reapply_rules_for_period(db, period_start=period_start, period_end=period_end, include_manual=include_manual)
    if run_analysis_after:
        run_analysis_for_period(db, period_start=period_start, period_end=period_end)
    request.session["flash"] = (
        f"Reaplicação concluída: {result['updated_count']} alterados de {result['checked_count']} avaliados."
    )
    return RedirectResponse(url="/admin/reapply", status_code=303)


@router.post("/analysis/run")
def admin_run_analysis(
    request: Request,
    period_start: date = Form(...),
    period_end: date = Form(...),
    return_to: str = Form("/admin"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    run = run_analysis_for_period(db, period_start=period_start, period_end=period_end)
    request.session["flash"] = f"Nova análise gerada (run #{run.id})."
    return RedirectResponse(url=unquote(return_to), status_code=303)
