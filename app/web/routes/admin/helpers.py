from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.admin_auth import admin_ui_enabled
from app.core.config import settings

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[3] / "templates"))


def render_admin(request: Request, template_name: str, context: dict, status_code: int = 200) -> HTMLResponse:
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


def parse_optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid date format") from exc
