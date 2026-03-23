from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.admin_auth import admin_ui_enabled, verify_admin_password

from .helpers import render_admin

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def admin_login_page(request: Request, next: str = "/admin"):
    if request.session.get("admin_authenticated"):
        return RedirectResponse(url=unquote(next or "/admin"), status_code=303)
    return render_admin(request, "admin/login.html", {"next": unquote(next or "/admin")})


@router.post("/login")
def admin_login(request: Request, password: str = Form(...), next: str = Form("/admin")):
    if not admin_ui_enabled():
        raise HTTPException(status_code=503, detail="Configure ADMIN_UI_PASSWORD to enable the admin UI")
    if not verify_admin_password(password):
        return render_admin(request, "admin/login.html", {"next": next, "error": "Senha inválida."}, status_code=401)
    request.session["admin_authenticated"] = True
    request.session["flash"] = "Login efetuado com sucesso."
    return RedirectResponse(url=next or "/admin", status_code=303)


@router.post("/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)
