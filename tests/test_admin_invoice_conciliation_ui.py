from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings
from app.repositories.models import (
    Category,
    CreditCard,
    CreditCardInvoice,
    CreditCardInvoiceConciliation,
    CreditCardInvoiceConciliationItem,
    CreditCardInvoiceItem,
    SourceFile,
    Transaction,
)


def _login(client):
    return client.post("/admin/login", data={"password": settings.admin_ui_password, "next": "/admin"})


def _seed_categories(db_session):
    db_session.add(Category(name="Outros", transaction_kind="expense", is_active=True))
    db_session.commit()


def _seed_invoice(db_session, *, card_final: str = "1234") -> CreditCardInvoice:
    card = CreditCard(
        issuer="itau",
        card_label=f"Itaú Visa final {card_final}",
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
        file_hash=f"invoice-hash-ui-{card_final}",
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
        due_date=date(2026, 3, 20),
        closing_date=date(2026, 3, 12),
        total_amount_brl=Decimal("250.00"),
        source_file_name=source_file.file_name,
        source_file_hash=f"invoice-ui-model-{card_final}",
        notes="invoice ui test",
        import_status="pending_review",
    )
    db_session.add(invoice)
    db_session.flush()

    db_session.add_all(
        [
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 3, 5),
                description_raw="COMPRA MERCADO",
                description_normalized="compra mercado",
                amount_brl=Decimal("200.00"),
                installment_current=None,
                installment_total=None,
                is_installment=False,
                derived_note=None,
                external_row_hash=f"row-{invoice.id}-1",
            ),
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 3, 6),
                description_raw="COMPRA FARMACIA",
                description_normalized="compra farmacia",
                amount_brl=Decimal("80.00"),
                installment_current=None,
                installment_total=None,
                is_installment=False,
                derived_note=None,
                external_row_hash=f"row-{invoice.id}-2",
            ),
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 3, 7),
                description_raw="DESCONTO NA FATURA - PO",
                description_normalized="desconto na fatura po",
                amount_brl=Decimal("-30.00"),
                installment_current=None,
                installment_total=None,
                is_installment=False,
                derived_note=None,
                external_row_hash=f"row-{invoice.id}-3",
            ),
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 3, 8),
                description_raw="PAGAMENTO EFETUADO",
                description_normalized="pagamento efetuado",
                amount_brl=Decimal("-100.00"),
                installment_current=None,
                installment_total=None,
                is_installment=False,
                derived_note=None,
                external_row_hash=f"row-{invoice.id}-4",
            ),
        ]
    )
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


def _seed_bank_payment(db_session, *, tx_key: str, tx_date: date, amount: float, description: str = "PAGAMENTO FATURA ITAUCARD") -> Transaction:
    source_file = SourceFile(
        source_type="bank_statement",
        file_name=f"statement-{tx_key}.ofx",
        file_path=f"upload://statement-{tx_key}.ofx",
        file_hash=f"statement-hash-ui-{tx_key}",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()

    tx = Transaction(
        source_file_id=source_file.id,
        source_type="bank_statement",
        account_ref="account-1",
        external_id=None,
        canonical_hash=f"tx-ui-{tx_key}",
        transaction_date=tx_date,
        competence_month=tx_date.strftime("%Y-%m"),
        description_raw=description,
        description_normalized=description.lower(),
        amount=amount,
        direction="credit" if amount > 0 else "debit",
        transaction_kind="expense",
        category="Outros",
        categorization_method="fallback",
        categorization_confidence=0.3,
        applied_rule=None,
        manual_override=False,
        is_card_bill_payment=True,
        should_count_in_spending=True,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


def test_admin_invoice_detail_shows_conciliation_blocks(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_invoice(db_session)
    candidate = _seed_bank_payment(db_session, tx_key="candidate", tx_date=date(2026, 3, 19), amount=-250.0)
    _login(client)

    response = client.get(f"/admin/credit-card-invoices/{invoice.id}")

    assert response.status_code == 200
    assert "Resumo da conciliação" in response.text
    assert "Pagamentos candidatos do extrato" in response.text
    assert "invoice_credit" in response.text
    assert "PAGAMENTO FATURA ITAUCARD" in response.text
    assert "Já conciliado" in response.text or "Ja conciliado" in response.text
    assert "Falta antes da nova seleção" in response.text or "Falta antes da nova selecao" in response.text
    assert "match_saldo" in response.text
    assert "muito_forte" in response.text
    assert "bate exatamente com o saldo restante" in response.text
    assert str(candidate.id) in response.text


def test_admin_can_link_and_unlink_invoice_payment_from_detail(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_invoice(db_session)
    payment = _seed_bank_payment(db_session, tx_key="link", tx_date=date(2026, 3, 19), amount=-250.0)
    _login(client)

    response = client.post(
        f"/admin/credit-card-invoices/{invoice.id}/conciliation",
        data={"selected_transaction_ids": str(payment.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Conciliação atualizada." in response.text
    assert "conciliated" in response.text
    assert "bank_payment" in response.text
    assert "Desfazer vínculo" in response.text

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

    unlink_response = client.post(
        f"/admin/credit-card-invoices/{invoice.id}/conciliation/items/{bank_item.id}/unlink",
        follow_redirects=True,
    )

    assert unlink_response.status_code == 200
    assert "Vínculo de pagamento removido." in unlink_response.text
    assert "pending_review" in unlink_response.text


def test_admin_blocks_linking_transaction_already_used_by_other_invoice(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice_a = _seed_invoice(db_session, card_final="1234")
    invoice_b = _seed_invoice(db_session, card_final="5678")
    payment = _seed_bank_payment(db_session, tx_key="shared", tx_date=date(2026, 3, 19), amount=-250.0)
    _login(client)

    first = client.post(
        f"/admin/credit-card-invoices/{invoice_a.id}/conciliation",
        data={"selected_transaction_ids": str(payment.id)},
        follow_redirects=True,
    )
    assert first.status_code == 200

    second = client.post(
        f"/admin/credit-card-invoices/{invoice_b.id}/conciliation",
        data={"selected_transaction_ids": str(payment.id)},
        follow_redirects=True,
    )

    assert second.status_code == 409
    assert "já conciliada em outra fatura" in second.text

