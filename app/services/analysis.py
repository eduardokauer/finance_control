from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json
from math import fabs

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.repositories.models import AnalysisRun, Transaction
from app.services.credit_card_bills import build_conciliation_analytics_snapshot
from app.utils.normalization import normalize_description

UNCATEGORIZED_NAMES = ("Não Categorizado", "Nao Categorizado")
MONTH_LABELS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
TECHNICAL_TRANSFER_KEYS = {"transferencias"}
TECHNICAL_CARD_BILL_KEYS = {"pagamento de fatura", "pagamento fatura"}


def format_currency_br(value: float) -> str:
    sign = "-" if value < 0 else ""
    formatted = f"{abs(float(value)):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{sign}R$ {formatted}"


def format_percent_br(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%".replace(".", ",")


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


def _is_transfer_technical(tx: Transaction) -> bool:
    return tx.transaction_kind == "transfer" or _normalized_category_name(tx.category) in TECHNICAL_TRANSFER_KEYS


def _is_card_bill_technical(tx: Transaction) -> bool:
    return bool(tx.is_card_bill_payment) or _normalized_category_name(tx.category) in TECHNICAL_CARD_BILL_KEYS


def _expense_amount(tx: Transaction) -> float:
    return abs(float(tx.amount)) if float(tx.amount) < 0 and tx.should_count_in_spending else 0.0


def _income_amount(tx: Transaction) -> float:
    return float(tx.amount) if float(tx.amount) > 0 else 0.0


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
        "percent_display": format_percent_br(percent),
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


def _build_category_rows(txs: list[Transaction], *, expense_total: float) -> list[dict]:
    grouped: dict[str, dict] = defaultdict(
        lambda: {
            "expense_total": 0.0,
            "income_total": 0.0,
            "transaction_count": 0,
            "is_transfer_technical": False,
            "is_card_bill_technical": False,
        }
    )
    for tx in txs:
        bucket = grouped[tx.category]
        bucket["expense_total"] += _expense_amount(tx)
        bucket["income_total"] += _income_amount(tx)
        bucket["transaction_count"] += 1
        bucket["is_transfer_technical"] = bucket["is_transfer_technical"] or _is_transfer_technical(tx)
        bucket["is_card_bill_technical"] = bucket["is_card_bill_technical"] or _is_card_bill_technical(tx)

    rows: list[dict] = []
    for category, values in grouped.items():
        movement_total = values["expense_total"] + values["income_total"]
        if values["expense_total"] > values["income_total"]:
            flow_label = "Despesa"
        elif values["income_total"] > values["expense_total"]:
            flow_label = "Receita"
        else:
            flow_label = "Misto"
        technical_label = None
        if values["is_transfer_technical"]:
            technical_label = "Transferências"
        elif values["is_card_bill_technical"]:
            technical_label = "Pagamento de Fatura"
        share_of_expense = values["expense_total"] / expense_total if expense_total else 0.0
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
                "share_of_expense_display": format_percent_br(share_of_expense if values["expense_total"] else None),
                "transaction_count": values["transaction_count"],
                "is_technical": technical_label is not None,
                "technical_label": technical_label,
            }
        )
    rows.sort(key=lambda item: (item["expense_total"], item["movement_total"], item["income_total"]), reverse=True)
    return rows


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


def _build_quality(summary: dict) -> dict:
    uncategorized_share = summary["uncategorized_total"] / summary["expense_total"] if summary["expense_total"] else 0.0
    return {
        "uncategorized_total": summary["uncategorized_total"],
        "uncategorized_display": summary["uncategorized_display"],
        "uncategorized_share": uncategorized_share,
        "uncategorized_share_display": format_percent_br(uncategorized_share),
    }


def _build_alerts(
    *,
    summary: dict,
    comparison: dict,
    categories: list[dict],
    technical_items: dict,
    quality: dict,
) -> list[dict]:
    alerts: list[dict] = []
    if summary["balance"] < 0:
        alerts.append(
            {
                "level": "danger",
                "title": "Saldo negativo no período",
                "body": f"O período fechou com saldo de {summary['balance_display']}. Vale revisar as maiores saídas antes do próximo fechamento.",
            }
        )
    if comparison["expense"]["trend"] == "up" and (comparison["expense"]["percent"] or 0) >= 0.15:
        alerts.append(
            {
                "level": "warn",
                "title": "Despesas subiram em relação ao mês anterior",
                "body": f"As despesas aumentaram {comparison['expense']['percent_display']} ({comparison['expense']['delta_display']}) contra o mês anterior.",
            }
        )
    top_expense_category = next((item for item in categories if item["expense_total"] > 0), None)
    if top_expense_category and top_expense_category["share_of_expense"] >= 0.35:
        alerts.append(
            {
                "level": "warn",
                "title": "Alta concentração em uma categoria",
                "body": f"{top_expense_category['name']} respondeu por {top_expense_category['share_of_expense_display']} das despesas do mês-base.",
            }
        )
    if quality["uncategorized_share"] >= 0.08:
        alerts.append(
            {
                "level": "warn",
                "title": "Não categorizado ainda alto",
                "body": f"Ainda existem {quality['uncategorized_display']} sem categoria definida, o que representa {quality['uncategorized_share_display']} das despesas.",
            }
        )
    if technical_items["combined_share"] >= 0.25:
        alerts.append(
            {
                "level": "warn",
                "title": "Itens técnicos pesam na leitura do mês",
                "body": f"Transferências e pagamento de fatura somam {technical_items['combined_display']} ({technical_items['combined_share_display']} das despesas).",
            }
        )
    if comparison["balance"]["percent"] is not None and fabs(comparison["balance"]["percent"]) >= 0.25:
        alerts.append(
            {
                "level": "warn",
                "title": "Variação forte frente ao mês anterior",
                "body": f"O saldo {comparison['balance']['trend_label']} {comparison['balance']['percent_display']} em relação ao período anterior comparável.",
            }
        )
    return alerts[:5]


def _build_actions(
    *,
    summary: dict,
    comparison: dict,
    categories: list[dict],
    technical_items: dict,
    quality: dict,
    previous_categories: dict[str, float],
) -> list[dict]:
    actions: list[dict] = []
    if quality["uncategorized_share"] >= 0.05:
        actions.append(
            {
                "title": "Melhorar a qualidade da base",
                "body": f"Priorize a revisão do não categorizado ({quality['uncategorized_display']}) para evitar distorção na leitura do mês.",
            }
        )

    top_expense_category = next((item for item in categories if item["expense_total"] > 0 and not item["is_technical"]), None)
    if top_expense_category:
        previous_amount = previous_categories.get(top_expense_category["name"], 0.0)
        delta = top_expense_category["expense_total"] - previous_amount
        if delta > 0:
            actions.append(
                {
                    "title": f"Revisar a categoria {top_expense_category['name']}",
                    "body": f"Ela concentrou {top_expense_category['share_of_expense_display']} das despesas e subiu {format_currency_br(delta)} contra o mês anterior.",
                }
            )
    if comparison["expense"]["trend"] == "up" and (comparison["expense"]["percent"] or 0) >= 0.15:
        actions.append(
            {
                "title": "Investigar o aumento das despesas",
                "body": "Compare as maiores categorias do mês atual com o mês anterior para identificar o que puxou a alta.",
            }
        )
    if technical_items["combined_share"] >= 0.2:
        actions.append(
            {
                "title": "Separar consumo real de itens técnicos",
                "body": "Ao revisar o mês, considere transferências e pagamento de fatura em separado para não superestimar o gasto recorrente.",
            }
        )
    if summary["balance"] < 0:
        focus_categories = [item["name"] for item in categories if item["expense_total"] > 0 and not item["is_technical"]][:2]
        categories_text = ", ".join(focus_categories) if focus_categories else "as maiores despesas variáveis"
        actions.append(
            {
                "title": "Atacar o saldo negativo imediatamente",
                "body": f"Comece por {categories_text} para tentar recuperar caixa já no próximo período.",
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


def build_analysis_snapshot(db: Session, *, period_start: date, period_end: date) -> dict:
    current_txs = db.scalars(
        select(Transaction).where(Transaction.transaction_date >= period_start, Transaction.transaction_date <= period_end)
    ).all()
    summary = _build_summary(current_txs)

    comparison_month = month_start(period_start)
    previous_month_end = comparison_month - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    previous_txs = db.scalars(
        select(Transaction).where(
            Transaction.transaction_date >= previous_month_start,
            Transaction.transaction_date <= previous_month_end,
        )
    ).all()
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
    current_month_txs = db.scalars(
        select(Transaction).where(Transaction.transaction_date >= current_month_start, Transaction.transaction_date <= current_month_end)
    ).all()
    current_month_summary = _build_summary(current_month_txs)
    category_rows = _build_category_rows(current_month_txs, expense_total=current_month_summary["expense_total"])
    technical_items = _build_technical_items(current_month_txs, expense_total=current_month_summary["expense_total"])
    quality = _build_quality(summary)

    previous_category_rows = _build_category_rows(previous_txs, expense_total=previous_summary["expense_total"])
    previous_categories = {item["name"]: item["expense_total"] for item in previous_category_rows}

    alerts = _build_alerts(
        summary=summary,
        comparison=comparison,
        categories=category_rows,
        technical_items=technical_items,
        quality=quality,
    )
    actions = _build_actions(
        summary=summary,
        comparison=comparison,
        categories=category_rows,
        technical_items=technical_items,
        quality=quality,
        previous_categories=previous_categories,
    )
    monthly_series = _build_monthly_series(db, anchor_month=anchor_month)
    conciliation_signals = build_conciliation_analytics_snapshot(db, period_start=period_start, period_end=period_end)

    top_expense_categories = [item for item in category_rows if item["expense_total"] > 0][:8]
    return {
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "label": f"{format_date_br(period_start)} a {format_date_br(period_end)}",
            "month_reference_label": format_month_label(anchor_month),
        },
        "summary": summary,
        "comparison": comparison,
        "monthly_series": monthly_series,
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
            "categories": {
                "labels": [item["name"] for item in top_expense_categories],
                "values": [round(item["expense_total"], 2) for item in top_expense_categories],
                "technical": [item["is_technical"] for item in top_expense_categories],
            },
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
        rows.append(f"<li><strong>{item['name']}</strong>: {item['display_total']} · {item['flow_label']}{note}</li>")
    return f"<ul>{''.join(rows)}</ul>" if rows else "<p>Sem categorias relevantes no mês-base.</p>"


def render_analysis_html(snapshot: dict) -> str:
    summary = snapshot["summary"]
    comparison = snapshot["comparison"]
    technical = snapshot["technical_items"]
    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset=\"UTF-8\"></head><body>"
        f"<h1>Análise financeira determinística</h1>"
        f"<p><strong>Período:</strong> {snapshot['period']['label']}</p>"
        f"<p>Receitas em {summary['income_display']}, despesas em {summary['expense_display']} e saldo de {summary['balance_display']}.</p>"
        f"<p>Contra {comparison['reference_label']}, as despesas {comparison['expense']['trend_label']} {comparison['expense']['percent_display']} ({comparison['expense']['delta_display']}).</p>"
        f"<p>Itens técnicos do mês-base: {technical['combined_display']} ({technical['combined_share_display']} das despesas).</p>"
        "<h2>Alertas</h2>"
        f"{_render_alert_items(snapshot['alerts'])}"
        "<h2>Ações recomendadas</h2>"
        f"{_render_action_items(snapshot['actions'])}"
        "<h2>Categorias em destaque</h2>"
        f"{_render_category_items(snapshot['categories'])}"
        "</body></html>"
    )


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
