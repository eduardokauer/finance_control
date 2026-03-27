import json
from datetime import date

from sqlalchemy import select

from app.repositories.models import (
    CreditCard,
    CreditCardInvoice,
    CreditCardInvoiceConciliation,
    CreditCardInvoiceItem,
    SourceFile,
    Transaction,
)
from app.services.credit_card_bills import ensure_credit_card_invoice_conciliation, reconcile_credit_card_invoice_bank_payments
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
    db_session.flush()
    return tx


def _add_invoice(
    db_session,
    *,
    due_date: date,
    card_final: str = "1234",
    item_specs: list[tuple[str, str] | tuple[str, str, date]] | None = None,
):
    card = CreditCard(
        issuer="itau",
        card_label=f"Ita\u00fa Visa final {card_final}",
        card_final=card_final,
        brand="Visa",
        is_active=True,
    )
    db_session.add(card)
    db_session.flush()
    source_file = SourceFile(
        source_type="credit_card_bill",
        file_name=f"invoice-{card_final}.csv",
        file_path=f"upload://invoice-{card_final}.csv",
        file_hash=f"invoice-hash-{card_final}-{due_date.isoformat()}",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()
    invoice = CreditCardInvoice(
        source_file_id=source_file.id,
        card_id=card.id,
        issuer=card.issuer,
        card_final=card.card_final,
        billing_year=due_date.year,
        billing_month=due_date.month,
        due_date=due_date,
        closing_date=None,
        total_amount_brl=0,
        source_file_name=source_file.file_name,
        source_file_hash=f"invoice-model-{card_final}-{due_date.isoformat()}",
        notes="analysis test",
        import_status="imported",
    )
    db_session.add(invoice)
    db_session.flush()
    for index, item_spec in enumerate(item_specs or [], start=1):
        if len(item_spec) == 3:
            description_raw, amount_brl, purchase_date = item_spec
        else:
            description_raw, amount_brl = item_spec
            purchase_date = due_date
        db_session.add(
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=purchase_date,
                description_raw=description_raw,
                description_normalized=description_raw.lower(),
                amount_brl=amount_brl,
                installment_current=None,
                installment_total=None,
                is_installment=False,
                derived_note=None,
                external_row_hash=f"row-hash-{invoice.id}-{index}",
            )
        )
    db_session.flush()
    return invoice


def _set_conciliation_status(db_session, *, invoice_id: int, status: str):
    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice_id)
    assert conciliation is not None
    conciliation.status = status
    db_session.flush()
    return conciliation


def _assign_invoice_item_categories(db_session, *, invoice_id: int, categories_by_description: dict[str, str]):
    items = db_session.scalars(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice_id)
        .order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    for item in items:
        category = categories_by_description.get(item.description_raw)
        if category is None:
            continue
        item.category = category
        item.categorization_method = "manual"
        item.categorization_confidence = 1.0
    db_session.flush()


def test_build_analysis_snapshot_returns_richer_structure(db_session):
    _add_tx(db_session, tx_date=date(2025, 4, 5), description="SALARIO ANTIGO", amount=4200.0, category="Sal\u00e1rio", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2025, 12, 8), description="PIX TRANSF", amount=-700.0, category="Transfer\u00eancias", transaction_kind="transfer")
    _add_tx(db_session, tx_date=date(2026, 2, 12), description="ALUGUEL FEV", amount=-1500.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 2, 22), description="FATURA FEV", amount=-1100.0, category="Pagamento de Fatura", transaction_kind="expense", is_card_bill_payment=True)
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Sal\u00e1rio", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 10), description="PIX TRANSF MAR", amount=-900.0, category="Transfer\u00eancias", transaction_kind="transfer")
    _add_tx(db_session, tx_date=date(2026, 3, 18), description="FATURA MAR", amount=-1300.0, category="Pagamento de Fatura", transaction_kind="expense", is_card_bill_payment=True)
    _add_tx(db_session, tx_date=date(2026, 3, 21), description="SEM CATEGORIA", amount=-450.0, category="N\u00e3o Categorizado", transaction_kind="expense")

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
    assert any(item["name"] == "Transfer\u00eancias" and item["is_technical"] for item in snapshot["categories"])


def test_run_analysis_persists_snapshot_payload_and_html(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Sal\u00e1rio", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 18), description="FATURA MAR", amount=-1300.0, category="Pagamento de Fatura", transaction_kind="expense", is_card_bill_payment=True)

    run = run_analysis(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31), trigger_source_file_id=None)
    payload = json.loads(run.payload)

    assert run.prompt == "deterministic_html_analysis_v2"
    assert payload["period"]["label"] == "01/03/2026 a 31/03/2026"
    assert payload["summary"]["transaction_count"] == 3
    assert len(payload["charts"]["monthly"]["labels"]) == 12
    assert "An\u00e1lise financeira determin\u00edstica" in run.html_output
    assert "Compara\u00e7\u00f5es hist\u00f3ricas por categoria" in run.html_output
    assert "data do próprio item importado" in run.html_output
    assert "sem redistribuição artificial entre categorias" in run.html_output
    assert "A\u00e7\u00f5es recomendadas" in run.html_output


def test_top_categories_of_month_are_ranked_by_expense_total(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=9000.0, category="Sal\u00e1rio", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 9), description="MERCADO MAR", amount=-950.0, category="Mercado", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 12), description="PIX RECEBIDO", amount=3200.0, category="Reembolsos", transaction_kind="income")

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    assert snapshot["categories"][0]["name"] == "Moradia"
    assert snapshot["categories"][1]["name"] == "Mercado"
    assert snapshot["top_expense_categories"][0]["name"] == "Moradia"
    assert snapshot["top_expense_categories"][1]["name"] == "Mercado"
    assert "Sal\u00e1rio" not in [item["name"] for item in snapshot["top_expense_categories"]]
    assert snapshot["charts"]["categories"]["labels"][0] == "Moradia"
    assert snapshot["charts"]["categories"]["values"][0] == 1800.0


def test_analysis_snapshot_exposes_conciliation_signals_without_changing_main_totals(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Sal\u00e1rio", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    payment = _add_tx(
        db_session,
        tx_date=date(2026, 3, 18),
        description="FATURA MAR",
        amount=-1300.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice = _add_invoice(
        db_session,
        due_date=date(2026, 3, 20),
        item_specs=[
            ("COMPRA MERCADO", "1400.00"),
            ("DESCONTO NA FATURA - PO", "-100.00"),
        ],
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice.id,
        bank_transaction_ids=[payment.id],
    )

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    assert snapshot["summary"]["expense_total"] == 3100.0
    assert snapshot["summary"]["income_total"] == 5000.0
    assert snapshot["primary_summary"]["mode"] == "conciliated"
    assert snapshot["primary_summary"]["income_total"] == 5000.0
    assert snapshot["primary_summary"]["expense_total"] == 3100.0
    assert snapshot["primary_summary"]["balance"] == 1900.0
    assert snapshot["conciliation_signals"]["conciliated_bank_payment_total_brl"] == 1300.0
    assert snapshot["conciliation_signals"]["invoice_credit_total_brl"] == 100.0
    assert snapshot["conciliation_signals"]["invoices_by_status"]["conciliated"] == 1
    assert snapshot["technical_items"]["card_bill_total"] == 1300.0


def test_analysis_snapshot_builds_conciliated_month_view_without_changing_main_totals(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Sal\u00e1rio", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    payment = _add_tx(
        db_session,
        tx_date=date(2026, 3, 18),
        description="FATURA MAR",
        amount=-1300.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice = _add_invoice(
        db_session,
        due_date=date(2026, 3, 20),
        item_specs=[
            ("COMPRA MERCADO", "900.00"),
            ("CURSO ONLINE", "500.00"),
            ("DESCONTO NA FATURA - PO", "-100.00"),
            ("PAGAMENTO EFETUADO", "-1300.00"),
        ],
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice.id,
        bank_transaction_ids=[payment.id],
    )

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    assert snapshot["summary"]["expense_total"] == 3100.0
    conciliated = snapshot["conciliated_month"]
    assert conciliated["bank_income_total"] == 5000.0
    assert conciliated["bank_expense_total_included"] == 1800.0
    assert conciliated["conciliated_card_charge_total"] == 1400.0
    assert conciliated["conciliated_invoice_credit_total"] == 100.0
    assert conciliated["excluded_conciliated_bank_payment_total"] == 1300.0
    assert conciliated["ignored_invoice_payment_item_total"] == 1300.0
    assert conciliated["net_conciliated_expense_total"] == 3100.0
    assert conciliated["conciliated_balance_total"] == 1900.0
    assert conciliated["included_invoice_count"] == 1
    assert conciliated["outside_invoices_total"] == 0
    assert snapshot["primary_summary"]["income_display"] == conciliated["bank_income_display"]
    assert snapshot["primary_summary"]["expense_display"] == conciliated["net_conciliated_expense_display"]
    assert snapshot["primary_summary"]["balance_display"] == conciliated["conciliated_balance_display"]
    assert snapshot["primary_summary"]["included_invoice_count"] == 1
    assert snapshot["primary_summary"]["outside_invoice_count"] == 0
    assert snapshot["primary_summary"]["excluded_bank_payment_count"] == 1


def test_analysis_snapshot_builds_home_cards_from_cash_flow_and_consumption_view(db_session):
    _add_tx(db_session, tx_date=date(2026, 2, 5), description="SALARIO FEV", amount=4500.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 2, 8), description="ALUGUEL FEV", amount=-1500.0, category="Moradia", transaction_kind="expense")
    payment_february = _add_tx(
        db_session,
        tx_date=date(2026, 2, 18),
        description="FATURA FEV",
        amount=-650.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_february = _add_invoice(
        db_session,
        due_date=date(2026, 2, 20),
        card_final="4242",
        item_specs=[
            ("SUPERMERCADO FEV", "700.00"),
            ("DESCONTO NA FATURA FEV", "-50.00"),
            ("PAGAMENTO EFETUADO FEV", "-650.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_february.id,
        categories_by_description={"SUPERMERCADO FEV": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_february.id,
        bank_transaction_ids=[payment_february.id],
    )

    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    payment_march = _add_tx(
        db_session,
        tx_date=date(2026, 3, 18),
        description="FATURA MAR",
        amount=-1300.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_march = _add_invoice(
        db_session,
        due_date=date(2026, 3, 20),
        card_final="4343",
        item_specs=[
            ("SUPERMERCADO MAR", "900.00"),
            ("CURSO MAR", "500.00"),
            ("DESCONTO NA FATURA MAR", "-100.00"),
            ("PAGAMENTO EFETUADO MAR", "-1300.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_march.id,
        categories_by_description={
            "SUPERMERCADO MAR": "Supermercado",
            "CURSO MAR": "Educação",
        },
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_march.id,
        bank_transaction_ids=[payment_march.id],
    )

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    cards = {item["key"]: item for item in snapshot["home_cards"]["cards"]}

    assert snapshot["home_cards"]["current_month_label"] == "mar/2026"
    assert snapshot["home_cards"]["previous_month_label"] == "fev/2026"

    assert cards["net_flow"]["current"] == 1900.0
    assert cards["net_flow"]["change"]["previous"] == 2350.0
    assert cards["net_flow"]["change"]["delta"] == -450.0

    assert cards["income"]["current"] == 5000.0
    assert cards["income"]["change"]["previous"] == 4500.0
    assert cards["income"]["change"]["delta"] == 500.0

    assert cards["expense"]["current"] == 3100.0
    assert cards["expense"]["change"]["previous"] == 2150.0
    assert cards["expense"]["change"]["delta"] == 950.0

    assert cards["consumption"]["current"] == 3200.0
    assert cards["consumption"]["change"]["previous"] == 2200.0
    assert cards["consumption"]["change"]["delta"] == 1000.0
    assert cards["consumption"]["current"] != cards["expense"]["current"]


def test_analysis_snapshot_home_cards_show_clear_fallback_without_previous_month_base(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    payment = _add_tx(
        db_session,
        tx_date=date(2026, 3, 18),
        description="FATURA MAR",
        amount=-1300.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice = _add_invoice(
        db_session,
        due_date=date(2026, 3, 20),
        card_final="4444",
        item_specs=[
            ("SUPERMERCADO MAR", "900.00"),
            ("CURSO MAR", "500.00"),
            ("DESCONTO NA FATURA MAR", "-100.00"),
            ("PAGAMENTO EFETUADO MAR", "-1300.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice.id,
        categories_by_description={
            "SUPERMERCADO MAR": "Supermercado",
            "CURSO MAR": "Educação",
        },
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice.id,
        bank_transaction_ids=[payment.id],
    )

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    cards = {item["key"]: item for item in snapshot["home_cards"]["cards"]}

    assert snapshot["home_cards"]["previous_month_label"] == "fev/2026"
    assert all(card["comparison_available"] is False for card in cards.values())
    assert all(card["change"] is None for card in cards.values())
    assert cards["consumption"]["current"] == 3200.0


def test_analysis_snapshot_builds_home_yearly_cash_flow_chart_with_calendar_year_and_zero_months(db_session):
    _add_tx(db_session, tx_date=date(2025, 12, 5), description="SALARIO DEZ 2025", amount=4100.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 1, 5), description="SALARIO JAN 2026", amount=5000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 1, 8), description="ALUGUEL JAN 2026", amount=-1500.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR 2026", amount=3200.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR 2026", amount=-1200.0, category="Moradia", transaction_kind="expense")

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    chart = snapshot["home_yearly_chart"]

    assert chart["year"] == 2026
    assert chart["labels"] == ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    assert chart["income"][0] == 5000.0
    assert chart["expense"][0] == -1500.0
    assert chart["balance"][0] == 3500.0
    assert chart["income"][1] == 0.0
    assert chart["expense"][1] == 0.0
    assert chart["balance"][1] == 0.0
    assert chart["income"][2] == 3200.0
    assert chart["expense"][2] == -1200.0
    assert chart["balance"][2] == 2000.0
    assert chart["months"][11]["month"] == "2026-12"
    assert chart["months"][11]["transaction_count"] == 0
    assert chart["all_zero"] is False


def test_analysis_snapshot_builds_home_yearly_cash_flow_chart_with_all_zero_months_when_year_is_empty(db_session):
    _add_tx(db_session, tx_date=date(2025, 12, 5), description="SALARIO DEZ 2025", amount=4100.0, category="Salário", transaction_kind="income")

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    chart = snapshot["home_yearly_chart"]

    assert chart["year"] == 2026
    assert chart["all_zero"] is True
    assert len(chart["labels"]) == 12
    assert all(value == 0.0 for value in chart["income"])
    assert all(value == 0.0 for value in chart["expense"])
    assert all(value == 0.0 for value in chart["balance"])


def test_analysis_snapshot_builds_home_category_comparison_from_top_five_consumption_categories(db_session):
    _add_tx(db_session, tx_date=date(2026, 2, 5), description="SALARIO FEV", amount=4500.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 2, 8), description="ALUGUEL FEV", amount=-1500.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 2, 12), description="MERCADO FEV", amount=-700.0, category="Supermercado", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 2, 18), description="UBER FEV", amount=-200.0, category="Transporte", transaction_kind="expense")

    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 12), description="MERCADO MAR", amount=-900.0, category="Supermercado", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 14), description="CURSO MAR", amount=-500.0, category="Educação", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 18), description="UBER MAR", amount=-120.0, category="Transporte", transaction_kind="expense")
    _add_tx(db_session, tx_date=date(2026, 3, 22), description="OUTROS MAR", amount=-60.0, category="Outros", transaction_kind="expense")

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    comparison = snapshot["home_category_comparison"]
    rows = comparison["rows"]

    assert comparison["current_month_label"] == "mar/2026"
    assert comparison["previous_month_label"] == "fev/2026"
    assert [row["name"] for row in rows] == ["Moradia", "Supermercado", "Educação", "Transporte", "Outros"]
    assert rows[0]["current_total"] == 1800.0
    assert rows[0]["previous_total"] == 1500.0
    assert rows[0]["change"]["delta"] == 300.0
    assert rows[0]["change"]["percent"] == 0.2
    assert rows[0]["percent_available"] is True
    assert rows[2]["previous_total"] == 0.0
    assert rows[2]["previous_display"] == "R$ 0,00"
    assert rows[2]["is_new_in_month"] is True
    assert rows[2]["change"]["delta"] == 500.0
    assert rows[2]["percent_available"] is False
    assert rows[3]["previous_total"] == 200.0
    assert rows[3]["change"]["delta"] == -80.0
    assert rows[3]["change"]["percent"] == -0.4
    assert rows[4]["is_new_in_month"] is True


def test_analysis_snapshot_builds_home_category_comparison_empty_state_without_consumption_categories(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Salário", transaction_kind="income")

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    comparison = snapshot["home_category_comparison"]

    assert comparison["current_month_label"] == "mar/2026"
    assert comparison["previous_month_label"] == "fev/2026"
    assert comparison["rows"] == []
    assert "Top 5 categorias de consumo do mês-base" in comparison["note"]


def test_analysis_snapshot_builds_conciliated_category_breakdown_from_account_and_invoice_items(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1800.0, category="Moradia", transaction_kind="expense")
    payment = _add_tx(
        db_session,
        tx_date=date(2026, 3, 18),
        description="FATURA MAR",
        amount=-1300.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice = _add_invoice(
        db_session,
        due_date=date(2026, 3, 20),
        item_specs=[
            ("SUPERMERCADO TESTE", "900.00"),
            ("CURSO ONLINE", "500.00"),
            ("DESCONTO NA FATURA - PO", "-100.00"),
            ("PAGAMENTO EFETUADO", "-1300.00"),
        ],
    )
    invoice_items = db_session.scalars(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id).order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    invoice_items[0].category = "Supermercado"
    invoice_items[1].category = "Educação"
    db_session.commit()
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice.id,
        bank_transaction_ids=[payment.id],
    )

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    category_map = {item["name"]: item for item in snapshot["categories"]}
    assert category_map["Moradia"]["expense_total"] == 1800.0
    assert category_map["Supermercado"]["expense_total"] == 900.0
    assert category_map["Educação"]["expense_total"] == 500.0
    assert "Pagamento de Fatura" not in category_map
    assert category_map["Créditos de Fatura"]["technical_label"] == "Crédito de Fatura"
    assert category_map["Créditos de Fatura"]["movement_total"] == -100.0
    assert snapshot["category_breakdown"]["invoice_credit_adjustment_total"] == 100.0
    assert snapshot["category_breakdown"]["excluded_bank_payment_total"] == 1300.0
    assert snapshot["top_expense_categories"][0]["name"] == "Moradia"
    assert snapshot["top_expense_categories"][1]["name"] == "Supermercado"
    assert snapshot["top_expense_categories"][2]["name"] == "Educação"
    assert snapshot["charts"]["categories"]["labels"][:3] == ["Moradia", "Supermercado", "Educação"]


def test_analysis_snapshot_anchors_invoice_consumption_by_purchase_date(db_session):
    payment = _add_tx(
        db_session,
        tx_date=date(2026, 2, 18),
        description="FATURA FEV",
        amount=-800.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice = _add_invoice(
        db_session,
        due_date=date(2026, 2, 20),
        card_final="2222",
        item_specs=[
            ("SUPERMERCADO TESTE", "900.00", date(2026, 1, 28)),
            ("DESCONTO NA FATURA - PO", "-100.00", date(2026, 1, 29)),
            ("PAGAMENTO EFETUADO", "-800.00", date(2026, 2, 18)),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice.id,
        bank_transaction_ids=[payment.id],
    )

    january_snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
    february_snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))

    january_categories = {item["name"]: item for item in january_snapshot["categories"]}
    february_categories = {item["name"]: item for item in february_snapshot["categories"]}

    assert january_categories["Supermercado"]["expense_total"] == 900.0
    assert january_categories["Créditos de Fatura"]["technical_label"] == "Crédito de Fatura"
    assert january_categories["Créditos de Fatura"]["movement_total"] == -100.0
    assert january_snapshot["category_breakdown"]["invoice_credit_adjustment_total"] == 100.0
    assert january_snapshot["category_breakdown"]["excluded_bank_payment_total"] == 0.0
    assert "data do próprio item importado" in january_snapshot["category_breakdown"]["note"]
    assert "sem redistribuição artificial entre categorias" in january_snapshot["category_history"]["technical_adjustments"]["note"]
    assert "Pagamento de Fatura" not in january_categories

    assert "Supermercado" not in february_categories
    assert "Créditos de Fatura" not in february_categories
    assert february_snapshot["category_breakdown"]["excluded_bank_payment_total"] == 800.0
    assert "Pagamento de Fatura" not in february_categories


def test_analysis_snapshot_manual_invoice_item_category_edit_affects_purchase_month_view(db_session):
    payment = _add_tx(
        db_session,
        tx_date=date(2026, 2, 18),
        description="FATURA FEV EDIT",
        amount=-250.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice = _add_invoice(
        db_session,
        due_date=date(2026, 2, 20),
        card_final="2323",
        item_specs=[("CURSO ONLINE", "250.00", date(2026, 1, 30))],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice.id,
        categories_by_description={"CURSO ONLINE": "Educação"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice.id,
        bank_transaction_ids=[payment.id],
    )

    january_before = build_analysis_snapshot(db_session, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
    assert {item["name"] for item in january_before["categories"]} == {"Educação"}

    item = db_session.scalar(
        select(CreditCardInvoiceItem).where(
            CreditCardInvoiceItem.invoice_id == invoice.id,
            CreditCardInvoiceItem.description_raw == "CURSO ONLINE",
        )
    )
    assert item is not None
    item.category = "Outros"
    item.categorization_method = "manual"
    item.categorization_confidence = 1.0
    db_session.commit()

    january_after = build_analysis_snapshot(db_session, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
    february_after = build_analysis_snapshot(db_session, period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
    january_categories = {item["name"]: item for item in january_after["categories"]}
    february_categories = {item["name"]: item for item in february_after["categories"]}

    assert "Educação" not in january_categories
    assert january_categories["Outros"]["expense_total"] == 250.0
    assert "Outros" not in february_categories


def test_analysis_snapshot_builds_conciliated_category_history_from_same_base(db_session):
    _add_tx(db_session, tx_date=date(2025, 3, 5), description="SALARIO MAR 2025", amount=4800.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2025, 3, 8), description="ALUGUEL MAR 2025", amount=-1500.0, category="Moradia", transaction_kind="expense")
    payment_2025 = _add_tx(
        db_session,
        tx_date=date(2025, 3, 18),
        description="FATURA MAR 2025",
        amount=-740.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_2025 = _add_invoice(
        db_session,
        due_date=date(2025, 3, 20),
        card_final="2525",
        item_specs=[
            ("SUPERMERCADO TESTE", "650.00"),
            ("CURSO ONLINE", "120.00"),
            ("DESCONTO NA FATURA - PO", "-30.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_2025.id,
        categories_by_description={
            "SUPERMERCADO TESTE": "Supermercado",
            "CURSO ONLINE": "Educação",
        },
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_2025.id,
        bank_transaction_ids=[payment_2025.id],
    )

    _add_tx(db_session, tx_date=date(2026, 2, 5), description="SALARIO FEV 2026", amount=4900.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 2, 8), description="ALUGUEL FEV 2026", amount=-1600.0, category="Moradia", transaction_kind="expense")
    payment_2026_02 = _add_tx(
        db_session,
        tx_date=date(2026, 2, 18),
        description="FATURA FEV 2026",
        amount=-650.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_2026_02 = _add_invoice(
        db_session,
        due_date=date(2026, 2, 20),
        card_final="2626",
        item_specs=[
            ("SUPERMERCADO TESTE", "700.00"),
            ("DESCONTO NA FATURA - PO", "-50.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_2026_02.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_2026_02.id,
        bank_transaction_ids=[payment_2026_02.id],
    )

    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR 2026", amount=5000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR 2026", amount=-1800.0, category="Moradia", transaction_kind="expense")
    payment_2026_03 = _add_tx(
        db_session,
        tx_date=date(2026, 3, 18),
        description="FATURA MAR 2026",
        amount=-1100.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_2026_03 = _add_invoice(
        db_session,
        due_date=date(2026, 3, 20),
        card_final="3636",
        item_specs=[
            ("SUPERMERCADO TESTE", "900.00"),
            ("CURSO ONLINE", "300.00"),
            ("DESCONTO NA FATURA - PO", "-100.00"),
            ("PAGAMENTO EFETUADO", "-1300.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_2026_03.id,
        categories_by_description={
            "SUPERMERCADO TESTE": "Supermercado",
            "CURSO ONLINE": "Educação",
        },
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_2026_03.id,
        bank_transaction_ids=[payment_2026_03.id],
    )

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    history = snapshot["category_history"]
    row_map = {item["name"]: item for item in history["rows"]}

    assert history["current_month_label"] == "mar/2026"
    assert history["previous_month_label"] == "fev/2026"
    assert history["previous_year_label"] == "mar/2025"
    assert history["previous_month_available"] is True
    assert history["previous_year_available"] is True
    assert row_map["Moradia"]["current_total"] == 1800.0
    assert row_map["Moradia"]["previous_month_total"] == 1600.0
    assert row_map["Moradia"]["previous_year_total"] == 1500.0
    assert row_map["Supermercado"]["current_total"] == 900.0
    assert row_map["Supermercado"]["previous_month_total"] == 700.0
    assert row_map["Supermercado"]["previous_year_total"] == 650.0
    assert row_map["Educação"]["current_total"] == 300.0
    assert row_map["Educação"]["previous_month_total"] == 0.0
    assert row_map["Educação"]["previous_month_change"] is not None
    assert row_map["Educação"]["previous_year_total"] == 120.0
    assert history["technical_adjustments"]["current_invoice_credit_total"] == 100.0
    assert history["technical_adjustments"]["previous_month_invoice_credit_total"] == 50.0
    assert history["technical_adjustments"]["previous_year_invoice_credit_total"] == 30.0


def test_analysis_snapshot_builds_category_history_from_purchase_month_for_invoice_items(db_session):
    payment_2025 = _add_tx(
        db_session,
        tx_date=date(2025, 2, 18),
        description="FATURA FEV 2025",
        amount=-620.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_2025 = _add_invoice(
        db_session,
        due_date=date(2025, 2, 20),
        card_final="2525",
        item_specs=[
            ("SUPERMERCADO TESTE", "650.00", date(2025, 1, 28)),
            ("DESCONTO NA FATURA - PO", "-30.00", date(2025, 1, 29)),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_2025.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_2025.id,
        bank_transaction_ids=[payment_2025.id],
    )

    payment_2025_12 = _add_tx(
        db_session,
        tx_date=date(2026, 1, 18),
        description="FATURA DEZ 2025",
        amount=-650.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_2025_12 = _add_invoice(
        db_session,
        due_date=date(2026, 1, 20),
        card_final="2626",
        item_specs=[
            ("SUPERMERCADO TESTE", "700.00", date(2025, 12, 27)),
            ("DESCONTO NA FATURA - PO", "-50.00", date(2025, 12, 28)),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_2025_12.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_2025_12.id,
        bank_transaction_ids=[payment_2025_12.id],
    )

    payment_2026 = _add_tx(
        db_session,
        tx_date=date(2026, 2, 18),
        description="FATURA FEV 2026",
        amount=-800.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_2026 = _add_invoice(
        db_session,
        due_date=date(2026, 2, 20),
        card_final="3636",
        item_specs=[
            ("SUPERMERCADO TESTE", "900.00", date(2026, 1, 28)),
            ("DESCONTO NA FATURA - PO", "-100.00", date(2026, 1, 29)),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_2026.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_2026.id,
        bank_transaction_ids=[payment_2026.id],
    )

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))

    history = snapshot["category_history"]
    row_map = {item["name"]: item for item in history["rows"]}

    assert history["current_month_label"] == "jan/2026"
    assert history["previous_month_label"] == "dez/2025"
    assert history["previous_year_label"] == "jan/2025"
    assert row_map["Supermercado"]["current_total"] == 900.0
    assert row_map["Supermercado"]["previous_month_total"] == 700.0
    assert row_map["Supermercado"]["previous_year_total"] == 650.0
    assert history["technical_adjustments"]["current_invoice_credit_total"] == 100.0
    assert history["technical_adjustments"]["previous_month_invoice_credit_total"] == 50.0
    assert history["technical_adjustments"]["previous_year_invoice_credit_total"] == 30.0


def test_analysis_snapshot_treats_historical_gaps_as_missing_base_for_category_history(db_session):
    _add_tx(db_session, tx_date=date(2025, 1, 5), description="SALARIO JAN 2025", amount=4700.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2025, 1, 8), description="ALUGUEL JAN 2025", amount=-1400.0, category="Moradia", transaction_kind="expense")
    payment_2025 = _add_tx(
        db_session,
        tx_date=date(2025, 1, 18),
        description="FATURA JAN 2025",
        amount=-450.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_2025 = _add_invoice(
        db_session,
        due_date=date(2025, 1, 20),
        card_final="1515",
        item_specs=[
            ("SUPERMERCADO TESTE", "470.00"),
            ("DESCONTO NA FATURA - PO", "-20.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_2025.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_2025.id,
        bank_transaction_ids=[payment_2025.id],
    )

    _add_tx(db_session, tx_date=date(2026, 1, 5), description="SALARIO JAN 2026", amount=4900.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 1, 8), description="ALUGUEL JAN 2026", amount=-1550.0, category="Moradia", transaction_kind="expense")
    payment_2026_01 = _add_tx(
        db_session,
        tx_date=date(2026, 1, 18),
        description="FATURA JAN 2026",
        amount=-500.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_2026_01 = _add_invoice(
        db_session,
        due_date=date(2026, 1, 20),
        card_final="1616",
        item_specs=[
            ("SUPERMERCADO TESTE", "530.00"),
            ("DESCONTO NA FATURA - PO", "-30.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_2026_01.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_2026_01.id,
        bank_transaction_ids=[payment_2026_01.id],
    )

    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR 2026", amount=5000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR 2026", amount=-1800.0, category="Moradia", transaction_kind="expense")
    payment_2026_03 = _add_tx(
        db_session,
        tx_date=date(2026, 3, 18),
        description="FATURA MAR 2026",
        amount=-820.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice_2026_03 = _add_invoice(
        db_session,
        due_date=date(2026, 3, 20),
        card_final="3636",
        item_specs=[
            ("SUPERMERCADO TESTE", "900.00"),
            ("DESCONTO NA FATURA - PO", "-80.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice_2026_03.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice_2026_03.id,
        bank_transaction_ids=[payment_2026_03.id],
    )

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    history = snapshot["category_history"]
    row_map = {item["name"]: item for item in history["rows"]}

    assert history["previous_month_label"] == "fev/2026"
    assert history["previous_year_label"] == "mar/2025"
    assert history["previous_month_available"] is False
    assert history["previous_year_available"] is False
    assert row_map["Moradia"]["previous_month_total"] is None
    assert row_map["Moradia"]["previous_month_display"] == "Sem base"
    assert row_map["Moradia"]["previous_month_change"] is None
    assert row_map["Supermercado"]["previous_year_total"] is None
    assert row_map["Supermercado"]["previous_year_display"] == "Sem base"
    assert row_map["Supermercado"]["previous_year_change"] is None
    assert history["technical_adjustments"]["previous_month_invoice_credit_total"] is None
    assert history["technical_adjustments"]["previous_month_change"] is None
    assert history["technical_adjustments"]["previous_year_invoice_credit_total"] is None
    assert history["technical_adjustments"]["previous_year_change"] is None


def test_analysis_snapshot_consumption_alerts_and_actions_follow_purchase_month(db_session):
    _add_tx(db_session, tx_date=date(2026, 1, 5), description="SALARIO JAN", amount=5000.0, category="Salário", transaction_kind="income")
    payment = _add_tx(
        db_session,
        tx_date=date(2026, 2, 18),
        description="FATURA FEV",
        amount=-800.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice = _add_invoice(
        db_session,
        due_date=date(2026, 2, 20),
        card_final="4242",
        item_specs=[
            ("SUPERMERCADO TESTE", "900.00", date(2026, 1, 28)),
            ("DESCONTO NA FATURA - PO", "-100.00", date(2026, 1, 29)),
            ("PAGAMENTO EFETUADO", "-800.00", date(2026, 2, 18)),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice.id,
        bank_transaction_ids=[payment.id],
    )

    january_snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
    february_snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))

    january_text = " ".join(
        f"{item['title']} {item['body']}" for item in january_snapshot["alerts"] + january_snapshot["actions"]
    )
    february_text = " ".join(
        f"{item['title']} {item['body']}" for item in february_snapshot["alerts"] + february_snapshot["actions"]
    )

    assert "Supermercado" in january_text
    assert "visão de consumo" in january_text
    assert "Pagamento de Fatura" not in january_text
    assert "Supermercado" not in february_text


def test_analysis_snapshot_consumption_recommendations_ignore_technical_card_entries(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=3000.0, category="Salário", transaction_kind="income")
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1200.0, category="Moradia", transaction_kind="expense")
    payment = _add_tx(
        db_session,
        tx_date=date(2026, 3, 18),
        description="FATURA MAR",
        amount=-500.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    invoice = _add_invoice(
        db_session,
        due_date=date(2026, 3, 20),
        card_final="5252",
        item_specs=[
            ("SUPERMERCADO TESTE", "600.00"),
            ("DESCONTO NA FATURA - PO", "-100.00"),
            ("PAGAMENTO EFETUADO", "-500.00"),
        ],
    )
    _assign_invoice_item_categories(
        db_session,
        invoice_id=invoice.id,
        categories_by_description={"SUPERMERCADO TESTE": "Supermercado"},
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=invoice.id,
        bank_transaction_ids=[payment.id],
    )

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))
    text = " ".join(f"{item['title']} {item['body']}" for item in snapshot["alerts"] + snapshot["actions"])

    assert "Moradia" in text
    assert "Pagamento de Fatura" not in text
    assert "Créditos de Fatura" not in text


def test_analysis_snapshot_keeps_general_balance_alert_coherent_with_conciliated_summary(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 8), description="ALUGUEL MAR", amount=-1500.0, category="Moradia", transaction_kind="expense")

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    assert any(item["title"] == "Saldo negativo no período" for item in snapshot["alerts"])
    assert any(
        item["title"] == "Atacar o saldo negativo imediatamente" and "Moradia" in item["body"]
        for item in snapshot["actions"]
    )


def test_analysis_snapshot_only_includes_fully_conciliated_invoices_in_conciliated_view(db_session):
    _add_tx(db_session, tx_date=date(2026, 3, 5), description="SALARIO MAR", amount=5000.0, category="Sal\u00e1rio", transaction_kind="income")
    payment = _add_tx(
        db_session,
        tx_date=date(2026, 3, 18),
        description="FATURA MAR",
        amount=-650.0,
        category="Pagamento de Fatura",
        transaction_kind="expense",
        is_card_bill_payment=True,
    )
    included_invoice = _add_invoice(
        db_session,
        due_date=date(2026, 3, 20),
        card_final="1234",
        item_specs=[
            ("COMPRA A", "700.00"),
            ("DESCONTO NA FATURA - PO", "-50.00"),
        ],
    )
    reconcile_credit_card_invoice_bank_payments(
        db_session,
        invoice_id=included_invoice.id,
        bank_transaction_ids=[payment.id],
    )

    pending_invoice = _add_invoice(
        db_session,
        due_date=date(2026, 3, 22),
        card_final="5678",
        item_specs=[("COMPRA PENDENTE", "200.00")],
    )
    partial_invoice = _add_invoice(
        db_session,
        due_date=date(2026, 3, 24),
        card_final="9012",
        item_specs=[("COMPRA PARCIAL", "300.00")],
    )
    conflict_invoice = _add_invoice(
        db_session,
        due_date=date(2026, 3, 26),
        card_final="3456",
        item_specs=[("COMPRA CONFLICT", "400.00")],
    )
    _set_conciliation_status(db_session, invoice_id=partial_invoice.id, status="partially_conciliated")
    _set_conciliation_status(db_session, invoice_id=conflict_invoice.id, status="conflict")
    assert db_session.scalar(
        select(CreditCardInvoiceConciliation.status).where(CreditCardInvoiceConciliation.invoice_id == pending_invoice.id)
    ) is None

    snapshot = build_analysis_snapshot(db_session, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))

    conciliated = snapshot["conciliated_month"]
    assert conciliated["included_invoice_count"] == 1
    assert conciliated["conciliated_card_charge_total"] == 700.0
    assert conciliated["conciliated_invoice_credit_total"] == 50.0
    assert conciliated["outside_invoices_by_status"]["pending_review"] == 1
    assert conciliated["outside_invoices_by_status"]["partially_conciliated"] == 1
    assert conciliated["outside_invoices_by_status"]["conflict"] == 1
    assert conciliated["outside_invoices_total"] == 3
    assert snapshot["primary_summary"]["included_invoice_count"] == 1
    assert snapshot["primary_summary"]["outside_invoice_count"] == 3
    assert snapshot["primary_summary"]["expense_total"] == 650.0

