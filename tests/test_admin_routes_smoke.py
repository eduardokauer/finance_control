import json
from datetime import date

from app.core.config import settings
from app.repositories.models import (
    AnalysisRun,
    Category,
    CreditCard,
    CreditCardInvoice,
    CreditCardInvoiceItem,
    SourceFile,
    Transaction,
)


def _login(client):
    return client.post("/admin/login", data={"password": settings.admin_ui_password, "next": "/admin"})


def _assert_route_ok(response, route: str):
    assert response.status_code == 200, route
    assert "Internal Server Error" not in response.text, route


def _seed_categories(db_session):
    for name, kind in [
        ("N\u00e3o Categorizado", "expense"),
        ("Transporte", "expense"),
        ("Sal\u00e1rio", "income"),
    ]:
        db_session.add(Category(name=name, transaction_kind=kind, is_active=True))
    db_session.commit()


def _seed_transaction(db_session) -> Transaction:
    source_file = SourceFile(
        source_type="bank_statement",
        file_name="routes-smoke.ofx",
        file_path="upload://routes-smoke.ofx",
        file_hash="routes-smoke-hash",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()
    tx = Transaction(
        source_file_id=source_file.id,
        source_type="bank_statement",
        account_ref="default-account",
        external_id=None,
        canonical_hash="routes-smoke-tx",
        transaction_date=date(2026, 3, 7),
        competence_month="2026-03",
        description_raw="UBER ROUTE TEST",
        description_normalized="uber route test",
        amount=-25.0,
        direction="debit",
        transaction_kind="expense",
        category="Transporte",
        categorization_method="rule",
        categorization_confidence=0.9,
        applied_rule=None,
        manual_override=False,
        should_count_in_spending=True,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


def _seed_invoice(db_session) -> CreditCardInvoice:
    card = CreditCard(
        issuer="itau",
        card_label="Ita\u00fa Visa final 1234",
        card_final="1234",
        brand="Visa",
        is_active=True,
    )
    db_session.add(card)
    db_session.flush()

    source_file = SourceFile(
        source_type="credit_card_bill",
        file_name="invoice-routes.csv",
        file_path="upload://invoice-routes.csv",
        file_hash="invoice-routes-hash",
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
        total_amount_brl="130.45",
        source_file_name=source_file.file_name,
        source_file_hash="invoice-routes-source-hash",
        notes="routes smoke",
        import_status="imported",
    )
    db_session.add(invoice)
    db_session.flush()

    db_session.add(
        CreditCardInvoiceItem(
            invoice_id=invoice.id,
            purchase_date=date(2026, 3, 5),
            description_raw="SUPERMERCADO TESTE",
            description_normalized="supermercado teste",
            amount_brl="130.45",
            installment_current=None,
            installment_total=None,
            is_installment=False,
            derived_note=None,
            external_row_hash=f"routes-smoke-row-{invoice.id}",
        )
    )
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


def _seed_legacy_analysis_run(db_session):
    legacy_payload = {
        "period": {"label": "01/03/2026 a 31/03/2026", "start": "2026-03-01", "end": "2026-03-31", "month_reference_label": "mar/2026"},
        "summary": {
            "income_total": 5000.0,
            "expense_total": 0.0,
            "balance": 5000.0,
            "uncategorized_total": 0.0,
            "transaction_count": 1,
            "income_display": "R$ 5.000,00",
            "expense_display": "R$ 0,00",
            "balance_display": "R$ 5.000,00",
            "uncategorized_display": "R$ 0,00",
        },
        "comparison": {
            "reference_label": "fev/2026",
            "income": {"trend": "up", "trend_label": "subiu", "percent_display": "n/a", "delta_display": "R$ 5.000,00", "current_display": "R$ 5.000,00", "previous_display": "R$ 0,00"},
            "expense": {"trend": "stable", "trend_label": "estável", "percent_display": "n/a", "delta_display": "R$ 0,00", "current_display": "R$ 0,00", "previous_display": "R$ 0,00"},
            "balance": {"trend": "up", "trend_label": "subiu", "percent_display": "n/a", "delta_display": "R$ 5.000,00", "current_display": "R$ 5.000,00", "previous_display": "R$ 0,00"},
        },
        "monthly_series": [],
        "categories": [],
        "top_expense_categories": [],
        "technical_items": {
            "transfer_total": 0.0,
            "transfer_display": "R$ 0,00",
            "transfer_share": 0.0,
            "transfer_share_display": "n/a",
            "card_bill_total": 0.0,
            "card_bill_display": "R$ 0,00",
            "card_bill_share": 0.0,
            "card_bill_share_display": "n/a",
            "combined_total": 0.0,
            "combined_display": "R$ 0,00",
            "combined_share": 0.0,
            "combined_share_display": "n/a",
            "note": "legacy smoke test",
        },
        "quality": {"uncategorized_total": 0.0, "uncategorized_display": "R$ 0,00", "uncategorized_share": 0.0, "uncategorized_share_display": "n/a"},
        "alerts": [],
        "actions": [],
        "charts": {"monthly": {"labels": [], "income": [], "expense": [], "balance": []}, "categories": {"labels": [], "values": [], "technical": []}},
        "conciliation_signals": {
            "conciliated_bank_payment_total_brl": 0.0,
            "conciliated_bank_payment_count": 0,
            "conciliated_bank_payment_display": "R$ 0,00",
            "invoice_credit_total_brl": 0.0,
            "invoice_credit_display": "R$ 0,00",
            "invoices_by_status": {"pending_review": 0, "partially_conciliated": 0, "conciliated": 0, "conflict": 0},
            "invoices_total": 0,
            "note": "legacy payload",
        },
    }
    db_session.add(
        AnalysisRun(
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            trigger_source_file_id=None,
            payload=json.dumps(legacy_payload, ensure_ascii=False),
            prompt="legacy_analysis",
            html_output="<p>legacy html</p>",
            status="success",
        )
    )
    db_session.commit()


def test_admin_main_routes_smoke(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(db_session)
    invoice = _seed_invoice(db_session)

    unauthenticated = client.get("/admin", follow_redirects=False)
    assert unauthenticated.status_code == 303
    assert "/admin/login" in unauthenticated.headers["location"]

    login_page = client.get("/admin/login")
    _assert_route_ok(login_page, "/admin/login")

    _login(client)

    routes = [
        "/admin",
        "/admin/analysis/charts?period_start=2026-03-01&period_end=2026-03-31",
        "/admin/analysis?period_start=2026-03-01&period_end=2026-03-31",
        "/admin/analysis/transactions?period_start=2026-03-01&period_end=2026-03-31",
        "/admin/conference?period_start=2026-03-01&period_end=2026-03-31",
        "/admin/conference/technical?period_start=2026-03-01&period_end=2026-03-31",
        "/admin/conference/manage",
        "/admin/operations",
        "/admin/transactions",
        "/admin/transactions/bulk",
        f"/admin/transactions/{tx.id}",
        "/admin/reapply",
        "/admin/rules",
        "/admin/categories",
        "/admin/categories/manage",
        "/admin/credit-card-invoices",
        "/admin/credit-card-invoices/manage",
        f"/admin/credit-card-invoices/{invoice.id}",
    ]

    for route in routes:
        response = client.get(route)
        _assert_route_ok(response, route)
        assert 'class="admin-topbar"' in response.text, route
        assert 'data-admin-nav' in response.text, route
        assert "Principal" in response.text, route
        assert "Operação" in response.text, route
        assert "Configuração" in response.text, route


def test_admin_analysis_and_conference_routes_support_legacy_saved_payload(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session)
    _seed_legacy_analysis_run(db_session)
    _login(client)

    analysis_response = client.get("/admin/analysis/charts?period_start=2026-03-01&period_end=2026-03-31")
    conference_response = client.get("/admin/conference?period_start=2026-03-01&period_end=2026-03-31")
    technical_response = client.get("/admin/conference/technical?period_start=2026-03-01&period_end=2026-03-31")

    _assert_route_ok(analysis_response, "/admin/analysis/charts?period_start=2026-03-01&period_end=2026-03-31")
    _assert_route_ok(conference_response, "/admin/conference?period_start=2026-03-01&period_end=2026-03-31")
    _assert_route_ok(technical_response, "/admin/conference/technical?period_start=2026-03-01&period_end=2026-03-31")
    assert "Gráficos analíticos" in analysis_response.text
    assert "Painel visual do período" in analysis_response.text
    assert "Abrir lançamentos" in analysis_response.text
    assert "Itens do extrato" in conference_response.text
    assert "Auditoria técnica" in conference_response.text
    assert "legacy html" in technical_response.text


def test_admin_archetype_routes_expose_layout_contracts(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(db_session)
    invoice = _seed_invoice(db_session)
    item = db_session.query(CreditCardInvoiceItem).filter_by(invoice_id=invoice.id).first()
    _login(client)

    summary_response = client.get("/admin")
    analysis_response = client.get("/admin/analysis/charts?period_start=2026-03-01&period_end=2026-03-31")
    conference_response = client.get("/admin/conference?period_start=2026-03-01&period_end=2026-03-31")
    technical_response = client.get("/admin/conference/technical?period_start=2026-03-01&period_end=2026-03-31")
    operations_response = client.get("/admin/operations")
    transactions_response = client.get("/admin/transactions")
    invoice_detail_response = client.get(f"/admin/credit-card-invoices/{invoice.id}")
    transaction_detail_response = client.get(f"/admin/transactions/{tx.id}")
    item_edit_response = client.get(f"/admin/credit-card-invoices/{invoice.id}/items/{item.id}/category")

    for response, route in [
        (summary_response, "/admin"),
        (analysis_response, "/admin/analysis/charts"),
        (conference_response, "/admin/conference"),
        (technical_response, "/admin/conference/technical"),
        (operations_response, "/admin/operations"),
        (transactions_response, "/admin/transactions"),
        (invoice_detail_response, f"/admin/credit-card-invoices/{invoice.id}"),
        (transaction_detail_response, f"/admin/transactions/{tx.id}"),
        (item_edit_response, f"/admin/credit-card-invoices/{invoice.id}/items/{item.id}/category"),
    ]:
        _assert_route_ok(response, route)

    assert "home-kpi-strip" in summary_response.text
    assert "home-dashboard-grid" in summary_response.text
    assert "analysis-context-chips" in analysis_response.text
    assert "analysis-page-stack" in analysis_response.text
    assert "analysis-page-stack" in conference_response.text
    assert "analysis-page-stack" in conference_response.text
    assert "analysis-page-stack" in technical_response.text
    assert "ops-shell-grid" in operations_response.text
    assert "summary-shortcuts" in operations_response.text
    assert "ops-shell-grid" in transactions_response.text
    assert "responsive-stack" in transactions_response.text
    assert "split-layout-wide" in invoice_detail_response.text
    assert "ops-shell-grid" in invoice_detail_response.text
    assert "ops-shell-grid" in transaction_detail_response.text
    assert "ops-shell-grid" in item_edit_response.text
