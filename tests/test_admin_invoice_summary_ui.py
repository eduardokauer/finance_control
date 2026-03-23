from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.repositories.models import Category, CreditCard, CreditCardInvoice, CreditCardInvoiceItem, SourceFile


def _login(client):
    return client.post("/admin/login", data={"password": settings.admin_ui_password, "next": "/admin"})


def _seed_categories(db_session):
    for name, kind in [
        ("Não Categorizado", "expense"),
        ("Transporte", "expense"),
        ("Outros", "expense"),
        ("Salário", "income"),
        ("Transferências", "transfer"),
    ]:
        db_session.add(Category(name=name, transaction_kind=kind, is_active=True))
    db_session.commit()


def _seed_invoice_for_summary_ui(db_session) -> CreditCardInvoice:
    card = CreditCard(
        issuer="itau",
        card_label="Itaú Visa final 1234",
        card_final="1234",
        brand="Visa",
        is_active=True,
    )
    db_session.add(card)
    db_session.flush()

    source_file = SourceFile(
        source_type="credit_card_bill",
        file_name="invoice-summary-ui.csv",
        file_path="upload://invoice-summary-ui.csv",
        file_hash="invoice-summary-ui-hash",
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
        billing_month=2,
        due_date=date(2026, 2, 20),
        closing_date=date(2026, 2, 7),
        total_amount_brl="110.45",
        source_file_name=source_file.file_name,
        source_file_hash=source_file.file_hash,
        notes="Resumo operacional",
        import_status="pending_review",
    )
    db_session.add(invoice)
    db_session.flush()

    db_session.add_all(
        [
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 2, 5),
                description_raw="SUPERMERCADO TESTE",
                description_normalized="supermercado teste",
                amount_brl="100.00",
                installment_current=None,
                installment_total=None,
                is_installment=False,
                derived_note=None,
                external_row_hash=f"row-hash-{invoice.id}-1",
            ),
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 2, 7),
                description_raw="CURSO PARCELADO",
                description_normalized="curso parcelado",
                amount_brl="30.45",
                installment_current=2,
                installment_total=3,
                is_installment=True,
                derived_note="parcela 2/3",
                external_row_hash=f"row-hash-{invoice.id}-2",
            ),
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 2, 8),
                description_raw="DESCONTO NA FATURA - PO",
                description_normalized="desconto na fatura - po",
                amount_brl="-20.00",
                installment_current=None,
                installment_total=None,
                is_installment=False,
                derived_note="desconto de pontos",
                external_row_hash=f"row-hash-{invoice.id}-3",
            ),
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 2, 9),
                description_raw="PAGAMENTO EFETUADO",
                description_normalized="pagamento efetuado",
                amount_brl="-50.00",
                installment_current=None,
                installment_total=None,
                is_installment=False,
                derived_note="pagamento tecnico",
                external_row_hash=f"row-hash-{invoice.id}-4",
            ),
        ]
    )
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


def test_admin_credit_card_invoice_detail_shows_operational_summary(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_invoice_for_summary_ui(db_session)
    _login(client)

    response = client.get(f"/admin/credit-card-invoices/{invoice.id}")

    assert response.status_code == 200
    assert f"Fatura #{invoice.id}" in response.text
    assert "pending_review" in response.text
    assert "Total de cobranças" in response.text
    assert "Total de créditos/descontos" in response.text
    assert "Total de pagamentos identificados" in response.text
    assert "Total composto da fatura" in response.text
    assert "Diferença para o total informado" in response.text
    assert "payment" in response.text
    assert "credit" in response.text
    assert "PAGAMENTO EFETUADO" in response.text
    assert "DESCONTO NA FATURA - PO" in response.text
    assert "R$ -50.00" in response.text
    assert "R$ -20.00" in response.text


def test_admin_credit_card_invoice_detail_summary_excludes_payment_from_composed_total(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_invoice_for_summary_ui(db_session)
    _login(client)

    response = client.get(f"/admin/credit-card-invoices/{invoice.id}")

    assert response.status_code == 200
    assert "R$ 130.45" in response.text
    assert "R$ -20.00" in response.text
    assert "R$ -50.00" in response.text
    assert "R$ 110.45" in response.text
    assert "R$ 0.00" in response.text
