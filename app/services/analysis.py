from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.repositories.models import AnalysisRun, CreditCard, CreditCardInvoice, CreditCardInvoiceConciliation, CreditCardInvoiceItem, Transaction
from app.services.credit_card_bills import build_conciliation_analytics_snapshot, classify_credit_card_invoice_item, map_conciliated_bank_payment_signals
from app.utils.normalization import normalize_description

UNCATEGORIZED_NAMES = (
    "N\u00e3o Categorizado",
    "Nao Categorizado",
    "N\u00c3\u00a3o Categorizado",
    "N\u00c3\u0192\u00c2\u00a3o Categorizado",
)
MONTH_LABELS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
TECHNICAL_TRANSFER_KEYS = {"transferencias"}
TECHNICAL_CARD_BILL_KEYS = {"pagamento de fatura", "pagamento fatura"}


def format_currency_br(value: float) -> str:
    sign = "-" if value < 0 else ""
    formatted = f"{abs(float(value)):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{sign}R$ {formatted}"


def format_signed_currency_br(value: float) -> str:
    if abs(float(value)) < 0.01:
        return "R$ 0,00"
    prefix = "+" if value > 0 else "-"
    return f"{prefix}{format_currency_br(abs(float(value)))}"


def format_percent_br(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%".replace(".", ",")


def format_percent_points_br(value: float) -> str:
    return f"{abs(value) * 100:.1f} p.p.".replace(".", ",")


def format_signed_percent_points_br(value: float) -> str:
    if abs(float(value)) < 0.0001:
        return "0,0 p.p."
    prefix = "+" if value > 0 else "-"
    return f"{prefix}{format_percent_points_br(value)}"


def format_date_br(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def format_month_label(value: date) -> str:
    return f"{MONTH_LABELS[value.month - 1]}/{value.year}"


def month_start(value: date) -> date:
    return value.replace(day=1)


def month_end(value: date) -> date:
    if value.month == 12:
        next_month = date(value.year + 1, 1, 1)
    else:
        next_month = date(value.year, value.month + 1, 1)
    return next_month - timedelta(days=1)


def add_months(value: date, offset: int) -> date:
    year = value.year + ((value.month - 1 + offset) // 12)
    month = ((value.month - 1 + offset) % 12) + 1
    return date(year, month, 1)


def is_uncategorized(category: str | None) -> bool:
    return category in UNCATEGORIZED_NAMES


def _normalized_category_name(value: str | None) -> str:
    return normalize_description(value or "")


def _analysis_category_key(value: str | None) -> str:
    return normalize_description(_analysis_category_name(value))


def _is_transfer_technical(tx: Transaction) -> bool:
    return tx.transaction_kind == "transfer" or _normalized_category_name(tx.category) in TECHNICAL_TRANSFER_KEYS


def _is_card_bill_technical(tx: Transaction) -> bool:
    return bool(tx.is_card_bill_payment) or _normalized_category_name(tx.category) in TECHNICAL_CARD_BILL_KEYS


def _expense_amount(tx: Transaction) -> float:
    return abs(float(tx.amount)) if float(tx.amount) < 0 and tx.should_count_in_spending else 0.0


def _income_amount(tx: Transaction) -> float:
    return float(tx.amount) if float(tx.amount) > 0 else 0.0


def _load_transactions_for_period(db: Session, *, period_start: date, period_end: date) -> list[Transaction]:
    return db.scalars(
        select(Transaction).where(Transaction.transaction_date >= period_start, Transaction.transaction_date <= period_end)
    ).all()


def _load_conciliated_invoice_items_for_purchase_period(
    db: Session,
    *,
    period_start: date,
    period_end: date,
) -> list[tuple[CreditCardInvoiceItem, int]]:
    return db.execute(
        select(CreditCardInvoiceItem, CreditCardInvoice.id)
        .join(CreditCardInvoice, CreditCardInvoice.id == CreditCardInvoiceItem.invoice_id)
        .join(CreditCardInvoiceConciliation, CreditCardInvoiceConciliation.invoice_id == CreditCardInvoice.id)
        .where(
            CreditCardInvoiceItem.purchase_date >= period_start,
            CreditCardInvoiceItem.purchase_date <= period_end,
            CreditCardInvoiceConciliation.status == "conciliated",
        )
        .order_by(CreditCardInvoiceItem.purchase_date.asc(), CreditCardInvoiceItem.id.asc())
    ).all()


def _build_summary(txs: list[Transaction]) -> dict:
    income_total = sum(_income_amount(tx) for tx in txs)
    expense_total = sum(_expense_amount(tx) for tx in txs)
    uncategorized_total = sum(_expense_amount(tx) for tx in txs if is_uncategorized(tx.category))
    balance = income_total - expense_total
    return {
        "income_total": income_total,
        "expense_total": expense_total,
        "balance": balance,
        "uncategorized_total": uncategorized_total,
        "transaction_count": len(txs),
        "income_display": format_currency_br(income_total),
        "expense_display": format_currency_br(expense_total),
        "balance_display": format_currency_br(balance),
        "uncategorized_display": format_currency_br(uncategorized_total),
    }


def _build_metric_change(current: float, previous: float) -> dict:
    delta = current - previous
    if abs(delta) < 0.01:
        trend = "stable"
    elif delta > 0:
        trend = "up"
    else:
        trend = "down"
    percent = None if abs(previous) < 0.01 else delta / abs(previous)
    return {
        "current": current,
        "previous": previous,
        "delta": delta,
        "percent": percent,
        "trend": trend,
        "trend_label": {"up": "subiu", "down": "desceu", "stable": "estável"}[trend],
        "current_display": format_currency_br(current),
        "previous_display": format_currency_br(previous),
        "delta_display": format_currency_br(delta),
        "delta_signed_display": format_signed_currency_br(delta),
        "percent_display": format_percent_br(percent),
    }


def _build_percent_point_change(current: float, previous: float) -> dict:
    delta = current - previous
    if abs(delta) < 0.0001:
        trend = "stable"
    elif delta > 0:
        trend = "up"
    else:
        trend = "down"
    return {
        "current": current,
        "previous": previous,
        "delta": delta,
        "percent": None,
        "trend": trend,
        "trend_label": {"up": "subiu", "down": "desceu", "stable": "estável"}[trend],
        "current_display": format_percent_br(current),
        "previous_display": format_percent_br(previous),
        "delta_display": format_percent_points_br(delta),
        "delta_signed_display": format_signed_percent_points_br(delta),
        "percent_display": None,
    }


def _sum_consumption_total_from_breakdown(*, breakdown: dict) -> float:
    return sum(
        row["expense_total"]
        for row in breakdown["rows"]
        if row["expense_total"] > 0 and not row["is_technical"]
    )


def _build_home_month_snapshot(
    db: Session,
    *,
    anchor_month: date,
    month_txs: list[Transaction] | None = None,
    category_breakdown: dict | None = None,
) -> dict:
    period_start = month_start(anchor_month)
    period_end = month_end(anchor_month)
    materialized_txs = (
        month_txs
        if month_txs is not None
        else _load_transactions_for_period(
            db,
            period_start=period_start,
            period_end=period_end,
        )
    )
    materialized_breakdown = (
        category_breakdown
        if category_breakdown is not None
        else _build_conciliated_category_breakdown(
            db,
            period_start=period_start,
            period_end=period_end,
            current_txs=materialized_txs,
        )
    )
    consumption_total = _sum_consumption_total_from_breakdown(breakdown=materialized_breakdown)
    return {
        "month": period_start.strftime("%Y-%m"),
        "label": format_month_label(period_start),
        "period_start": period_start,
        "period_end": period_end,
        "flow_summary": _build_summary(materialized_txs),
        "flow_has_activity": bool(materialized_txs),
        "consumption_total": consumption_total,
        "consumption_display": format_currency_br(consumption_total),
        "consumption_has_activity": bool(materialized_breakdown["rows"]),
    }


def _build_home_metric_card(
    *,
    key: str,
    title: str,
    subtitle: str,
    current: float,
    previous: float | None,
    reference_label: str,
    value_class: str,
    is_primary: bool = False,
    current_display_override: str | None = None,
    detail: str | None = None,
    change: dict | None = None,
    comparison_primary_display: str | None = None,
    comparison_secondary_display: str | None = None,
) -> dict:
    materialized_change = change if change is not None else (
        _build_metric_change(current, previous)
        if previous is not None
        else None
    )
    return {
        "key": key,
        "title": title,
        "subtitle": subtitle,
        "current": current,
        "current_display": current_display_override or format_currency_br(current),
        "value_class": value_class,
        "is_primary": is_primary,
        "reference_label": reference_label,
        "detail": detail,
        "change": materialized_change,
        "comparison_available": materialized_change is not None,
        "comparison_primary_display": comparison_primary_display
        or (
            f"{materialized_change['delta_signed_display']} vs {reference_label}"
            if materialized_change is not None
            else None
        ),
        "comparison_secondary_display": comparison_secondary_display
        if comparison_secondary_display is not None
        else (
            materialized_change["percent_display"]
            if materialized_change is not None and materialized_change["percent"] is not None
            else None
        ),
    }


def _build_largest_expense_snapshot(month_txs: list[Transaction]) -> dict:
    expense_candidates = [tx for tx in month_txs if _expense_amount(tx) > 0]
    if not expense_candidates:
        return {
            "amount": 0.0,
            "display": format_currency_br(0.0),
            "description": "Sem saídas individuais no mês-base.",
            "has_expense": False,
        }

    largest = max(
        expense_candidates,
        key=lambda tx: (_expense_amount(tx), tx.transaction_date, tx.id or 0),
    )
    amount = _expense_amount(largest)
    return {
        "amount": amount,
        "display": format_currency_br(amount),
        "description": largest.description_raw or "Saída sem descrição",
        "has_expense": True,
    }


def _build_cash_home_cards(
    db: Session,
    *,
    anchor_month: date,
    current_month_txs: list[Transaction],
    current_category_breakdown: dict,
) -> dict:
    current_snapshot = _build_home_month_snapshot(
        db,
        anchor_month=anchor_month,
        month_txs=current_month_txs,
        category_breakdown=current_category_breakdown,
    )
    previous_month = add_months(month_start(anchor_month), -1)
    previous_snapshot = _build_home_month_snapshot(db, anchor_month=previous_month)
    previous_flow_summary = previous_snapshot["flow_summary"] if previous_snapshot["flow_has_activity"] else None
    current_largest_expense = _build_largest_expense_snapshot(current_month_txs)
    previous_month_txs = (
        _load_transactions_for_period(
            db,
            period_start=previous_snapshot["period_start"],
            period_end=previous_snapshot["period_end"],
        )
        if previous_snapshot["flow_has_activity"]
        else []
    )
    previous_largest_expense = (
        _build_largest_expense_snapshot(previous_month_txs)
        if previous_snapshot["flow_has_activity"]
        else None
    )

    return {
        "lens": "cash",
        "lens_label": "Visão de Caixa",
        "current_month_label": current_snapshot["label"],
        "previous_month_label": previous_snapshot["label"],
        "cards": [
            _build_home_metric_card(
                key="net_flow",
                title="Fluxo líquido do mês",
                subtitle="Entradas realizadas menos saídas realizadas no mês-base.",
                current=current_snapshot["flow_summary"]["balance"],
                previous=previous_flow_summary["balance"] if previous_flow_summary is not None else None,
                reference_label=previous_snapshot["label"],
                value_class="amount-positive" if current_snapshot["flow_summary"]["balance"] >= 0 else "amount-negative",
                is_primary=True,
            ),
            _build_home_metric_card(
                key="income",
                title="Entradas do mês",
                subtitle="Todas as entradas realizadas no período.",
                current=current_snapshot["flow_summary"]["income_total"],
                previous=previous_flow_summary["income_total"] if previous_flow_summary is not None else None,
                reference_label=previous_snapshot["label"],
                value_class="amount-positive",
            ),
            _build_home_metric_card(
                key="expense",
                title="Saídas do mês",
                subtitle="Todas as saídas realizadas no período.",
                current=current_snapshot["flow_summary"]["expense_total"],
                previous=previous_flow_summary["expense_total"] if previous_flow_summary is not None else None,
                reference_label=previous_snapshot["label"],
                value_class="amount-negative",
            ),
            _build_home_metric_card(
                key="largest_expense",
                title="Maior saída do mês",
                subtitle=(
                    "Maior lançamento individual de saída do mês-base."
                    if current_largest_expense["has_expense"]
                    else "Sem saídas individuais registradas no mês-base."
                ),
                current=current_largest_expense["amount"],
                previous=(
                    previous_largest_expense["amount"]
                    if previous_largest_expense is not None
                    else None
                ),
                reference_label=previous_snapshot["label"],
                value_class="amount-negative" if current_largest_expense["has_expense"] else "trend-stable",
                current_display_override=current_largest_expense["display"],
                detail=current_largest_expense["description"],
            ),
        ],
    }


def _build_competence_home_cards(
    db: Session,
    *,
    anchor_month: date,
    current_month_txs: list[Transaction],
    current_category_breakdown: dict,
) -> dict:
    current_snapshot = _build_home_month_snapshot(
        db,
        anchor_month=anchor_month,
        month_txs=current_month_txs,
        category_breakdown=current_category_breakdown,
    )
    previous_month = add_months(month_start(anchor_month), -1)
    previous_snapshot = _build_home_month_snapshot(db, anchor_month=previous_month)
    previous_has_base = previous_snapshot["flow_has_activity"] or previous_snapshot["consumption_has_activity"]

    current_revenue_total = current_snapshot["flow_summary"]["income_total"]
    current_expense_total = current_snapshot["consumption_total"]
    current_result_total = current_revenue_total - current_expense_total
    current_margin = current_result_total / current_revenue_total if current_revenue_total > 0 else None

    previous_revenue_total = previous_snapshot["flow_summary"]["income_total"] if previous_has_base else None
    previous_expense_total = previous_snapshot["consumption_total"] if previous_has_base else None
    previous_result_total = (
        (previous_revenue_total or 0.0) - (previous_expense_total or 0.0)
        if previous_has_base
        else None
    )
    previous_margin = (
        previous_result_total / previous_revenue_total
        if previous_has_base and previous_revenue_total is not None and previous_revenue_total > 0
        else None
    )
    margin_change = (
        _build_percent_point_change(current_margin, previous_margin)
        if current_margin is not None and previous_margin is not None
        else None
    )

    return {
        "lens": "competence",
        "lens_label": "Visão de Competência",
        "current_month_label": current_snapshot["label"],
        "previous_month_label": previous_snapshot["label"],
        "cards": [
            _build_home_metric_card(
                key="result",
                title="Resultado do mês",
                subtitle="Receitas por competência menos despesas por competência do mês-base.",
                current=current_result_total,
                previous=previous_result_total,
                reference_label=previous_snapshot["label"],
                value_class="amount-positive" if current_result_total >= 0 else "amount-negative",
                is_primary=True,
            ),
            _build_home_metric_card(
                key="competence_income",
                title="Receitas por competência",
                subtitle="Receitas reconhecidas no mês-base dentro da leitura mensal já disponível no produto.",
                current=current_revenue_total,
                previous=previous_revenue_total,
                reference_label=previous_snapshot["label"],
                value_class="amount-positive",
            ),
            _build_home_metric_card(
                key="competence_expense",
                title="Despesas por competência",
                subtitle="Despesas reconhecidas pela visão de consumo no mês-base.",
                current=current_expense_total,
                previous=previous_expense_total,
                reference_label=previous_snapshot["label"],
                value_class="amount-negative",
            ),
            _build_home_metric_card(
                key="margin",
                title="Margem do mês",
                subtitle="Resultado dividido pelas receitas por competência do mês-base.",
                current=current_margin or 0.0,
                previous=previous_margin,
                reference_label=previous_snapshot["label"],
                value_class=(
                    "amount-positive"
                    if current_margin is not None and current_margin >= 0
                    else ("amount-negative" if current_margin is not None else "trend-stable")
                ),
                current_display_override=format_percent_br(current_margin) if current_margin is not None else "—",
                change=margin_change,
                comparison_primary_display=(
                    f"{margin_change['delta_signed_display']} vs {previous_snapshot['label']}"
                    if margin_change is not None
                    else None
                ),
                comparison_secondary_display=None,
            ),
        ],
    }


def _build_home_cards(
    db: Session,
    *,
    anchor_month: date,
    current_month_txs: list[Transaction],
    current_category_breakdown: dict,
    lens: str = "cash",
) -> dict:
    if lens == "competence":
        return _build_competence_home_cards(
            db,
            anchor_month=anchor_month,
            current_month_txs=current_month_txs,
            current_category_breakdown=current_category_breakdown,
        )
    return _build_cash_home_cards(
        db,
        anchor_month=anchor_month,
        current_month_txs=current_month_txs,
        current_category_breakdown=current_category_breakdown,
    )


def _round_chart_value(value: float) -> float:
    return 0.0 if abs(float(value)) < 0.01 else round(float(value), 2)


def _build_cash_chart_month_metrics(db: Session, *, anchor_month: date) -> dict:
    snapshot = _build_home_month_snapshot(db, anchor_month=anchor_month)
    flow_summary = snapshot["flow_summary"]
    return {
        "month": anchor_month.strftime("%Y-%m"),
        "income_total": flow_summary["income_total"],
        "expense_total": flow_summary["expense_total"],
        "expense_chart_total": -flow_summary["expense_total"] if flow_summary["expense_total"] > 0 else 0.0,
        "balance": flow_summary["balance"],
        "transaction_count": flow_summary["transaction_count"],
    }


def _build_competence_chart_month_metrics(db: Session, *, anchor_month: date) -> dict:
    snapshot = _build_home_month_snapshot(db, anchor_month=anchor_month)
    revenue_total = snapshot["flow_summary"]["income_total"]
    expense_total = snapshot["consumption_total"]
    result_total = revenue_total - expense_total
    return {
        "month": anchor_month.strftime("%Y-%m"),
        "income_total": revenue_total,
        "expense_total": expense_total,
        "expense_chart_total": -expense_total if expense_total > 0 else 0.0,
        "balance": result_total,
        "transaction_count": snapshot["flow_summary"]["transaction_count"],
    }


def _chart_axis_label(value: date, *, mode: str) -> str:
    if mode == "year":
        return MONTH_LABELS[value.month - 1]
    return f"{MONTH_LABELS[value.month - 1]}/{str(value.year)[2:]}"


def _build_chart_month_sequence(*, anchor_month: date, mode: str, selected_year: int) -> list[date]:
    if mode == "year":
        return [date(selected_year, month_number, 1) for month_number in range(1, 13)]
    rolling_start = add_months(month_start(anchor_month), -11)
    return [add_months(rolling_start, offset) for offset in range(12)]


def _build_home_primary_chart(
    db: Session,
    *,
    anchor_month: date,
    lens: str,
    mode: str,
    selected_year: int,
    compare_metric: str,
) -> dict:
    value_key_map = {
        "balance": "balance",
        "income": "income_total",
        "expense": "expense_chart_total",
    }
    metric_map = {
        "cash": {
            "balance": {"label": "Fluxo líquido", "style": "cash-balance", "type": "line"},
            "income": {"label": "Entradas", "style": "cash-income", "type": "bar"},
            "expense": {"label": "Saídas", "style": "cash-expense", "type": "bar"},
        },
        "competence": {
            "balance": {"label": "Resultado", "style": "competence-balance", "type": "line"},
            "income": {"label": "Receitas", "style": "competence-income", "type": "bar"},
            "expense": {"label": "Despesas", "style": "competence-expense", "type": "bar"},
        },
    }
    metric_definitions = metric_map[lens]
    if compare_metric not in metric_definitions:
        compare_metric = "balance"

    current_months = _build_chart_month_sequence(
        anchor_month=anchor_month,
        mode=mode,
        selected_year=selected_year,
    )
    if mode == "year":
        comparison_months = [date(selected_year - 1, month_number, 1) for month_number in range(1, 13)]
    else:
        comparison_start = add_months(month_start(anchor_month), -23)
        comparison_months = [add_months(comparison_start, offset) for offset in range(12)]

    builder = _build_cash_chart_month_metrics if lens == "cash" else _build_competence_chart_month_metrics
    current_series = [builder(db, anchor_month=item) for item in current_months]
    comparison_series = [builder(db, anchor_month=item) for item in comparison_months]

    labels = [_chart_axis_label(item, mode=mode) for item in current_months]
    datasets: list[dict] = []
    for key, spec in metric_definitions.items():
        value_key = value_key_map[key]
        values = [
            _round_chart_value(series[value_key])
            for series in current_series
        ]
        datasets.append(
            {
                "type": spec["type"],
                "label": spec["label"],
                "style": spec["style"],
                "data": values,
            }
        )

    comparison_spec = metric_definitions[compare_metric]
    comparison_value_key = value_key_map[compare_metric]
    comparison_values = [
        _round_chart_value(series[comparison_value_key])
        for series in comparison_series
    ]
    datasets.append(
        {
            "type": "line",
            "label": f"{comparison_spec['label']} | período anterior",
            "style": f"comparison-{comparison_spec['style']}",
            "data": comparison_values,
            "dashed": True,
        }
    )

    all_zero = all(all(abs(value) < 0.01 for value in dataset["data"]) for dataset in datasets)
    if mode == "year":
        period_note = f"Ano calendário {selected_year}, de janeiro a dezembro, com meses zerados visíveis."
        comparison_note = f"Comparação mês a mês contra o ano calendário {selected_year - 1}."
    else:
        comparison_note = (
            f"Comparação contra a janela anterior até {format_month_label(add_months(anchor_month, -12))}."
        )
        period_note = f"Janela móvel de 12 meses ancorada em {format_month_label(anchor_month)}."

    lens_label = "Visão de Caixa" if lens == "cash" else "Visão de Competência"
    return {
        "lens": lens,
        "lens_label": lens_label,
        "mode": mode,
        "selected_year": selected_year,
        "compare_metric": compare_metric,
        "labels": labels,
        "datasets": datasets,
        "all_zero": all_zero,
        "title": f"{lens_label}: evolução principal",
        "note": f"{period_note} {comparison_note}",
    }


def _available_chart_years(db: Session, *, anchor_month: date) -> list[int]:
    earliest_month = _earliest_history_month(db)
    if earliest_month is None:
        return [anchor_month.year]
    return list(reversed(list(range(earliest_month.year, anchor_month.year + 1))))


def _build_home_category_comparison(db: Session, *, anchor_month: date, visible: bool = True) -> dict:
    current_snapshot = _build_conciliated_category_month_snapshot(db, anchor_month=anchor_month)
    previous_month = add_months(month_start(anchor_month), -1)
    earliest_month = _earliest_history_month(db)
    previous_snapshot = (
        _build_conciliated_category_month_snapshot(db, anchor_month=previous_month)
        if earliest_month is not None and previous_month >= earliest_month
        else None
    )
    previous_expense_by_category = (
        previous_snapshot["expense_by_category"]
        if previous_snapshot is not None and previous_snapshot["has_activity"]
        else {}
    )

    rows: list[dict] = []
    current_rows = [
        row
        for row in current_snapshot["breakdown"]["rows"]
        if row["expense_total"] > 0 and not row["is_technical"]
    ]
    current_rows.sort(key=lambda entry: entry["expense_total"], reverse=True)
    for item in current_rows[:5]:
        previous_total = previous_expense_by_category.get(item["name"], 0.0)
        change = _build_metric_change(item["expense_total"], previous_total)
        is_new_in_month = abs(previous_total) < 0.01
        rows.append(
            {
                "name": item["name"],
                "current_total": item["expense_total"],
                "current_display": item["expense_display"],
                "previous_total": previous_total,
                "previous_display": format_currency_br(previous_total),
                "change": change,
                "percent_available": change["percent"] is not None,
                "is_new_in_month": is_new_in_month,
            }
        )

    return {
        "current_month_label": current_snapshot["label"],
        "previous_month_label": format_month_label(previous_month),
        "rows": rows,
        "visible": visible,
        "note": (
            "Top 5 categorias de consumo do mês-base, ordenadas pelo maior gasto atual e comparadas com o mês anterior. "
            "A home segue como resumo; a leitura completa continua na análise detalhada."
        ),
    }


def _build_home_cash_summary(*, cash_cards: dict) -> dict:
    cards = {item["key"]: item for item in cash_cards["cards"]}
    return {
        "title": "Resumo executivo da Visão de Caixa",
        "executive_summary": (
            f"No mês-base, entradas de {cards['income']['current_display']}, saídas de "
            f"{cards['expense']['current_display']} e fluxo líquido de {cards['net_flow']['current_display']}."
        ),
        "coverage_note": (
            "Leitura ancorada na movimentação de caixa do período. Pagamentos de fatura seguem como liquidação de caixa, "
            "sem misturar essa visão com o consumo por competência."
        ),
    }


def _build_home_competence_summary(*, competence_cards: dict) -> dict:
    cards = {item["key"]: item for item in competence_cards["cards"]}
    return {
        "title": "Resumo executivo da Visão de Competência",
        "executive_summary": (
            f"No mês-base, receitas por competência de {cards['competence_income']['current_display']}, despesas por competência "
            f"de {cards['competence_expense']['current_display']} e resultado de {cards['result']['current_display']}."
        ),
        "coverage_note": (
            f"Margem do mês: {cards['margin']['current_display']}. A despesa usa a visão de consumo já consolidada; a receita "
            "segue a leitura mensal já disponível no produto, sem criar motor contábil novo."
        ),
    }


def _build_home_cash_alerts(*, cash_cards: dict) -> list[dict]:
    cards = {item["key"]: item for item in cash_cards["cards"]}
    alerts: list[dict] = []
    if cards["net_flow"]["current"] < 0:
        alerts.append(
            {
                "level": "danger",
                "title": "Fluxo de caixa negativo no mês",
                "body": (
                    f"A Visão de Caixa fechou o mês-base com fluxo líquido de {cards['net_flow']['current_display']}."
                ),
            }
        )
    if cards["largest_expense"]["current"] > 0:
        alerts.append(
            {
                "level": "warn",
                "title": "Maior saída individual sob atenção",
                "body": (
                    f"A maior saída do mês-base foi {cards['largest_expense']['current_display']} em "
                    f"{cards['largest_expense']['detail']}."
                ),
            }
        )
    return alerts[:5]


def _build_home_cash_actions(*, cash_cards: dict) -> list[dict]:
    cards = {item["key"]: item for item in cash_cards["cards"]}
    actions: list[dict] = []
    if cards["largest_expense"]["current"] > 0:
        actions.append(
            {
                "title": "Revisar a maior saída do mês",
                "body": (
                    f"Comece por {cards['largest_expense']['detail']} ({cards['largest_expense']['current_display']}) "
                    "antes de aprofundar a leitura na análise detalhada."
                ),
            }
        )
    if cards["net_flow"]["current"] < 0:
        actions.append(
            {
                "title": "Atacar o fluxo de caixa negativo",
                "body": (
                    "Priorize as maiores saídas já liquidadas no mês-base para recuperar caixa no período seguinte."
                ),
            }
        )
    return actions[:5]


def _build_home_competence_alerts(*, competence_cards: dict, consumption_context: dict) -> list[dict]:
    cards = {item["key"]: item for item in competence_cards["cards"]}
    alerts: list[dict] = []
    if cards["result"]["current"] < 0:
        alerts.append(
            {
                "level": "danger",
                "title": "Resultado negativo na Visão de Competência",
                "body": (
                    f"O mês-base fechou com resultado de {cards['result']['current_display']} na leitura por competência."
                ),
            }
        )
    top_expense_category = consumption_context["top_category"]
    if top_expense_category and top_expense_category["consumption_share"] >= 0.35:
        alerts.append(
            {
                "level": "warn",
                "title": "Alta concentração em uma categoria de consumo",
                "body": (
                    f"Na Visão de Competência, {top_expense_category['name']} respondeu por "
                    f"{top_expense_category['consumption_share_display']} do gasto do mês-base."
                ),
            }
        )
    largest_increase = consumption_context["largest_increase"]
    if largest_increase and _is_meaningful_consumption_change(largest_increase["previous_month_change"]):
        alerts.append(
            {
                "level": "warn",
                "title": f"Alta relevante no consumo de {largest_increase['name']}",
                "body": (
                    f"Na Visão de Competência, {largest_increase['name']} subiu "
                    f"{largest_increase['previous_month_change']['delta_display']} contra "
                    f"{consumption_context['previous_month_label']}."
                ),
            }
        )
    if consumption_context["uncategorized_share"] >= 0.08:
        alerts.append(
            {
                "level": "warn",
                "title": "Não categorizado ainda alto na Visão de Competência",
                "body": (
                    f"Ainda existem {consumption_context['uncategorized_display']} sem categoria definida, o que representa "
                    f"{consumption_context['uncategorized_share_display']} do gasto categorial de consumo."
                ),
            }
        )
    return alerts[:5]


def _build_home_competence_actions(*, competence_cards: dict, consumption_context: dict) -> list[dict]:
    cards = {item["key"]: item for item in competence_cards["cards"]}
    actions: list[dict] = []
    if consumption_context["uncategorized_share"] >= 0.05:
        actions.append(
            {
                "title": "Melhorar a qualidade da Visão de Competência",
                "body": (
                    f"Priorize a revisão do não categorizado ({consumption_context['uncategorized_display']}) "
                    "para reduzir ruído na leitura por categorias."
                ),
            }
        )
    top_expense_category = consumption_context["top_category"]
    if top_expense_category and (
        top_expense_category["expense_total"] >= 100.0
        and (
            top_expense_category["consumption_share"] >= 0.3
            or _is_meaningful_consumption_change(top_expense_category.get("previous_month_change"))
        )
    ):
        top_category_change = top_expense_category.get("previous_month_change")
        top_category_change_text = ""
        if top_category_change is not None and top_category_change["delta"] > 0:
            top_category_change_text = (
                f" e subiu {top_category_change['delta_display']} contra "
                f"{consumption_context['previous_month_label']}"
            )
        actions.append(
            {
                "title": f"Revisar a categoria {top_expense_category['name']}",
                "body": (
                    f"Na Visão de Competência, ela concentrou {top_expense_category['consumption_share_display']} do gasto do mês-base"
                    f"{top_category_change_text}."
                ),
            }
        )
    if cards["result"]["current"] < 0:
        focus_categories = [item["name"] for item in consumption_context["top_categories"]]
        categories_text = ", ".join(focus_categories) if focus_categories else "as maiores despesas variáveis"
        actions.append(
            {
                "title": "Recuperar o resultado do mês",
                "body": (
                    f"Comece por {categories_text} para reduzir pressão na Visão de Competência já no próximo fechamento."
                ),
            }
        )
    return actions[:5]


def _build_home_recent_movements(
    db: Session,
    *,
    month_txs: list[Transaction],
    limit: int = 6,
) -> dict:
    ordered_txs = sorted(
        month_txs,
        key=lambda tx: (tx.transaction_date, tx.id or 0),
        reverse=True,
    )
    signal_map = map_conciliated_bank_payment_signals(
        db,
        transaction_ids=[tx.id for tx in ordered_txs if tx.id is not None],
    )
    rows: list[dict] = []
    for tx in ordered_txs[:limit]:
        signal = signal_map.get(tx.id)
        if signal and signal.conciliation_status == "conciliated":
            status_label = "Conciliado"
            status_variant = "ok"
        elif is_uncategorized(tx.category):
            status_label = "Não categorizado"
            status_variant = "warn"
        elif tx.manual_override:
            status_label = "Ajustado"
            status_variant = ""
        else:
            status_label = "Classificado"
            status_variant = ""

        rows.append(
            {
                "description": tx.description_raw,
                "category": tx.category or "Não Categorizado",
                "date_display": format_date_br(tx.transaction_date),
                "amount": float(tx.amount),
                "amount_display": format_signed_currency_br(float(tx.amount)),
                "amount_class": "amount-positive" if float(tx.amount) > 0 else "amount-negative" if float(tx.amount) < 0 else "",
                "status_label": status_label,
                "status_variant": status_variant,
                "source_label": "Extrato" if tx.source_type == "bank_statement" else "Fatura",
            }
        )

    return {
        "title": "Movimentações recentes",
        "note": "Últimos lançamentos do mês-base, sem criar uma nova tela operacional dentro da home.",
        "rows": rows,
    }


def _build_home_dashboard(
    db: Session,
    *,
    anchor_month: date,
    current_month_txs: list[Transaction],
    category_breakdown: dict,
    category_history: dict,
    active_lens: str,
    chart_mode: str,
    chart_year: int | None,
    chart_compare: str | None,
) -> dict:
    active_lens = active_lens if active_lens in {"cash", "competence"} else "cash"
    chart_mode = chart_mode if chart_mode in {"year", "rolling_12"} else "year"
    available_years = _available_chart_years(db, anchor_month=anchor_month)
    if chart_year not in available_years:
        chart_year = anchor_month.year
        if chart_year not in available_years:
            available_years = [chart_year, *available_years]
            available_years = list(dict.fromkeys(available_years))

    cash_cards = _build_cash_home_cards(
        db,
        anchor_month=anchor_month,
        current_month_txs=current_month_txs,
        current_category_breakdown=category_breakdown,
    )
    competence_cards = _build_competence_home_cards(
        db,
        anchor_month=anchor_month,
        current_month_txs=current_month_txs,
        current_category_breakdown=category_breakdown,
    )
    category_comparison = _build_home_category_comparison(
        db,
        anchor_month=anchor_month,
        visible=active_lens == "competence",
    )
    recent_movements = _build_home_recent_movements(
        db,
        month_txs=current_month_txs,
    )
    consumption_context = _build_consumption_signal_context(
        category_breakdown=category_breakdown,
        category_history=category_history,
    )
    lens_config = {
        "cash": {
            "label": "Visão de Caixa",
            "cards": cash_cards,
            "summary": _build_home_cash_summary(cash_cards=cash_cards),
            "alerts": _build_home_cash_alerts(cash_cards=cash_cards),
            "actions": _build_home_cash_actions(cash_cards=cash_cards),
            "compare_tabs": [
                {"key": "balance", "label": "Fluxo líquido"},
                {"key": "income", "label": "Entradas"},
                {"key": "expense", "label": "Saídas"},
            ],
        },
        "competence": {
            "label": "Visão de Competência",
            "cards": competence_cards,
            "summary": _build_home_competence_summary(competence_cards=competence_cards),
            "alerts": _build_home_competence_alerts(
                competence_cards=competence_cards,
                consumption_context=consumption_context,
            ),
            "actions": _build_home_competence_actions(
                competence_cards=competence_cards,
                consumption_context=consumption_context,
            ),
            "compare_tabs": [
                {"key": "balance", "label": "Resultado"},
                {"key": "income", "label": "Receitas"},
                {"key": "expense", "label": "Despesas"},
            ],
        },
    }

    active_compare = chart_compare or "balance"
    chart = _build_home_primary_chart(
        db,
        anchor_month=anchor_month,
        lens=active_lens,
        mode=chart_mode,
        selected_year=chart_year,
        compare_metric=active_compare,
    )
    chart["available_years"] = available_years

    return {
        "active_lens": active_lens,
        "current_month_label": lens_config[active_lens]["cards"]["current_month_label"],
        "previous_month_label": lens_config[active_lens]["cards"]["previous_month_label"],
        "lenses": [
            {"key": "cash", "label": lens_config["cash"]["label"]},
            {"key": "competence", "label": lens_config["competence"]["label"]},
        ],
        "cards": lens_config[active_lens]["cards"]["cards"],
        "summary": lens_config[active_lens]["summary"],
        "alerts": lens_config[active_lens]["alerts"],
        "actions": lens_config[active_lens]["actions"],
        "category_comparison": category_comparison,
        "recent_movements": recent_movements,
        "chart": {
            **chart,
            "mode_tabs": [
                {"key": "year", "label": "Ano"},
                {"key": "rolling_12", "label": "Últimos 12 meses"},
            ],
            "compare_tabs": lens_config[active_lens]["compare_tabs"],
        },
    }


def _build_monthly_series(db: Session, *, anchor_month: date) -> list[dict]:
    series_start = add_months(month_start(anchor_month), -11)
    series_end = month_end(anchor_month)
    txs = db.scalars(
        select(Transaction).where(Transaction.transaction_date >= series_start, Transaction.transaction_date <= series_end)
    ).all()
    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for tx in txs:
        grouped[tx.transaction_date.strftime("%Y-%m")].append(tx)

    items: list[dict] = []
    for offset in range(12):
        current_month = add_months(series_start, offset)
        key = current_month.strftime("%Y-%m")
        month_txs = grouped.get(key, [])
        summary = _build_summary(month_txs)
        items.append(
            {
                "month": key,
                "label": format_month_label(current_month),
                **summary,
            }
        )
    return items


def _build_statement_category_breakdown(*, current_txs: list[Transaction]) -> dict:
    summary = _build_summary(current_txs)
    rows = _build_category_rows(current_txs, expense_total=summary["expense_total"])
    top_expense_categories = [item for item in rows if item["expense_total"] > 0][:8]
    return {
        "mode": "statement",
        "rows": rows,
        "top_expense_categories": top_expense_categories,
        "note": (
            "Visão de Extrato: considera apenas as transações da conta pela data da transação, "
            "sem incorporar compras de fatura nem ajustar pagamentos conciliados."
        ),
    }


def _load_invoice_items_for_due_period(
    db: Session,
    *,
    period_start: date,
    period_end: date,
) -> list[CreditCardInvoiceItem]:
    return db.scalars(
        select(CreditCardInvoiceItem)
        .join(CreditCardInvoice, CreditCardInvoice.id == CreditCardInvoiceItem.invoice_id)
        .where(
            CreditCardInvoice.due_date >= period_start,
            CreditCardInvoice.due_date <= period_end,
        )
        .order_by(CreditCardInvoiceItem.purchase_date.asc(), CreditCardInvoiceItem.id.asc())
    ).all()


def _build_invoice_category_breakdown(items: list[CreditCardInvoiceItem]) -> dict:
    grouped: dict[str, dict] = defaultdict(_empty_category_bucket)
    credit_total = 0.0
    payment_total = 0.0
    for item in items:
        item_type = classify_credit_card_invoice_item(item)
        amount = float(item.amount_brl)
        if item_type == "charge":
            bucket = grouped[_analysis_category_name(item.category)]
            bucket["expense_total"] += amount
            bucket["transaction_count"] += 1
            bucket["flow_label"] = "Despesa da fatura"
        elif item_type == "credit":
            credit_total += abs(amount)
        elif item_type == "payment":
            payment_total += abs(amount)

    expense_total = sum(values["expense_total"] for values in grouped.values() if values["expense_total"] > 0)
    rows = _materialize_category_rows(grouped, expense_total=expense_total)
    top_expense_categories = [item for item in rows if item["expense_total"] > 0][:8]
    return {
        "mode": "invoice",
        "rows": rows,
        "top_expense_categories": top_expense_categories,
        "credit_total": credit_total,
        "credit_display": format_currency_br(credit_total),
        "payment_total": payment_total,
        "payment_display": format_currency_br(payment_total),
        "note": (
            "Visão de Faturas: o ranking de categorias considera apenas itens charge das faturas com vencimento no período. "
            "Créditos e pagamentos técnicos permanecem fora do gráfico categorial principal."
        ),
    }


def _build_invoice_month_snapshot(
    db: Session,
    *,
    period_start: date,
    period_end: date,
) -> dict:
    invoices = db.scalars(
        select(CreditCardInvoice)
        .where(
            CreditCardInvoice.due_date >= period_start,
            CreditCardInvoice.due_date <= period_end,
        )
        .order_by(CreditCardInvoice.due_date.asc(), CreditCardInvoice.id.asc())
    ).all()
    items = _load_invoice_items_for_due_period(db, period_start=period_start, period_end=period_end) if invoices else []
    category_breakdown = _build_invoice_category_breakdown(items)

    status_counts = {
        "imported": 0,
        "pending_review": 0,
        "partially_conciliated": 0,
        "conciliated": 0,
        "conflict": 0,
    }
    for invoice in invoices:
        status_counts[invoice.import_status] = status_counts.get(invoice.import_status, 0) + 1

    total_billed = sum(float(invoice.total_amount_brl) for invoice in invoices)
    charge_total = sum(row["expense_total"] for row in category_breakdown["rows"])
    return {
        "invoice_count": len(invoices),
        "total_billed": total_billed,
        "total_billed_display": format_currency_br(total_billed),
        "charge_total": charge_total,
        "charge_total_display": format_currency_br(charge_total),
        "credit_total": category_breakdown["credit_total"],
        "credit_total_display": category_breakdown["credit_display"],
        "payment_total": category_breakdown["payment_total"],
        "payment_total_display": category_breakdown["payment_display"],
        "status_counts": status_counts,
        "category_breakdown": category_breakdown,
        "note": (
            "A visão de faturas acompanha os vencimentos dentro do período selecionado e separa "
            "compras, créditos técnicos e pagamentos técnicos."
        ),
    }


def _build_invoice_monthly_series(db: Session, *, anchor_month: date) -> list[dict]:
    series_start = add_months(month_start(anchor_month), -11)
    items: list[dict] = []
    for offset in range(12):
        current_month = add_months(series_start, offset)
        period_start = month_start(current_month)
        period_end = month_end(current_month)
        snapshot = _build_invoice_month_snapshot(db, period_start=period_start, period_end=period_end)
        items.append(
            {
                "month": period_start.strftime("%Y-%m"),
                "label": format_month_label(period_start),
                "invoice_count": snapshot["invoice_count"],
                "total_billed": snapshot["total_billed"],
                "total_billed_display": snapshot["total_billed_display"],
                "charge_total": snapshot["charge_total"],
                "charge_total_display": snapshot["charge_total_display"],
                "credit_total": snapshot["credit_total"],
                "credit_total_display": snapshot["credit_total_display"],
            }
        )
    return items


def build_statement_category_monthly_series(
    db: Session,
    *,
    anchor_month: date,
    category_names: list[str] | None = None,
) -> dict:
    selected_names: list[str] = []
    seen_names: set[str] = set()
    for raw_name in category_names or []:
        normalized_name = _analysis_category_name(raw_name)
        normalized_key = _analysis_category_key(normalized_name)
        if normalized_key in seen_names:
            continue
        seen_names.add(normalized_key)
        selected_names.append(normalized_name)

    series_start = add_months(month_start(anchor_month), -11)
    month_snapshots: list[dict] = []
    category_totals: dict[str, float] = defaultdict(float)
    category_labels: dict[str, str] = {}
    for offset in range(12):
        current_month = add_months(series_start, offset)
        current_txs = _load_transactions_for_period(
            db,
            period_start=month_start(current_month),
            period_end=month_end(current_month),
        )
        snapshot = _build_statement_category_breakdown(current_txs=current_txs)
        month_snapshots.append(
            {
                "label": format_month_label(month_start(current_month)),
                "rows": snapshot["rows"],
            }
        )
        for row in snapshot["rows"]:
            if row["expense_total"] <= 0 or row["is_technical"]:
                continue
            category_key = _analysis_category_key(row["name"])
            category_labels.setdefault(category_key, row["name"])
            category_totals[category_key] += row["expense_total"]

    resolved_names = selected_names or [
        category_labels[key]
        for key, _total in sorted(
            category_totals.items(),
            key=lambda item: (-item[1], category_labels[item[0]].casefold()),
        )
    ]
    labels = [snapshot["label"] for snapshot in month_snapshots]
    datasets = [{"label": name, "values": []} for name in resolved_names]
    for snapshot in month_snapshots:
        row_lookup = {
            _analysis_category_key(row["name"]): row
            for row in snapshot["rows"]
            if row["expense_total"] > 0 and not row["is_technical"]
        }
        for dataset in datasets:
            row = row_lookup.get(_analysis_category_key(dataset["label"]))
            dataset["values"].append(round(row["expense_total"], 2) if row else 0.0)
    return {
        "labels": labels,
        "datasets": datasets,
    }


def build_invoice_category_monthly_series(
    db: Session,
    *,
    anchor_month: date,
    category_names: list[str] | None = None,
) -> dict:
    selected_names: list[str] = []
    seen_names: set[str] = set()
    for raw_name in category_names or []:
        normalized_name = _analysis_category_name(raw_name)
        normalized_key = _analysis_category_key(normalized_name)
        if normalized_key in seen_names:
            continue
        seen_names.add(normalized_key)
        selected_names.append(normalized_name)

    series_start = add_months(month_start(anchor_month), -11)
    month_snapshots: list[dict] = []
    category_totals: dict[str, float] = defaultdict(float)
    category_labels: dict[str, str] = {}
    for offset in range(12):
        current_month = add_months(series_start, offset)
        snapshot = _build_invoice_month_snapshot(
            db,
            period_start=month_start(current_month),
            period_end=month_end(current_month),
        )
        month_snapshots.append(
            {
                "label": format_month_label(month_start(current_month)),
                "rows": snapshot["category_breakdown"]["rows"],
            }
        )
        for row in snapshot["category_breakdown"]["rows"]:
            if row["expense_total"] <= 0 or row["is_technical"]:
                continue
            category_key = _analysis_category_key(row["name"])
            category_labels.setdefault(category_key, row["name"])
            category_totals[category_key] += row["expense_total"]

    resolved_names = selected_names or [
        category_labels[key]
        for key, _total in sorted(
            category_totals.items(),
            key=lambda item: (-item[1], category_labels[item[0]].casefold()),
        )
    ]
    labels = [snapshot["label"] for snapshot in month_snapshots]
    datasets = [{"label": name, "values": []} for name in resolved_names]
    for snapshot in month_snapshots:
        row_lookup = {
            _analysis_category_key(row["name"]): row
            for row in snapshot["rows"]
            if row["expense_total"] > 0 and not row["is_technical"]
        }
        for dataset in datasets:
            row = row_lookup.get(_analysis_category_key(dataset["label"]))
            dataset["values"].append(round(row["expense_total"], 2) if row else 0.0)
    return {
        "labels": labels,
        "datasets": datasets,
    }


def _build_conciliated_monthly_series(db: Session, *, anchor_month: date) -> list[dict]:
    series_start = add_months(month_start(anchor_month), -11)
    items: list[dict] = []
    for offset in range(12):
        current_month = add_months(series_start, offset)
        period_start = month_start(current_month)
        period_end = month_end(current_month)
        month_txs = _load_transactions_for_period(db, period_start=period_start, period_end=period_end)
        snapshot = _build_conciliated_month_snapshot(
            db,
            period_start=period_start,
            period_end=period_end,
            current_txs=month_txs,
        )
        items.append(
            {
                "month": period_start.strftime("%Y-%m"),
                "label": format_month_label(period_start),
                "income_total": snapshot["real_bank_income_total"],
                "income_display": snapshot["real_bank_income_display"],
                "expense_total": snapshot["real_conciliated_expense_total"],
                "expense_display": snapshot["real_conciliated_expense_display"],
                "balance": snapshot["real_conciliated_balance_total"],
                "balance_display": snapshot["real_conciliated_balance_display"],
                "included_invoice_count": snapshot["included_invoice_count"],
            }
        )
    return items


def _build_consumption_monthly_series(db: Session, *, anchor_month: date) -> list[dict]:
    series_start = add_months(month_start(anchor_month), -11)
    items: list[dict] = []
    for offset in range(12):
        current_month = add_months(series_start, offset)
        snapshot = _build_conciliated_category_month_snapshot(db, anchor_month=current_month)
        consumption_total = sum(
            row["expense_total"]
            for row in snapshot["breakdown"]["rows"]
            if row["expense_total"] > 0 and not row["is_technical"]
        )
        items.append(
            {
                "month": snapshot["month"],
                "label": snapshot["label"],
                "consumption_total": consumption_total,
                "consumption_display": format_currency_br(consumption_total),
                "category_count": len([row for row in snapshot["breakdown"]["rows"] if row["expense_total"] > 0 and not row["is_technical"]]),
            }
        )
    return items


def _analysis_category_name(value: str | None) -> str:
    return value or "Não Categorizado"


def _empty_category_bucket() -> dict:
    return {
        "expense_total": 0.0,
        "income_total": 0.0,
        "movement_total": None,
        "transaction_count": 0,
        "is_transfer_technical": False,
        "is_card_bill_technical": False,
        "technical_label": None,
        "flow_label": None,
    }


def _materialize_category_rows(grouped: dict[str, dict], *, expense_total: float) -> list[dict]:
    rows: list[dict] = []
    for category, values in grouped.items():
        movement_total = values["movement_total"]
        if movement_total is None:
            movement_total = values["expense_total"] + values["income_total"]

        flow_label = values["flow_label"]
        if not flow_label:
            if values["expense_total"] > values["income_total"]:
                flow_label = "Despesa"
            elif values["income_total"] > values["expense_total"]:
                flow_label = "Receita"
            else:
                flow_label = "Misto"

        technical_label = values["technical_label"]
        if technical_label is None:
            if values["is_transfer_technical"]:
                technical_label = "Transferências"
            elif values["is_card_bill_technical"]:
                technical_label = "Pagamento de Fatura"

        share_of_expense = values["expense_total"] / expense_total if expense_total and values["expense_total"] > 0 else 0.0
        rows.append(
            {
                "name": category,
                "expense_total": values["expense_total"],
                "income_total": values["income_total"],
                "movement_total": movement_total,
                "flow_label": flow_label,
                "display_total": format_currency_br(movement_total),
                "expense_display": format_currency_br(values["expense_total"]),
                "income_display": format_currency_br(values["income_total"]),
                "share_of_expense": share_of_expense,
                "share_of_expense_display": format_percent_br(share_of_expense if values["expense_total"] > 0 else None),
                "transaction_count": values["transaction_count"],
                "is_technical": technical_label is not None,
                "technical_label": technical_label,
            }
        )
    rows.sort(key=lambda item: (item["expense_total"], item["movement_total"], item["income_total"]), reverse=True)
    return rows


def _build_category_period_totals_chart(rows: list[dict]) -> dict:
    chart_rows: list[dict] = []
    for row in rows:
        category_name = row["name"]
        expense_total = round(float(row["expense_total"]), 2)
        income_total = round(float(row["income_total"]), 2)
        movement_total = round(float(row["movement_total"]), 2)

        if row["is_technical"]:
            if movement_total > 0:
                chart_rows.append(
                    {
                        "label": category_name,
                        "category_name": category_name,
                        "value": movement_total,
                        "value_display": row["display_total"],
                        "flow_label": row["technical_label"] or row["flow_label"] or "Técnico",
                        "flow_kind": "transfer",
                        "is_technical": True,
                    }
                )
            continue

        if income_total > 0 and expense_total > 0:
            chart_rows.extend(
                [
                    {
                        "label": f"{category_name} · Receita",
                        "category_name": category_name,
                        "value": income_total,
                        "value_display": row["income_display"],
                        "flow_label": "Receita",
                        "flow_kind": "income",
                        "is_technical": False,
                    },
                    {
                        "label": f"{category_name} · Despesa",
                        "category_name": category_name,
                        "value": expense_total,
                        "value_display": row["expense_display"],
                        "flow_label": row["flow_label"] if row["flow_label"] not in {"Receita", "Misto"} else "Despesa",
                        "flow_kind": "expense",
                        "is_technical": False,
                    },
                ]
            )
            continue

        if income_total > 0:
            chart_rows.append(
                {
                    "label": category_name,
                    "category_name": category_name,
                    "value": income_total,
                    "value_display": row["income_display"],
                    "flow_label": "Receita",
                    "flow_kind": "income",
                    "is_technical": False,
                }
            )
        elif expense_total > 0:
            chart_rows.append(
                {
                    "label": category_name,
                    "category_name": category_name,
                    "value": expense_total,
                    "value_display": row["expense_display"],
                    "flow_label": row["flow_label"] if row["flow_label"] != "Misto" else "Despesa",
                    "flow_kind": "expense",
                    "is_technical": False,
                }
            )

    chart_rows.sort(key=lambda item: (-item["value"], item["label"].casefold()))
    return {
        "labels": [item["label"] for item in chart_rows],
        "category_names": [item["category_name"] for item in chart_rows],
        "values": [item["value"] for item in chart_rows],
        "value_displays": [item["value_display"] for item in chart_rows],
        "flow_labels": [item["flow_label"] for item in chart_rows],
        "flow_kinds": [item["flow_kind"] for item in chart_rows],
        "technical": [item["is_technical"] for item in chart_rows],
    }


def _build_category_rows(txs: list[Transaction], *, expense_total: float) -> list[dict]:
    grouped: dict[str, dict] = defaultdict(_empty_category_bucket)
    for tx in txs:
        bucket = grouped[_analysis_category_name(tx.category)]
        bucket["expense_total"] += _expense_amount(tx)
        bucket["income_total"] += _income_amount(tx)
        bucket["transaction_count"] += 1
        bucket["is_transfer_technical"] = bucket["is_transfer_technical"] or _is_transfer_technical(tx)
        bucket["is_card_bill_technical"] = bucket["is_card_bill_technical"] or _is_card_bill_technical(tx)

    return _materialize_category_rows(grouped, expense_total=expense_total)


def _build_technical_items(txs: list[Transaction], *, expense_total: float) -> dict:
    transfer_total = sum(_expense_amount(tx) for tx in txs if _is_transfer_technical(tx))
    card_bill_total = sum(_expense_amount(tx) for tx in txs if _is_card_bill_technical(tx))
    combined_total = transfer_total + card_bill_total
    transfer_share = transfer_total / expense_total if expense_total else 0.0
    card_bill_share = card_bill_total / expense_total if expense_total else 0.0
    combined_share = combined_total / expense_total if expense_total else 0.0
    return {
        "transfer_total": transfer_total,
        "transfer_display": format_currency_br(transfer_total),
        "transfer_share": transfer_share,
        "transfer_share_display": format_percent_br(transfer_share),
        "card_bill_total": card_bill_total,
        "card_bill_display": format_currency_br(card_bill_total),
        "card_bill_share": card_bill_share,
        "card_bill_share_display": format_percent_br(card_bill_share),
        "combined_total": combined_total,
        "combined_display": format_currency_br(combined_total),
        "combined_share": combined_share,
        "combined_share_display": format_percent_br(combined_share),
        "note": "Transferências e pagamento de fatura continuam no consolidado, mas podem distorcer a leitura do consumo real.",
    }


def _build_conciliated_category_breakdown(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    current_txs: list[Transaction],
) -> dict:
    invoice_item_rows = _load_conciliated_invoice_items_for_purchase_period(
        db,
        period_start=period_start,
        period_end=period_end,
    )

    signal_map = map_conciliated_bank_payment_signals(db, transaction_ids=[tx.id for tx in current_txs])
    excluded_payment_ids = {
        tx.id
        for tx in current_txs
        if tx.id in signal_map and signal_map[tx.id].conciliation_status == "conciliated"
    }

    grouped: dict[str, dict] = defaultdict(_empty_category_bucket)
    for tx in current_txs:
        if tx.id in excluded_payment_ids:
            continue
        bucket = grouped[_analysis_category_name(tx.category)]
        bucket["expense_total"] += _expense_amount(tx)
        bucket["income_total"] += _income_amount(tx)
        bucket["transaction_count"] += 1
        bucket["is_transfer_technical"] = bucket["is_transfer_technical"] or _is_transfer_technical(tx)
        bucket["is_card_bill_technical"] = bucket["is_card_bill_technical"] or _is_card_bill_technical(tx)

    included_invoice_ids: set[int] = set()
    credit_item_count = 0
    invoice_credit_total = 0.0
    for item, invoice_id in invoice_item_rows:
        item_type = classify_credit_card_invoice_item(item)
        if item_type == "charge":
            bucket = grouped[_analysis_category_name(item.category)]
            bucket["expense_total"] += float(item.amount_brl)
            bucket["transaction_count"] += 1
            included_invoice_ids.add(invoice_id)
        elif item_type == "credit":
            invoice_credit_total += abs(float(item.amount_brl))
            credit_item_count += 1
            included_invoice_ids.add(invoice_id)

    if invoice_credit_total > 0:
        grouped["Créditos de Fatura"] = {
            "expense_total": 0.0,
            "income_total": 0.0,
            "movement_total": -invoice_credit_total,
            "transaction_count": credit_item_count or 1,
            "is_transfer_technical": False,
            "is_card_bill_technical": False,
            "technical_label": "Crédito de Fatura",
            "flow_label": "Ajuste técnico",
        }

    expense_total = sum(values["expense_total"] for values in grouped.values() if values["expense_total"] > 0)
    rows = _materialize_category_rows(grouped, expense_total=expense_total)
    top_expense_categories = [item for item in rows if item["expense_total"] > 0][:8]
    excluded_bank_payment_total = sum(_expense_amount(tx) for tx in current_txs if tx.id in excluded_payment_ids)

    return {
        "mode": "conciliated",
        "rows": rows,
        "top_expense_categories": top_expense_categories,
        "included_invoice_count": len(included_invoice_ids),
        "invoice_credit_adjustment_total": invoice_credit_total,
        "invoice_credit_adjustment_display": format_currency_br(invoice_credit_total),
        "excluded_bank_payment_total": excluded_bank_payment_total,
        "excluded_bank_payment_display": format_currency_br(excluded_bank_payment_total),
        "note": (
            "Visão de consumo do mês-base: conta entra pela data da transação e cartão conciliado entra pela data da compra. "
            "Créditos genéricos de fatura seguem em bloco técnico separado pela data do próprio item importado quando ela existe, "
            "sem redistribuição artificial entre categorias. Pagamentos conciliados ficam fora das categorias de consumo."
        ),
    }


def _earliest_history_month(db: Session) -> date | None:
    earliest_tx_date = db.scalar(select(func.min(Transaction.transaction_date)))
    earliest_invoice_purchase_date = db.scalar(
        select(func.min(CreditCardInvoiceItem.purchase_date))
        .select_from(CreditCardInvoiceItem)
        .join(CreditCardInvoice, CreditCardInvoice.id == CreditCardInvoiceItem.invoice_id)
        .join(CreditCardInvoiceConciliation, CreditCardInvoiceConciliation.invoice_id == CreditCardInvoice.id)
        .where(CreditCardInvoiceConciliation.status == "conciliated")
    )
    candidates = [value for value in (earliest_tx_date, earliest_invoice_purchase_date) if value is not None]
    if not candidates:
        return None
    return month_start(min(candidates))


def _build_conciliated_category_month_snapshot(
    db: Session,
    *,
    anchor_month: date,
) -> dict:
    period_start = month_start(anchor_month)
    period_end = month_end(anchor_month)
    month_txs = _load_transactions_for_period(db, period_start=period_start, period_end=period_end)
    breakdown = _build_conciliated_category_breakdown(
        db,
        period_start=period_start,
        period_end=period_end,
        current_txs=month_txs,
    )
    expense_rows = [row for row in breakdown["rows"] if row["expense_total"] > 0]
    return {
        "month": period_start.strftime("%Y-%m"),
        "label": format_month_label(period_start),
        "period_start": period_start,
        "period_end": period_end,
        "breakdown": breakdown,
        "expense_rows": expense_rows,
        "expense_by_category": {row["name"]: row["expense_total"] for row in expense_rows},
        "row_lookup": {row["name"]: row for row in breakdown["rows"]},
        "has_activity": bool(breakdown["rows"]),
    }


def _build_conciliated_category_history(
    db: Session,
    *,
    anchor_month: date,
) -> dict:
    current_snapshot = _build_conciliated_category_month_snapshot(db, anchor_month=anchor_month)
    previous_month = add_months(month_start(anchor_month), -1)
    previous_year_month = add_months(month_start(anchor_month), -12)
    earliest_month = _earliest_history_month(db)

    previous_month_snapshot = (
        _build_conciliated_category_month_snapshot(db, anchor_month=previous_month)
        if earliest_month is not None and previous_month >= earliest_month
        else None
    )
    previous_year_snapshot = (
        _build_conciliated_category_month_snapshot(db, anchor_month=previous_year_month)
        if earliest_month is not None and previous_year_month >= earliest_month
        else None
    )
    previous_month_available = bool(previous_month_snapshot and previous_month_snapshot["has_activity"])
    previous_year_available = bool(previous_year_snapshot and previous_year_snapshot["has_activity"])
    previous_snapshot = previous_month_snapshot if previous_month_available else None
    previous_year_snapshot = previous_year_snapshot if previous_year_available else None

    rows: list[dict] = []
    for current_row in current_snapshot["breakdown"]["top_expense_categories"]:
        previous_month_total = (
            previous_snapshot["expense_by_category"].get(current_row["name"], 0.0)
            if previous_snapshot is not None
            else None
        )
        previous_year_total = (
            previous_year_snapshot["expense_by_category"].get(current_row["name"], 0.0)
            if previous_year_snapshot is not None
            else None
        )
        previous_month_change = (
            _build_metric_change(current_row["expense_total"], previous_month_total)
            if previous_month_total is not None
            else None
        )
        previous_year_change = (
            _build_metric_change(current_row["expense_total"], previous_year_total)
            if previous_year_total is not None
            else None
        )
        rows.append(
            {
                "name": current_row["name"],
                "flow_label": current_row["flow_label"],
                "is_technical": current_row["is_technical"],
                "technical_label": current_row["technical_label"],
                "current_total": current_row["expense_total"],
                "current_display": current_row["expense_display"],
                "current_share_of_expense_display": current_row["share_of_expense_display"],
                "previous_month_total": previous_month_total,
                "previous_month_display": format_currency_br(previous_month_total) if previous_month_total is not None else "Sem base",
                "previous_month_change": previous_month_change,
                "previous_year_total": previous_year_total,
                "previous_year_display": format_currency_br(previous_year_total) if previous_year_total is not None else "Sem base",
                "previous_year_change": previous_year_change,
            }
        )

    current_adjustment_total = current_snapshot["breakdown"]["invoice_credit_adjustment_total"]
    previous_month_adjustment_total = (
        previous_snapshot["breakdown"]["invoice_credit_adjustment_total"]
        if previous_snapshot is not None
        else None
    )
    previous_year_adjustment_total = (
        previous_year_snapshot["breakdown"]["invoice_credit_adjustment_total"]
        if previous_year_snapshot is not None
        else None
    )

    return {
        "current_month_label": current_snapshot["label"],
        "previous_month_label": format_month_label(previous_month),
        "previous_year_label": format_month_label(previous_year_month),
        "previous_month_available": previous_month_available,
        "previous_year_available": previous_year_available,
        "rows": rows,
        "note": (
            "Comparações históricas por categoria na visão de consumo: conta por data da transação e cartão conciliado por "
            "data da compra. Créditos técnicos seguem separados pela data do próprio item importado quando disponível, sem "
            "redistribuição artificial entre categorias, e pagamentos conciliados continuam fora do consumo."
        ),
        "technical_adjustments": {
            "current_invoice_credit_total": current_adjustment_total,
            "current_invoice_credit_display": format_currency_br(current_adjustment_total),
            "previous_month_invoice_credit_total": previous_month_adjustment_total,
            "previous_month_invoice_credit_display": (
                format_currency_br(previous_month_adjustment_total)
                if previous_month_adjustment_total is not None
                else "Sem base"
            ),
            "previous_month_change": (
                _build_metric_change(current_adjustment_total, previous_month_adjustment_total)
                if previous_month_adjustment_total is not None
                else None
            ),
            "previous_year_invoice_credit_total": previous_year_adjustment_total,
            "previous_year_invoice_credit_display": (
                format_currency_br(previous_year_adjustment_total)
                if previous_year_adjustment_total is not None
                else "Sem base"
            ),
            "previous_year_change": (
                _build_metric_change(current_adjustment_total, previous_year_adjustment_total)
                if previous_year_adjustment_total is not None
                else None
            ),
            "note": (
                "Créditos genéricos de fatura continuam fora das categorias de consumo. Na implementação atual, esse ajuste "
                "técnico segue a data do próprio item importado quando ela existe, sem redistribuição artificial entre categorias. "
                "Os pagamentos bancários conciliados seguem fora da visão principal em todos os meses comparados."
            ),
        },
    }


def _build_conciliated_month_snapshot(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    current_txs: list[Transaction],
) -> dict:
    conciliated_invoice_rows = db.execute(
        select(CreditCardInvoice, CreditCardInvoiceConciliation)
        .join(CreditCardInvoiceConciliation, CreditCardInvoiceConciliation.invoice_id == CreditCardInvoice.id)
        .where(
            CreditCardInvoice.due_date >= period_start,
            CreditCardInvoice.due_date <= period_end,
            CreditCardInvoiceConciliation.status == "conciliated",
        )
    ).all()

    included_invoice_ids = {invoice.id for invoice, _ in conciliated_invoice_rows}
    outside_status_counts = {
        "pending_review": 0,
        "partially_conciliated": 0,
        "conflict": 0,
    }
    outside_status_rows = db.execute(
        select(
            CreditCardInvoiceConciliation.status,
            func.count(CreditCardInvoice.id),
        )
        .select_from(CreditCardInvoice)
        .outerjoin(CreditCardInvoiceConciliation, CreditCardInvoiceConciliation.invoice_id == CreditCardInvoice.id)
        .where(
            CreditCardInvoice.due_date >= period_start,
            CreditCardInvoice.due_date <= period_end,
        )
        .group_by(CreditCardInvoiceConciliation.status)
    ).all()
    for raw_status, count_value in outside_status_rows:
        status = raw_status or "pending_review"
        if status in outside_status_counts:
            outside_status_counts[status] = int(count_value or 0)

    invoice_item_rows = db.execute(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id.in_(included_invoice_ids))
        .order_by(CreditCardInvoiceItem.invoice_id.asc(), CreditCardInvoiceItem.id.asc())
    ).scalars().all() if included_invoice_ids else []

    charge_total = 0.0
    payment_item_total = 0.0
    for item in invoice_item_rows:
        item_type = classify_credit_card_invoice_item(item)
        amount = float(item.amount_brl)
        if item_type == "charge":
            charge_total += amount
        elif item_type == "payment":
            payment_item_total += abs(amount)

    invoice_credit_total = sum(float(conciliation.invoice_credit_total_brl) for _, conciliation in conciliated_invoice_rows)
    signal_map = map_conciliated_bank_payment_signals(
        db,
        transaction_ids=[tx.id for tx in current_txs],
    )
    excluded_payment_ids = {
        tx.id
        for tx in current_txs
        if tx.id in signal_map and signal_map[tx.id].conciliation_status == "conciliated" and signal_map[tx.id].invoice_id in included_invoice_ids
    }

    bank_income_total = sum(_income_amount(tx) for tx in current_txs)
    transfer_income_total = sum(_income_amount(tx) for tx in current_txs if _is_transfer_technical(tx))
    total_bank_outflow_total = sum(_expense_amount(tx) for tx in current_txs)
    transfer_expense_total = sum(_expense_amount(tx) for tx in current_txs if _is_transfer_technical(tx))
    bank_expense_total_included = sum(
        _expense_amount(tx)
        for tx in current_txs
        if tx.id not in excluded_payment_ids
    )
    real_bank_income_total = max(bank_income_total - transfer_income_total, 0.0)
    real_bank_expense_total = sum(
        _expense_amount(tx)
        for tx in current_txs
        if tx.id not in excluded_payment_ids and not _is_transfer_technical(tx)
    )
    excluded_conciliated_bank_payment_total = sum(
        _expense_amount(tx)
        for tx in current_txs
        if tx.id in excluded_payment_ids
    )
    net_conciliated_expense_total = (
        bank_expense_total_included
        + charge_total
        - invoice_credit_total
    )
    real_conciliated_expense_total = (
        real_bank_expense_total
        + charge_total
        - invoice_credit_total
    )
    conciliated_balance_total = bank_income_total - net_conciliated_expense_total
    real_conciliated_balance_total = real_bank_income_total - real_conciliated_expense_total
    invoices_outside_total = sum(outside_status_counts.values())

    return {
        "bank_income_total": bank_income_total,
        "transfer_income_total": transfer_income_total,
        "real_bank_income_total": real_bank_income_total,
        "total_bank_outflow_total": total_bank_outflow_total,
        "bank_expense_total_included": bank_expense_total_included,
        "transfer_expense_total": transfer_expense_total,
        "real_bank_expense_total": real_bank_expense_total,
        "conciliated_card_charge_total": charge_total,
        "conciliated_invoice_credit_total": invoice_credit_total,
        "excluded_conciliated_bank_payment_total": excluded_conciliated_bank_payment_total,
        "net_conciliated_expense_total": net_conciliated_expense_total,
        "real_conciliated_expense_total": real_conciliated_expense_total,
        "conciliated_balance_total": conciliated_balance_total,
        "real_conciliated_balance_total": real_conciliated_balance_total,
        "included_invoice_count": len(included_invoice_ids),
        "outside_invoices_by_status": outside_status_counts,
        "outside_invoices_total": invoices_outside_total,
        "excluded_bank_payment_count": len(excluded_payment_ids),
        "ignored_invoice_payment_item_total": payment_item_total,
        "bank_income_display": format_currency_br(bank_income_total),
        "transfer_income_display": format_currency_br(transfer_income_total),
        "real_bank_income_display": format_currency_br(real_bank_income_total),
        "total_bank_outflow_display": format_currency_br(total_bank_outflow_total),
        "bank_expense_total_included_display": format_currency_br(bank_expense_total_included),
        "transfer_expense_display": format_currency_br(transfer_expense_total),
        "real_bank_expense_display": format_currency_br(real_bank_expense_total),
        "conciliated_card_charge_display": format_currency_br(charge_total),
        "conciliated_invoice_credit_display": format_currency_br(invoice_credit_total),
        "excluded_conciliated_bank_payment_display": format_currency_br(excluded_conciliated_bank_payment_total),
        "net_conciliated_expense_display": format_currency_br(net_conciliated_expense_total),
        "real_conciliated_expense_display": format_currency_br(real_conciliated_expense_total),
        "conciliated_balance_display": format_currency_br(conciliated_balance_total),
        "real_conciliated_balance_display": format_currency_br(real_conciliated_balance_total),
        "ignored_invoice_payment_item_display": format_currency_br(payment_item_total),
        "note": (
            "Considera apenas faturas totalmente conciliadas. "
            "Transferências ficam fora da leitura real, pagamentos bancários conciliados saem do gasto real "
            "e compras/créditos da fatura entram como consumo líquido do mês."
        ),
    }


def _build_quality(summary: dict) -> dict:
    uncategorized_share = summary["uncategorized_total"] / summary["expense_total"] if summary["expense_total"] else 0.0
    return {
        "uncategorized_total": summary["uncategorized_total"],
        "uncategorized_display": summary["uncategorized_display"],
        "uncategorized_share": uncategorized_share,
        "uncategorized_share_display": format_percent_br(uncategorized_share),
    }


def _build_primary_summary(*, conciliated_month: dict) -> dict:
    income_total = conciliated_month["real_bank_income_total"]
    expense_total = conciliated_month["real_conciliated_expense_total"]
    balance_total = conciliated_month["real_conciliated_balance_total"]
    included_invoice_count = conciliated_month["included_invoice_count"]
    outside_invoice_count = conciliated_month["outside_invoices_total"]
    excluded_payment_count = conciliated_month["excluded_bank_payment_count"]
    if included_invoice_count or outside_invoice_count:
        coverage_note = (
            f"{included_invoice_count} fatura(s) conciliada(s) entraram na leitura principal e "
            f"{outside_invoice_count} ficaram fora por pendência, parcial ou conflito."
        )
    else:
        coverage_note = (
            "Sem faturas conciliadas no período; a leitura principal mostra a movimentação real da conta, "
            "já sem transferências."
        )
    executive_summary = (
        f"Receitas reais conciliadas em {conciliated_month['real_bank_income_display']}, despesas reais conciliadas em "
        f"{conciliated_month['real_conciliated_expense_display']} e saldo real conciliado de "
        f"{conciliated_month['real_conciliated_balance_display']}. "
        f"Como apoio, entradas totais da conta em {conciliated_month['bank_income_display']} e saídas totais da conta em "
        f"{conciliated_month['total_bank_outflow_display']}."
    )
    return {
        "mode": "conciliated",
        "income_total": income_total,
        "expense_total": expense_total,
        "balance": balance_total,
        "income_display": format_currency_br(income_total),
        "expense_display": format_currency_br(expense_total),
        "balance_display": format_currency_br(balance_total),
        "gross_income_total": conciliated_month["bank_income_total"],
        "gross_income_display": conciliated_month["bank_income_display"],
        "gross_expense_total": conciliated_month["total_bank_outflow_total"],
        "gross_expense_display": conciliated_month["total_bank_outflow_display"],
        "excluded_transfer_income_total": conciliated_month["transfer_income_total"],
        "excluded_transfer_income_display": conciliated_month["transfer_income_display"],
        "excluded_transfer_expense_total": conciliated_month["transfer_expense_total"],
        "excluded_transfer_expense_display": conciliated_month["transfer_expense_display"],
        "included_invoice_count": included_invoice_count,
        "outside_invoice_count": outside_invoice_count,
        "excluded_bank_payment_count": excluded_payment_count,
        "excluded_bank_payment_display": conciliated_month["excluded_conciliated_bank_payment_display"],
        "coverage_note": coverage_note,
        "executive_summary": executive_summary,
    }


def _build_consumption_signal_context(*, category_breakdown: dict, category_history: dict) -> dict:
    history_rows_by_name = {row["name"]: row for row in category_history["rows"]}
    consumption_rows: list[dict] = []
    consumption_total = 0.0
    for row in category_breakdown["rows"]:
        if row["expense_total"] <= 0 or row["is_technical"]:
            continue
        materialized_row = dict(row)
        history_row = history_rows_by_name.get(row["name"])
        materialized_row["previous_month_change"] = history_row["previous_month_change"] if history_row else None
        consumption_rows.append(materialized_row)
        consumption_total += row["expense_total"]

    for row in consumption_rows:
        share = row["expense_total"] / consumption_total if consumption_total else 0.0
        row["consumption_share"] = share
        row["consumption_share_display"] = format_percent_br(share if row["expense_total"] > 0 else None)

    uncategorized_total = sum(row["expense_total"] for row in consumption_rows if is_uncategorized(row["name"]))
    uncategorized_share = uncategorized_total / consumption_total if consumption_total else 0.0

    historical_rows = [row for row in category_history["rows"] if row["current_total"] > 0 and not row["is_technical"]]
    increasing_rows = [
        row
        for row in historical_rows
        if row["previous_month_change"] is not None and row["previous_month_change"]["delta"] > 0
    ]
    increasing_rows.sort(
        key=lambda row: (
            row["previous_month_change"]["delta"],
            row["current_total"],
        ),
        reverse=True,
    )

    return {
        "rows": consumption_rows,
        "consumption_total": consumption_total,
        "consumption_total_display": format_currency_br(consumption_total),
        "top_category": consumption_rows[0] if consumption_rows else None,
        "top_categories": consumption_rows[:2],
        "uncategorized_total": uncategorized_total,
        "uncategorized_display": format_currency_br(uncategorized_total),
        "uncategorized_share": uncategorized_share,
        "uncategorized_share_display": format_percent_br(uncategorized_share),
        "largest_increase": increasing_rows[0] if increasing_rows else None,
        "previous_month_label": category_history["previous_month_label"],
    }


def build_category_consumption_monthly_series(
    db: Session,
    *,
    anchor_month: date,
    category_names: list[str] | None = None,
) -> dict:
    selected_names: list[str] = []
    seen_names: set[str] = set()
    for raw_name in category_names or []:
        normalized_name = _analysis_category_name(raw_name)
        normalized_key = _analysis_category_key(normalized_name)
        if normalized_key in seen_names:
            continue
        seen_names.add(normalized_key)
        selected_names.append(normalized_name)

    series_start = add_months(month_start(anchor_month), -11)
    month_snapshots: list[dict] = []
    category_totals: dict[str, float] = defaultdict(float)
    category_labels: dict[str, str] = {}
    for offset in range(12):
        current_month = add_months(series_start, offset)
        snapshot = _build_conciliated_category_month_snapshot(db, anchor_month=current_month)
        month_snapshots.append(snapshot)
        for row in snapshot["breakdown"]["rows"]:
            if row["expense_total"] <= 0 or row["is_technical"]:
                continue
            category_key = _analysis_category_key(row["name"])
            category_labels.setdefault(category_key, row["name"])
            category_totals[category_key] += row["expense_total"]

    resolved_names = selected_names or [
        category_labels[key]
        for key, _total in sorted(
            category_totals.items(),
            key=lambda item: (-item[1], category_labels[item[0]].casefold()),
        )
    ]
    labels = [snapshot["label"] for snapshot in month_snapshots]
    datasets = [{"label": name, "values": []} for name in resolved_names]
    for snapshot in month_snapshots:
        row_lookup = {
            _analysis_category_key(row["name"]): row
            for row in snapshot["breakdown"]["rows"]
            if row["expense_total"] > 0 and not row["is_technical"]
        }
        for dataset in datasets:
            row = row_lookup.get(_analysis_category_key(dataset["label"]))
            dataset["values"].append(round(row["expense_total"], 2) if row else 0.0)
    return {
        "labels": labels,
        "datasets": datasets,
    }


def build_category_consumption_total_for_selection(
    db: Session,
    *,
    anchor_month: date,
    category_names: list[str] | None = None,
) -> list[dict]:
    selected_categories = {
        _analysis_category_key(name)
        for name in (category_names or [])
        if name
    }
    series_start = add_months(month_start(anchor_month), -11)
    items: list[dict] = []
    for offset in range(12):
        current_month = add_months(series_start, offset)
        snapshot = _build_conciliated_category_month_snapshot(db, anchor_month=current_month)
        rows = [
            row
            for row in snapshot["breakdown"]["rows"]
            if row["expense_total"] > 0 and not row["is_technical"]
        ]
        if selected_categories:
            rows = [row for row in rows if _analysis_category_key(row["name"]) in selected_categories]
        consumption_total = sum(row["expense_total"] for row in rows)
        items.append(
            {
                "month": snapshot["month"],
                "label": snapshot["label"],
                "consumption_total": consumption_total,
                "consumption_display": format_currency_br(consumption_total),
                "category_count": len(rows),
            }
        )
    return items


def build_category_composition_for_period(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    category_name: str | None = None,
    category_names: list[str] | None = None,
) -> dict:
    selected_names: list[str] = []
    seen_names: set[str] = set()
    for raw_name in [*(category_names or []), *( [category_name] if category_name else [])]:
        normalized_name = _analysis_category_name(raw_name)
        normalized_key = _analysis_category_key(normalized_name)
        if normalized_key in seen_names:
            continue
        seen_names.add(normalized_key)
        selected_names.append(normalized_name)

    selected_name_keys = {_analysis_category_key(name) for name in selected_names}
    current_txs = _load_transactions_for_period(db, period_start=period_start, period_end=period_end)
    signal_map = map_conciliated_bank_payment_signals(db, transaction_ids=[tx.id for tx in current_txs])
    excluded_payment_ids = {
        tx.id
        for tx in current_txs
        if tx.id in signal_map and signal_map[tx.id].conciliation_status == "conciliated"
    }

    rows: list[dict] = []
    for tx in current_txs:
        tx_category_name = _analysis_category_name(tx.category)
        if tx.id in excluded_payment_ids or (
            selected_name_keys and _analysis_category_key(tx_category_name) not in selected_name_keys
        ):
            continue
        expense_amount = _expense_amount(tx)
        income_amount = _income_amount(tx)
        considered_amount = expense_amount if expense_amount > 0 else income_amount
        if considered_amount <= 0:
            continue
        rows.append(
            {
                "date": tx.transaction_date,
                "date_display": format_date_br(tx.transaction_date),
                "description": tx.description_raw,
                "category_name": tx_category_name,
                "source_label": "Extrato",
                "scope_label": "Conta",
                "amount": considered_amount,
                "amount_display": format_currency_br(considered_amount),
                "detail": tx.transaction_kind,
                "edit_kind": "transaction",
                "transaction_id": tx.id,
            }
        )

    invoice_item_rows = _load_conciliated_invoice_items_for_purchase_period(
        db,
        period_start=period_start,
        period_end=period_end,
    )
    for item, invoice_id in invoice_item_rows:
        item_category_name = _analysis_category_name(item.category)
        if classify_credit_card_invoice_item(item) != "charge" or (
            selected_name_keys and _analysis_category_key(item_category_name) not in selected_name_keys
        ):
            continue
        rows.append(
            {
                "date": item.purchase_date,
                "date_display": format_date_br(item.purchase_date),
                "description": item.description_raw,
                "category_name": item_category_name,
                "source_label": "Fatura",
                "scope_label": f"Fatura #{invoice_id}",
                "amount": float(item.amount_brl),
                "amount_display": format_currency_br(float(item.amount_brl)),
                "detail": "charge conciliado",
                "edit_kind": "invoice_item",
                "invoice_id": invoice_id,
                "item_id": item.id,
            }
        )

    rows.sort(
        key=lambda item: (
            item["amount"],
            item["date"],
            item["description"].casefold(),
        ),
        reverse=True,
    )
    total = sum(item["amount"] for item in rows)
    selection_label = "Categoria" if len(selected_names) == 1 else "Categorias"
    if not selected_names:
        selection_display = "Todas as categorias"
    elif len(selected_names) == 1:
        selection_display = selected_names[0]
    else:
        selection_display = ", ".join(selected_names)
    return {
        "category_name": selection_display,
        "selection_label": selection_label,
        "selection_display": selection_display,
        "selected_categories": selected_names,
        "rows": rows,
        "total": total,
        "total_display": format_currency_br(total),
        "note": (
            "Composição do valor no período selecionado, combinando conta por data da transação "
            "e itens charge de faturas conciliadas por data da compra."
        ),
    }


def build_statement_operational_snapshot(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    conciliated_view: bool = False,
) -> dict:
    current_txs = _load_transactions_for_period(db, period_start=period_start, period_end=period_end)
    signal_map = map_conciliated_bank_payment_signals(db, transaction_ids=[tx.id for tx in current_txs])
    included_invoice_ids: set[int] = set()
    if conciliated_view:
        included_invoice_ids = {
            invoice.id
            for invoice, _conciliation in db.execute(
                select(CreditCardInvoice, CreditCardInvoiceConciliation)
                .join(CreditCardInvoiceConciliation, CreditCardInvoiceConciliation.invoice_id == CreditCardInvoice.id)
                .where(
                    CreditCardInvoice.due_date >= period_start,
                    CreditCardInvoice.due_date <= period_end,
                    CreditCardInvoiceConciliation.status == "conciliated",
                )
            ).all()
        }

    rows: list[dict] = []
    for tx in current_txs:
        signal = signal_map.get(tx.id)
        is_transfer = _is_transfer_technical(tx)
        is_excluded_payment = bool(
            conciliated_view
            and signal is not None
            and signal.conciliation_status == "conciliated"
            and signal.invoice_id in included_invoice_ids
        )
        is_included = not is_transfer and not is_excluded_payment if conciliated_view else True
        if conciliated_view:
            if is_excluded_payment:
                inclusion_label = "Fora da leitura"
                inclusion_reason = "Pagamento bancário substituído pela fatura conciliada."
            elif is_transfer:
                inclusion_label = "Fora da leitura"
                inclusion_reason = "Transferência técnica removida da leitura real."
            else:
                inclusion_label = "Dentro da leitura"
                inclusion_reason = "Lançamento considerado na leitura conciliada."
        else:
            if signal is not None:
                inclusion_label = "Vinculado"
                inclusion_reason = (
                    f"{signal.card_label} · "
                    f"{signal.billing_month:02d}/{signal.billing_year} · "
                    f"status {signal.conciliation_status}"
                )
            else:
                inclusion_label = "Sem vínculo"
                inclusion_reason = "Nenhuma conciliação encontrada para este lançamento."

        rows.append(
            {
                "id": tx.id,
                "transaction_date": tx.transaction_date,
                "transaction_date_display": format_date_br(tx.transaction_date),
                "description": tx.description_raw,
                "description_normalized": tx.description_normalized,
                "category": _analysis_category_name(tx.category),
                "transaction_kind": tx.transaction_kind,
                "source_type": tx.source_type,
                "amount": float(tx.amount),
                "amount_display": format_currency_br(abs(float(tx.amount))),
                "direction": tx.direction,
                "is_transfer_technical": is_transfer,
                "is_conciliated_bank_payment": signal is not None,
                "conciliation_status": signal.conciliation_status if signal is not None else None,
                "conciliation_label": inclusion_label,
                "conciliation_reason": inclusion_reason,
                "is_included": is_included,
                "invoice_id": signal.invoice_id if signal is not None else None,
                "invoice_reference": (
                    f"{signal.card_label} · {signal.billing_month:02d}/{signal.billing_year}"
                    if signal is not None
                    else None
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            row["transaction_date"],
            abs(row["amount"]),
            row["description"].casefold(),
            row["id"],
        ),
        reverse=True,
    )
    return {
        "rows": rows,
        "transaction_count": len(rows),
        "included_count": sum(1 for row in rows if row["is_included"]),
        "excluded_count": sum(1 for row in rows if not row["is_included"]),
    }


def build_invoice_operational_snapshot(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    conciliated_only: bool = False,
) -> dict:
    rows = db.execute(
        select(
            CreditCardInvoiceItem,
            CreditCardInvoice,
            CreditCard,
            CreditCardInvoiceConciliation.status,
        )
        .join(CreditCardInvoice, CreditCardInvoice.id == CreditCardInvoiceItem.invoice_id)
        .join(CreditCard, CreditCard.id == CreditCardInvoice.card_id)
        .outerjoin(CreditCardInvoiceConciliation, CreditCardInvoiceConciliation.invoice_id == CreditCardInvoice.id)
        .where(
            CreditCardInvoice.due_date >= period_start,
            CreditCardInvoice.due_date <= period_end,
        )
        .order_by(
            CreditCardInvoiceItem.purchase_date.desc(),
            CreditCardInvoiceItem.id.desc(),
        )
    ).all()

    item_rows: list[dict] = []
    for item, invoice, card, conciliation_status in rows:
        resolved_status = conciliation_status or "pending_review"
        item_type = classify_credit_card_invoice_item(item)
        is_visible_in_conciliated = resolved_status == "conciliated" and item_type in {"charge", "credit"}
        if conciliated_only and not is_visible_in_conciliated:
            continue
        if is_visible_in_conciliated:
            visibility_label = "Dentro da leitura"
            visibility_reason = "Item de fatura considerado na leitura conciliada."
        elif item_type == "payment":
            visibility_label = "Técnico"
            visibility_reason = "Pagamento técnico de fatura; não entra como consumo."
        elif item_type == "credit":
            visibility_label = "Fora da leitura"
            visibility_reason = "Crédito técnico fora da leitura principal enquanto a fatura não estiver conciliada."
        else:
            visibility_label = "Fora da leitura"
            visibility_reason = (
                "Item de compra so entra na leitura conciliada quando a fatura estiver com status conciliated."
            )

        item_rows.append(
            {
                "id": item.id,
                "invoice_id": invoice.id,
                "card_label": card.card_label,
                "purchase_date": item.purchase_date,
                "purchase_date_display": format_date_br(item.purchase_date),
                "due_date": invoice.due_date,
                "due_date_display": format_date_br(invoice.due_date),
                "closing_date_display": format_date_br(invoice.closing_date) if invoice.closing_date else "-",
                "description": item.description_raw,
                "description_normalized": item.description_normalized or "",
                "category": _analysis_category_name(item.category),
                "item_type": item_type,
                "conciliation_status": resolved_status,
                "amount": float(item.amount_brl),
                "amount_display": format_currency_br(abs(float(item.amount_brl))),
                "is_visible_in_conciliated": is_visible_in_conciliated,
                "visibility_label": visibility_label,
                "visibility_reason": visibility_reason,
            }
        )

    return {
        "rows": item_rows,
        "item_count": len(item_rows),
        "visible_count": sum(1 for row in item_rows if row["is_visible_in_conciliated"]),
    }


def build_conciliated_operational_snapshot(
    db: Session,
    *,
    period_start: date,
    period_end: date,
) -> dict:
    statement_snapshot = build_statement_operational_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
        conciliated_view=True,
    )
    invoice_snapshot = build_invoice_operational_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
        conciliated_only=True,
    )

    rows: list[dict] = []
    for row in statement_snapshot["rows"]:
        if not row["is_included"]:
            continue
        impact_amount = float(row["amount"])
        analytic_type = "income" if impact_amount > 0 else "expense"
        rows.append(
            {
                "source": "statement",
                "source_label": "Extrato",
                "record_id": row["id"],
                "event_date": row["transaction_date"],
                "event_date_display": row["transaction_date_display"],
                "secondary_date_display": None,
                "description": row["description"],
                "description_normalized": row["description_normalized"],
                "category": row["category"],
                "analytic_type": analytic_type,
                "analytic_type_label": "Receita" if analytic_type == "income" else "Despesa",
                "source_kind": row["transaction_kind"],
                "source_kind_label": row["transaction_kind"],
                "reference": row["invoice_reference"] or "Conta",
                "impact_amount": impact_amount,
                "impact_display": format_signed_currency_br(impact_amount),
                "impact_abs_display": row["amount_display"],
                "reason": row["conciliation_reason"],
                "primary_action_href": f"/admin/transactions/{row['id']}",
                "primary_action_label": "Abrir",
                "secondary_action_href": (
                    f"/admin/credit-card-invoices/{row['invoice_id']}#invoice-conciliation-section"
                    if row["invoice_id"]
                    else None
                ),
                "secondary_action_label": "Fatura" if row["invoice_id"] else None,
            }
        )

    for row in invoice_snapshot["rows"]:
        if not row["is_visible_in_conciliated"]:
            continue
        if row["item_type"] == "charge":
            impact_amount = -abs(float(row["amount"]))
            analytic_type = "expense"
            analytic_type_label = "Despesa"
        elif row["item_type"] == "credit":
            impact_amount = abs(float(row["amount"]))
            analytic_type = "credit"
            analytic_type_label = "Crédito"
        else:
            continue
        rows.append(
            {
                "source": "invoice",
                "source_label": "Fatura",
                "record_id": row["id"],
                "event_date": row["purchase_date"],
                "event_date_display": row["purchase_date_display"],
                "secondary_date_display": f"venc. {row['due_date_display']}",
                "description": row["description"],
                "description_normalized": row["description_normalized"],
                "category": row["category"],
                "analytic_type": analytic_type,
                "analytic_type_label": analytic_type_label,
                "source_kind": row["item_type"],
                "source_kind_label": row["item_type"],
                "reference": f"{row['card_label']} · fatura #{row['invoice_id']}",
                "impact_amount": impact_amount,
                "impact_display": format_signed_currency_br(impact_amount),
                "impact_abs_display": row["amount_display"],
                "reason": row["visibility_reason"],
                "primary_action_href": f"/admin/credit-card-invoices/{row['invoice_id']}/items/{row['id']}/category",
                "primary_action_label": "Editar item",
                "secondary_action_href": f"/admin/credit-card-invoices/{row['invoice_id']}",
                "secondary_action_label": "Fatura",
            }
        )

    rows.sort(
        key=lambda row: (
            row["event_date"],
            abs(row["impact_amount"]),
            row["description"].casefold(),
            row["record_id"],
        ),
        reverse=True,
    )
    return {
        "rows": rows,
        "row_count": len(rows),
        "statement_count": sum(1 for row in rows if row["source"] == "statement"),
        "invoice_count": sum(1 for row in rows if row["source"] == "invoice"),
        "income_count": sum(1 for row in rows if row["analytic_type"] == "income"),
        "expense_count": sum(1 for row in rows if row["analytic_type"] == "expense"),
        "credit_count": sum(1 for row in rows if row["analytic_type"] == "credit"),
        "net_impact_total": round(sum(row["impact_amount"] for row in rows), 2),
        "net_impact_display": format_signed_currency_br(sum(row["impact_amount"] for row in rows)),
    }


def build_conciliated_composition_snapshot(
    db: Session,
    *,
    period_start: date,
    period_end: date,
) -> dict:
    current_txs = _load_transactions_for_period(db, period_start=period_start, period_end=period_end)
    conciliated_month = _build_conciliated_month_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
        current_txs=current_txs,
    )
    rows = [
        {
            "key": "bank_income_total",
            "label": "Entradas totais da conta",
            "value": conciliated_month["bank_income_total"],
            "value_display": conciliated_month["bank_income_display"],
        },
        {
            "key": "transfer_income_total",
            "label": "Transferências de entrada removidas",
            "value": conciliated_month["transfer_income_total"],
            "value_display": conciliated_month["transfer_income_display"],
        },
        {
            "key": "real_bank_income_total",
            "label": "Receitas reais conciliadas",
            "value": conciliated_month["real_bank_income_total"],
            "value_display": conciliated_month["real_bank_income_display"],
        },
        {
            "key": "total_bank_outflow_total",
            "label": "Saídas totais da conta",
            "value": conciliated_month["total_bank_outflow_total"],
            "value_display": conciliated_month["total_bank_outflow_display"],
        },
        {
            "key": "transfer_expense_total",
            "label": "Transferências de saída removidas",
            "value": conciliated_month["transfer_expense_total"],
            "value_display": conciliated_month["transfer_expense_display"],
        },
        {
            "key": "excluded_conciliated_bank_payment_total",
            "label": "Pagamentos bancários conciliados removidos",
            "value": conciliated_month["excluded_conciliated_bank_payment_total"],
            "value_display": conciliated_month["excluded_conciliated_bank_payment_display"],
        },
        {
            "key": "conciliated_card_charge_total",
            "label": "Charges de fatura conciliadas",
            "value": conciliated_month["conciliated_card_charge_total"],
            "value_display": conciliated_month["conciliated_card_charge_display"],
        },
        {
            "key": "conciliated_invoice_credit_total",
            "label": "Créditos de fatura",
            "value": conciliated_month["conciliated_invoice_credit_total"],
            "value_display": conciliated_month["conciliated_invoice_credit_display"],
        },
        {
            "key": "real_conciliated_expense_total",
            "label": "Despesas reais conciliadas",
            "value": conciliated_month["real_conciliated_expense_total"],
            "value_display": conciliated_month["real_conciliated_expense_display"],
        },
        {
            "key": "real_conciliated_balance_total",
            "label": "Saldo real conciliado",
            "value": conciliated_month["real_conciliated_balance_total"],
            "value_display": conciliated_month["real_conciliated_balance_display"],
        },
    ]
    return {
        "rows": rows,
        "summary": conciliated_month,
    }


def _is_meaningful_consumption_change(change: dict | None) -> bool:
    if change is None or change["delta"] <= 0:
        return False
    percent = change["percent"] or 0.0
    return change["delta"] >= 150.0 or percent >= 0.15


def _build_alerts(
    *,
    primary_summary: dict,
    consumption_context: dict,
) -> list[dict]:
    alerts: list[dict] = []
    if primary_summary["balance"] < 0:
        alerts.append(
            {
                "level": "danger",
                "title": "Saldo negativo no período",
                "body": (
                    f"O período fechou com saldo real conciliado de {primary_summary['balance_display']}. "
                    "Vale revisar as maiores saídas de consumo antes do próximo fechamento."
                ),
            }
        )
    top_expense_category = consumption_context["top_category"]
    if top_expense_category and top_expense_category["consumption_share"] >= 0.35:
        alerts.append(
            {
                "level": "warn",
                "title": "Alta concentração em uma categoria de consumo",
                "body": (
                    f"Na visão de consumo, {top_expense_category['name']} respondeu por "
                    f"{top_expense_category['consumption_share_display']} do gasto do mês-base."
                ),
            }
        )
    largest_increase = consumption_context["largest_increase"]
    if largest_increase and _is_meaningful_consumption_change(largest_increase["previous_month_change"]):
        alerts.append(
            {
                "level": "warn",
                "title": f"Alta relevante no consumo de {largest_increase['name']}",
                "body": (
                    f"Na visão de consumo, {largest_increase['name']} subiu "
                    f"{largest_increase['previous_month_change']['delta_display']} contra "
                    f"{consumption_context['previous_month_label']}."
                ),
            }
        )
    if consumption_context["uncategorized_share"] >= 0.08:
        alerts.append(
            {
                "level": "warn",
                "title": "Não categorizado ainda alto na visão de consumo",
                "body": (
                    f"Ainda existem {consumption_context['uncategorized_display']} sem categoria definida, o que representa "
                    f"{consumption_context['uncategorized_share_display']} do gasto categorial de consumo."
                ),
            }
        )
    return alerts[:5]


def _build_actions(
    *,
    primary_summary: dict,
    consumption_context: dict,
) -> list[dict]:
    actions: list[dict] = []
    if consumption_context["uncategorized_share"] >= 0.05:
        actions.append(
            {
                "title": "Melhorar a qualidade da visão de consumo",
                "body": (
                    f"Priorize a revisão do não categorizado ({consumption_context['uncategorized_display']}) "
                    "para evitar distorção na leitura categorial do mês."
                ),
            }
        )

    top_expense_category = consumption_context["top_category"]
    if top_expense_category and (
        top_expense_category["expense_total"] >= 100.0
        and (
            top_expense_category["consumption_share"] >= 0.3
            or _is_meaningful_consumption_change(top_expense_category.get("previous_month_change"))
        )
    ):
        top_category_change = top_expense_category.get("previous_month_change")
        top_category_change_text = ""
        if top_category_change is not None and top_category_change["delta"] > 0:
            top_category_change_text = (
                f" e subiu {top_category_change['delta_display']} contra "
                f"{consumption_context['previous_month_label']}"
            )
        actions.append(
            {
                "title": f"Revisar a categoria {top_expense_category['name']}",
                "body": (
                    f"Na visão de consumo, ela concentrou {top_expense_category['consumption_share_display']} do gasto do mês-base"
                    f"{top_category_change_text}."
                ),
            }
        )

    largest_increase = consumption_context["largest_increase"]
    if (
        largest_increase
        and largest_increase["name"] != (top_expense_category["name"] if top_expense_category else None)
        and _is_meaningful_consumption_change(largest_increase["previous_month_change"])
    ):
        actions.append(
            {
                "title": "Investigar o aumento do consumo",
                "body": (
                    f"Comece por {largest_increase['name']}, que subiu "
                    f"{largest_increase['previous_month_change']['delta_display']} frente a "
                    f"{consumption_context['previous_month_label']}."
                ),
            }
        )

    if primary_summary["balance"] < 0:
        focus_categories = [item["name"] for item in consumption_context["top_categories"]]
        categories_text = ", ".join(focus_categories) if focus_categories else "as maiores despesas variáveis"
        actions.append(
            {
                "title": "Atacar o saldo negativo imediatamente",
                "body": (
                    f"Comece por {categories_text} para tentar recuperar caixa já no próximo período, "
                    "sem misturar consumo com pagamentos técnicos de fatura."
                ),
            }
        )

    unique: list[dict] = []
    seen_titles: set[str] = set()
    for item in actions:
        if item["title"] in seen_titles:
            continue
        unique.append(item)
        seen_titles.add(item["title"])
    return unique[:5]


def build_analysis_snapshot(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    home_lens: str = "cash",
    home_chart_mode: str = "year",
    home_chart_year: int | None = None,
    home_chart_compare: str | None = None,
) -> dict:
    current_txs = _load_transactions_for_period(db, period_start=period_start, period_end=period_end)
    summary = _build_summary(current_txs)

    comparison_month = month_start(period_start)
    previous_month_end = comparison_month - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    previous_txs = _load_transactions_for_period(db, period_start=previous_month_start, period_end=previous_month_end)
    previous_summary = _build_summary(previous_txs)
    comparison = {
        "reference_label": format_month_label(previous_month_start),
        "income": _build_metric_change(summary["income_total"], previous_summary["income_total"]),
        "expense": _build_metric_change(summary["expense_total"], previous_summary["expense_total"]),
        "balance": _build_metric_change(summary["balance"], previous_summary["balance"]),
    }

    anchor_month = month_start(period_end)
    current_month_start = anchor_month
    current_month_end = month_end(anchor_month)
    current_month_txs = _load_transactions_for_period(db, period_start=current_month_start, period_end=current_month_end)
    current_month_summary = _build_summary(current_month_txs)
    category_breakdown = _build_conciliated_category_breakdown(
        db,
        period_start=current_month_start,
        period_end=current_month_end,
        current_txs=current_month_txs,
    )
    period_category_breakdown = _build_conciliated_category_breakdown(
        db,
        period_start=period_start,
        period_end=period_end,
        current_txs=current_txs,
    )
    category_history = _build_conciliated_category_history(db, anchor_month=anchor_month)
    home_cards = _build_home_cards(
        db,
        anchor_month=anchor_month,
        current_month_txs=current_month_txs,
        current_category_breakdown=category_breakdown,
        lens=home_lens,
    )
    category_rows = category_breakdown["rows"]
    technical_items = _build_technical_items(current_month_txs, expense_total=current_month_summary["expense_total"])
    quality = _build_quality(summary)
    home_category_comparison = _build_home_category_comparison(
        db,
        anchor_month=anchor_month,
        visible=(home_lens == "competence"),
    )
    conciliation_signals = build_conciliation_analytics_snapshot(db, period_start=period_start, period_end=period_end)
    conciliated_month = _build_conciliated_month_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
        current_txs=current_txs,
    )
    primary_summary = _build_primary_summary(conciliated_month=conciliated_month)
    consumption_context = _build_consumption_signal_context(
        category_breakdown=category_breakdown,
        category_history=category_history,
    )
    home_dashboard = _build_home_dashboard(
        db,
        anchor_month=anchor_month,
        current_month_txs=current_month_txs,
        category_breakdown=category_breakdown,
        category_history=category_history,
        active_lens=home_lens,
        chart_mode=home_chart_mode,
        chart_year=home_chart_year,
        chart_compare=home_chart_compare,
    )

    alerts = _build_alerts(
        primary_summary=primary_summary,
        consumption_context=consumption_context,
    )
    actions = _build_actions(
        primary_summary=primary_summary,
        consumption_context=consumption_context,
    )
    monthly_series = _build_monthly_series(db, anchor_month=anchor_month)
    conciliated_monthly_series = _build_conciliated_monthly_series(db, anchor_month=anchor_month)
    statement_category_breakdown = _build_statement_category_breakdown(current_txs=current_txs)
    invoice_month_snapshot = _build_invoice_month_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
    )
    invoice_monthly_series = _build_invoice_monthly_series(db, anchor_month=anchor_month)
    consumption_monthly_series = _build_consumption_monthly_series(db, anchor_month=anchor_month)
    statement_category_monthly_series = build_statement_category_monthly_series(
        db,
        anchor_month=anchor_month,
    )
    invoice_category_monthly_series = build_invoice_category_monthly_series(
        db,
        anchor_month=anchor_month,
    )
    top_expense_categories = category_breakdown["top_expense_categories"]
    category_consumption_monthly_series = build_category_consumption_monthly_series(
        db,
        anchor_month=anchor_month,
        category_names=None,
    )
    return {
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "label": f"{format_date_br(period_start)} a {format_date_br(period_end)}",
            "month_reference_label": format_month_label(anchor_month),
        },
        "primary_summary": primary_summary,
        "summary": summary,
        "comparison": comparison,
        "home_cards": home_cards,
        "home_yearly_chart": home_dashboard["chart"],
        "home_category_comparison": home_category_comparison,
        "home_dashboard": home_dashboard,
        "monthly_series": monthly_series,
        "conciliated_monthly_series": conciliated_monthly_series,
        "statement_category_breakdown": statement_category_breakdown,
        "invoice_month_snapshot": invoice_month_snapshot,
        "invoice_monthly_series": invoice_monthly_series,
        "consumption_monthly_series": consumption_monthly_series,
        "category_breakdown": category_breakdown,
        "category_history": category_history,
        "categories": category_rows,
        "top_expense_categories": top_expense_categories,
        "technical_items": technical_items,
        "conciliation_signals": {
            "conciliated_bank_payment_total_brl": float(conciliation_signals.conciliated_bank_payment_total_brl),
            "conciliated_bank_payment_count": conciliation_signals.conciliated_bank_payment_count,
            "conciliated_bank_payment_display": format_currency_br(float(conciliation_signals.conciliated_bank_payment_total_brl)),
            "invoice_credit_total_brl": float(conciliation_signals.invoice_credit_total_brl),
            "invoice_credit_display": format_currency_br(float(conciliation_signals.invoice_credit_total_brl)),
            "invoices_by_status": conciliation_signals.invoices_by_status,
            "invoices_total": conciliation_signals.invoices_total,
            "note": conciliation_signals.note,
        },
        "conciliated_month": conciliated_month,
        "quality": quality,
        "alerts": alerts,
        "actions": actions,
        "charts": {
            "monthly": {
                "labels": [item["label"] for item in monthly_series],
                "income": [round(item["income_total"], 2) for item in monthly_series],
                "expense": [round(item["expense_total"], 2) for item in monthly_series],
                "balance": [round(item["balance"], 2) for item in monthly_series],
            },
            "conciliated": {
                "labels": [item["label"] for item in conciliated_monthly_series],
                "income": [round(item["income_total"], 2) for item in conciliated_monthly_series],
                "expense": [round(item["expense_total"], 2) for item in conciliated_monthly_series],
                "balance": [round(item["balance"], 2) for item in conciliated_monthly_series],
            },
            "invoice_monthly": {
                "labels": [item["label"] for item in invoice_monthly_series],
                "total_billed": [round(item["total_billed"], 2) for item in invoice_monthly_series],
                "charge_total": [round(item["charge_total"], 2) for item in invoice_monthly_series],
                "credit_total": [round(item["credit_total"], 2) for item in invoice_monthly_series],
            },
            "consumption_monthly": {
                "labels": [item["label"] for item in consumption_monthly_series],
                "values": [round(item["consumption_total"], 2) for item in consumption_monthly_series],
            },
            "categories": {
                "labels": [item["name"] for item in top_expense_categories],
                "values": [round(item["expense_total"], 2) for item in top_expense_categories],
                "technical": [item["is_technical"] for item in top_expense_categories],
            },
            "categories_monthly": category_consumption_monthly_series,
            "conciliated_categories_period": _build_category_period_totals_chart(period_category_breakdown["rows"]),
            "statement_categories_monthly": statement_category_monthly_series,
            "statement_categories_period": _build_category_period_totals_chart(statement_category_breakdown["rows"]),
            "statement_categories": {
                "labels": [item["name"] for item in statement_category_breakdown["top_expense_categories"]],
                "values": [round(item["expense_total"], 2) for item in statement_category_breakdown["top_expense_categories"]],
                "technical": [item["is_technical"] for item in statement_category_breakdown["top_expense_categories"]],
            },
            "invoice_categories_monthly": invoice_category_monthly_series,
            "invoice_categories_period": _build_category_period_totals_chart(invoice_month_snapshot["category_breakdown"]["rows"]),
            "invoice_categories": {
                "labels": [item["name"] for item in invoice_month_snapshot["category_breakdown"]["top_expense_categories"]],
                "values": [round(item["expense_total"], 2) for item in invoice_month_snapshot["category_breakdown"]["top_expense_categories"]],
                "technical": [item["is_technical"] for item in invoice_month_snapshot["category_breakdown"]["top_expense_categories"]],
            },
            "overview_categories_period": _build_category_period_totals_chart(period_category_breakdown["rows"]),
        },
    }


def _render_alert_items(items: list[dict]) -> str:
    if not items:
        return "<p>Nenhum alerta determinístico relevante para este período.</p>"
    rows = "".join(f"<li><strong>{item['title']}</strong><br>{item['body']}</li>" for item in items)
    return f"<ul>{rows}</ul>"


def _render_action_items(items: list[dict]) -> str:
    if not items:
        return "<p>Nenhuma ação prioritária sugerida no momento.</p>"
    rows = "".join(f"<li><strong>{item['title']}</strong><br>{item['body']}</li>" for item in items)
    return f"<ul>{rows}</ul>"


def _render_category_items(items: list[dict]) -> str:
    rows = []
    for item in items[:5]:
        note = f" <em>({item['technical_label']})</em>" if item["is_technical"] else ""
        rows.append(f"<li><strong>{item['name']}</strong>: {item['display_total']} - {item['flow_label']}{note}</li>")
    return "<ul>{}</ul>".format("".join(rows)) if rows else "<p>Sem categorias relevantes no mês-base.</p>"


def _render_category_history_items(history: dict) -> str:
    rows = []
    for item in history.get("rows", [])[:5]:
        technical_note = ""
        if item["is_technical"] and item["technical_label"]:
            technical_note = " <em>({})</em>".format(item["technical_label"])
        previous_month_note = (
            "{}: {} | delta: {}".format(
                history["previous_month_label"],
                item["previous_month_display"],
                item["previous_month_change"]["delta_display"],
            )
            if item["previous_month_change"] is not None
            else "{}: sem base".format(history["previous_month_label"])
        )
        previous_year_note = (
            "{}: {} | delta: {}".format(
                history["previous_year_label"],
                item["previous_year_display"],
                item["previous_year_change"]["delta_display"],
            )
            if item["previous_year_change"] is not None
            else "{}: sem base".format(history["previous_year_label"])
        )
        rows.append(
            "<li><strong>{name}</strong>{technical}: {current} | {previous_month} | {previous_year}</li>".format(
                name=item["name"],
                technical=technical_note,
                current=item["current_display"],
                previous_month=previous_month_note,
                previous_year=previous_year_note,
            )
        )
    return "<ul>{}</ul>".format("".join(rows)) if rows else "<p>Sem categorias conciliadas suficientes para comparar historicamente.</p>"


def render_analysis_html(snapshot: dict) -> str:
    summary = snapshot["summary"]
    primary_summary = snapshot.get("primary_summary", summary)
    comparison = snapshot["comparison"]
    technical = snapshot["technical_items"]
    conciliated_month = snapshot["conciliated_month"]
    category_breakdown = snapshot.get("category_breakdown", {})
    category_history = snapshot.get("category_history", {})
    category_breakdown_note = category_breakdown.get("note") or "Breakdown mensal por categoria usando a visão de consumo atual."
    invoice_credit_adjustment_display = category_breakdown.get("invoice_credit_adjustment_display") or "R$ 0,00"
    category_history_note = category_history.get("note") or "Comparações históricas por categoria na visão de consumo ainda indisponíveis."
    category_history_html = _render_category_history_items(category_history)
    alerts_html = _render_alert_items(snapshot["alerts"])
    actions_html = _render_action_items(snapshot["actions"])
    categories_html = _render_category_items(snapshot["categories"])
    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset=\"UTF-8\"></head><body>",
        "<h1>Análise financeira determinística</h1>",
        "<p><strong>Período:</strong> {}</p>".format(snapshot["period"]["label"]),
        "<h2>Resumo principal conciliado</h2>",
        "<p>{}</p>".format(primary_summary["executive_summary"]),
        "<p>{} Pagamentos bancários excluídos por conciliação: {}.</p>".format(
            primary_summary["coverage_note"],
            primary_summary["excluded_bank_payment_display"],
        ),
        "<h2>Visão bruta de apoio</h2>",
        "<p>Receitas brutas em {}, despesas brutas em {} e saldo bruto de {}.</p>".format(
            summary["income_display"],
            summary["expense_display"],
            summary["balance_display"],
        ),
        "<p>Contra {}, as despesas brutas {} {} ({}).</p>".format(
            comparison["reference_label"],
            comparison["expense"]["trend_label"],
            comparison["expense"]["percent_display"],
            comparison["expense"]["delta_display"],
        ),
        "<p>Itens técnicos do mês-base: {} ({} das despesas brutas).</p>".format(
            technical["combined_display"],
            technical["combined_share_display"],
        ),
        "<h2>Categorias do mês-base na visão de consumo</h2>",
        "<p>{}</p>".format(category_breakdown_note),
        (
            "<p>Créditos técnicos de fatura fora das categorias de consumo: {}. "
            "Na implementação atual, esse bloco técnico segue a data do próprio item importado quando disponível, "
            "sem redistribuição artificial entre categorias.</p>"
        ).format(invoice_credit_adjustment_display),
        "<h2>Comparações históricas por categoria na visão de consumo</h2>",
        "<p>{}</p>".format(category_history_note),
        category_history_html,
        "<h2>Cobertura da visão conciliada</h2>",
        "<p>Receitas reais conciliadas em {}, despesas reais conciliadas em {} e saldo real conciliado de {}.</p>".format(
            conciliated_month["real_bank_income_display"],
            conciliated_month["real_conciliated_expense_display"],
            conciliated_month["real_conciliated_balance_display"],
        ),
        "<p>Como apoio, entradas totais da conta em {} e saídas totais da conta em {}.</p>".format(
            conciliated_month["bank_income_display"],
            conciliated_month["total_bank_outflow_display"],
        ),
        "<p>Faturas conciliadas consideradas: {}. Faturas fora da leitura principal: {}.</p>".format(
            conciliated_month["included_invoice_count"],
            conciliated_month["outside_invoices_total"],
        ),
        "<h2>Alertas</h2>",
        alerts_html,
        "<h2>Ações recomendadas</h2>",
        actions_html,
        "<h2>Categorias em destaque</h2>",
        categories_html,
        "</body></html>",
    ]
    return "".join(parts)


def parse_analysis_payload(payload: str) -> dict | None:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) and "summary" in parsed else None


def run_analysis(db: Session, period_start: date, period_end: date, trigger_source_file_id: int | None):
    snapshot = build_analysis_snapshot(db, period_start=period_start, period_end=period_end)
    txs = db.scalars(
        select(Transaction).where(Transaction.transaction_date >= period_start, Transaction.transaction_date <= period_end)
    ).all()
    payload = {
        "transactions": len(txs),
        "total": round(sum(float(t.amount) for t in txs if t.should_count_in_spending), 2),
        **snapshot,
    }
    html = render_analysis_html(snapshot)
    run = AnalysisRun(
        period_start=period_start,
        period_end=period_end,
        trigger_source_file_id=trigger_source_file_id,
        payload=json.dumps(payload, ensure_ascii=False),
        prompt="deterministic_html_analysis_v2",
        html_output=html,
        status="success",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
