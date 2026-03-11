from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.repositories.models import AnalysisRun, Transaction


def run_analysis(db: Session, period_start: date, period_end: date, trigger_source_file_id: int | None):
    txs = db.scalars(
        select(Transaction).where(Transaction.transaction_date >= period_start, Transaction.transaction_date <= period_end)
    ).all()
    total = sum(t.amount for t in txs if t.should_count_in_spending)
    by_cat = {}
    for t in txs:
        if not t.should_count_in_spending:
            continue
        by_cat[t.category] = by_cat.get(t.category, 0) + t.amount
    cat_rows = "".join(f"<li>{k}: {v:.2f}</li>" for k, v in sorted(by_cat.items(), key=lambda i: i[1], reverse=True))

    previous_month_start = (period_start.replace(day=1) - timedelta(days=1)).replace(day=1)
    prev_txs = db.scalars(
        select(Transaction).where(
            Transaction.transaction_date >= previous_month_start,
            Transaction.transaction_date < period_start,
            Transaction.should_count_in_spending.is_(True),
        )
    ).all()
    prev_total = sum(t.amount for t in prev_txs)

    html = (
        f"<html><body><h1>Análise Financeira</h1><p>Período: {period_start} a {period_end}</p>"
        f"<p>Total de gastos: {total:.2f}</p><p>Mês anterior: {prev_total:.2f}</p>"
        "<p>Comparação ano contra ano: MVP com base histórica parcial.</p>"
        f"<h2>Categorias</h2><ul>{cat_rows}</ul>"
        "<h2>Oportunidades de redução</h2><p>Revise categorias com maior peso e assinaturas recorrentes.</p>"
        "<h2>Saúde financeira</h2><p>Mantenha reserva e reduza despesas variáveis elevadas.</p></body></html>"
    )
    run = AnalysisRun(
        period_start=period_start,
        period_end=period_end,
        trigger_source_file_id=trigger_source_file_id,
        payload=str({"transactions": len(txs), "total": total}),
        prompt="deterministic_html_analysis",
        html_output=html,
        status="success",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
