from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import list_categories, upsert_category

from .helpers import render_admin

router = APIRouter()


@router.get("/categories", response_class=HTMLResponse)
def admin_categories(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    return render_admin(request, "admin/categories.html", {"categories": list_categories(db)})


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
