from __future__ import annotations

from datetime import date
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import list_categories, list_recent_source_files, resolve_analysis_period, upsert_category
from app.services.analysis import build_analysis_snapshot, build_category_composition_for_period

from .helpers import render_admin

router = APIRouter()


def _category_focus_href(
    *,
    selection_mode: str,
    month_value: str | None,
    period_start: date,
    period_end: date,
    category_name: str,
) -> str:
    params: list[str] = [f"selection_mode={selection_mode}"]
    if selection_mode == "month" and month_value:
        params.append(f"month={month_value}")
    else:
        params.append(f"period_start={period_start.isoformat()}")
        params.append(f"period_end={period_end.isoformat()}")
    params.append(f"focus_category={category_name}")
    return "/admin/categories?" + "&".join(params) + "#category-composition-section"


def _categories_page_context(
    db: Session,
    *,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
    focus_category: str | None,
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
    elif selected_mode == "custom" and period_start and period_end:
        resolved_start, resolved_end = resolve_analysis_period(
            db,
            month=None,
            period_start=period_start,
            period_end=period_end,
        )
    else:
        resolved_start, resolved_end = latest_closed_start, latest_closed_end

    analysis_data = build_analysis_snapshot(
        db,
        period_start=resolved_start,
        period_end=resolved_end,
    )
    all_categories = list_categories(db)
    ranking_rows = [
        row
        for row in analysis_data["category_breakdown"]["rows"]
        if row["expense_total"] > 0 and not row["is_technical"]
    ]
    ranking_rows.sort(key=lambda item: item["expense_total"], reverse=True)

    valid_focus = focus_category if any(row["name"] == focus_category for row in ranking_rows) else None
    composition = (
        build_category_composition_for_period(
            db,
            period_start=resolved_start,
            period_end=resolved_end,
            category_name=valid_focus,
        )
        if valid_focus
        else None
    )
    recent_loads = list_recent_source_files(db, source_types=["bank_statement", "credit_card_bill"], limit=10)

    category_rows = []
    for row in ranking_rows:
        category_rows.append(
            {
                **row,
                "href": _category_focus_href(
                    selection_mode=selected_mode,
                    month_value=month_value if selected_mode == "month" else None,
                    period_start=resolved_start,
                    period_end=resolved_end,
                    category_name=row["name"],
                ),
            }
        )

    breakdown = analysis_data["category_breakdown"]
    top_category = breakdown["top_expense_categories"][0] if breakdown["top_expense_categories"] else None

    return {
        "selection_mode": selected_mode,
        "period_start": resolved_start,
        "period_end": resolved_end,
        "month_value": month_value,
        "latest_closed_start": latest_closed_start,
        "latest_closed_end": latest_closed_end,
        "month_preview_start": month_preview_start,
        "month_preview_end": month_preview_end,
        "analysis_breadcrumb_items": [{"label": "Categorias", "href": None}],
        "analysis_back_href": None,
        "analysis_context_chips": [
            {"key": "period", "label": "Periodo", "value": analysis_data["period"]["label"]},
            *(
                [{"key": "focus_category", "label": "Categoria em foco", "value": valid_focus}]
                if valid_focus
                else []
            ),
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
            "Categorias vira uma area propria: o filtro define o periodo da leitura, do grafico principal, "
            "do ranking e da composicao clicavel."
        ),
        "analysis_extra_hidden_fields": [
            {"name": "focus_category", "value": valid_focus},
        ],
        "categories": all_categories,
        "category_rows": category_rows,
        "category_breakdown": breakdown,
        "category_composition": composition,
        "recent_loads": recent_loads,
        "top_category": top_category,
        "consumption_chart": analysis_data["charts"]["consumption_monthly"],
        "category_chart": analysis_data["charts"]["categories"],
        "active_categories_count": len([category for category in all_categories if category.is_active]),
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
    return render_admin(
        request,
        "admin/categories.html",
        _categories_page_context(
            db,
            selection_mode=selection_mode,
            month=month,
            period_start=period_start,
            period_end=period_end,
            focus_category=focus_category,
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
    return RedirectResponse(url=unquote(return_to or "/admin/categories"), status_code=303)


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
    return RedirectResponse(url=unquote(return_to or "/admin/categories"), status_code=303)
