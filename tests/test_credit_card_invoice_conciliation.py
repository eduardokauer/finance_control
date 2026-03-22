from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.repositories.models import (
    CreditCard,
    CreditCardInvoice,
    CreditCardInvoiceConciliation,
    CreditCardInvoiceConciliationItem,
    CreditCardInvoiceItem,
    SourceFile,
    Transaction,
)
from app.services.credit_card_bills import (
    CreditCardInvoiceConciliationError,
    ensure_credit_card_invoice_conciliation,
    get_credit_card_invoice_detail,
    list_invoice_payment_candidates,
    reconcile_credit_card_invoice_bank_payments,
    unlink_credit_card_invoice_bank_payment,
)


def _create_card(db_session, *, card_final: str = "1234") -> CreditCard:
    card = CreditCard(
        issuer="itau",
        card_label=f"Itaú Visa final {card_final}",
        card_final=card_final,
        brand="Visa",
        is_active=True,
    )
    db_session.add(card)
    db_session.flush()
    return card


def _create_invoice(db_session, *, card_final: str = "1234", item_specs: list[tuple[str, str]] | None = None, due_date: date = date(2026, 3, 20)) -> CreditCardInvoice:
    card = _create_card(db_session, card_final=card_final)
    source_file = SourceFile(
        source_type="credit_card_bill",
        file_name=f"invoice-{card_final}.csv",
        file_path=f"upload://invoice-{card_final}.csv",
        file_hash=f"invoice-hash-{card_final}",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()

    invoice = CreditCardInvoice(
        source_file_id=source_file.id,
        card_id=card.id,
        issuer=card.issuer,
        card_final=card.card_final,
        billing_year=2026,
        billing_month=3,
        due_date=due_date,
        closing_date=date(2026, 3, 12),
        total_amount_brl=Decimal("0.00"),
        source_file_name=source_file.file_name,
        source_file_hash=f"invoice-model-{card_final}",
        notes="invoice test",
        import_status="imported",
    )
    db_session.add(invoice)
    db_session.flush()

    item_specs = item_specs or []
    for index, (description_raw, amount_brl) in enumerate(item_specs, start=1):
        db_session.add(
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 3, min(index, 28)),
                description_raw=description_raw,
                description_normalized=description_raw.lower(),
                amount_brl=Decimal(amount_brl),
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


def _add_bank_transaction(
    db_session,
    *,
    tx_key: str,
    tx_date: date,
    description: str,
    normalized: str,
    amount: float,
    is_card_bill_payment: bool = False,
    transaction_kind: str = "expense",
    category: str = "Outros",
) -> Transaction:
    source_file = SourceFile(
        source_type="bank_statement",
        file_name=f"statement-{tx_key}.ofx",
        file_path=f"upload://statement-{tx_key}.ofx",
        file_hash=f"statement-hash-{tx_key}",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()

    tx = Transaction(
        source_file_id=source_file.id,
        source_type="bank_statement",
        account_ref="account-1",
        external_id=None,
        canonical_hash=f"tx-hash-{tx_key}",
        transaction_date=tx_date,
        competence_month=tx_date.strftime("%Y-%m"),
        description_raw=description,
        description_normalized=normalized,
        amount=amount,
        direction="credit" if amount > 0 else "debit",
        transaction_kind=transaction_kind,
        category=category,
        categorization_method="fallback",
        categorization_confidence=0.3,
        applied_rule=None,
        manual_override=False,
        is_card_bill_payment=is_card_bill_payment,
        should_count_in_spending=True,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


def test_ensure_invoice_conciliation_creates_header_and_auto_credit_items(db_session):
    invoice = _create_invoice(
        db_session,
        item_specs=[
            ("DESCONTO NA FATURA - PO", "-50.00"),
            ("COMPRA MERCADO", "200.00"),
            ("PAGAMENTO EFETUADO", "-200.00"),
        ],
    )

    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice.id)

    assert conciliation is not None
    assert conciliation.status == "partially_conciliated"
    assert conciliation.gross_amount_brl == Decimal("200.00")
    assert conciliation.invoice_credit_total_brl == Decimal("50.00")
    assert conciliation.bank_payment_total_brl == Decimal("0.00")
    assert conciliation.conciliated_total_brl == Decimal("50.00")
    assert conciliation.remaining_balance_brl == Decimal("150.00")

    items = db_session.scalars(
        select(CreditCardInvoiceConciliationItem).where(
            CreditCardInvoiceConciliationItem.conciliation_id == conciliation.id
        )
    ).all()
    assert len(items) == 1
    assert items[0].item_type == "invoice_credit"
    assert items[0].amount_brl == Decimal("50.00")



def test_invoice_credit_only_marks_invoice_as_partially_conciliated(db_session):
    invoice = _create_invoice(
        db_session,
        item_specs=[
            ("COMPRA A", "180.00"),
            ("COMPRA B", "100.00"),
            ("DESCONTO NA FATURA - PO", "-30.00"),
        ],
    )

    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice.id)

    assert conciliation is not None
    assert conciliation.gross_amount_brl == Decimal("280.00")
    assert conciliation.invoice_credit_total_brl == Decimal("30.00")
    assert conciliation.bank_payment_total_brl == Decimal("0.00")
    assert conciliation.conciliated_total_brl == Decimal("30.00")
    assert conciliation.remaining_balance_brl == Decimal("250.00")
    assert conciliation.status == "partially_conciliated"

def test_list_invoice_payment_candidates_filters_statement_transactions(db_session):
    invoice = _create_invoice(
        db_session,
        item_specs=[
            ("COMPRA MERCADO", "300.00"),
        ],
    )
    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice.id)

    good = _add_bank_transaction(
        db_session,
        tx_key="good",
        tx_date=date(2026, 3, 18),
        description="PAGAMENTO FATURA ITAUCARD",
        normalized="pagamento fatura itaucard",
        amount=-300.0,
        is_card_bill_payment=True,
    )
    _add_bank_transaction(
        db_session,
        tx_key="outside",
        tx_date=date(2026, 5, 5),
        description="PAGAMENTO FATURA ITAUCARD",
        normalized="pagamento fatura itaucard",
        amount=-300.0,
        is_card_bill_payment=True,
    )
    _add_bank_transaction(
        db_session,
        tx_key="incoming",
        tx_date=date(2026, 3, 18),
        description="PAGAMENTO FATURA ITAUCARD",
        normalized="pagamento fatura itaucard",
        amount=300.0,
        is_card_bill_payment=True,
    )
    _add_bank_transaction(
        db_session,
        tx_key="noise",
        tx_date=date(2026, 3, 18),
        description="SUPERMERCADO CENTRAL",
        normalized="supermercado central",
        amount=-300.0,
        is_card_bill_payment=False,
    )

    detail = get_credit_card_invoice_detail(db_session, invoice_id=invoice.id)
    assert detail is not None
    candidates = list_invoice_payment_candidates(db_session, invoice=detail.invoice, conciliation=conciliation)

    assert [candidate.transaction.id for candidate in candidates] == [good.id]


def test_list_invoice_payment_candidates_accepts_itau_black_bill_payment_signal(db_session):
    invoice = _create_invoice(
        db_session,
        card_final="1291",
        due_date=date(2026, 2, 7),
        item_specs=[
            ("COMPRA MERCADO", "10691.62"),
        ],
    )
    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice.id)

    good = _add_bank_transaction(
        db_session,
        tx_key="itau-black-bill",
        tx_date=date(2026, 2, 9),
        description="ITAU BLACK 3101 1291",
        normalized="itau black 3101 1291",
        amount=-10691.62,
        is_card_bill_payment=False,
        transaction_kind="expense",
        category="Pagamento de Fatura",
    )

    candidates = list_invoice_payment_candidates(db_session, invoice=invoice, conciliation=conciliation)

    assert [candidate.transaction.id for candidate in candidates] == [good.id]
    assert candidates[0].fit_label == "match_saldo"



def test_list_invoice_payment_candidates_orders_strongest_signals_first(db_session):
    invoice = _create_invoice(
        db_session,
        item_specs=[
            ("COMPRA A", "180.00"),
            ("COMPRA B", "100.00"),
            ("DESCONTO NA FATURA - PO", "-30.00"),
        ],
    )
    invoice.total_amount_brl = Decimal("220.00")
    db_session.commit()
    db_session.refresh(invoice)
    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice.id)

    exact_remaining = _add_bank_transaction(
        db_session,
        tx_key="rank-remaining",
        tx_date=date(2026, 3, 20),
        description="PAGAMENTO FATURA ITAUCARD",
        normalized="pagamento fatura itaucard",
        amount=-250.0,
        is_card_bill_payment=True,
    )
    exact_total = _add_bank_transaction(
        db_session,
        tx_key="rank-total",
        tx_date=date(2026, 3, 19),
        description="PAGAMENTO FATURA CARTAO ITAU",
        normalized="pagamento fatura cartao itau",
        amount=-220.0,
        is_card_bill_payment=True,
    )
    near_remaining = _add_bank_transaction(
        db_session,
        tx_key="rank-near",
        tx_date=date(2026, 3, 18),
        description="PAGAMENTO FATURA ITAUCARD",
        normalized="pagamento fatura itaucard",
        amount=-247.0,
        is_card_bill_payment=True,
    )
    weak = _add_bank_transaction(
        db_session,
        tx_key="rank-weak",
        tx_date=date(2026, 4, 18),
        description="PAGAMENTO CARTAO",
        normalized="pagamento cartao",
        amount=-180.0,
        is_card_bill_payment=False,
    )

    candidates = list_invoice_payment_candidates(db_session, invoice=invoice, conciliation=conciliation)

    assert [candidate.transaction.id for candidate in candidates[:4]] == [
        exact_remaining.id,
        exact_total.id,
        near_remaining.id,
        weak.id,
    ]
    assert candidates[0].fit_label == "match_saldo"
    assert candidates[0].strength_label == "muito_forte"
    assert candidates[0].description_signal == "descricao_forte"
    assert candidates[1].fit_label == "match_total"
    assert candidates[1].strength_label == "forte"
    assert candidates[2].fit_label == "proximo_do_saldo"
    assert candidates[2].strength_label == "boa"
    assert candidates[3].fit_label == "candidato_fraco"
    assert candidates[3].strength_label == "fraca"


def test_candidate_with_weak_value_and_very_close_date_stays_fraca(db_session):
    invoice = _create_invoice(
        db_session,
        item_specs=[
            ("COMPRA A", "180.00"),
            ("COMPRA B", "100.00"),
            ("DESCONTO NA FATURA - PO", "-30.00"),
        ],
    )
    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice.id)

    weak_close = _add_bank_transaction(
        db_session,
        tx_key="weak-close-date",
        tx_date=date(2026, 3, 20),
        description="PAGAMENTO CARTAO",
        normalized="pagamento cartao",
        amount=-180.0,
        is_card_bill_payment=False,
    )

    candidates = list_invoice_payment_candidates(db_session, invoice=invoice, conciliation=conciliation)
    candidate = next(candidate for candidate in candidates if candidate.transaction.id == weak_close.id)

    assert candidate.fit_label == "candidato_fraco"
    assert candidate.date_signal == "muito_proximo_vencimento"
    assert candidate.strength_label == "fraca"


def test_candidate_with_weak_value_and_strong_description_stays_fraca(db_session):
    invoice = _create_invoice(
        db_session,
        item_specs=[
            ("COMPRA A", "180.00"),
            ("COMPRA B", "100.00"),
            ("DESCONTO NA FATURA - PO", "-30.00"),
        ],
    )
    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice.id)

    weak_strong_description = _add_bank_transaction(
        db_session,
        tx_key="weak-strong-description",
        tx_date=date(2026, 3, 24),
        description="PAGAMENTO FATURA ITAUCARD",
        normalized="pagamento fatura itaucard",
        amount=-180.0,
        is_card_bill_payment=True,
    )

    candidates = list_invoice_payment_candidates(db_session, invoice=invoice, conciliation=conciliation)
    candidate = next(candidate for candidate in candidates if candidate.transaction.id == weak_strong_description.id)

    assert candidate.fit_label == "candidato_fraco"
    assert candidate.description_signal == "descricao_forte"
    assert candidate.strength_label == "fraca"

def test_reconcile_invoice_payments_supports_single_and_multiple_links(db_session):
    invoice = _create_invoice(
        db_session,
        item_specs=[
            ("COMPRA A", "180.00"),
            ("COMPRA B", "100.00"),
            ("DESCONTO NA FATURA - PO", "-30.00"),
        ],
    )
    payment_a = _add_bank_transaction(
        db_session,
        tx_key="p1",
        tx_date=date(2026, 3, 19),
        description="PAGAMENTO FATURA ITAUCARD",
        normalized="pagamento fatura itaucard",
        amount=-100.0,
        is_card_bill_payment=True,
    )
    payment_b = _add_bank_transaction(
        db_session,
        tx_key="p2",
        tx_date=date(2026, 3, 25),
        description="PAGAMENTO FATURA CARTAO ITAU",
        normalized="pagamento fatura cartao itau",
        amount=-150.0,
        is_card_bill_payment=True,
    )

    first = reconcile_credit_card_invoice_bank_payments(db_session, invoice_id=invoice.id, bank_transaction_ids=[payment_a.id])
    assert first.status == "partially_conciliated"
    assert first.gross_amount_brl == Decimal("280.00")
    assert first.invoice_credit_total_brl == Decimal("30.00")
    assert first.bank_payment_total_brl == Decimal("100.00")
    assert first.conciliated_total_brl == Decimal("130.00")
    assert first.remaining_balance_brl == Decimal("150.00")

    second = reconcile_credit_card_invoice_bank_payments(db_session, invoice_id=invoice.id, bank_transaction_ids=[payment_b.id])
    assert second.status == "conciliated"
    assert second.bank_payment_total_brl == Decimal("250.00")
    assert second.conciliated_total_brl == Decimal("280.00")
    assert second.remaining_balance_brl == Decimal("0.00")


def test_reconcile_invoice_blocks_bank_transaction_already_used_by_other_invoice(db_session):
    invoice_a = _create_invoice(db_session, card_final="1111", item_specs=[("COMPRA A", "200.00")])
    invoice_b = _create_invoice(db_session, card_final="2222", item_specs=[("COMPRA B", "200.00")])
    payment = _add_bank_transaction(
        db_session,
        tx_key="shared",
        tx_date=date(2026, 3, 20),
        description="PAGAMENTO FATURA ITAUCARD",
        normalized="pagamento fatura itaucard",
        amount=-200.0,
        is_card_bill_payment=True,
    )

    reconcile_credit_card_invoice_bank_payments(db_session, invoice_id=invoice_a.id, bank_transaction_ids=[payment.id])

    with pytest.raises(CreditCardInvoiceConciliationError):
        reconcile_credit_card_invoice_bank_payments(db_session, invoice_id=invoice_b.id, bank_transaction_ids=[payment.id])


def test_unlink_invoice_payment_recomputes_balance_and_status(db_session):
    invoice = _create_invoice(
        db_session,
        item_specs=[
            ("COMPRA A", "200.00"),
            ("DESCONTO NA FATURA - PO", "-20.00"),
        ],
    )
    payment = _add_bank_transaction(
        db_session,
        tx_key="unlink",
        tx_date=date(2026, 3, 18),
        description="PAGAMENTO FATURA ITAUCARD",
        normalized="pagamento fatura itaucard",
        amount=-180.0,
        is_card_bill_payment=True,
    )

    reconcile_credit_card_invoice_bank_payments(db_session, invoice_id=invoice.id, bank_transaction_ids=[payment.id])
    conciliation = db_session.scalar(
        select(CreditCardInvoiceConciliation).where(CreditCardInvoiceConciliation.invoice_id == invoice.id)
    )
    assert conciliation is not None
    bank_item = db_session.scalar(
        select(CreditCardInvoiceConciliationItem).where(
            CreditCardInvoiceConciliationItem.conciliation_id == conciliation.id,
            CreditCardInvoiceConciliationItem.item_type == "bank_payment",
        )
    )
    assert bank_item is not None

    updated = unlink_credit_card_invoice_bank_payment(
        db_session,
        invoice_id=invoice.id,
        conciliation_item_id=bank_item.id,
    )

    assert updated.status == "partially_conciliated"
    assert updated.bank_payment_total_brl == Decimal("0.00")
    assert updated.invoice_credit_total_brl == Decimal("20.00")
    assert updated.conciliated_total_brl == Decimal("20.00")
    assert updated.remaining_balance_brl == Decimal("180.00")


def test_invoice_payment_items_are_not_used_as_official_conciliation_source(db_session):
    invoice = _create_invoice(
        db_session,
        item_specs=[
            ("PAGAMENTO EFETUADO", "-300.00"),
            ("COMPRA MERCADO", "300.00"),
        ],
    )

    detail = get_credit_card_invoice_detail(db_session, invoice_id=invoice.id)

    assert detail is not None
    assert detail.summary.payment_total_brl == Decimal("-300.00")
    assert detail.conciliation_summary.bank_payment_total_brl == Decimal("0.00")
    assert detail.conciliation_summary.conciliated_total_brl == Decimal("0.00")
    assert detail.conciliation_summary.remaining_balance_brl == Decimal("300.00")
    assert all(item.conciliation_item.item_type != "bank_payment" for item in detail.conciliation_items)




