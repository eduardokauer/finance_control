from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.admin_auth import admin_ui_enabled
from app.core.config import settings

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[3] / "templates"))
ADMIN_PERIOD_SESSION_KEY = "admin_selected_period"
ADMIN_HOME_LENS_SESSION_KEY = "admin_selected_home_lens"


ADMIN_NAV_SECTIONS = [
    {
        "label": "Principal",
        "items": [
            {"key": "overview", "label": "Visão Geral", "href": "/admin"},
            {"key": "conciliated", "label": "Visão conciliada", "href": "/admin/analysis"},
            {
                "key": "statement",
                "label": "Visão de Extrato",
                "href": "/admin/conference",
                "children": [
                    {
                        "key": "statement_manage",
                        "label": "Administrar extratos",
                        "href": "/admin/conference/manage",
                    },
                    {
                        "key": "statement_technical",
                        "label": "Auditoria técnica",
                        "href": "/admin/conference/technical",
                    }
                ],
            },
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
            {
                "key": "transactions",
                "label": "Lançamentos",
                "href": "/admin/transactions",
                "children": [
                    {
                        "key": "transactions_bulk",
                        "label": "Ações em lote",
                        "href": "/admin/transactions/bulk",
                    }
                ],
            },
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
    if path.startswith("/admin/conference/manage"):
        return "statement_manage"
    if path.startswith("/admin/conference/technical"):
        return "statement_technical"
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
    if path.startswith("/admin/transactions/bulk"):
        return "transactions_bulk"
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


def is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def build_admin_toast_payload(message: str, *, level: str = "info") -> dict:
    return {
        "message": message,
        "level": level,
    }


def merge_hx_trigger_headers(existing: str | None, new_events: dict) -> str:
    if not existing:
        return json.dumps(new_events)
    try:
        merged = json.loads(existing)
    except json.JSONDecodeError:
        merged = {}
    if not isinstance(merged, dict):
        merged = {}
    merged.update(new_events)
    return json.dumps(merged)


def apply_htmx_response_headers(
    response: HTMLResponse,
    *,
    triggers: dict | None = None,
    push_url: str | None = None,
    replace_url: str | None = None,
    reswap: str | None = None,
    retarget: str | None = None,
) -> HTMLResponse:
    if triggers:
        response.headers["HX-Trigger"] = merge_hx_trigger_headers(
            response.headers.get("HX-Trigger"),
            triggers,
        )
    if push_url is not None:
        response.headers["HX-Push-Url"] = push_url
    if replace_url is not None:
        response.headers["HX-Replace-Url"] = replace_url
    if reswap is not None:
        response.headers["HX-Reswap"] = reswap
    if retarget is not None:
        response.headers["HX-Retarget"] = retarget
    return response


def trigger_admin_toast(response: HTMLResponse, message: str, *, level: str = "info") -> HTMLResponse:
    return apply_htmx_response_headers(
        response,
        triggers={"admin:toast": build_admin_toast_payload(message, level=level)},
    )


def render_admin(
    request: Request,
    template_name: str,
    context: dict,
    status_code: int = 200,
    headers: dict | None = None,
) -> HTMLResponse:
    flash = request.session.pop("flash", None)
    response = templates.TemplateResponse(
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
    if headers:
        for key, value in headers.items():
            response.headers[key] = value
    return response


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


def _safe_date_from_session(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def restore_admin_period_selection(
    request: Request,
    *,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, str | date | None]:
    has_explicit_period_params = any(
        key in request.query_params
        for key in ("selection_mode", "month", "period_start", "period_end")
    )
    if has_explicit_period_params:
        return {
            "selection_mode": selection_mode,
            "month": month,
            "period_start": period_start,
            "period_end": period_end,
        }
    saved_state = request.session.get(ADMIN_PERIOD_SESSION_KEY)
    if not isinstance(saved_state, dict):
        return {
            "selection_mode": selection_mode,
            "month": month,
            "period_start": period_start,
            "period_end": period_end,
        }
    return {
        "selection_mode": saved_state.get("selection_mode") or selection_mode,
        "month": saved_state.get("month") or month,
        "period_start": _safe_date_from_session(saved_state.get("period_start")) or period_start,
        "period_end": _safe_date_from_session(saved_state.get("period_end")) or period_end,
    }


def persist_admin_period_selection(
    request: Request,
    *,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
) -> None:
    request.session[ADMIN_PERIOD_SESSION_KEY] = {
        "selection_mode": selection_mode,
        "month": month,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
    }


def restore_admin_home_lens_selection(
    request: Request,
    *,
    home_lens: str | None,
    default: str = "cash",
) -> str:
    if "home_lens" in request.query_params:
        selected = (home_lens or "").strip().lower()
        if selected in {"cash", "competence"}:
            return selected
        saved_lens = request.session.get(ADMIN_HOME_LENS_SESSION_KEY)
        if isinstance(saved_lens, str):
            normalized = saved_lens.strip().lower()
            if normalized in {"cash", "competence"}:
                return normalized
        return default
    saved_lens = request.session.get(ADMIN_HOME_LENS_SESSION_KEY)
    if isinstance(saved_lens, str):
        normalized = saved_lens.strip().lower()
        if normalized in {"cash", "competence"}:
            return normalized
    normalized_home_lens = (home_lens or "").strip().lower()
    return normalized_home_lens if normalized_home_lens in {"cash", "competence"} else default


def persist_admin_home_lens_selection(
    request: Request,
    *,
    home_lens: str | None,
    default: str = "cash",
) -> None:
    normalized_home_lens = (home_lens or "").strip().lower()
    request.session[ADMIN_HOME_LENS_SESSION_KEY] = (
        normalized_home_lens if normalized_home_lens in {"cash", "competence"} else default
    )
