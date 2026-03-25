from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json
from math import fabs

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.repositories.models import AnalysisRun, CreditCardInvoice, CreditCardInvoiceConciliation, CreditCardInvoiceItem, Transaction
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
    bank_expense_total_included = sum(
        _expense_amount(tx)
        for tx in current_txs
        if tx.id not in excluded_payment_ids
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
    conciliated_balance_total = bank_income_total - net_conciliated_expense_total
    invoices_outside_total = sum(outside_status_counts.values())

    return {
        "bank_income_total": bank_income_total,
        "bank_expense_total_included": bank_expense_total_included,
        "conciliated_card_charge_total": charge_total,
        "conciliated_invoice_credit_total": invoice_credit_total,
        "excluded_conciliated_bank_payment_total": excluded_conciliated_bank_payment_total,
        "net_conciliated_expense_total": net_conciliated_expense_total,
        "conciliated_balance_total": conciliated_balance_total,
        "included_invoice_count": len(included_invoice_ids),
        "outside_invoices_by_status": outside_status_counts,
        "outside_invoices_total": invoices_outside_total,
        "excluded_bank_payment_count": len(excluded_payment_ids),
        "ignored_invoice_payment_item_total": payment_item_total,
        "bank_income_display": format_currency_br(bank_income_total),
        "bank_expense_total_included_display": format_currency_br(bank_expense_total_included),
        "conciliated_card_charge_display": format_currency_br(charge_total),
        "conciliated_invoice_credit_display": format_currency_br(invoice_credit_total),
        "excluded_conciliated_bank_payment_display": format_currency_br(excluded_conciliated_bank_payment_total),
        "net_conciliated_expense_display": format_currency_br(net_conciliated_expense_total),
        "conciliated_balance_display": format_currency_br(conciliated_balance_total),
        "ignored_invoice_payment_item_display": format_currency_br(payment_item_total),
        "note": (
            "Considera apenas faturas totalmente conciliadas. "
            "Pagamentos bancários conciliados saem do gasto real e compras/créditos da fatura entram como consumo líquido do mês."
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
    income_total = conciliated_month["bank_income_total"]
    expense_total = conciliated_month["net_conciliated_expense_total"]
    balance_total = conciliated_month["conciliated_balance_total"]
    included_invoice_count = conciliated_month["included_invoice_count"]
    outside_invoice_count = conciliated_month["outside_invoices_total"]
    excluded_payment_count = conciliated_month["excluded_bank_payment_count"]
    if included_invoice_count or outside_invoice_count:
        coverage_note = (
            f"{included_invoice_count} fatura(s) conciliada(s) entraram na leitura principal e "
            f"{outside_invoice_count} ficaram fora por pendência, parcial ou conflito."
        )
    else:
        coverage_note = "Sem faturas conciliadas no período; a leitura principal coincide com a movimentação líquida da conta."
    executive_summary = (
        f"Receitas da conta em {conciliated_month['bank_income_display']}, despesa líquida conciliada em "
        f"{conciliated_month['net_conciliated_expense_display']} e saldo conciliado de "
        f"{conciliated_month['conciliated_balance_display']}."
    )
    return {
        "mode": "conciliated",
        "income_total": income_total,
        "expense_total": expense_total,
        "balance": balance_total,
        "income_display": format_currency_br(income_total),
        "expense_display": format_currency_br(expense_total),
        "balance_display": format_currency_br(balance_total),
        "included_invoice_count": included_invoice_count,
        "outside_invoice_count": outside_invoice_count,
        "excluded_bank_payment_count": excluded_payment_count,
        "excluded_bank_payment_display": conciliated_month["excluded_conciliated_bank_payment_display"],
        "coverage_note": coverage_note,
        "executive_summary": executive_summary,
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
    raw_category_rows = _build_category_rows(current_month_txs, expense_total=current_month_summary["expense_total"])
    category_breakdown = _build_conciliated_category_breakdown(
        db,
        period_start=current_month_start,
        period_end=current_month_end,
        current_txs=current_month_txs,
    )
    category_rows = category_breakdown["rows"]
    technical_items = _build_technical_items(current_month_txs, expense_total=current_month_summary["expense_total"])
    quality = _build_quality(summary)

    previous_category_rows = _build_category_rows(previous_txs, expense_total=previous_summary["expense_total"])
    previous_categories = {item["name"]: item["expense_total"] for item in previous_category_rows}

    alerts = _build_alerts(
        summary=summary,
        comparison=comparison,
        categories=raw_category_rows,
        technical_items=technical_items,
        quality=quality,
    )
    actions = _build_actions(
        summary=summary,
        comparison=comparison,
        categories=raw_category_rows,
        technical_items=technical_items,
        quality=quality,
        previous_categories=previous_categories,
    )
    monthly_series = _build_monthly_series(db, anchor_month=anchor_month)
    category_history = _build_conciliated_category_history(db, anchor_month=anchor_month)
    conciliation_signals = build_conciliation_analytics_snapshot(db, period_start=period_start, period_end=period_end)
    conciliated_month = _build_conciliated_month_snapshot(
        db,
        period_start=period_start,
        period_end=period_end,
        current_txs=current_txs,
    )
    primary_summary = _build_primary_summary(conciliated_month=conciliated_month)

    top_expense_categories = category_breakdown["top_expense_categories"]
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
        "monthly_series": monthly_series,
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
        "<p>Receitas da conta em {}, despesas líquidas conciliadas em {} e saldo conciliado de {}.</p>".format(
            conciliated_month["bank_income_display"],
            conciliated_month["net_conciliated_expense_display"],
            conciliated_month["conciliated_balance_display"],
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
