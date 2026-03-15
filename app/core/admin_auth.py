from __future__ import annotations

from secrets import compare_digest
from urllib.parse import quote

from fastapi import HTTPException, Request, status

from app.core.config import settings


def admin_ui_enabled() -> bool:
    return bool(settings.admin_ui_password)


def verify_admin_password(password: str) -> bool:
    if not settings.admin_ui_password:
        return False
    return compare_digest(password, settings.admin_ui_password)


def require_admin_session(request: Request):
    if not admin_ui_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin UI disabled")
    if request.session.get("admin_authenticated"):
        return True
    next_value = request.url.path if not request.url.query else f"{request.url.path}?{request.url.query}"
    location = f"/admin/login?next={quote(next_value, safe='/?:=&')}"
    raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": location})
