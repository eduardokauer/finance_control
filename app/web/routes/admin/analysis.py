from __future__ import annotations

from datetime import date
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

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
    build_conciliated_operational_snapshot,
    build_invoice_operational_snapshot,
    build_statement_operational_snapshot,
    format_currency_br,
    parse_analysis_payload,
)
from app.services.credit_card_bills import list_credit_card_invoices

from .helpers import (
    is_htmx_request,
    parse_optional_date,
    persist_admin_period_selection,
    render_admin,
    restore_admin_period_selection,
    templates,
)

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


def _extend_url(
    url: str,
    *,
    params: dict[str, str | int | None] | None = None,
    fragment: str | None = None,
) -> str:
    split_url = urlsplit(url)
    merged_params = dict(parse_qsl(split_url.query, keep_blank_values=True))
    if params:
        for key, value in params.items():
            if value in (None, ""):
                merged_params.pop(key, None)
            else:
                merged_params[key] = str(value)
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            urlencode(merged_params),
            fragment or split_url.fragment,
        )
    )


def _relative_request_url(request: Request) -> str:
    return request.url.path + (f"?{request.url.query}" if request.url.query else "")


def _analysis_shell_template(base_path: str) -> str | None:
    return {
        "/admin": "admin/partials/summary_page_shell.html",
        "/admin/analysis": "admin/partials/analysis_page_shell.html",
        "/admin/conference": "admin/partials/conference_page_shell.html",
    }.get(base_path)


def _analysis_shell_target(base_path: str) -> str | None:
    return {
        "/admin": "#summary-view-shell",
        "/admin/analysis": "#analysis-view-shell",
        "/admin/conference": "#conference-view-shell",
    }.get(base_path)


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


def _build_overview_cards(
    *,
    conciliated_month: dict,
    period_label: str,
    cards_detail_href: str,
) -> list[dict]:
    return [
        {
            "eyebrow": f"Conciliado | {period_label}",
            "title": "Receitas reais",
            "subtitle": "Transferências de entrada ficam fora da leitura principal do mês.",
            "value": conciliated_month["real_bank_income_display"],
            "value_class": "amount-positive",
            "detail": f"Entradas totais: {conciliated_month['bank_income_display']}",
            "action": {
                "href": _extend_url(
                    cards_detail_href,
                    params={
                        "conciliated_analytic_type": "income",
                    },
                    fragment="conciliated-considered-table",
                ),
                "key": "real-income",
            },
        },
        {
            "eyebrow": period_label,
            "title": "Despesas reais",
            "subtitle": "Transferências de saída ficam fora e pagamentos conciliados são substituídos pela fatura.",
            "value": conciliated_month["real_conciliated_expense_display"],
            "value_class": "amount-negative",
            "detail": f"Saídas totais: {conciliated_month['total_bank_outflow_display']}",
            "action": {
                "href": _extend_url(
                    cards_detail_href,
                    params={"conciliated_analytic_type": "expense"},
                    fragment="conciliated-considered-table",
                ),
                "key": "real-expense",
            },
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
            "action": {
                "href": _extend_url(cards_detail_href, fragment="conciliated-considered-table"),
                "key": "real-balance",
            },
        },
        {
            "eyebrow": period_label,
            "title": "Faturas conciliadas",
            "subtitle": "Quantidade de faturas que entraram na leitura principal deste período.",
            "value": str(conciliated_month["included_invoice_count"]),
            "value_class": "trend-stable",
            "detail": f"{conciliated_month['outside_invoices_total']} fora da leitura principal",
            "action": {
                "href": _extend_url(cards_detail_href, fragment="conciliated-invoices-section"),
                "key": "conciliated-invoices",
            },
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


def _build_period_category_chart(
    *,
    title: str,
    note: str,
    canvas_id: str,
    data: dict,
    href_builder,
) -> dict:
    labels = data.get("labels", [])
    category_names = data.get("category_names", labels)
    flow_kinds = data.get("flow_kinds", [None] * len(labels))
    return {
        "title": title,
        "note": note,
        "canvas_id": canvas_id,
        "data": {
            **data,
            "hrefs": [
                href_builder(
                    category_names[index],
                    flow_kinds[index] if index < len(flow_kinds) else None,
                )
                for index, _label in enumerate(labels)
            ],
        },
    }


def _build_overview_charts(analysis_data: dict, analysis_urls: dict) -> dict[str, dict]:
    period_label = analysis_data["period"]["month_reference_label"]
    return {
        "conciliated": {
            "title": "Visão conciliada",
            "note": f"Mesmo histórico da visão conciliada, ao redor de {period_label}, com receitas e despesas reais sem transferências técnicas.",
            "canvas_id": "overview-conciliated-chart",
            "kind": "cash-flow",
            "data": analysis_data["charts"]["conciliated"],
            "period_categories": _build_period_category_chart(
                title="Categorias no período",
                note="Totais da leitura conciliada no recorte atual, do maior para o menor, com drill down por categoria.",
                canvas_id="overview-conciliated-period-categories-chart",
                data=analysis_data["charts"]["conciliated_categories_period"],
                href_builder=lambda category_name, flow_kind: _extend_url(
                    analysis_urls["contextual"]["chart_detail"],
                    params={
                        "conciliated_category": category_name,
                        "conciliated_analytic_type": flow_kind if flow_kind in {"income", "expense", "credit"} else None,
                    },
                    fragment="conciliated-considered-table",
                ),
            ),
        },
        "statement": {
            "title": "Visão de Extrato",
            "note": "Mesmo histórico bruto da conta usado na visão de extrato, sem substituir pagamentos por composição de fatura.",
            "canvas_id": "overview-statement-chart",
            "kind": "cash-flow",
            "data": analysis_data["charts"]["monthly"],
            "period_categories": _build_period_category_chart(
                title="Categorias do período",
                note="Totais do extrato no recorte atual, do maior para o menor, preservando categorias de receita, despesa e transferência.",
                canvas_id="overview-statement-period-categories-chart",
                data=analysis_data["charts"]["statement_categories_period"],
                href_builder=lambda category_name, flow_kind: _extend_url(
                    analysis_urls["contextual"]["conference"],
                    params={
                        "statement_category": category_name,
                        "statement_transaction_kind": flow_kind if flow_kind in {"income", "expense", "transfer"} else None,
                    },
                    fragment="statement-table",
                ),
            ),
        },
        "invoice": {
            "title": "Visão de Faturas",
            "note": "Mesmo histórico de itens e valores faturados usado na visão de faturas do período.",
            "canvas_id": "overview-invoice-chart",
            "kind": "invoice",
            "data": analysis_data["charts"]["invoice_monthly"],
            "period_categories": _build_period_category_chart(
                title="Categorias do período",
                note="Totais dos itens de fatura no recorte atual, ordenados do maior para o menor.",
                canvas_id="overview-invoice-period-categories-chart",
                data=analysis_data["charts"]["invoice_categories_period"],
                href_builder=lambda category_name, flow_kind: _extend_url(
                    analysis_urls["invoice_view"],
                    params={
                        "category": category_name,
                        "item_type": "charge" if flow_kind == "expense" else "credit" if flow_kind == "credit" else None,
                    },
                    fragment="invoice-items-table",
                ),
            ),
        },
        "categories": {
            "title": "Categorias do período",
            "note": "Leitura categorial consolidada do período com total mensal visível e filtros rápidos na legenda.",
            "canvas_id": "overview-categories-chart",
            "kind": "categories",
            "data": analysis_data["charts"]["categories_monthly"],
            "period_categories": _build_period_category_chart(
                title="Valor por categoria no período",
                note="Mesma leitura consolidada da área de categorias, ordenada do maior para o menor no recorte atual.",
                canvas_id="overview-categories-period-categories-chart",
                data=analysis_data["charts"]["overview_categories_period"],
                href_builder=lambda category_name, _flow_kind: _extend_url(
                    analysis_urls["contextual"]["categories_detail"],
                    params={
                        "focus_category": category_name,
                        "selected_category": category_name,
                    },
                    fragment="category-composition-section",
                ),
            ),
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


def _filter_conciliated_rows(
    rows: list[dict],
    *,
    category: str | None,
    description: str | None,
    origin: str | None,
    analytic_type: str | None,
    sort: str | None,
) -> list[dict]:
    filtered_rows = rows
    if category:
        filtered_rows = [row for row in filtered_rows if row["category"] == category]
    if origin:
        filtered_rows = [row for row in filtered_rows if row["source"] == origin]
    if analytic_type:
        filtered_rows = [row for row in filtered_rows if row["analytic_type"] == analytic_type]
    if description:
        filtered_rows = [
            row
            for row in filtered_rows
            if _matches_description(row["description"], description)
            or _matches_description(row["description_normalized"], description)
            or _matches_description(row["reference"], description)
        ]
    sort_key = sort or "recent"
    if sort_key == "amount_desc":
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (abs(row["impact_amount"]), row["event_date"], row["record_id"]),
            reverse=True,
        )
    elif sort_key == "amount_asc":
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (abs(row["impact_amount"]), row["event_date"], row["record_id"]),
        )
    elif sort_key == "description":
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (
                row["description_normalized"].casefold(),
                row["event_date"],
                row["record_id"],
            ),
        )
    else:
        filtered_rows = sorted(
            filtered_rows,
            key=lambda row: (row["event_date"], abs(row["impact_amount"]), row["record_id"]),
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
    priority_alerts_source = home_dashboard.get("alerts") if base_path == "/admin" else None
    priority_actions_source = home_dashboard.get("actions") if base_path == "/admin" else None
    overview_alerts = _build_alerts_with_links((priority_alerts_source or analysis_data.get("alerts", []))[:4], overview_state)
    overview_cards = _build_overview_cards(
        conciliated_month=conciliated_composition["summary"],
        period_label=analysis_data["period"]["month_reference_label"],
        cards_detail_href=analysis_urls["contextual"]["cards_detail"],
    )
    overview_charts = _build_overview_charts(analysis_data, analysis_urls)
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
        "analysis_show_generate": base_path in ("/admin/analysis", "/admin/conference"),
        "analysis_context_chips": analysis_context_chips,
        "analysis_focus_banner": analysis_focus_banner,
        "recent_loads": recent_loads,
        "analysis_global_tabs": [],
        "format_currency_br": format_currency_br,
        "analysis_shell_target": _analysis_shell_target(base_path),
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


def _conciliated_operational_context(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    category: str | None,
    description: str | None,
    origin: str | None,
    analytic_type: str | None,
    sort: str | None,
) -> dict:
    operational_snapshot = build_conciliated_operational_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
    )
    filtered_rows = _filter_conciliated_rows(
        operational_snapshot["rows"],
        category=category,
        description=description,
        origin=origin,
        analytic_type=analytic_type,
        sort=sort,
    )
    full_rows = operational_snapshot["rows"]
    return {
        "conciliated_rows": filtered_rows,
        "conciliated_filters": {
            "category": category or "",
            "description": description or "",
            "origin": origin or "",
            "analytic_type": analytic_type or "",
            "sort": sort or "recent",
        },
        "conciliated_filter_options": {
            "categories": sorted({row["category"] for row in full_rows if row["category"]}),
            "origins": sorted({row["source"] for row in full_rows if row["source"]}),
            "analytic_types": sorted({row["analytic_type"] for row in full_rows if row["analytic_type"]}),
        },
        "conciliated_stats": {
            "total_rows": len(filtered_rows),
            "full_total_rows": operational_snapshot["row_count"],
            "statement_count": sum(1 for row in filtered_rows if row["source"] == "statement"),
            "invoice_count": sum(1 for row in filtered_rows if row["source"] == "invoice"),
            "income_count": sum(1 for row in filtered_rows if row["analytic_type"] == "income"),
            "expense_count": sum(1 for row in filtered_rows if row["analytic_type"] == "expense"),
            "credit_count": sum(1 for row in filtered_rows if row["analytic_type"] == "credit"),
            "net_impact_display": format_currency_br(sum(abs(row["impact_amount"]) for row in filtered_rows)),
            "net_result_display": format_currency_br(sum(row["impact_amount"] for row in filtered_rows)),
        },
    }


def _summary_page_context(
    db: Session,
    *,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
    home_lens: str | None,
    home_chart_mode: str | None,
    home_chart_year: int | None,
    home_chart_compare: str | None,
) -> dict:
    return _analysis_page_context(
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
    )


def _analysis_detail_page_context(
    db: Session,
    *,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
    home_lens: str | None,
    home_chart_mode: str | None,
    home_chart_year: int | None,
    home_chart_compare: str | None,
    origin: str | None,
    origin_block: str | None,
    conciliated_category: str | None,
    conciliated_description: str | None,
    conciliated_origin: str | None,
    conciliated_analytic_type: str | None,
    conciliated_sort: str | None,
    statement_category: str | None,
    statement_description: str | None,
    statement_transaction_kind: str | None,
    statement_scope: str | None,
    statement_sort: str | None,
    invoice_category: str | None,
    invoice_description: str | None,
    invoice_item_type: str | None,
    invoice_card_label: str | None,
    invoice_status: str | None,
    invoice_sort: str | None,
) -> dict:
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
        _conciliated_operational_context(
            db,
            period_start=page_context["period_start"],
            period_end=page_context["period_end"],
            category=conciliated_category,
            description=conciliated_description,
            origin=conciliated_origin,
            analytic_type=conciliated_analytic_type,
            sort=conciliated_sort,
        )
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
    return page_context


def _conference_page_context(
    db: Session,
    *,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
    home_lens: str | None,
    home_chart_mode: str | None,
    home_chart_year: int | None,
    home_chart_compare: str | None,
    origin: str | None,
    origin_block: str | None,
    statement_category: str | None,
    statement_description: str | None,
    statement_transaction_kind: str | None,
    statement_scope: str | None,
    statement_sort: str | None,
) -> dict:
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
    return page_context


def _render_analysis_shell(request: Request, *, base_path: str, context: dict, status_code: int = 200) -> HTMLResponse:
    template_name = _analysis_shell_template(base_path)
    if not template_name:
        raise ValueError(f"Unsupported analysis shell base path: {base_path}")
    return templates.TemplateResponse(
        request,
        template_name,
        {"request": request, **context},
        status_code=status_code,
    )


def render_analysis_shell_for_return_to(request: Request, db: Session, return_to: str, *, status_code: int = 200) -> HTMLResponse:
    split_url = urlsplit(unquote(return_to or "/admin"))
    params = dict(parse_qsl(split_url.query, keep_blank_values=True))
    base_path = split_url.path or "/admin"

    common = {
        "selection_mode": params.get("selection_mode") or None,
        "month": params.get("month") or None,
        "period_start": parse_optional_date(params.get("period_start")),
        "period_end": parse_optional_date(params.get("period_end")),
        "home_lens": params.get("home_lens") or None,
        "home_chart_mode": params.get("home_chart_mode") or None,
        "home_chart_year": int(params["home_chart_year"]) if params.get("home_chart_year") else None,
        "home_chart_compare": params.get("home_chart_compare") or None,
        "origin": params.get("origin") or None,
        "origin_block": params.get("origin_block") or None,
    }

    if base_path in {"/admin", "/admin/summary"}:
        context = _summary_page_context(db, **common)
        context["topbar_period_oob"] = True
    elif base_path == "/admin/analysis":
        context = _analysis_detail_page_context(
            db,
            **common,
            conciliated_category=params.get("conciliated_category") or None,
            conciliated_description=params.get("conciliated_description") or None,
            conciliated_origin=params.get("conciliated_origin") or None,
            conciliated_analytic_type=params.get("conciliated_analytic_type") or None,
            conciliated_sort=params.get("conciliated_sort") or "recent",
            statement_category=params.get("statement_category") or None,
            statement_description=params.get("statement_description") or None,
            statement_transaction_kind=params.get("statement_transaction_kind") or None,
            statement_scope=params.get("statement_scope") or None,
            statement_sort=params.get("statement_sort") or "recent",
            invoice_category=params.get("invoice_category") or None,
            invoice_description=params.get("invoice_description") or None,
            invoice_item_type=params.get("invoice_item_type") or None,
            invoice_card_label=params.get("invoice_card_label") or None,
            invoice_status=params.get("invoice_status") or None,
            invoice_sort=params.get("invoice_sort") or "recent",
        )
        context["topbar_period_oob"] = True
    elif base_path == "/admin/conference":
        context = _conference_page_context(
            db,
            **common,
            statement_category=params.get("statement_category") or None,
            statement_description=params.get("statement_description") or None,
            statement_transaction_kind=params.get("statement_transaction_kind") or None,
            statement_scope=params.get("statement_scope") or None,
            statement_sort=params.get("statement_sort") or "recent",
        )
        context["topbar_period_oob"] = True
    else:
        raise ValueError(f"Unsupported analysis return_to path: {base_path}")
    persist_admin_period_selection(
        request,
        selection_mode=context.get("selection_mode"),
        month=context.get("month_value"),
        period_start=context.get("period_start"),
        period_end=context.get("period_end"),
    )
    normalized_base_path = "/admin" if base_path == "/admin/summary" else base_path
    return _render_analysis_shell(request, base_path=normalized_base_path, context=context, status_code=status_code)


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
    restored_period = restore_admin_period_selection(
        request,
        selection_mode=selection_mode,
        month=month,
        period_start=period_start,
        period_end=period_end,
    )
    page_context = _summary_page_context(
        db,
        selection_mode=restored_period["selection_mode"],
        month=restored_period["month"],
        period_start=restored_period["period_start"],
        period_end=restored_period["period_end"],
        home_lens=home_lens,
        home_chart_mode=home_chart_mode,
        home_chart_year=home_chart_year,
        home_chart_compare=home_chart_compare,
    )
    persist_admin_period_selection(
        request,
        selection_mode=page_context["selection_mode"],
        month=page_context["month_value"],
        period_start=page_context["period_start"],
        period_end=page_context["period_end"],
    )
    if is_htmx_request(request):
        page_context["topbar_period_oob"] = True
        response = _render_analysis_shell(request, base_path="/admin", context=page_context)
        response.headers["HX-Push-Url"] = _relative_request_url(request)
        return response
    return render_admin(request, "admin/summary.html", page_context)


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
    conciliated_category: str | None = None,
    conciliated_description: str | None = None,
    conciliated_origin: str | None = None,
    conciliated_analytic_type: str | None = None,
    conciliated_sort: str | None = "recent",
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
    restored_period = restore_admin_period_selection(
        request,
        selection_mode=selection_mode,
        month=month,
        period_start=period_start,
        period_end=period_end,
    )
    page_context = _analysis_detail_page_context(
        db,
        selection_mode=restored_period["selection_mode"],
        month=restored_period["month"],
        period_start=restored_period["period_start"],
        period_end=restored_period["period_end"],
        home_lens=home_lens,
        home_chart_mode=home_chart_mode,
        home_chart_year=home_chart_year,
        home_chart_compare=home_chart_compare,
        origin=origin,
        origin_block=origin_block,
        conciliated_category=conciliated_category,
        conciliated_description=conciliated_description,
        conciliated_origin=conciliated_origin,
        conciliated_analytic_type=conciliated_analytic_type,
        conciliated_sort=conciliated_sort,
        statement_category=statement_category,
        statement_description=statement_description,
        statement_transaction_kind=statement_transaction_kind,
        statement_scope=statement_scope,
        statement_sort=statement_sort,
        invoice_category=invoice_category,
        invoice_description=invoice_description,
        invoice_item_type=invoice_item_type,
        invoice_card_label=invoice_card_label,
        invoice_status=invoice_status,
        invoice_sort=invoice_sort,
    )
    persist_admin_period_selection(
        request,
        selection_mode=page_context["selection_mode"],
        month=page_context["month_value"],
        period_start=page_context["period_start"],
        period_end=page_context["period_end"],
    )
    if is_htmx_request(request):
        page_context["topbar_period_oob"] = True
        response = _render_analysis_shell(request, base_path="/admin/analysis", context=page_context)
        response.headers["HX-Push-Url"] = _relative_request_url(request)
        return response
    return render_admin(request, "admin/analysis.html", page_context)


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
    restored_period = restore_admin_period_selection(
        request,
        selection_mode=selection_mode,
        month=month,
        period_start=period_start,
        period_end=period_end,
    )
    page_context = _conference_page_context(
        db,
        selection_mode=restored_period["selection_mode"],
        month=restored_period["month"],
        period_start=restored_period["period_start"],
        period_end=restored_period["period_end"],
        home_lens=home_lens,
        home_chart_mode=home_chart_mode,
        home_chart_year=home_chart_year,
        home_chart_compare=home_chart_compare,
        origin=origin,
        origin_block=origin_block,
        statement_category=statement_category,
        statement_description=statement_description,
        statement_transaction_kind=statement_transaction_kind,
        statement_scope=statement_scope,
        statement_sort=statement_sort,
    )
    persist_admin_period_selection(
        request,
        selection_mode=page_context["selection_mode"],
        month=page_context["month_value"],
        period_start=page_context["period_start"],
        period_end=page_context["period_end"],
    )
    if is_htmx_request(request):
        page_context["topbar_period_oob"] = True
        response = _render_analysis_shell(request, base_path="/admin/conference", context=page_context)
        response.headers["HX-Push-Url"] = _relative_request_url(request)
        return response
    return render_admin(request, "admin/conference.html", page_context)


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
    restored_period = restore_admin_period_selection(
        request,
        selection_mode=selection_mode,
        month=month,
        period_start=period_start,
        period_end=period_end,
    )
    page_context = _analysis_page_context(
        db,
        base_path="/admin/conference/technical",
        selection_mode=restored_period["selection_mode"],
        month=restored_period["month"],
        period_start=restored_period["period_start"],
        period_end=restored_period["period_end"],
        home_lens=home_lens,
        home_chart_mode=home_chart_mode,
        home_chart_year=home_chart_year,
        home_chart_compare=home_chart_compare,
        origin=origin,
        origin_block=origin_block,
    )
    persist_admin_period_selection(
        request,
        selection_mode=page_context["selection_mode"],
        month=page_context["month_value"],
        period_start=page_context["period_start"],
        period_end=page_context["period_end"],
    )
    return render_admin(
        request,
        "admin/conference_technical.html",
        page_context,
    )
