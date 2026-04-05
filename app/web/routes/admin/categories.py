from __future__ import annotations

from datetime import date
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import list_available_analysis_months, list_categories, resolve_analysis_period, upsert_category
from app.services.analysis import (
    build_analysis_snapshot,
    build_category_composition_for_period,
    build_category_consumption_monthly_series,
)

from .helpers import render_admin

router = APIRouter()


def _normalize_focus_category(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _summarize_selected_categories(category_names: list[str]) -> str:
    if not category_names:
        return "Todas as categorias"
    if len(category_names) == 1:
        return category_names[0]
    if len(category_names) == 2:
        return f"{category_names[0]} + {category_names[1]}"
    return f"{category_names[0]} +{len(category_names) - 1}"


def _categories_page_context(
    db: Session,
    *,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
    focus_category: str | None,
    selected_categories: list[str] | None,
) -> dict:
    latest_closed_start, latest_closed_end = resolve_analysis_period(
        db,
        month=None,
        period_start=None,
        period_end=None,
    )
    selected_mode = selection_mode or ("custom" if period_start and period_end else ("month" if month else "closed"))
    month_value = month or f"{latest_closed_start.year:04d}-{latest_closed_start.month:02d}"
    month_preview_start, month_preview_end = resolve_analysis_period(
        db,
        month=month_value,
        period_start=None,
        period_end=None,
    )

    if selected_mode == "month":
        resolved_start, resolved_end = month_preview_start, month_preview_end
    elif period_start and period_end:
        resolved_start, resolved_end = resolve_analysis_period(
            db,
            month=None,
            period_start=period_start,
            period_end=period_end,
        )
        if selected_mode == "closed" and (resolved_start != latest_closed_start or resolved_end != latest_closed_end):
            selected_mode = "custom"
    else:
        resolved_start, resolved_end = latest_closed_start, latest_closed_end

    analysis_data = build_analysis_snapshot(
        db,
        period_start=resolved_start,
        period_end=resolved_end,
    )
    all_categories = list_categories(db)
    available_categories = [
        category
        for category in all_categories
        if category.transaction_kind == "expense" and category.is_active
    ]
    available_category_names = [category.name for category in available_categories]

    ranking_rows = [
        row
        for row in analysis_data["category_breakdown"]["rows"]
        if row["expense_total"] > 0 and not row["is_technical"]
    ]
    ranking_rows.sort(key=lambda item: item["expense_total"], reverse=True)

    explicit_selected_category_keys = {
        _normalize_focus_category(category_name)
        for category_name in (selected_categories or [])
        if category_name
    }
    selected_category_keys = set(explicit_selected_category_keys)
    if not selected_category_keys and focus_category:
        selected_category_keys.add(_normalize_focus_category(focus_category))

    selected_category_names = [
        category_name
        for category_name in available_category_names
        if _normalize_focus_category(category_name) in selected_category_keys
    ]
    filtered_ranking_rows = [
        row
        for row in ranking_rows
        if not selected_category_names or row["name"] in selected_category_names
    ]

    normalized_focus = _normalize_focus_category(focus_category)
    valid_focus = next(
        (row["name"] for row in filtered_ranking_rows if _normalize_focus_category(row["name"]) == normalized_focus),
        None,
    )
    composition_categories = selected_category_names or ([valid_focus] if valid_focus else None)
    composition = (
        build_category_composition_for_period(
            db,
            period_start=resolved_start,
            period_end=resolved_end,
            category_names=composition_categories,
        )
        if composition_categories or available_category_names
        else None
    )

    category_filter_options = [
        {
            "value": category.name,
            "label": category.name,
            "is_selected": category.name in selected_category_names,
        }
        for category in available_categories
    ]
    filtered_consumption_chart = build_category_consumption_monthly_series(
        db,
        anchor_month=resolved_end,
        category_names=selected_category_names or None,
    )
    all_categories_selected = bool(available_category_names) and len(selected_category_names) == len(available_category_names)
    selected_categories_summary = (
        "Todas as categorias"
        if all_categories_selected or not selected_category_names
        else _summarize_selected_categories(selected_category_names)
    )

    latest_closed_value = f"{latest_closed_start.year:04d}-{latest_closed_start.month:02d}"
    analysis_month_options = list_available_analysis_months(db)
    latest_closed_label = next(
        (option["label"] for option in analysis_month_options if option["value"] == latest_closed_value),
        latest_closed_value,
    )

    return {
        "selection_mode": selected_mode,
        "period_start": resolved_start,
        "period_end": resolved_end,
        "month_value": month_value,
        "latest_closed_start": latest_closed_start,
        "latest_closed_end": latest_closed_end,
        "month_preview_start": month_preview_start,
        "month_preview_end": month_preview_end,
        "analysis_month_options": analysis_month_options,
        "latest_closed_label": latest_closed_label,
        "analysis_breadcrumb_items": [{"label": "Categorias", "href": None}],
        "analysis_back_href": None,
        "analysis_context_chips": [
            {"key": "period", "label": "Periodo", "value": analysis_data["period"]["label"]},
            *(
                [{"key": "focus_category", "label": "Categoria em foco", "value": valid_focus}]
                if valid_focus
                else []
            ),
            {
                "key": "selected_categories",
                "label": "Categorias",
                "value": selected_categories_summary,
            },
        ],
        "analysis_focus_banner": (
            {
                "key": "categories",
                "title": "Composicao aberta a partir da overview",
                "body": (
                    f"A composicao de {valid_focus} foi restaurada com o mesmo periodo do clique, "
                    "combinando conta e charges conciliados de fatura."
                ),
                "href": "#category-composition-section",
                "link_label": "Ir para a composicao",
            }
            if valid_focus
            else None
        ),
        "analysis_form_action": "/admin/categories",
        "analysis_submit_label": "Ver categorias",
        "analysis_show_generate": False,
        "analysis_global_tabs": [],
        "analysis_controls_intro": (
            "Categorias vira uma area propria: o filtro define o periodo da leitura, do grafico principal "
            "e da composicao clicavel."
        ),
        "analysis_toolbar_filters": [
            {
                "kind": "multi_select_dropdown",
                "name": "selected_category",
                "label": "Selecionar categorias",
                "summary": selected_categories_summary,
                "options": category_filter_options,
                "actions": [
                    {"key": "select_all", "label": "Selecionar todas"},
                    {"key": "clear_all", "label": "Limpar selecao"},
                ],
            }
        ],
        "analysis_extra_hidden_fields": [
            {"name": "focus_category", "value": valid_focus, "clear_on_empty": True},
        ],
        "categories": all_categories,
        "category_breakdown": analysis_data["category_breakdown"],
        "category_composition": composition,
        "consumption_chart": filtered_consumption_chart,
    }


def _categories_management_context(
    db: Session,
    *,
    request_url: str,
) -> dict:
    all_categories = list_categories(db)
    return {
        "categories": all_categories,
        "management_return_to": request_url,
    }


@router.get("/categories", response_class=HTMLResponse)
def admin_categories(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    focus_category: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    selected_categories = request.query_params.getlist("selected_category")
    context = _categories_page_context(
        db,
        selection_mode=selection_mode,
        month=month,
        period_start=period_start,
        period_end=period_end,
        focus_category=focus_category,
        selected_categories=selected_categories,
    )
    current_relative_url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    encoded_return_to = quote(current_relative_url, safe="")
    composition = context.get("category_composition")
    if composition:
        for row in composition.get("rows", []):
            if row.get("edit_kind") == "transaction" and row.get("transaction_id"):
                row["edit_href"] = f"/admin/transactions/{row['transaction_id']}?return_to={encoded_return_to}"
                row["edit_label"] = "Editar lançamento"
            elif row.get("edit_kind") == "invoice_item" and row.get("invoice_id") and row.get("item_id"):
                row["edit_href"] = (
                    f"/admin/credit-card-invoices/{row['invoice_id']}/items/{row['item_id']}/category"
                    f"?return_to={encoded_return_to}"
                )
                row["edit_label"] = "Editar categoria"
            else:
                row["edit_href"] = None
                row["edit_label"] = None
    return render_admin(
        request,
        "admin/categories.html",
        context,
    )


@router.get("/categories/manage", response_class=HTMLResponse)
def admin_categories_manage(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/categories_manage.html",
        _categories_management_context(
            db,
            request_url=str(request.url),
        ),
    )


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
    return RedirectResponse(url=unquote(return_to or "/admin/categories/manage"), status_code=303)


@router.post("/categories/{category_id}/update")
def admin_update_category(
    category_id: int,
    request: Request,
    name: str = Form(...),
    transaction_kind: str = Form(...),
    is_active: bool = Form(False),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    upsert_category(db, category_id=category_id, name=name, transaction_kind=transaction_kind, is_active=is_active)
    request.session["flash"] = "Categoria atualizada."
    return RedirectResponse(url=unquote(return_to or "/admin/categories/manage"), status_code=303)
