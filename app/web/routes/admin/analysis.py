from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import (
    latest_analysis_run_for_period,
    list_available_analysis_months,
    list_recent_source_files,
    renderable_analysis_html,
    resolve_analysis_period,
)
from app.services.analysis import (
    build_analysis_snapshot,
    build_conciliated_composition_snapshot,
    build_invoice_operational_snapshot,
    build_statement_operational_snapshot,
    format_currency_br,
    parse_analysis_payload,
)
from app.services.credit_card_bills import list_credit_card_invoices

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


def _merge_payload_section_defaults(
    payload_snapshot: dict,
    live_snapshot: dict,
    *,
    section_name: str,
    fallback_section_name: str | None = None,
) -> None:
    current_section = payload_snapshot.get(section_name)
    if current_section is None and fallback_section_name:
        current_section = payload_snapshot.get(fallback_section_name)
    live_section = live_snapshot.get(section_name, {})
    if isinstance(current_section, dict) and isinstance(live_section, dict):
        payload_snapshot[section_name] = {**live_section, **current_section}
    elif current_section is None:
        payload_snapshot[section_name] = live_section


def _build_overview_cards(*, conciliated_month: dict, period_label: str) -> list[dict]:
    return [
        {
            "eyebrow": f"Conciliado | {period_label}",
            "title": "Receitas reais",
            "subtitle": "Transferências de entrada ficam fora da leitura principal do mês.",
            "value": conciliated_month["real_bank_income_display"],
            "value_class": "amount-positive",
            "detail": f"Entradas totais: {conciliated_month['bank_income_display']}",
        },
        {
            "eyebrow": period_label,
            "title": "Despesas reais",
            "subtitle": "Transferências de saída ficam fora e pagamentos conciliados são substituídos pela fatura.",
            "value": conciliated_month["real_conciliated_expense_display"],
            "value_class": "amount-negative",
            "detail": f"Saídas totais: {conciliated_month['total_bank_outflow_display']}",
        },
        {
            "eyebrow": period_label,
            "title": "Saldo real",
            "subtitle": "Saldo final da leitura principal sem transferências técnicas.",
            "value": conciliated_month["real_conciliated_balance_display"],
            "value_class": "amount-positive" if conciliated_month["real_conciliated_balance_total"] >= 0 else "amount-negative",
            "detail": (
                f"Transferências fora da leitura: "
                f"{conciliated_month['transfer_income_display']} em entradas | "
                f"{conciliated_month['transfer_expense_display']} em saídas"
            ),
        },
        {
            "eyebrow": period_label,
            "title": "Faturas conciliadas",
            "subtitle": "Quantidade de faturas que entraram na leitura principal deste período.",
            "value": str(conciliated_month["included_invoice_count"]),
            "value_class": "trend-stable",
            "detail": f"{conciliated_month['outside_invoices_total']} fora da leitura principal",
        },
    ]


def _build_alerts_with_links(alerts: list[dict], state: dict[str, str | int | None]) -> list[dict]:
    linked_alerts = []
    for alert in alerts:
        title = (alert.get("title") or "").lower()
        if "nao categorizado" in title or "não categorizado" in title:
            href = _url_with_query(
                "/admin/transactions",
                {
                    "period_start": state.get("period_start"),
                    "period_end": state.get("period_end"),
                    "uncategorized_only": "true",
                },
            )
            link_label = "Abrir lançamentos não categorizados"
        elif "saldo" in title:
            href = _url_with_query(
                "/admin/transactions",
                {
                    "period_start": state.get("period_start"),
                    "period_end": state.get("period_end"),
                    "transaction_kind": "expense",
                },
            )
            link_label = "Abrir lançamentos do período"
        else:
            href = _url_with_query(
                "/admin/categories",
                {
                    "selection_mode": state.get("selection_mode"),
                    "month": state.get("month"),
                    "period_start": state.get("period_start"),
                    "period_end": state.get("period_end"),
                },
            )
            link_label = "Abrir categorias do período"
        linked_alerts.append({**alert, "href": href, "link_label": link_label})
    return linked_alerts


def _build_overview_charts(analysis_data: dict) -> dict[str, dict]:
    period_label = analysis_data["period"]["month_reference_label"]
    return {
        "conciliated": {
            "title": "Visão conciliada",
            "note": f"Mesmo histórico da visão conciliada, ao redor de {period_label}, com receitas e despesas reais sem transferências técnicas.",
            "canvas_id": "overview-conciliated-chart",
            "kind": "cash-flow",
            "data": analysis_data["charts"]["conciliated"],
        },
        "statement": {
            "title": "Visão de Extrato",
            "note": "Mesmo histórico bruto da conta usado na visão de extrato, sem substituir pagamentos por composição de fatura.",
            "canvas_id": "overview-statement-chart",
            "kind": "cash-flow",
            "data": analysis_data["charts"]["monthly"],
        },
        "invoice": {
            "title": "Visão de Faturas",
            "note": "Mesmo histórico de itens e valores faturados usado na visão de faturas do período.",
            "canvas_id": "overview-invoice-chart",
            "kind": "invoice",
            "data": analysis_data["charts"]["invoice_monthly"],
        },
        "categories": {
            "title": "Categorias do período",
            "note": "Leitura categorial consolidada do período com total mensal visível e filtros rápidos na legenda.",
            "canvas_id": "overview-categories-chart",
            "kind": "categories",
            "data": analysis_data["charts"]["categories_monthly"],
        },
    }


def _matches_description(value: str, expected: str | None) -> bool:
    if not expected:
        return True
    return expected.casefold() in (value or "").casefold()


def _filter_statement_rows(
    rows: list[dict],
    *,
    category: str | None,
    transaction_kind: str | None,
    description: str | None,
    scope: str | None,
    sort: str | None,
) -> list[dict]:
    filtered_rows = rows
    if category:
        filtered_rows = [row for row in filtered_rows if row["category"] == category]
    if transaction_kind:
        filtered_rows = [row for row in filtered_rows if row["transaction_kind"] == transaction_kind]
    if description:
        filtered_rows = [
            row
            for row in filtered_rows
            if _matches_description(row["description"], description)
            or _matches_description(row["description_normalized"], description)
        ]
    if scope == "linked":
        filtered_rows = [row for row in filtered_rows if row["is_conciliated_bank_payment"]]
    elif scope == "unlinked":
        filtered_rows = [row for row in filtered_rows if not row["is_conciliated_bank_payment"]]
    elif scope == "included":
        filtered_rows = [row for row in filtered_rows if row["is_included"]]
    elif scope == "excluded":
        filtered_rows = [row for row in filtered_rows if not row["is_included"]]
    elif scope == "excluded_transfer":
        filtered_rows = [row for row in filtered_rows if not row["is_included"] and row["is_transfer_technical"]]
    elif scope == "excluded_payment":
        filtered_rows = [row for row in filtered_rows if not row["is_included"] and row["is_conciliated_bank_payment"]]

    sort_key = sort or "recent"
    if sort_key == "amount_desc":
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (abs(row["amount"]), row["transaction_date"], row["id"]),
            reverse=True,
        )
    elif sort_key == "amount_asc":
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (abs(row["amount"]), row["transaction_date"], row["id"]),
        )
    elif sort_key == "description":
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (
                row["description_normalized"].casefold(),
                row["transaction_date"],
                row["id"],
            ),
        )
    else:
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (row["transaction_date"], row["id"]),
            reverse=True,
        )
    return filtered_rows


def _filter_invoice_rows(
    rows: list[dict],
    *,
    category: str | None,
    item_type: str | None,
    description: str | None,
    conciliation_status: str | None,
    visibility: str | None,
    card_label: str | None,
    sort: str | None,
) -> list[dict]:
    filtered_rows = rows
    if category:
        filtered_rows = [row for row in filtered_rows if row["category"] == category]
    if item_type:
        filtered_rows = [row for row in filtered_rows if row["item_type"] == item_type]
    if conciliation_status:
        filtered_rows = [row for row in filtered_rows if row["conciliation_status"] == conciliation_status]
    if visibility == "visible":
        filtered_rows = [row for row in filtered_rows if row["is_visible_in_conciliated"]]
    elif visibility == "outside":
        filtered_rows = [row for row in filtered_rows if not row["is_visible_in_conciliated"]]
    if card_label:
        filtered_rows = [row for row in filtered_rows if row["card_label"] == card_label]
    if description:
        filtered_rows = [
            row
            for row in filtered_rows
            if _matches_description(row["description"], description)
            or _matches_description(row["description_normalized"], description)
        ]

    sort_key = sort or "recent"
    if sort_key == "amount_desc":
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (abs(row["amount"]), row["purchase_date"], row["id"]),
            reverse=True,
        )
    elif sort_key == "amount_asc":
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (abs(row["amount"]), row["purchase_date"], row["id"]),
        )
    elif sort_key == "description":
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (
                row["description_normalized"].casefold(),
                row["purchase_date"],
                row["id"],
            ),
        )
    else:
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (row["purchase_date"], row["id"]),
            reverse=True,
        )
    return filtered_rows


def _filter_invoice_entries(
    entries: list,
    *,
    period_start: date,
    period_end: date,
    conciliation_status: str | None = None,
    card_label: str | None = None,
) -> list:
    filtered_entries = [
        entry
        for entry in entries
        if period_start <= entry.invoice.due_date <= period_end
    ]
    if conciliation_status:
        filtered_entries = [entry for entry in filtered_entries if entry.conciliation_status == conciliation_status]
    if card_label:
        filtered_entries = [entry for entry in filtered_entries if entry.card.card_label == card_label]
    return filtered_entries


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
    if lens_label and base_path != "/admin":
        chips.append(
            {
                "key": "lens",
                "label": "Lente de origem",
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
                "href": "#conciliated-composition",
                "link_label": "Ir para a composição",
            }
        if origin_block == "chart":
            return {
                "key": "chart",
                "title": "Leitura histórica aberta a partir do gráfico principal",
                "body": f"Contexto restaurado do resumo: {lens_label}, horizonte {chart_mode_label.lower()} e comparação focada em {compare_label.lower()}.",
                "href": "#conciliated-cashflow-chart",
                "link_label": "Ir para a leitura histórica",
            }
        if origin_block == "categories":
            return {
                "key": "categories",
                "title": "Categorias abertas a partir do comparativo rápido da home",
                "body": "A leitura chegou ao breakdown categorial completo com o mesmo período e a mesma lente de origem preservados.",
                "href": "#conciliated-categories-chart",
                "link_label": "Ir para categorias e histórico",
            }
        if origin_block == "alerts":
            return {
                "key": "alerts",
                "title": "Alertas e ações abertos a partir do resumo",
                "body": "Os sinais determinísticos abaixo mantêm o período e a lente de origem para facilitar a continuidade da decisão.",
                "href": "#conciliated-bank-table",
                "link_label": "Ir para alertas e ações",
            }

    if base_path == "/admin/conference" and origin_block == "conference":
        return {
            "key": "conference",
            "title": "Conferência aberta a partir do resumo",
            "body": f"Esta auditoria preserva o período e a lente de origem ({lens_label}) para apoiar a validação da leitura principal.",
            "href": "#statement-table",
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
    overview_mode = base_path == "/admin"
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
    summary_home_lens = None if overview_mode else home_lens
    summary_chart_mode = None if overview_mode else home_chart_mode
    summary_chart_year = None if overview_mode else home_chart_year
    summary_chart_compare = None if overview_mode else home_chart_compare
    live_snapshot = build_analysis_snapshot(
        db,
        period_start=resolved_start,
        period_end=resolved_end,
        home_lens=summary_home_lens or "cash",
        home_chart_mode=summary_chart_mode or "year",
        home_chart_year=summary_chart_year,
        home_chart_compare=summary_chart_compare,
    )
    payload_snapshot = parse_analysis_payload(analysis_run.payload) if analysis_run else None
    analysis_data = live_snapshot
    conciliated_composition = build_conciliated_composition_snapshot(
        db,
        period_start=resolved_start,
        period_end=resolved_end,
    )
    home_dashboard = analysis_data.get("home_dashboard", {})
    active_chart = home_dashboard.get("chart", {})
    active_lens = home_dashboard.get("active_lens", home_lens or "cash")
    effective_home_chart_mode = active_chart.get("mode") or home_chart_mode or "year"
    effective_home_chart_year = active_chart.get("selected_year") if effective_home_chart_mode == "year" else None
    effective_home_chart_compare = active_chart.get("compare_metric") or home_chart_compare
    shared_summary_state = (
        {
            **summary_query_params,
            "home_lens": active_lens,
            "home_chart_mode": effective_home_chart_mode,
            "home_chart_year": effective_home_chart_year,
            "home_chart_compare": effective_home_chart_compare,
        }
        if not overview_mode
        else {
            "selection_mode": selected_mode,
            "month": month_value if selected_mode == "month" else None,
            "period_start": resolved_start.isoformat(),
            "period_end": resolved_end.isoformat(),
        }
    )
    overview_state = {
        "selection_mode": selected_mode,
        "month": month_value if selected_mode == "month" else None,
        "period_start": resolved_start.isoformat(),
        "period_end": resolved_end.isoformat(),
    }
    page_query_params = {
        **shared_summary_state,
        "origin": origin,
        "origin_block": origin_block,
    }

    priority_alerts_source = home_dashboard.get("alerts") if base_path == "/admin" else None
    priority_actions_source = home_dashboard.get("actions") if base_path == "/admin" else None
    overview_alerts = _build_alerts_with_links((priority_alerts_source or analysis_data.get("alerts", []))[:4], overview_state)
    overview_cards = _build_overview_cards(
        conciliated_month=conciliated_composition["summary"],
        period_label=analysis_data["period"]["month_reference_label"],
    )
    overview_charts = _build_overview_charts(analysis_data)
    analysis_urls = {
        "summary": _url_with_query("/admin", overview_state),
        "detail": _url_with_query("/admin/analysis", page_query_params),
        "conference": _url_with_query("/admin/conference", page_query_params),
        "conference_technical": _url_with_query("/admin/conference/technical", page_query_params),
        "invoice_view": _url_with_query("/admin/credit-card-invoices", overview_state),
        "categories_view": _url_with_query("/admin/categories", overview_state),
        "operations": "/admin/operations",
        "return_to": _url_with_query(base_path, shared_summary_state if base_path == "/admin" else page_query_params),
        "contextual": {
            "cards_detail": _url_with_query("/admin/analysis", {**overview_state, "origin": "summary", "origin_block": "cards"}),
            "chart_detail": _url_with_query("/admin/analysis", {**overview_state, "origin": "summary", "origin_block": "chart"}),
            "categories_detail": _url_with_query("/admin/categories", {**overview_state, "origin": "summary", "origin_block": "categories"}),
            "alerts_detail": _url_with_query("/admin/analysis", {**overview_state, "origin": "summary", "origin_block": "alerts"}),
            "conference": _url_with_query("/admin/conference", {**overview_state, "origin": "summary", "origin_block": "conference"}),
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
        analysis_breadcrumb_items.append({"label": "Visão conciliada", "href": None})
    elif base_path == "/admin/conference":
        analysis_breadcrumb_items.append({"label": "Visão de Extrato", "href": None})
    elif base_path == "/admin/conference/technical":
        analysis_breadcrumb_items.append({"label": "Visão de Extrato", "href": analysis_urls["conference"]})
        analysis_breadcrumb_items.append({"label": "Auditoria técnica", "href": None})
    if base_path == "/admin/analysis":
        recent_loads = list_recent_source_files(db, source_types=["bank_statement", "credit_card_bill"], limit=10)
    elif base_path in ("/admin/conference", "/admin/conference/technical"):
        recent_loads = list_recent_source_files(db, source_types=["bank_statement"], limit=10)
    else:
        recent_loads = []
    analysis_month_options = list_available_analysis_months(db)
    latest_closed_value = f"{latest_closed_start.year:04d}-{latest_closed_start.month:02d}"
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
        "summary": analysis_data.get("primary_summary", analysis_data["summary"]),
        "analysis_run": analysis_run,
        "analysis_data": analysis_data,
        "conciliated_composition": conciliated_composition,
        "analysis_html_fragment": renderable_analysis_html(analysis_run.html_output) if analysis_run else None,
        "llm_html_available": False,
        "priority_alerts": (priority_alerts_source or analysis_data.get("alerts", []))[:3],
        "priority_actions": (priority_actions_source or analysis_data.get("actions", []))[:2],
        "overview_cards": overview_cards,
        "overview_alerts": overview_alerts,
        "overview_charts": overview_charts,
        "analysis_extra_hidden_fields": (
            []
            if overview_mode
            else [
                {"name": "home_lens", "value": active_lens},
                {"name": "home_chart_mode", "value": effective_home_chart_mode},
                {"name": "home_chart_year", "value": effective_home_chart_year},
                {"name": "home_chart_compare", "value": effective_home_chart_compare},
                {"name": "origin", "value": origin},
                {"name": "origin_block", "value": origin_block},
            ]
        ),
        "analysis_urls": analysis_urls,
        "analysis_breadcrumb_items": analysis_breadcrumb_items,
        "analysis_back_href": (
            analysis_urls["summary"]
            if base_path in ("/admin/analysis", "/admin/conference")
            else analysis_urls["conference"]
            if base_path == "/admin/conference/technical"
            else None
        ),
        "analysis_context_chips": analysis_context_chips,
        "analysis_focus_banner": analysis_focus_banner,
        "recent_loads": recent_loads,
        "analysis_global_tabs": [],
        "format_currency_br": format_currency_br,
        "analysis_controls_intro": (
            "Período global da página."
            if base_path != "/admin/conference/technical"
            else "Período global da auditoria."
        ),
    }


def _statement_view_context(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    category: str | None,
    description: str | None,
    transaction_kind: str | None,
    scope: str | None,
    sort: str | None,
    conciliated_view: bool = False,
) -> dict:
    operational_snapshot = build_statement_operational_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
        conciliated_view=conciliated_view,
    )
    filtered_rows = _filter_statement_rows(
        operational_snapshot["rows"],
        category=category,
        transaction_kind=transaction_kind,
        description=description,
        scope=scope,
        sort=sort,
    )
    full_rows = operational_snapshot["rows"]
    return {
        "statement_rows": filtered_rows,
        "statement_filters": {
            "category": category or "",
            "description": description or "",
            "transaction_kind": transaction_kind or "",
            "scope": scope or "",
            "sort": sort or "recent",
        },
        "statement_filter_options": {
            "categories": sorted({row["category"] for row in full_rows if row["category"]}),
            "transaction_kinds": sorted({row["transaction_kind"] for row in full_rows if row["transaction_kind"]}),
        },
        "statement_stats": {
            "total_rows": len(filtered_rows),
            "full_total_rows": operational_snapshot["transaction_count"],
            "included_count": sum(1 for row in filtered_rows if row["is_included"]),
            "excluded_count": sum(1 for row in filtered_rows if not row["is_included"]),
            "linked_count": sum(1 for row in filtered_rows if row["is_conciliated_bank_payment"]),
            "unlinked_count": sum(1 for row in filtered_rows if not row["is_conciliated_bank_payment"]),
        },
    }


def _invoice_view_context(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    category: str | None,
    description: str | None,
    item_type: str | None,
    conciliation_status: str | None,
    visibility: str | None,
    card_label: str | None,
    sort: str | None,
    conciliated_only: bool = False,
) -> dict:
    operational_snapshot = build_invoice_operational_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
        conciliated_only=conciliated_only,
    )
    filtered_rows = _filter_invoice_rows(
        operational_snapshot["rows"],
        category=category,
        item_type=item_type,
        description=description,
        conciliation_status=conciliation_status,
        visibility=visibility,
        card_label=card_label,
        sort=sort,
    )
    invoice_entries = _filter_invoice_entries(
        list_credit_card_invoices(db),
        period_start=period_start,
        period_end=period_end,
        conciliation_status=conciliation_status,
        card_label=card_label,
    )
    full_rows = operational_snapshot["rows"]
    return {
        "invoice_rows": filtered_rows,
        "invoice_entries": invoice_entries,
        "invoice_filters": {
            "category": category or "",
            "description": description or "",
            "item_type": item_type or "",
            "conciliation_status": conciliation_status or "",
            "visibility": visibility or "",
            "card_label": card_label or "",
            "sort": sort or "recent",
        },
        "invoice_filter_options": {
            "categories": sorted({row["category"] for row in full_rows if row["category"]}),
            "item_types": sorted({row["item_type"] for row in full_rows if row["item_type"]}),
            "card_labels": sorted({row["card_label"] for row in full_rows if row["card_label"]}),
            "conciliation_statuses": sorted({row["conciliation_status"] for row in full_rows if row["conciliation_status"]}),
        },
        "invoice_stats": {
            "total_rows": len(filtered_rows),
            "full_total_rows": operational_snapshot["item_count"],
            "visible_count": sum(1 for row in filtered_rows if row["is_visible_in_conciliated"]),
            "invoice_count": len(invoice_entries),
        },
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
    statement_category: str | None = None,
    statement_description: str | None = None,
    statement_transaction_kind: str | None = None,
    statement_scope: str | None = None,
    statement_sort: str | None = "recent",
    invoice_category: str | None = None,
    invoice_description: str | None = None,
    invoice_item_type: str | None = None,
    invoice_card_label: str | None = None,
    invoice_status: str | None = None,
    invoice_sort: str | None = "recent",
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    page_context = _analysis_page_context(
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
    )
    page_context.update(
        _statement_view_context(
            db,
            period_start=page_context["period_start"],
            period_end=page_context["period_end"],
            category=statement_category,
            description=statement_description,
            transaction_kind=statement_transaction_kind,
            scope=statement_scope,
            sort=statement_sort,
            conciliated_view=True,
        )
    )
    page_context.update(
        _invoice_view_context(
            db,
            period_start=page_context["period_start"],
            period_end=page_context["period_end"],
            category=invoice_category,
            description=invoice_description,
            item_type=invoice_item_type,
            conciliation_status=invoice_status,
            visibility="visible",
            card_label=invoice_card_label,
            sort=invoice_sort,
            conciliated_only=True,
        )
    )
    page_context["conciliated_composition"] = build_conciliated_composition_snapshot(
        db,
        period_start=page_context["period_start"],
        period_end=page_context["period_end"],
    )
    return render_admin(
        request,
        "admin/analysis.html",
        page_context,
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
    statement_category: str | None = None,
    statement_description: str | None = None,
    statement_transaction_kind: str | None = None,
    statement_scope: str | None = None,
    statement_sort: str | None = "recent",
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    page_context = _analysis_page_context(
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
    )
    page_context.update(
        _statement_view_context(
            db,
            period_start=page_context["period_start"],
            period_end=page_context["period_end"],
            category=statement_category,
            description=statement_description,
            transaction_kind=statement_transaction_kind,
            scope=statement_scope,
            sort=statement_sort,
            conciliated_view=False,
        )
    )
    return render_admin(
        request,
        "admin/conference.html",
        page_context,
    )


@router.get("/conference/technical", response_class=HTMLResponse)
def admin_conference_technical_page(
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
    page_context = _analysis_page_context(
        db,
        base_path="/admin/conference/technical",
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
    )
    return render_admin(
        request,
        "admin/conference_technical.html",
        page_context,
    )
