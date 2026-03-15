from datetime import date

from app.repositories.models import SourceFile, Transaction


def _seed_source_file(db_session):
    source_file = SourceFile(
        source_type="bank_statement",
        file_name="seed.ofx",
        file_path="seed://seed.ofx",
        file_hash="seed-hash",
        status="processed",
    )
    db_session.add(source_file)
    db_session.commit()
    db_session.refresh(source_file)
    return source_file


def _add_transaction(
    db_session,
    source_file_id: int,
    tx_id: int,
    transaction_date: date,
    amount: float,
    category: str,
    should_count_in_spending: bool = True,
    transaction_kind: str | None = None,
):
    direction = "credit" if amount > 0 else "debit"
    db_session.add(
        Transaction(
            id=tx_id,
            source_file_id=source_file_id,
            source_type="bank_statement",
            account_ref="checking",
            external_id=f"ext-{tx_id}",
            canonical_hash=f"hash-{tx_id}",
            transaction_date=transaction_date,
            competence_month=transaction_date.strftime("%Y-%m"),
            description_raw=f"Transaction {tx_id}",
            description_normalized=f"transaction {tx_id}",
            amount=amount,
            direction=direction,
            transaction_kind=transaction_kind or ("income" if amount > 0 else "expense"),
            category=category,
            categorization_method="seed",
            categorization_confidence=1.0,
            applied_rule="seed",
            should_count_in_spending=should_count_in_spending,
        )
    )


def _seed_history(db_session, months_before: int):
    source_file = _seed_source_file(db_session)
    next_id = 1
    for month_offset in range(months_before, 0, -1):
        month = 3 - month_offset
        year = 2026
        while month <= 0:
            month += 12
            year -= 1
        _add_transaction(db_session, source_file.id, next_id, date(year, month, 5), 5000.0, "Salário")
        next_id += 1
        _add_transaction(db_session, source_file.id, next_id, date(year, month, 6), -1200.0 - month_offset, "Moradia")
        next_id += 1
        _add_transaction(db_session, source_file.id, next_id, date(year, month, 7), -300.0, "Alimentação")
        next_id += 1

    _add_transaction(db_session, source_file.id, next_id, date(2026, 3, 5), 5500.0, "Salário")
    next_id += 1
    _add_transaction(db_session, source_file.id, next_id, date(2026, 3, 8), -1800.0, "Moradia")
    next_id += 1
    _add_transaction(db_session, source_file.id, next_id, date(2026, 3, 11), -600.0, "Saúde")
    next_id += 1
    _add_transaction(db_session, source_file.id, next_id, date(2026, 3, 14), -400.0, "Alimentação")
    db_session.commit()


def test_llm_email_analysis_with_insufficient_history(client, auth_headers, db_session):
    _seed_history(db_session, months_before=2)

    resp = client.post(
        "/analysis/llm-email",
        headers=auth_headers,
        json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    summary_html = payload["summary_html"]
    assert "<section>" in summary_html
    assert "<h2>Resumo Determinístico</h2>" in summary_html
    assert "<ul>" in summary_html
    assert "<li><strong>" in summary_html
    assert "Período analisado: 2026-03-01 a 2026-03-31" in summary_html
    assert payload["llm_payload"]["analysis_mode"] == "insufficient_history"
    assert payload["llm_payload"]["current_period"]["months_available_for_history"] == 2
    assert payload["llm_payload"]["current_period"]["history_window_used_months"] == 2
    assert payload["llm_payload"]["current_period"]["history_quality"] == "insufficient"


def test_llm_email_analysis_with_partial_history(client, auth_headers, db_session):
    _seed_history(db_session, months_before=5)

    resp = client.post(
        "/analysis/llm-email",
        headers=auth_headers,
        json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    )

    assert resp.status_code == 200
    llm_payload = resp.json()["llm_payload"]
    assert llm_payload["analysis_mode"] == "partial_history"
    assert llm_payload["current_period"]["months_available_for_history"] == 5
    assert llm_payload["current_period"]["history_window_used_months"] == 5
    assert llm_payload["deterministic_summary"]["transactions_count"] == 4
    assert llm_payload["deterministic_summary"]["income_total"] == 5500.0
    assert llm_payload["deterministic_summary"]["expense_total"] == 2800.0
    assert llm_payload["historical_baseline"]["expense_total_avg_12m"] is not None
    assert llm_payload["current_vs_history"]["vs_previous_month"]["month"] == "2026-02"
    assert "high_concentration_categories" in llm_payload["signals"]
    assert llm_payload["guardrails"]["must_not_invent_missing_history"] is True


def test_llm_email_analysis_with_full_history_uses_all_month_categories(client, auth_headers, db_session):
    _seed_history(db_session, months_before=12)
    _add_transaction(db_session, 1, 100, date(2025, 3, 9), -150.0, "Transporte")
    _add_transaction(db_session, 1, 101, date(2025, 3, 10), -120.0, "Lazer")
    _add_transaction(db_session, 1, 102, date(2025, 3, 11), -110.0, "Pets")
    _add_transaction(db_session, 1, 103, date(2025, 3, 12), -90.0, "Educação")
    db_session.commit()

    resp = client.post(
        "/analysis/llm-email",
        headers=auth_headers,
        json={"period_start": "2026-03-01", "period_end": "2026-03-31", "trigger_source_file_id": 1},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert "<section>" in body["summary_html"]
    assert "<h3>Top categorias</h3>" in body["summary_html"]
    llm_payload = body["llm_payload"]
    assert llm_payload["analysis_mode"] == "full_history"
    assert llm_payload["current_period"]["months_available_for_history"] == 12
    assert llm_payload["current_period"]["history_window_used_months"] == 12
    assert llm_payload["current_period"]["trigger_source_file_id"] == 1
    assert len(llm_payload["historical_baseline"]["monthly_totals"]) == 12
    assert len(llm_payload["deterministic_summary"]["top_categories"]) >= 2
    assert len(llm_payload["deterministic_summary"]["largest_expenses"]) >= 2
    assert "category_deltas" in llm_payload["current_vs_history"]

    baseline_categories = {
        item["category"]: item["avg_amount"] for item in llm_payload["historical_baseline"]["category_baselines"]
    }
    assert "Pets" in baseline_categories
    assert baseline_categories["Pets"] > 0


def test_llm_email_analysis_exposes_uncategorized_signals(client, auth_headers, db_session):
    source_file = _seed_source_file(db_session)
    _add_transaction(db_session, source_file.id, 1, date(2026, 3, 5), 4500.0, "Salário")
    _add_transaction(db_session, source_file.id, 2, date(2026, 3, 6), -300.0, "Não Categorizado")
    _add_transaction(db_session, source_file.id, 3, date(2026, 3, 7), -200.0, "Outros")
    _add_transaction(db_session, source_file.id, 4, date(2026, 3, 8), 120.0, "Outros")
    _add_transaction(db_session, source_file.id, 5, date(2026, 3, 9), -500.0, "Moradia")
    db_session.commit()

    resp = client.post(
        "/analysis/llm-email",
        headers=auth_headers,
        json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    )

    assert resp.status_code == 200
    signals = resp.json()["llm_payload"]["signals"]
    assert signals["uncategorized_expense_total"] == 500.0
    assert signals["uncategorized_income_total"] == 120.0
    assert signals["uncategorized_transactions_count"] == 3
    assert signals["uncategorized_share_pct"] == 50.0
