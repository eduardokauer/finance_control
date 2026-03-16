import json
from datetime import date

from app.repositories.models import SourceFile, Transaction
from app.services.analysis import build_analysis_snapshot, run_analysis


def _add_tx(db_session, *, tx_date: date, description: str, amount: float, category: str, transaction_kind: str, should_count_in_spending: bool = True, is_card_bill_payment: bool = False):
    source_file = SourceFile(
        source_type="bank_statement",
        file_name=f"{description}.ofx",
        file_path=f"upload://{description}.ofx",
        file_hash=f"hash-{description}-{tx_date.isoformat()}",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()
    tx = Transaction(
        source_file_id=source_file.id,
        source_type="bank_statement",
        account_ref="conta-principal",
        external_id=None,
        canonical_hash=f"tx-{description}-{tx_date.isoformat()}-{amount}",
        transaction_date=tx_date,
        competence_month=tx_date.strftime("%Y-%m"),
        description_raw=description,
        description_normalized=description.lower(),
        amount=amount,
        direction="credit" if amount > 0 else "debit",
        transaction_kind=transaction_kind,
        category=category,
        categorization_method="rule",
        categorization_confidence=0.9,
        applied_rule=None,
        manual_override=False,
        should_count_in_spending=should_count_in_spending,
        is_card_bill_payment=is_card_bill_payment,
    )
    db_session.add(tx)
    db_session.commit()
    return tx


def test_build_analysis_snapshot_returns_richer_structure(db_session):
    _add_tx(db_session, tx_date=date(2025, 4, 5), description="SALARIO ANTIGO", amount=4200.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2025, 12, 8), description="PIX TRANSF", amount=-700.0, category="Transferências", transaction_kind="transfer")
    _add_tx(db_session, tx_date=date(2026, 2, 12), description="ALUGUEL FEV", amount=-1500.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 2, 22), description="FATURA FEV", amount=-1100.0, category="Pagamento de Fatura", transaction_kind="expense", is_card_bill_payment=True)
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 10), description="PIX TRANSF MAR", amount=-900.0, category="Transferências", transaction_kind="transfer")
    _add_tx(db_session, tx_date=date(2026, 3, 18), description="FATURA MAR", amount=-1300.0, category="Pagamento de Fatura", transaction_kind="expense", is_card_bill_payment=True)
    _add_tx(db_session, tx_date=date(2026, 3, 21), description="SEM CATEGORIA", amount=-450.0, category="Não Categorizado", transaction_kind="expense")

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    assert snapshot["summary"]["income_display"].startswith("R$ ")
    assert snapshot["summary"]["expense_display"].startswith("R$ ")
    assert len(snapshot["monthly_series"]) == 12
    assert snapshot["monthly_series"][0]["month"] == "2025-04"
    assert snapshot["monthly_series"][-1]["month"] == "2026-03"
    assert any(item["month"] == "2025-05" and item["transaction_count"] == 0 for item in snapshot["monthly_series"])
    assert snapshot["technical_items"]["transfer_total"] == 900.0
    assert snapshot["technical_items"]["card_bill_total"] == 1300.0
    assert snapshot["quality"]["uncategorized_total"] == 450.0
    assert snapshot["alerts"]
    assert snapshot["actions"]
    assert any(item["name"] == "Transferências" and item["is_technical"] for item in snapshot["categories"])


def test_run_analysis_persists_snapshot_payload_and_html(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 18), description="FATURA MAR", amount=-1300.0, category="Pagamento de Fatura", transaction_kind="expense", is_card_bill_payment=True)

    run = run_analysis(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31), trigger_source_file_id=None)
    payload = json.loads(run.payload)

    assert run.prompt == "deterministic_html_analysis_v2"
    assert payload["period"]["label"] == "01/03/2026 a 31/03/2026"
    assert payload["summary"]["transaction_count"] == 3
    assert len(payload["charts"]["monthly"]["labels"]) == 12
    assert "Análise financeira determinística" in run.html_output or "AnÃ¡lise financeira determinÃ­stica" in run.html_output
    assert "Ações recomendadas" in run.html_output or "AÃ§Ãµes recomendadas" in run.html_output
