from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.admin_auth import admin_ui_enabled
from app.core.config import settings

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[3] / "templates"))


ADMIN_NAV_SECTIONS = [
    {
        "label": "Principal",
        "items": [
            {"key": "overview", "label": "Visão Geral", "href": "/admin"},
            {"key": "conciliated", "label": "Visão conciliada", "href": "/admin/analysis"},
            {"key": "statement", "label": "Visão de Extrato", "href": "/admin/conference"},
            {
                "key": "invoice_view",
                "label": "Visão de Faturas",
                "href": "/admin/credit-card-invoices",
                "children": [
                    {
                        "key": "invoice_manage",
                        "label": "Administrar faturas",
                        "href": "/admin/credit-card-invoices/manage",
                    }
                ],
            },
            {
                "key": "categories",
                "label": "Categorias",
                "href": "/admin/categories",
                "children": [
                    {
                        "key": "categories_manage",
                        "label": "Administrar categorias",
                        "href": "/admin/categories/manage",
                    }
                ],
            },
        ],
    },
    {
        "label": "Operação",
        "items": [
            {"key": "operations", "label": "Central operacional", "href": "/admin/operations"},
            {"key": "transactions", "label": "Lançamentos", "href": "/admin/transactions"},
        ],
    },
    {
        "label": "Configuração",
        "items": [
            {"key": "rules", "label": "Regras", "href": "/admin/rules"},
            {"key": "reapply", "label": "Reaplicar regras", "href": "/admin/reapply"},
        ],
    },
]


def _active_nav_key(path: str) -> str:
    if path.startswith("/admin/credit-card-invoices/manage"):
        return "invoice_manage"
    if path.startswith("/admin/categories/manage"):
        return "categories_manage"
    if path.startswith("/admin/analysis"):
        return "conciliated"
    if path.startswith("/admin/conference"):
        return "statement"
    if path.startswith("/admin/operations"):
        return "operations"
    if path.startswith("/admin/transactions"):
        return "transactions"
    if path.startswith("/admin/credit-card-invoices"):
        return "invoice_view"
    if path.startswith("/admin/reapply"):
        return "reapply"
    if path.startswith("/admin/rules"):
        return "rules"
    if path.startswith("/admin/categories"):
        return "categories"
    return "overview"


def _build_shell_context(request: Request) -> dict:
    active_key = _active_nav_key(request.url.path)
    nav_sections = []
    active_item = None
    active_section = None

    for section in ADMIN_NAV_SECTIONS:
        items = []
        for item in section["items"]:
            children = []
            active_child = None
            for child in item.get("children", []):
                enriched_child = {**child, "is_current": child["key"] == active_key}
                if enriched_child["is_current"]:
                    active_child = enriched_child
                    active_item = enriched_child
                    active_section = section["label"]
                children.append(enriched_child)

            item_is_current = item["key"] == active_key
            enriched_item = {
                **item,
                "children": children,
                "is_current": item_is_current,
                "is_active": item_is_current or active_child is not None,
            }
            if item_is_current:
                active_item = enriched_item
                active_section = section["label"]
            items.append(enriched_item)
        nav_sections.append({**section, "items": items})

    return {
        "nav_sections": nav_sections,
        "active_nav_key": active_key,
        "active_nav_label": active_item["label"] if active_item else "Admin",
        "active_nav_section_label": active_section or "Principal",
        "admin_brand_name": "Finance Control Admin",
        "admin_brand_subtitle": "Gestão Financeira",
    }


def render_admin(request: Request, template_name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request,
        template_name,
        {
            **_build_shell_context(request),
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
