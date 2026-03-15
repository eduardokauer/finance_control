from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.repositories.models import Transaction

UNCATEGORIZED_CATEGORIES = {"Não Categorizado", "Outros"}


def build_llm_email_analysis(
    db: Session,
    period_start: date,
    period_end: date,
    trigger_source_file_id: int | None = None,
) -> dict:
    current_transactions = db.scalars(
        select(Transaction).where(Transaction.transaction_date >= period_start, Transaction.transaction_date <= period_end)
    ).all()
    history_transactions = db.scalars(select(Transaction).where(Transaction.transaction_date < period_start)).all()

    current_summary = _summarize_period(current_transactions)
    monthly_history = _build_monthly_history(history_transactions)
    used_history = monthly_history[-12:]
    months_available = len(monthly_history)
    months_used = len(used_history)
    analysis_mode = _analysis_mode(months_available)

    history_quality = {
        "full_history": "full",
        "partial_history": "partial",
        "insufficient_history": "insufficient",
    }[analysis_mode]
    historical_baseline = _build_historical_baseline(used_history)
    current_vs_history = _build_current_vs_history(current_summary, historical_baseline, used_history)
    signals = _build_signals(current_summary, current_transactions, historical_baseline, used_history)

    llm_payload = {
        "analysis_mode": analysis_mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "currency": "BRL",
        "current_period": {
            "start_date": period_start.isoformat(),
            "end_date": period_end.isoformat(),
            "days": (period_end - period_start).days + 1,
            "months_available_for_history": months_available,
            "history_window_target_months": 12,
            "history_window_used_months": months_used,
            "history_quality": history_quality,
            "trigger_source_file_id": trigger_source_file_id,
        },
        "deterministic_summary": current_summary,
        "historical_baseline": historical_baseline,
        "current_vs_history": current_vs_history,
        "signals": signals,
        "guardrails": {
            "must_not_invent_missing_history": True,
            "must_state_when_history_is_partial": True,
            "must_prioritize_actionable_insights": True,
            "must_avoid_generic_advice": True,
        },
    }
    return {
        "summary_html": _build_summary_html(period_start, period_end, current_summary),
        "llm_payload": llm_payload,
    }


def _analysis_mode(months_available: int) -> str:
    if months_available >= 12:
        return "full_history"
    if months_available >= 3:
        return "partial_history"
    return "insufficient_history"


def _summarize_period(transactions: list[Transaction]) -> dict:
    income_total = round(sum(t.amount for t in transactions if t.amount > 0), 2)
    expense_total_raw = sum(t.amount for t in transactions if t.should_count_in_spending and t.amount < 0)
    net_total = round(sum(t.amount for t in transactions), 2)
    category_totals = _collect_category_totals(transactions)
    expense_transactions = [tx for tx in transactions if tx.should_count_in_spending and tx.amount < 0]

    top_categories = [
        {"category": category, "amount": round(amount, 2)}
        for category, amount in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
    largest_expenses = [
        {
            "transaction_id": tx.id,
            "date": tx.transaction_date.isoformat(),
            "description": tx.description_raw,
            "category": tx.category,
            "amount": round(abs(tx.amount), 2),
        }
        for tx in sorted(expense_transactions, key=lambda item: abs(item.amount), reverse=True)[:5]
    ]
    return {
        "income_total": income_total,
        "expense_total": round(abs(expense_total_raw), 2),
        "net_total": net_total,
        "transactions_count": len(transactions),
        "top_categories": top_categories,
        "largest_expenses": largest_expenses,
    }


def _collect_category_totals(transactions: list[Transaction]) -> dict[str, float]:
    category_totals: dict[str, float] = defaultdict(float)
    for tx in transactions:
        if tx.should_count_in_spending and tx.amount < 0:
            category_totals[tx.category] += abs(tx.amount)
    return {category: round(amount, 2) for category, amount in category_totals.items()}


def _build_monthly_history(transactions: list[Transaction]) -> list[dict]:
    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for tx in transactions:
        grouped[tx.competence_month].append(tx)

    history = []
    for month in sorted(grouped):
        month_transactions = grouped[month]
        summary = _summarize_period(month_transactions)
        history.append(
            {
                "month": month,
                "income_total": summary["income_total"],
                "expense_total": summary["expense_total"],
                "net_total": summary["net_total"],
                "transactions_count": summary["transactions_count"],
                "category_totals": _collect_category_totals(month_transactions),
            }
        )
    return history


def _build_historical_baseline(used_history: list[dict]) -> dict:
    if not used_history:
        return {
            "monthly_totals": [],
            "expense_total_avg_12m": None,
            "expense_total_median_12m": None,
            "income_total_avg_12m": None,
            "net_total_avg_12m": None,
            "category_baselines": [],
        }

    expense_values = [month["expense_total"] for month in used_history]
    income_values = [month["income_total"] for month in used_history]
    net_values = [month["net_total"] for month in used_history]
    category_buckets: dict[str, list[float]] = defaultdict(list)
    for month in used_history:
        for category, amount in month["category_totals"].items():
            category_buckets[category].append(amount)

    category_baselines = [
        {
            "category": category,
            "avg_amount": round(sum(values) / len(used_history), 2),
            "months_present": len(values),
        }
        for category, values in sorted(category_buckets.items())
    ]
    return {
        "monthly_totals": [
            {
                "month": month["month"],
                "income_total": month["income_total"],
                "expense_total": month["expense_total"],
                "net_total": month["net_total"],
                "transactions_count": month["transactions_count"],
            }
            for month in used_history
        ],
        "expense_total_avg_12m": round(sum(expense_values) / len(expense_values), 2),
        "expense_total_median_12m": round(median(expense_values), 2),
        "income_total_avg_12m": round(sum(income_values) / len(income_values), 2),
        "net_total_avg_12m": round(sum(net_values) / len(net_values), 2),
        "category_baselines": category_baselines,
    }


def _build_current_vs_history(current_summary: dict, historical_baseline: dict, used_history: list[dict]) -> dict:
    prev_month = used_history[-1] if used_history else None
    category_baselines = {item["category"]: item["avg_amount"] for item in historical_baseline["category_baselines"]}
    current_categories = {item["category"]: item["amount"] for item in current_summary["top_categories"]}

    return {
        "expense_vs_avg_12m_abs": _delta_abs(current_summary["expense_total"], historical_baseline["expense_total_avg_12m"]),
        "expense_vs_avg_12m_pct": _delta_pct(current_summary["expense_total"], historical_baseline["expense_total_avg_12m"]),
        "income_vs_avg_12m_abs": _delta_abs(current_summary["income_total"], historical_baseline["income_total_avg_12m"]),
        "income_vs_avg_12m_pct": _delta_pct(current_summary["income_total"], historical_baseline["income_total_avg_12m"]),
        "net_vs_avg_12m_abs": _delta_abs(current_summary["net_total"], historical_baseline["net_total_avg_12m"]),
        "net_vs_avg_12m_pct": _delta_pct(current_summary["net_total"], historical_baseline["net_total_avg_12m"]),
        "vs_previous_month": None
        if prev_month is None
        else {
            "month": prev_month["month"],
            "expense_abs": round(current_summary["expense_total"] - prev_month["expense_total"], 2),
            "income_abs": round(current_summary["income_total"] - prev_month["income_total"], 2),
            "net_abs": round(current_summary["net_total"] - prev_month["net_total"], 2),
        },
        "category_deltas": [
            {
                "category": category,
                "current_amount": round(amount, 2),
                "baseline_avg_amount": round(category_baselines.get(category, 0.0), 2),
                "delta_abs": round(amount - category_baselines.get(category, 0.0), 2),
                "delta_pct": _delta_pct(amount, category_baselines.get(category)),
            }
            for category, amount in sorted(current_categories.items(), key=lambda item: item[1], reverse=True)
        ],
    }


def _build_signals(
    current_summary: dict,
    current_transactions: list[Transaction],
    historical_baseline: dict,
    used_history: list[dict],
) -> dict:
    expense_total = current_summary["expense_total"] or 0.0
    current_categories = current_summary["top_categories"]
    category_baselines = {item["category"]: item["avg_amount"] for item in historical_baseline["category_baselines"]}
    recurring_threshold = max(2, len(used_history) // 3) if used_history else 0
    occurrences: dict[str, int] = defaultdict(int)
    for month in used_history:
        for category in month["category_totals"]:
            occurrences[category] += 1

    uncategorized_expense_total = round(
        sum(
            abs(tx.amount)
            for tx in current_transactions
            if tx.category in UNCATEGORIZED_CATEGORIES and tx.should_count_in_spending and tx.amount < 0
        ),
        2,
    )
    uncategorized_income_total = round(
        sum(tx.amount for tx in current_transactions if tx.category in UNCATEGORIZED_CATEGORIES and tx.amount > 0),
        2,
    )
    uncategorized_transactions_count = sum(1 for tx in current_transactions if tx.category in UNCATEGORIZED_CATEGORIES)

    high_concentration_categories = [
        {
            "category": item["category"],
            "share_of_expenses": round(item["amount"] / expense_total, 4),
        }
        for item in current_categories
        if expense_total and item["amount"] / expense_total >= 0.35
    ]
    growing_categories = []
    declining_categories = []
    for item in current_categories:
        baseline = category_baselines.get(item["category"])
        if baseline is None or baseline == 0:
            continue
        ratio = item["amount"] / baseline
        if ratio >= 1.25:
            growing_categories.append(
                {"category": item["category"], "current_amount": item["amount"], "baseline_avg_amount": round(baseline, 2)}
            )
        elif ratio <= 0.75:
            declining_categories.append(
                {"category": item["category"], "current_amount": item["amount"], "baseline_avg_amount": round(baseline, 2)}
            )

    recurring_expenses = [
        {"category": category, "months_present": months_present}
        for category, months_present in sorted(occurrences.items())
        if months_present >= recurring_threshold
    ]
    unusual_transactions = []
    if historical_baseline["expense_total_avg_12m"]:
        threshold = max(250.0, historical_baseline["expense_total_avg_12m"] * 0.25)
        unusual_transactions = [
            item for item in current_summary["largest_expenses"] if item["amount"] >= threshold
        ]

    return {
        "uncategorized_expense_total": uncategorized_expense_total,
        "uncategorized_income_total": uncategorized_income_total,
        "uncategorized_transactions_count": uncategorized_transactions_count,
        "uncategorized_share_pct": _share_pct(uncategorized_expense_total, expense_total),
        "high_concentration_categories": high_concentration_categories,
        "unusual_transactions": unusual_transactions[:3],
        "recurring_expenses": recurring_expenses[:5],
        "growing_categories": growing_categories[:5],
        "declining_categories": declining_categories[:5],
    }


def _build_summary_html(period_start: date, period_end: date, current_summary: dict) -> str:
    category_items = "".join(
        f"<li><strong>{item['category']}</strong>: {item['amount']:.2f}</li>" for item in current_summary["top_categories"]
    )
    if not category_items:
        category_items = "<li>Sem categorias relevantes no período.</li>"
    return (
        "<section>"
        "<h2>Resumo Determinístico</h2>"
        f"<p>Período analisado: {period_start} a {period_end}</p>"
        f"<p>Total de receitas: {current_summary['income_total']:.2f}</p>"
        f"<p>Total de despesas: {current_summary['expense_total']:.2f}</p>"
        f"<p>Saldo: {current_summary['net_total']:.2f}</p>"
        f"<p>Quantidade de transações: {current_summary['transactions_count']}</p>"
        "<h3>Top categorias</h3>"
        f"<ul>{category_items}</ul>"
        "</section>"
    )


def _delta_abs(current: float, baseline: float | None) -> float | None:
    if baseline is None:
        return None
    return round(current - baseline, 2)


def _delta_pct(current: float, baseline: float | None) -> float | None:
    if baseline in (None, 0):
        return None
    return round(((current - baseline) / baseline) * 100, 2)


def _share_pct(part: float, total: float) -> float | None:
    if total == 0:
        return None
    return round((part / total) * 100, 2)
