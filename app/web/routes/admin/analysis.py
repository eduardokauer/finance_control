from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import latest_analysis_run_for_period, renderable_analysis_html, resolve_analysis_period
from app.services.analysis import build_analysis_snapshot, parse_analysis_payload

from .helpers import render_admin

router = APIRouter()

HOME_LENS_LABELS = {
    "cash": "Visão de Caixa",
    "competence": "Visão de Competência",
}

ORIGIN_BLOCK_LABELS = {
    "cards": "cards",
    "chart": "gráfico",
    "categories": "categorias",
    "alerts": "alertas",
    "conference": "conferência",
}


def _url_with_query(path: str, params: dict[str, str | int | None]) -> str:
    filtered = {key: value for key, value in params.items() if value not in (None, "")}
    if not filtered:
        return path
    return f"{path}?{urlencode(filtered)}"


def _lens_label(lens: str | None) -> str | None:
    return HOME_LENS_LABELS.get(lens or "")


def _origin_block_label(origin_block: str | None) -> str | None:
    return ORIGIN_BLOCK_LABELS.get(origin_block or "")


def _build_context_chips(
    *,
    period_label: str,
    active_lens: str,
    base_path: str,
    origin: str | None,
    origin_block: str | None,
    home_chart_mode: str | None,
    home_chart_compare: str | None,
) -> list[dict[str, str]]:
    chips = [{"key": "period", "label": "Período", "value": period_label}]
    lens_label = _lens_label(active_lens)
    if lens_label:
        chips.append(
            {
                "key": "lens",
                "label": "Lente ativa" if base_path == "/admin" else "Lente de origem",
                "value": lens_label,
            }
        )
    if origin == "summary":
        chips.append({"key": "origin", "label": "Origem", "value": "Resumo"})
    origin_label = _origin_block_label(origin_block)
    if origin_label:
        chips.append({"key": "origin_block", "label": "Bloco", "value": origin_label})
    if origin_block == "chart":
        if home_chart_mode == "rolling_12":
            chips.append({"key": "chart_mode", "label": "Horizonte", "value": "Últimos 12 meses"})
        elif home_chart_mode == "year":
            chips.append({"key": "chart_mode", "label": "Horizonte", "value": "Ano"})
        if home_chart_compare:
            compare_label = {
                "income": "Entradas" if active_lens == "cash" else "Receitas",
                "expense": "Saídas" if active_lens == "cash" else "Despesas",
                "balance": "Fluxo líquido" if active_lens == "cash" else "Resultado",
            }.get(home_chart_compare, home_chart_compare)
            chips.append({"key": "chart_compare", "label": "Comparação", "value": compare_label})
    return chips


def _build_focus_banner(
    *,
    base_path: str,
    origin: str | None,
    origin_block: str | None,
    active_lens: str,
    home_chart_mode: str | None,
    home_chart_compare: str | None,
) -> dict | None:
    if origin != "summary":
        return None

    lens_label = _lens_label(active_lens) or "Leitura atual"
    compare_label = {
        "income": "Entradas" if active_lens == "cash" else "Receitas",
        "expense": "Saídas" if active_lens == "cash" else "Despesas",
        "balance": "Fluxo líquido" if active_lens == "cash" else "Resultado",
    }.get(home_chart_compare or "", "métrica atual")
    chart_mode_label = "Últimos 12 meses" if home_chart_mode == "rolling_12" else "Ano"

    if base_path == "/admin/analysis":
        if origin_block == "cards":
            return {
                "key": "cards",
                "title": "Leitura geral aberta a partir dos cards do resumo",
                "body": f"Você veio da {lens_label}. Esta tela aprofunda a leitura geral do período sem perder o contexto de origem.",
                "href": "#analysis-overview-section",
                "link_label": "Ir para a leitura principal",
            }
        if origin_block == "chart":
            return {
                "key": "chart",
                "title": "Leitura histórica aberta a partir do gráfico principal",
                "body": f"Contexto restaurado do resumo: {lens_label}, horizonte {chart_mode_label.lower()} e comparação focada em {compare_label.lower()}.",
                "href": "#analysis-historical-section",
                "link_label": "Ir para a leitura histórica",
            }
        if origin_block == "categories":
            return {
                "key": "categories",
                "title": "Categorias abertas a partir do comparativo rápido da home",
                "body": "A leitura chegou ao breakdown categorial completo com o mesmo período e a mesma lente de origem preservados.",
                "href": "#analysis-category-history-section",
                "link_label": "Ir para categorias e histórico",
            }
        if origin_block == "alerts":
            return {
                "key": "alerts",
                "title": "Alertas e ações abertos a partir do resumo",
                "body": "Os sinais determinísticos abaixo mantêm o período e a lente de origem para facilitar a continuidade da decisão.",
                "href": "#analysis-alerts-section",
                "link_label": "Ir para alertas e ações",
            }

    if base_path == "/admin/conference" and origin_block == "conference":
        return {
            "key": "conference",
            "title": "Conferência aberta a partir do resumo",
            "body": f"Esta auditoria preserva o período e a lente de origem ({lens_label}) para apoiar a validação da leitura principal.",
            "href": "#conference-coverage-section",
            "link_label": "Ir para a cobertura da leitura",
        }

    return None


def _analysis_page_context(
    db: Session,
    *,
    base_path: str,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
    home_lens: str | None = None,
    home_chart_mode: str | None = None,
    home_chart_year: int | None = None,
    home_chart_compare: str | None = None,
    origin: str | None = None,
    origin_block: str | None = None,
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

    summary_query_params = {
        "selection_mode": selected_mode,
        "month": month_value if selected_mode == "month" else None,
        "period_start": resolved_start.isoformat(),
        "period_end": resolved_end.isoformat(),
        "home_lens": home_lens,
        "home_chart_mode": home_chart_mode,
        "home_chart_year": home_chart_year if home_chart_mode == "year" else None,
        "home_chart_compare": home_chart_compare,
    }

    analysis_run = latest_analysis_run_for_period(db, period_start=resolved_start, period_end=resolved_end)
    live_snapshot = build_analysis_snapshot(
        db,
        period_start=resolved_start,
        period_end=resolved_end,
        home_lens=home_lens or "cash",
        home_chart_mode=home_chart_mode or "year",
        home_chart_year=home_chart_year,
        home_chart_compare=home_chart_compare,
    )
    payload_snapshot = parse_analysis_payload(analysis_run.payload) if analysis_run else None
    if payload_snapshot and "conciliation_signals" not in payload_snapshot:
        payload_snapshot["conciliation_signals"] = live_snapshot["conciliation_signals"]
    if payload_snapshot and "conciliated_month" not in payload_snapshot:
        payload_snapshot["conciliated_month"] = live_snapshot["conciliated_month"]
    if payload_snapshot and "primary_summary" not in payload_snapshot:
        payload_snapshot["primary_summary"] = live_snapshot["primary_summary"]
    if payload_snapshot:
        payload_snapshot["home_cards"] = live_snapshot["home_cards"]
        payload_snapshot["home_yearly_chart"] = live_snapshot["home_yearly_chart"]
        payload_snapshot["home_category_comparison"] = live_snapshot["home_category_comparison"]
        payload_snapshot["home_dashboard"] = live_snapshot["home_dashboard"]
        payload_snapshot["category_breakdown"] = live_snapshot["category_breakdown"]
        payload_snapshot["category_history"] = live_snapshot["category_history"]
        payload_snapshot["categories"] = live_snapshot["categories"]
        payload_snapshot["top_expense_categories"] = live_snapshot["top_expense_categories"]
        payload_snapshot["alerts"] = live_snapshot["alerts"]
        payload_snapshot["actions"] = live_snapshot["actions"]
        payload_snapshot.setdefault("charts", {})
        payload_snapshot["charts"]["categories"] = live_snapshot["charts"]["categories"]
    analysis_data = payload_snapshot or live_snapshot
    home_dashboard = analysis_data.get("home_dashboard", {})
    active_chart = home_dashboard.get("chart", {})
    active_lens = home_dashboard.get("active_lens", home_lens or "cash")
    effective_home_chart_mode = active_chart.get("mode") or home_chart_mode or "year"
    effective_home_chart_year = active_chart.get("selected_year") if effective_home_chart_mode == "year" else None
    effective_home_chart_compare = active_chart.get("compare_metric") or home_chart_compare
    shared_summary_state = {
        **summary_query_params,
        "home_lens": active_lens,
        "home_chart_mode": effective_home_chart_mode,
        "home_chart_year": effective_home_chart_year,
        "home_chart_compare": effective_home_chart_compare,
    }
    page_query_params = {
        **shared_summary_state,
        "origin": origin,
        "origin_block": origin_block,
    }

    if base_path == "/admin" and home_dashboard:
        for lens_item in home_dashboard.get("lenses", []):
            lens_item["is_active"] = lens_item["key"] == active_lens
            lens_item["href"] = _url_with_query(
                "/admin",
                {
                    **summary_query_params,
                    "home_lens": lens_item["key"],
                },
            )

        for mode_item in active_chart.get("mode_tabs", []):
            mode_item["is_active"] = mode_item["key"] == active_chart.get("mode")
            mode_item["href"] = _url_with_query(
                "/admin",
                {
                    **summary_query_params,
                    "home_lens": active_lens,
                    "home_chart_mode": mode_item["key"],
                    "home_chart_year": active_chart.get("selected_year") if mode_item["key"] == "year" else None,
                },
            )

        for compare_item in active_chart.get("compare_tabs", []):
            compare_item["is_active"] = compare_item["key"] == active_chart.get("compare_metric")
            compare_item["href"] = _url_with_query(
                "/admin",
                {
                    **summary_query_params,
                    "home_lens": active_lens,
                    "home_chart_mode": active_chart.get("mode"),
                    "home_chart_year": active_chart.get("selected_year") if active_chart.get("mode") == "year" else None,
                    "home_chart_compare": compare_item["key"],
                },
            )

    priority_alerts_source = home_dashboard.get("alerts") if base_path == "/admin" else None
    priority_actions_source = home_dashboard.get("actions") if base_path == "/admin" else None
    analysis_urls = {
        "summary": _url_with_query("/admin", shared_summary_state),
        "detail": _url_with_query("/admin/analysis", page_query_params),
        "conference": _url_with_query("/admin/conference", page_query_params),
        "operations": "/admin/operations",
        "return_to": _url_with_query(base_path, shared_summary_state if base_path == "/admin" else page_query_params),
        "contextual": {
            "cards_detail": _url_with_query("/admin/analysis", {**shared_summary_state, "origin": "summary", "origin_block": "cards"}),
            "chart_detail": _url_with_query("/admin/analysis", {**shared_summary_state, "origin": "summary", "origin_block": "chart"}),
            "categories_detail": _url_with_query("/admin/analysis", {**shared_summary_state, "origin": "summary", "origin_block": "categories"}),
            "alerts_detail": _url_with_query("/admin/analysis", {**shared_summary_state, "origin": "summary", "origin_block": "alerts"}),
            "conference": _url_with_query("/admin/conference", {**shared_summary_state, "origin": "summary", "origin_block": "conference"}),
        },
    }
    analysis_context_chips = _build_context_chips(
        period_label=analysis_data["period"]["label"],
        active_lens=active_lens,
        base_path=base_path,
        origin=origin,
        origin_block=origin_block,
        home_chart_mode=effective_home_chart_mode,
        home_chart_compare=effective_home_chart_compare,
    )
    analysis_focus_banner = _build_focus_banner(
        base_path=base_path,
        origin=origin,
        origin_block=origin_block,
        active_lens=active_lens,
        home_chart_mode=effective_home_chart_mode,
        home_chart_compare=effective_home_chart_compare,
    )
    analysis_breadcrumb_items = [{"label": "Resumo", "href": analysis_urls["summary"] if base_path != "/admin" else None}]
    if base_path == "/admin/analysis":
        analysis_breadcrumb_items.append({"label": "Análise detalhada", "href": None})
    elif base_path == "/admin/conference":
        analysis_breadcrumb_items.append({"label": "Conferência", "href": None})
    return {
        "selection_mode": selected_mode,
        "period_start": resolved_start,
        "period_end": resolved_end,
        "month_value": month_value,
        "latest_closed_start": latest_closed_start,
        "latest_closed_end": latest_closed_end,
        "month_preview_start": month_preview_start,
        "month_preview_end": month_preview_end,
        "summary": analysis_data.get("primary_summary", analysis_data["summary"]),
        "analysis_run": analysis_run,
        "analysis_data": analysis_data,
        "analysis_html_fragment": renderable_analysis_html(analysis_run.html_output) if analysis_run else None,
        "llm_html_available": False,
        "priority_alerts": (priority_alerts_source or analysis_data.get("alerts", []))[:3],
        "priority_actions": (priority_actions_source or analysis_data.get("actions", []))[:2],
        "analysis_extra_hidden_fields": [
            {"name": "home_lens", "value": active_lens},
            {"name": "home_chart_mode", "value": effective_home_chart_mode},
            {"name": "home_chart_year", "value": effective_home_chart_year},
            {"name": "home_chart_compare", "value": effective_home_chart_compare},
            {"name": "origin", "value": origin},
            {"name": "origin_block", "value": origin_block},
        ],
        "analysis_urls": analysis_urls,
        "analysis_breadcrumb_items": analysis_breadcrumb_items,
        "analysis_back_href": analysis_urls["summary"] if base_path in ("/admin/analysis", "/admin/conference") else None,
        "analysis_context_chips": analysis_context_chips,
        "analysis_focus_banner": analysis_focus_banner,
        "analysis_global_tabs": home_dashboard.get("lenses", []) if base_path == "/admin" else [],
        "analysis_controls_intro": (
            "Período e lente reorganizam a leitura inteira do resumo. Os controles do gráfico continuam locais ao bloco histórico."
            if base_path == "/admin"
            else "Esses controles afetam a página inteira. A lente de origem e o contexto de navegação seguem preservados abaixo."
        ),
    }


def admin_summary_page(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    home_lens: str | None = None,
    home_chart_mode: str | None = None,
    home_chart_year: int | None = None,
    home_chart_compare: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/summary.html",
        _analysis_page_context(
            db,
            base_path="/admin",
            selection_mode=selection_mode,
            month=month,
            period_start=period_start,
            period_end=period_end,
            home_lens=home_lens,
            home_chart_mode=home_chart_mode,
            home_chart_year=home_chart_year,
            home_chart_compare=home_chart_compare,
        ),
    )


@router.get("/summary", response_class=HTMLResponse)
def admin_summary_alias_page(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    home_lens: str | None = None,
    home_chart_mode: str | None = None,
    home_chart_year: int | None = None,
    home_chart_compare: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return admin_summary_page(
        request=request,
        selection_mode=selection_mode,
        month=month,
        period_start=period_start,
        period_end=period_end,
        home_lens=home_lens,
        home_chart_mode=home_chart_mode,
        home_chart_year=home_chart_year,
        home_chart_compare=home_chart_compare,
        db=db,
        _=_,
    )


@router.get("/analysis", response_class=HTMLResponse)
def admin_analysis_page(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    home_lens: str | None = None,
    home_chart_mode: str | None = None,
    home_chart_year: int | None = None,
    home_chart_compare: str | None = None,
    origin: str | None = None,
    origin_block: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/analysis.html",
        _analysis_page_context(
            db,
            base_path="/admin/analysis",
            selection_mode=selection_mode,
            month=month,
            period_start=period_start,
            period_end=period_end,
            home_lens=home_lens,
            home_chart_mode=home_chart_mode,
            home_chart_year=home_chart_year,
            home_chart_compare=home_chart_compare,
            origin=origin,
            origin_block=origin_block,
        ),
    )


@router.get("/conference", response_class=HTMLResponse)
def admin_conference_page(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    home_lens: str | None = None,
    home_chart_mode: str | None = None,
    home_chart_year: int | None = None,
    home_chart_compare: str | None = None,
    origin: str | None = None,
    origin_block: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/conference.html",
        _analysis_page_context(
            db,
            base_path="/admin/conference",
            selection_mode=selection_mode,
            month=month,
            period_start=period_start,
            period_end=period_end,
            home_lens=home_lens,
            home_chart_mode=home_chart_mode,
            home_chart_year=home_chart_year,
            home_chart_compare=home_chart_compare,
            origin=origin,
            origin_block=origin_block,
        ),
    )
