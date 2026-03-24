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
    db_session.commit()
    return tx


def _add_invoice(db_session, *, due_date: date, card_final: str = "1234", item_specs: list[tuple[str, str]] | None = None):
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
    for index, (description_raw, amount_brl) in enumerate(item_specs or [], start=1):
        db_session.add(
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=due_date,
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
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


def _set_conciliation_status(db_session, *, invoice_id: int, status: str):
    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice_id)
    assert conciliation is not None
    conciliation.status = status
    db_session.commit()
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
    db_session.commit()


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
    assert row_map["Moradia"]["current_total"] == 1800.0
    assert row_map["Moradia"]["previous_month_total"] == 1600.0
    assert row_map["Moradia"]["previous_year_total"] == 1500.0
    assert row_map["Supermercado"]["current_total"] == 900.0
    assert row_map["Supermercado"]["previous_month_total"] == 700.0
    assert row_map["Supermercado"]["previous_year_total"] == 650.0
    assert row_map["Educação"]["current_total"] == 300.0
    assert row_map["Educação"]["previous_month_total"] == 0.0
    assert row_map["Educação"]["previous_year_total"] == 120.0
    assert history["technical_adjustments"]["current_invoice_credit_total"] == 100.0
    assert history["technical_adjustments"]["previous_month_invoice_credit_total"] == 50.0
    assert history["technical_adjustments"]["previous_year_invoice_credit_total"] == 30.0


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

