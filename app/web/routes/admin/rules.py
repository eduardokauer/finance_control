from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.repositories.models import CategorizationRule
from app.services.admin import list_categories, list_rules, upsert_rule

from .helpers import render_admin

router = APIRouter()


@router.get("/rules", response_class=HTMLResponse)
def admin_rules(
    request: Request,
    open_rule_id: int | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/rules.html",
        {
            "rules": list_rules(db),
            "categories": list_categories(db),
            "open_rule_id": open_rule_id,
        },
    )


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
