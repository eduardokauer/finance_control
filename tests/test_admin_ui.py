import html as html_lib
import json
import re
from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.repositories.models import (
    AnalysisRun,
    CategorizationRule,
    Category,
    CreditCard,
    CreditCardInvoice,
    CreditCardInvoiceConciliation,
    CreditCardInvoiceConciliationItem,
    CreditCardInvoiceItem,
    SourceFile,
    Transaction,
    TransactionAuditLog,
)
from app.services.analysis import run_analysis


def _login(client):
    return client.post("/admin/login", data={"password": settings.admin_ui_password, "next": "/admin"})


def _extract_href_by_data_attr(page_html: str, attr_name: str, attr_value: str) -> str:
    match = re.search(rf'href="([^"]+)"[^>]*{attr_name}="{attr_value}"', page_html)
    assert match is not None
    return html_lib.unescape(match.group(1))


def _extract_return_summary_href(page_html: str) -> str:
    match = re.search(r'href="([^"]+)"[^>]*data-return-summary-link', page_html)
    assert match is not None
    return html_lib.unescape(match.group(1))


def _seed_categories(db_session):
    for name, kind in [
        ("N\u00e3o Categorizado", "expense"),
        ("Moradia", "expense"),
        ("Supermercado", "expense"),
        ("Educa\u00e7\u00e3o", "expense"),
        ("Transporte", "expense"),
        ("Outros", "expense"),
        ("Sal\u00e1rio", "income"),
        ("Transfer\u00eancias", "transfer"),
    ]:
        db_session.add(Category(name=name, transaction_kind=kind, is_active=True))
    db_session.commit()


def _seed_transaction(
    db_session,
    *,
    description: str = "UBER TRIP",
    normalized: str = "uber trip",
    transaction_date: date = date(2026, 3, 7),
    amount: float = -25.0,
    transaction_kind: str = "expense",
    category: str = "N\u00e3o Categorizado",
):
    source_file = SourceFile(
        source_type="bank_statement",
        file_name="manual.ofx",
        file_path="upload://manual.ofx",
        file_hash=f"hash-admin-ui-{normalized}",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()
    tx = Transaction(
        source_file_id=source_file.id,
        source_type="bank_statement",
        account_ref="default-account",
        external_id=None,
        canonical_hash=f"tx-{normalized}-{transaction_date.isoformat()}",
        transaction_date=transaction_date,
        competence_month=transaction_date.strftime("%Y-%m"),
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
        should_count_in_spending=True,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


def _seed_conciliated_bank_payment(db_session, *, tx: Transaction, due_date: date = date(2026, 3, 20)):
    card = CreditCard(
        issuer="itau",
        card_label="Ita\u00fa Visa final 9999",
        card_final="9999",
        brand="Visa",
        is_active=True,
    )
    db_session.add(card)
    db_session.flush()
    source_file = SourceFile(
        source_type="credit_card_bill",
        file_name="invoice-9999.csv",
        file_path="upload://invoice-9999.csv",
        file_hash=f"invoice-hash-ui-{tx.id}",
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
        total_amount_brl="130.00",
        source_file_name=source_file.file_name,
        source_file_hash=source_file.file_hash,
        notes="conciliation ui test",
        import_status="imported",
    )
    db_session.add(invoice)
    db_session.flush()
    invoice_item = CreditCardInvoiceItem(
        invoice_id=invoice.id,
        purchase_date=due_date,
        description_raw="DESCONTO NA FATURA - PO",
        description_normalized="desconto na fatura - po",
        amount_brl="-10.00",
        installment_current=None,
        installment_total=None,
        is_installment=False,
        derived_note=None,
        external_row_hash=f"row-hash-ui-{invoice.id}",
    )
    db_session.add(invoice_item)
    db_session.flush()
    conciliation = CreditCardInvoiceConciliation(
        invoice_id=invoice.id,
        status="conciliated",
        gross_amount_brl="130.00",
        invoice_credit_total_brl="10.00",
        bank_payment_total_brl="120.00",
        conciliated_total_brl="130.00",
        remaining_balance_brl="0.00",
    )
    db_session.add(conciliation)
    db_session.flush()
    db_session.add_all(
        [
            CreditCardInvoiceConciliationItem(
                conciliation_id=conciliation.id,
                item_type="invoice_credit",
                amount_brl="10.00",
                bank_transaction_id=None,
                invoice_item_id=invoice_item.id,
                notes="auto credit",
            ),
            CreditCardInvoiceConciliationItem(
                conciliation_id=conciliation.id,
                item_type="bank_payment",
                amount_brl="120.00",
                bank_transaction_id=tx.id,
                invoice_item_id=None,
                notes="manual link",
            ),
        ]
    )
    db_session.commit()
    return invoice

def test_admin_login_required_and_dashboard_renders(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)

    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert "/admin/login" in resp.headers["location"]

    login = client.post("/admin/login", data={"password": "secret-123", "next": "/admin"}, follow_redirects=False)
    assert login.status_code == 303
    assert login.headers["location"] == "/admin"

    home = client.get("/admin")
    assert home.status_code == 200
    assert "Finance Control Admin" in home.text
    assert 'class="admin-topbar"' in home.text
    assert 'data-admin-nav' in home.text
    assert "Principal" in home.text
    assert "Operação" in home.text
    assert "Configuração" in home.text
    assert "Visão Geral" in home.text
    assert "Resumo das leituras do período." in home.text
    assert 'data-analysis-breadcrumbs' in home.text
    assert 'data-context-chip="period"' in home.text
    assert 'data-context-chip="lens"' not in home.text
    assert "Controles globais da página" in home.text
    assert 'class="analysis-period-bar"' in home.text
    assert "Último mês fechado disponível" in home.text
    assert 'id="analysis-apply-button"' in home.text
    assert "Receitas reais" in home.text
    assert "Despesas reais" in home.text
    assert "Saldo real" in home.text
    assert "Entradas totais:" in home.text
    assert "Saídas totais:" in home.text
    assert "Faturas conciliadas" in home.text
    assert "Leituras especializadas" in home.text
    assert "Categorias do período" in home.text
    assert "Alertas" in home.text
    assert "chart.js" in home.text.lower()
    assert "Resumo executivo da Visão de Caixa" not in home.text
    assert "Análise detalhada" not in home.text
    assert "Conferência" not in home.text
    assert "Visão conciliada" in home.text
    assert "Visão de Extrato" in home.text
    assert "Visão de Faturas" in home.text
    assert "Central operacional" in home.text
    assert "Visão bruta de apoio" not in home.text
    assert "Sinais analíticos de conciliação" not in home.text
    assert "Análise determinística renderizada" not in home.text


def test_admin_login_page_uses_shell_auth_header(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")

    response = client.get("/admin/login")

    assert response.status_code == 200
    assert "Finance Control Admin" in response.text
    assert "Interface administrativa" in response.text
    assert "A nova shell tamb" in response.text


def test_admin_sidebar_exposes_categories_submenu(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _login(client)

    response = client.get("/admin/categories/manage")

    assert response.status_code == 200
    assert "Categorias" in response.text
    assert "Administrar categorias" in response.text
    assert 'href="/admin/categories/manage"' in response.text
    assert "admin-sidebar-sublink-active" in response.text


def test_admin_sidebar_exposes_invoice_submenu(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _login(client)

    response = client.get("/admin/credit-card-invoices/manage")

    assert response.status_code == 200
    assert "Visão de Faturas" in response.text
    assert "Administrar faturas" in response.text
    assert 'href="/admin/credit-card-invoices/manage"' in response.text
    assert "admin-sidebar-sublink-active" in response.text


def test_admin_sidebar_exposes_transactions_bulk_submenu(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _login(client)

    response = client.get("/admin/transactions/bulk")

    assert response.status_code == 200
    assert "Lançamentos" in response.text
    assert "Ações em lote" in response.text
    assert 'href="/admin/transactions/bulk"' in response.text
    assert "admin-sidebar-sublink-active" in response.text


def test_admin_categories_manage_can_reassign_category_references_and_delete_source_category(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    casa = Category(name="Casa", transaction_kind="expense", is_active=True)
    db_session.add(casa)
    db_session.flush()
    moradia = db_session.scalar(select(Category).where(Category.name == "Moradia"))
    assert moradia is not None

    tx = _seed_transaction(
        db_session,
        description="ALUGUEL CASA",
        normalized="aluguel casa",
        transaction_date=date(2026, 3, 10),
        amount=-1850.0,
        transaction_kind="expense",
        category="Casa",
    )
    rule = CategorizationRule(
        rule_type="contains",
        pattern="casa",
        category_name="Casa",
        kind_mode="flow",
        source_scope="both",
        priority=40,
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(casa)
    db_session.refresh(rule)

    invoice = _seed_credit_card_invoice(
        db_session,
        card_label="Itaú Visa final 8888",
        card_final="8888",
        item_specs=[("MATERIAL CASA", "180.00")],
    )
    invoice_item = db_session.scalars(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id)
    ).first()
    assert invoice_item is not None
    invoice_item.category = "Casa"
    invoice_item.categorization_method = "rule"
    invoice_item.categorization_confidence = 0.9
    invoice_item.categorization_rule_id = rule.id
    db_session.commit()
    _login(client)

    move_response = client.post(
        f"/admin/categories/{casa.id}/reassign",
        data={
            "target_category_id": moradia.id,
            "return_to": "/admin/categories/manage",
        },
        follow_redirects=False,
    )

    assert move_response.status_code == 303
    assert move_response.headers["location"] == "/admin/categories/manage"

    db_session.refresh(tx)
    db_session.refresh(invoice_item)
    db_session.refresh(rule)

    assert tx.category == "Moradia"
    assert invoice_item.category == "Moradia"
    assert rule.category_name == "Moradia"
    audit_logs = db_session.scalars(
        select(TransactionAuditLog).where(TransactionAuditLog.transaction_id == tx.id)
    ).all()
    assert any(
        log.origin == "admin_category_reassignment"
        and log.previous_category == "Casa"
        and log.new_category == "Moradia"
        for log in audit_logs
    )

    follow_up = client.get("/admin/categories/manage")
    assert follow_up.status_code == 200
    assert "Categoria consolidada: Casa -&gt; Moradia." in follow_up.text
    assert "Mover tudo" in follow_up.text
    assert "Excluir categoria" in follow_up.text

    delete_response = client.post(
        f"/admin/categories/{casa.id}/delete",
        data={"return_to": "/admin/categories/manage"},
        follow_redirects=False,
    )

    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/admin/categories/manage"
    assert db_session.get(Category, casa.id) is None


def test_admin_categories_manage_blocks_delete_while_category_still_has_usage(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    casa = Category(name="Casa", transaction_kind="expense", is_active=True)
    db_session.add(casa)
    db_session.commit()
    _seed_transaction(
        db_session,
        description="CONTA CASA",
        normalized="conta casa",
        transaction_date=date(2026, 3, 8),
        amount=-120.0,
        transaction_kind="expense",
        category="Casa",
    )
    _login(client)

    response = client.post(
        f"/admin/categories/{casa.id}/delete",
        data={"return_to": "/admin/categories/manage"},
    )

    assert response.status_code == 400
    assert "Mova lançamentos, itens de fatura e regras antes de excluir a categoria." in response.text
    assert db_session.get(Category, casa.id) is not None


def test_admin_summary_page_exposes_contextual_ctas_with_preserved_state(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO MAR",
        normalized="salario mar context links",
        transaction_date=date(2026, 3, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Salário",
    )
    _seed_transaction(
        db_session,
        description="ALUGUEL MAR",
        normalized="aluguel mar context links",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _seed_transaction(
        db_session,
        description="MERCADO MAR",
        normalized="mercado mar context links",
        transaction_date=date(2026, 3, 12),
        amount=-900.0,
        transaction_kind="expense",
        category="Supermercado",
    )
    _login(client)

    response = client.get("/admin?selection_mode=month&month=2026-03")

    assert response.status_code == 200
    assert 'data-context-cta="conciliated"' in response.text
    assert 'data-context-cta="statement"' in response.text
    assert 'data-context-cta="invoice"' in response.text
    assert 'data-context-cta="alerts"' in response.text
    assert 'data-context-cta="categories"' in response.text

    chart_href = _extract_href_by_data_attr(response.text, "data-context-cta", "conciliated")
    assert "selection_mode=month" in chart_href
    assert "month=2026-03" in chart_href
    assert chart_href.startswith("/admin/analysis?")

    statement_href = _extract_href_by_data_attr(response.text, "data-context-cta", "statement")
    assert statement_href.startswith("/admin/conference?")
    assert "selection_mode=month" in statement_href
    assert "month=2026-03" in statement_href

    categories_href = _extract_href_by_data_attr(response.text, "data-context-cta", "categories")
    assert categories_href.startswith("/admin/categories")


def test_admin_summary_page_shows_overview_categories_chart_without_redundant_list(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO FEV",
        normalized="salario fev",
        transaction_date=date(2026, 2, 5),
        amount=4500.0,
        transaction_kind="income",
        category="Salário",
    )
    _seed_transaction(
        db_session,
        description="ALUGUEL FEV",
        normalized="aluguel fev",
        transaction_date=date(2026, 2, 8),
        amount=-1500.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _seed_transaction(
        db_session,
        description="MERCADO FEV",
        normalized="mercado fev",
        transaction_date=date(2026, 2, 12),
        amount=-700.0,
        transaction_kind="expense",
        category="Supermercado",
    )
    _seed_transaction(
        db_session,
        description="UBER FEV",
        normalized="uber fev",
        transaction_date=date(2026, 2, 18),
        amount=-200.0,
        transaction_kind="expense",
        category="Transporte",
    )
    _seed_transaction(
        db_session,
        description="SALARIO MAR",
        normalized="salario mar",
        transaction_date=date(2026, 3, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Salário",
    )
    _seed_transaction(
        db_session,
        description="ALUGUEL MAR",
        normalized="aluguel mar",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _seed_transaction(
        db_session,
        description="MERCADO MAR",
        normalized="mercado mar",
        transaction_date=date(2026, 3, 12),
        amount=-900.0,
        transaction_kind="expense",
        category="Supermercado",
    )
    _seed_transaction(
        db_session,
        description="CURSO MAR",
        normalized="curso mar",
        transaction_date=date(2026, 3, 14),
        amount=-500.0,
        transaction_kind="expense",
        category="Educação",
    )
    _seed_transaction(
        db_session,
        description="UBER MAR",
        normalized="uber mar",
        transaction_date=date(2026, 3, 18),
        amount=-120.0,
        transaction_kind="expense",
        category="Transporte",
    )
    _seed_transaction(
        db_session,
        description="OUTROS MAR",
        normalized="outros mar",
        transaction_date=date(2026, 3, 22),
        amount=-60.0,
        transaction_kind="expense",
        category="Outros",
    )
    _login(client)

    response = client.get("/admin?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Categorias do período" in response.text
    assert "Ver composição" not in response.text
    assert 'data-category-row="' not in response.text
    assert 'id="overview-categories-legend"' in response.text
    assert "mountAdminStackedCategoryChart" in response.text

    chart_match = re.search(
        r"window\.mountAdminStackedCategoryChart\(\s*.*?,\s*(\{.*?\}),\s*\{ legendId: 'overview-categories-legend' \}\s*\);",
        response.text,
        re.S,
    )
    assert chart_match is not None
    chart_payload = json.loads(chart_match.group(1))
    assert [dataset["label"] for dataset in chart_payload["datasets"]] == [
        "Moradia",
        "Supermercado",
        "Educação",
        "Transporte",
        "Outros",
    ]


def test_admin_summary_categories_cta_opens_categories_with_same_period(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO MAR",
        normalized="salario mar category focus",
        transaction_date=date(2026, 3, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Sal\u00e1rio",
    )
    _seed_transaction(
        db_session,
        description="ALUGUEL MAR",
        normalized="aluguel mar category focus",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _seed_transaction(
        db_session,
        description="MERCADO MAR",
        normalized="mercado mar category focus",
        transaction_date=date(2026, 3, 12),
        amount=-900.0,
        transaction_kind="expense",
        category="Supermercado",
    )
    _login(client)

    summary = client.get("/admin?selection_mode=month&month=2026-03")

    assert summary.status_code == 200
    categories_href = _extract_href_by_data_attr(summary.text, "data-context-cta", "categories")
    assert categories_href.startswith("/admin/categories?")
    assert "selection_mode=month" in categories_href
    assert "month=2026-03" in categories_href

    categories = client.get(categories_href)

    assert categories.status_code == 200
    assert "Categoria em foco" not in categories.text
    assert "Moradia" in categories.text
    assert "01/03/2026" in categories.text
    assert "31/03/2026" in categories.text
    assert "Composição da categoria" in categories.text
    assert "ALUGUEL MAR" in categories.text


def test_admin_categories_page_filters_by_multiple_selected_categories(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="ALUGUEL MAR",
        normalized="aluguel mar multi category filter",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _seed_transaction(
        db_session,
        description="MERCADO MAR",
        normalized="mercado mar multi category filter",
        transaction_date=date(2026, 3, 12),
        amount=-900.0,
        transaction_kind="expense",
        category="Supermercado",
    )
    _seed_transaction(
        db_session,
        description="UBER MAR",
        normalized="uber mar multi category filter",
        transaction_date=date(2026, 3, 18),
        amount=-120.0,
        transaction_kind="expense",
        category="Transporte",
    )
    _login(client)

    response = client.get(
        "/admin/categories?selection_mode=month&month=2026-03"
        "&selected_category=Moradia&selected_category=Supermercado"
    )

    assert response.status_code == 200
    assert "Selecionar categorias" in response.text
    assert 'name="selected_category"' in response.text
    assert 'value="Moradia"' in response.text
    assert 'value="Supermercado"' in response.text
    assert "Categoria" in response.text
    assert "Editar lançamento" in response.text
    assert "/admin/transactions/" in response.text
    assert 'data-context-chip="selected_categories"' in response.text
    assert 'data-sort-key="amount"' in response.text
    assert 'data-sort-direction="desc"' in response.text
    assert 'id="categories-main-monthly-legend"' in response.text
    assert "mountAdminStackedCategoryChart" in response.text
    assert "Grafico de categorias" not in response.text
    assert 'data-category-row="Moradia"' not in response.text
    assert 'data-category-row="Supermercado"' not in response.text
    assert "ALUGUEL MAR" in response.text
    assert "MERCADO MAR" in response.text
    assert "UBER MAR" not in response.text
    assert response.text.index("ALUGUEL MAR") < response.text.index("MERCADO MAR")
    monthly_chart_match = re.search(r"const monthlyData = (\{.*?\});", response.text, re.S)
    assert monthly_chart_match is not None
    monthly_chart_payload = json.loads(monthly_chart_match.group(1))
    assert len(monthly_chart_payload["labels"]) == 12
    assert [dataset["label"] for dataset in monthly_chart_payload["datasets"]] == [
        "Moradia",
        "Supermercado",
    ]
    assert monthly_chart_payload["datasets"][0]["values"][-1] == 1800.0
    assert monthly_chart_payload["datasets"][1]["values"][-1] == 900.0


def test_admin_categories_page_treats_empty_selection_as_all_categories(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="ALUGUEL MAR TODAS",
        normalized="aluguel mar todas categorias",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _seed_transaction(
        db_session,
        description="MERCADO MAR TODAS",
        normalized="mercado mar todas categorias",
        transaction_date=date(2026, 3, 12),
        amount=-900.0,
        transaction_kind="expense",
        category="Supermercado",
    )
    _seed_transaction(
        db_session,
        description="UBER MAR TODAS",
        normalized="uber mar todas categorias",
        transaction_date=date(2026, 3, 18),
        amount=-120.0,
        transaction_kind="expense",
        category="Transporte",
    )
    _login(client)

    response = client.get("/admin/categories?selection_mode=month&month=2026-03")

    assert response.status_code == 200
    assert "Selecionar todas" in response.text
    assert "Limpar selecao" in response.text
    assert 'data-context-chip="selected_categories"' in response.text
    assert "Todas as categorias" in response.text
    assert "ALUGUEL MAR TODAS" in response.text
    assert "MERCADO MAR TODAS" in response.text
    assert "UBER MAR TODAS" in response.text
    assert response.text.index("ALUGUEL MAR TODAS") < response.text.index("MERCADO MAR TODAS") < response.text.index("UBER MAR TODAS")
    assert 'value="Moradia" checked' not in response.text
    assert 'value="Supermercado" checked' not in response.text
    assert 'value="Transporte" checked' not in response.text
    monthly_chart_match = re.search(r"const monthlyData = (\{.*?\});", response.text, re.S)
    assert monthly_chart_match is not None
    monthly_chart_payload = json.loads(monthly_chart_match.group(1))
    assert len(monthly_chart_payload["datasets"]) >= 3
    assert {dataset["label"] for dataset in monthly_chart_payload["datasets"]} >= {
        "Moradia",
        "Supermercado",
        "Transporte",
    }


def test_admin_categories_composition_exposes_invoice_item_category_edit_link(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    payment = _seed_transaction(
        db_session,
        description="PAGAMENTO FATURA MAR",
        normalized="pagamento fatura mar categoria",
        transaction_date=date(2026, 3, 20),
        amount=-120.0,
        transaction_kind="expense",
        category="Pagamento de Fatura",
    )
    invoice = _seed_credit_card_invoice(
        db_session,
        card_label="Itaú Visa final 3333",
        card_final="3333",
        billing_year=2026,
        billing_month=3,
        total_amount="120.00",
        status="imported",
        item_specs=[("SUPERMERCADO FATURA", "120.00", date(2026, 3, 10))],
    )
    item = db_session.scalar(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice.id, CreditCardInvoiceItem.description_raw == "SUPERMERCADO FATURA")
    )
    item.category = "Supermercado"
    item.categorization_method = "manual"
    item.categorization_confidence = 1.0
    db_session.add(
        CreditCardInvoiceConciliation(
            invoice_id=invoice.id,
            status="conciliated",
            gross_amount_brl="120.00",
            invoice_credit_total_brl="0.00",
            bank_payment_total_brl="120.00",
            conciliated_total_brl="120.00",
            remaining_balance_brl="0.00",
        )
    )
    db_session.commit()
    _login(client)

    response = client.get("/admin/categories?selection_mode=month&month=2026-03&selected_category=Supermercado")

    assert response.status_code == 200
    assert "SUPERMERCADO FATURA" in response.text
    assert "Editar categoria" in response.text
    assert f'/admin/credit-card-invoices/{invoice.id}/items/{item.id}/category?return_to=' in response.text


def test_admin_categories_composition_supports_inline_transaction_category_edit(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(
        db_session,
        description="ALUGUEL INLINE",
        normalized="aluguel inline categoria",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _login(client)

    page = client.get("/admin/categories?selection_mode=month&month=2026-03&selected_category=Moradia")

    assert page.status_code == 200
    assert f"/admin/categories/composition/transactions/{tx.id}/edit" in page.text
    assert "data-inline-category-edit" in page.text

    editor = client.get(
        f"/admin/categories/composition/transactions/{tx.id}/edit",
        params={"return_to": "/admin/categories?selection_mode=month&month=2026-03&selected_category=Moradia"},
    )

    assert editor.status_code == 200
    assert "Buscar categoria" in editor.text
    assert "data-inline-category-editor" in editor.text
    assert "data-inline-save-button" in editor.text
    assert "disabled" in editor.text
    assert "Moradia" in editor.text
    assert "Supermercado" in editor.text
    assert "Salário" not in editor.text

    applied = client.post(
        f"/admin/categories/composition/transactions/{tx.id}/edit",
        data={
            "category": "Supermercado",
            "return_to": "/admin/categories?selection_mode=month&month=2026-03&selected_category=Moradia",
        },
    )

    assert applied.status_code == 200
    assert applied.text == ""

    db_session.expire_all()
    refreshed = db_session.get(Transaction, tx.id)
    assert refreshed is not None
    assert refreshed.category == "Supermercado"
    assert refreshed.categorization_method == "manual"
    assert refreshed.transaction_kind == "expense"


def test_admin_categories_composition_supports_inline_invoice_item_category_edit(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    payment = _seed_transaction(
        db_session,
        description="PAGAMENTO FATURA INLINE",
        normalized="pagamento fatura inline categoria",
        transaction_date=date(2026, 3, 20),
        amount=-120.0,
        transaction_kind="expense",
        category="Pagamento de Fatura",
    )
    invoice = _seed_credit_card_invoice(
        db_session,
        card_label="Itaú Visa final 4444",
        card_final="4444",
        billing_year=2026,
        billing_month=3,
        total_amount="120.00",
        status="imported",
        item_specs=[("SUPERMERCADO INLINE FATURA", "120.00", date(2026, 3, 10))],
    )
    item = db_session.scalar(
        select(CreditCardInvoiceItem)
        .where(
            CreditCardInvoiceItem.invoice_id == invoice.id,
            CreditCardInvoiceItem.description_raw == "SUPERMERCADO INLINE FATURA",
        )
    )
    assert item is not None
    item.category = "Supermercado"
    item.categorization_method = "manual"
    item.categorization_confidence = 1.0
    db_session.add(
        CreditCardInvoiceConciliation(
            invoice_id=invoice.id,
            status="conciliated",
            gross_amount_brl="120.00",
            invoice_credit_total_brl="0.00",
            bank_payment_total_brl="120.00",
            conciliated_total_brl="120.00",
            remaining_balance_brl="0.00",
        )
    )
    db_session.commit()
    _login(client)

    page = client.get("/admin/categories?selection_mode=month&month=2026-03&selected_category=Supermercado")

    assert page.status_code == 200
    assert f"/admin/categories/composition/invoice-items/{item.id}/edit" in page.text

    editor = client.get(
        f"/admin/categories/composition/invoice-items/{item.id}/edit",
        params={"return_to": "/admin/categories?selection_mode=month&month=2026-03&selected_category=Supermercado"},
    )

    assert editor.status_code == 200
    assert "Buscar categoria" in editor.text
    assert "data-inline-category-editor" in editor.text
    assert "Outros" in editor.text
    assert "Transferências" not in editor.text

    applied = client.post(
        f"/admin/categories/composition/invoice-items/{item.id}/edit",
        data={
            "category": "Outros",
            "return_to": "/admin/categories?selection_mode=month&month=2026-03&selected_category=Supermercado",
        },
    )

    assert applied.status_code == 200
    assert applied.text == ""

    db_session.expire_all()
    refreshed = db_session.get(CreditCardInvoiceItem, item.id)
    assert refreshed is not None
    assert refreshed.category == "Outros"
    assert refreshed.categorization_method == "manual"


def test_admin_categories_composition_keeps_all_selected_categories_even_with_focus(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="ALUGUEL MAR COMPOSICAO",
        normalized="aluguel mar composicao categorias",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _seed_transaction(
        db_session,
        description="MERCADO MAR COMPOSICAO",
        normalized="mercado mar composicao categorias",
        transaction_date=date(2026, 3, 12),
        amount=-900.0,
        transaction_kind="expense",
        category="Supermercado",
    )
    _login(client)

    response = client.get(
        "/admin/categories?selection_mode=month&month=2026-03"
        "&selected_category=Moradia&selected_category=Supermercado"
        "&focus_category=Moradia"
    )

    assert response.status_code == 200
    assert "Composição das categorias selecionadas" in response.text
    assert "Moradia, Supermercado" in response.text
    assert "ALUGUEL MAR COMPOSICAO" in response.text
    assert "MERCADO MAR COMPOSICAO" in response.text


def test_admin_summary_page_switches_home_lenses_and_hides_top_categories_in_cash_view(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO MAR",
        normalized="salario mar cash lens",
        transaction_date=date(2026, 3, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Salário",
    )
    _seed_transaction(
        db_session,
        description="ALUGUEL MAR",
        normalized="aluguel mar cash lens",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _seed_transaction(
        db_session,
        description="MERCADO MAR",
        normalized="mercado mar cash lens",
        transaction_date=date(2026, 3, 12),
        amount=-900.0,
        transaction_kind="expense",
        category="Supermercado",
    )
    _login(client)

    cash_response = client.get("/admin?period_start=2026-03-01&period_end=2026-03-31")
    competence_response = client.get("/admin?period_start=2026-03-01&period_end=2026-03-31&home_lens=competence")

    assert cash_response.status_code == 200
    assert "Receitas reais" in cash_response.text
    assert "Visão conciliada" in cash_response.text
    assert 'data-context-cta="categories"' in cash_response.text
    assert 'id="overview-categories-legend"' in cash_response.text
    assert "mountAdminStackedCategoryChart" in cash_response.text

    assert competence_response.status_code == 200
    assert "Receitas reais" in competence_response.text
    assert "Visão conciliada" in competence_response.text
    assert 'data-context-cta="categories"' in competence_response.text
    assert 'id="overview-categories-legend"' in competence_response.text
    assert 'data-context-chip="lens"' not in competence_response.text


def test_admin_summary_page_shows_local_chart_controls_for_both_lenses(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO MAR",
        normalized="salario mar chart controls",
        transaction_date=date(2026, 3, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Salário",
    )
    _seed_transaction(
        db_session,
        description="ALUGUEL MAR",
        normalized="aluguel mar chart controls",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _login(client)

    cash_response = client.get("/admin?period_start=2026-03-01&period_end=2026-03-31")
    competence_response = client.get("/admin?period_start=2026-03-01&period_end=2026-03-31&home_lens=competence")

    assert cash_response.status_code == 200
    assert "Visão conciliada" in cash_response.text
    assert "Visão de Extrato" in cash_response.text
    assert "Visão de Faturas" in cash_response.text
    assert 'name="home_chart_year"' not in cash_response.text

    assert competence_response.status_code == 200
    assert "Visão conciliada" in competence_response.text
    assert "Visão de Extrato" in competence_response.text
    assert "Visão de Faturas" in competence_response.text


def test_admin_summary_page_shows_recent_movements_block(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO MAR RECENT",
        normalized="salario mar recent home",
        transaction_date=date(2026, 3, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Salário",
    )
    _seed_transaction(
        db_session,
        description="MERCADO MAR RECENT",
        normalized="mercado mar recent home",
        transaction_date=date(2026, 3, 12),
        amount=-900.0,
        transaction_kind="expense",
        category="Supermercado",
    )
    _login(client)

    response = client.get("/admin?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Movimentações recentes" not in response.text
    assert "Alertas" in response.text
    assert "Categorias do período" in response.text


def test_admin_summary_page_uses_deferred_period_apply_controls(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO MAR CONTROLES",
        normalized="salario mar controles resumo",
        transaction_date=date(2026, 3, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Sal\u00e1rio",
    )
    _seed_credit_card_invoice(
        db_session,
        card_label="Ita\u00fa Visa final 2222",
        card_final="2222",
        billing_year=2026,
        billing_month=2,
        status="imported",
    )
    _login(client)

    response = client.get("/admin")

    assert response.status_code == 200
    assert "Ver resumo" not in response.text
    assert 'id="analysis-apply-button"' in response.text
    assert "Aplicar" in response.text
    assert "Último mês fechado disponível" in response.text
    assert 'name="month"' in response.text
    assert "marco de 2026" in response.text
    assert "fevereiro de 2026" in response.text


def test_admin_analysis_page_restores_summary_context_from_chart_navigation(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO MAR",
        normalized="salario mar context analysis",
        transaction_date=date(2026, 3, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Salário",
    )
    _seed_transaction(
        db_session,
        description="ALUGUEL MAR",
        normalized="aluguel mar context analysis",
        transaction_date=date(2026, 3, 8),
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _login(client)

    response = client.get(
        "/admin/analysis?selection_mode=month&month=2026-03&period_start=2026-03-01&period_end=2026-03-31"
        "&home_lens=competence&home_chart_mode=rolling_12&home_chart_compare=expense&origin=summary&origin_block=chart"
    )

    assert response.status_code == 200
    assert 'data-analysis-breadcrumbs' in response.text
    assert "Visão conciliada" in response.text
    assert "Composição da leitura" in response.text
    assert "12 meses conciliado" in response.text
    assert 'data-origin-banner="chart"' in response.text
    assert 'data-context-chip="origin_block"' in response.text
    assert "#conciliated-cashflow-chart" in response.text

    return_href = _extract_return_summary_href(response.text)
    assert return_href.startswith("/admin?")
    assert "selection_mode=month" in return_href
    assert "month=2026-03" in return_href
    assert "home_lens=" not in return_href
    assert "home_chart_mode=" not in return_href
    assert "home_chart_compare=" not in return_href


def test_admin_conference_page_restores_summary_context(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO MAR",
        normalized="salario mar conference context",
        transaction_date=date(2026, 3, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Salário",
    )
    _login(client)

    response = client.get(
        "/admin/conference?selection_mode=month&month=2026-03&period_start=2026-03-01&period_end=2026-03-31"
        "&home_lens=cash&origin=summary&origin_block=conference"
    )

    assert response.status_code == 200
    assert 'data-analysis-breadcrumbs' in response.text
    assert "Visão de Extrato" in response.text
    assert "Itens do extrato" in response.text
    assert "12 meses de extrato" in response.text
    assert "Auditoria técnica" in response.text
    assert 'data-origin-banner="conference"' in response.text
    assert 'data-context-chip="origin_block"' in response.text

    return_href = _extract_return_summary_href(response.text)
    assert return_href.startswith("/admin?")
    assert "selection_mode=month" in return_href
    assert "month=2026-03" in return_href
    assert "home_lens=" not in return_href


def test_admin_can_create_credit_card_and_upload_invoice(client, db_session, monkeypatch, sample_credit_card_csv_file):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _login(client)

    create_card = client.post(
        "/admin/credit-cards",
        data={
            "issuer": "itau",
            "card_label": "Ita\u00fa Visa final 1234",
            "card_final": "1234",
            "brand": "Visa",
            "is_active": "true",
        },
        follow_redirects=False,
    )
    assert create_card.status_code == 303

    card = db_session.scalar(select(CreditCard))
    assert card is not None

    with sample_credit_card_csv_file.open("rb") as handle:
        upload = client.post(
            "/admin/credit-card-bills/upload",
            data={
                "billing_month": "3",
                "billing_year": "2026",
                "due_date": "2026-03-20",
                "card_id": str(card.id),
                "total_amount_brl": "130,45",
                "closing_date": "2026-03-12",
                "notes": "Upload admin",
                "return_to": "/admin/credit-card-invoices/manage",
            },
            files={"file": (sample_credit_card_csv_file.name, handle, "text/csv")},
            follow_redirects=True,
        )

    assert upload.status_code == 200
    assert "Visão de Faturas" in upload.text
    assert "03/2026" in upload.text
    assert "Ita\u00fa Visa final 1234" in upload.text
    assert "Itens de fatura" in upload.text
    assert "SUPERMERCADO EXTRA 06/08" in upload.text
    assert "ESTORNO LOJA" in upload.text
    assert db_session.scalar(select(CreditCardInvoice)) is not None
    assert db_session.scalar(select(CreditCardInvoiceItem)) is not None


def test_admin_invoice_upload_form_is_available_only_on_invoice_page(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    db_session.add(
        CreditCard(
            issuer="itau",
            card_label="Itaú Visa final 1234",
            card_final="1234",
            brand="Visa",
            is_active=True,
        )
    )
    db_session.commit()
    _login(client)

    operations = client.get("/admin/operations")
    invoices = client.get("/admin/credit-card-invoices")
    invoices_manage = client.get("/admin/credit-card-invoices/manage")
    invoices_manage = client.get("/admin/credit-card-invoices/manage")

    assert operations.status_code == 200
    assert 'action="/admin/credit-card-bills/upload"' not in operations.text
    assert "Importar fatura" not in operations.text
    assert invoices.status_code == 200
    assert "Importar fatura" not in invoices.text
    assert 'action="/admin/credit-card-bills/upload"' not in invoices.text
    assert "Arquivo CSV" not in invoices.text
    assert invoices_manage.status_code == 200
    assert "Administrar faturas" in invoices_manage.text
    assert "Importar fatura" in invoices_manage.text
    assert 'action="/admin/credit-card-bills/upload"' in invoices_manage.text
    assert "Arquivo CSV" in invoices_manage.text


def test_admin_bank_statement_upload_form_is_available_only_on_statement_manage_page(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session, description="EXTRATO MAR", normalized="extrato mar upload admin", amount=-25.0, transaction_kind="expense", category="Transporte")
    _login(client)

    operations = client.get("/admin/operations")
    conference = client.get("/admin/conference?period_start=2026-03-01&period_end=2026-03-31")
    statement_manage = client.get("/admin/conference/manage")

    assert operations.status_code == 200
    assert 'action="/admin/bank-statements/upload"' not in operations.text
    assert "Importar extrato" not in operations.text
    assert conference.status_code == 200
    assert 'action="/admin/bank-statements/upload"' not in conference.text
    assert "Importar extrato" not in conference.text
    assert "Administrar extratos" in conference.text
    assert statement_manage.status_code == 200
    assert "Administrar extratos" in statement_manage.text
    assert "Importar extrato" in statement_manage.text
    assert 'action="/admin/bank-statements/upload"' in statement_manage.text
    assert "Arquivo OFX" in statement_manage.text


def test_admin_can_upload_bank_statement(client, db_session, monkeypatch, sample_ofx_file):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _login(client)

    with sample_ofx_file.open("rb") as handle:
        upload = client.post(
            "/admin/bank-statements/upload",
            data={
                "reference_id": "admin-ofx-mar-2026",
                "return_to": "/admin/conference/manage",
            },
            files={"file": (sample_ofx_file.name, handle, "application/octet-stream")},
            follow_redirects=False,
        )

    assert upload.status_code == 303
    assert upload.headers["location"].startswith("/admin/conference?")
    assert "period_start=2026-03-07" in upload.headers["location"]
    assert "period_end=2026-03-07" in upload.headers["location"]

    conference = client.get(upload.headers["location"])

    assert conference.status_code == 200
    assert "Visão de Extrato" in conference.text
    assert "07/03/2026" in conference.text
    assert db_session.scalar(select(SourceFile).where(SourceFile.source_type == "bank_statement")) is not None
    assert db_session.scalar(select(Transaction).where(Transaction.source_type == "bank_statement")) is not None
    assert db_session.scalar(select(AnalysisRun).where(AnalysisRun.period_start == date(2026, 3, 7))) is not None


def test_admin_manual_edit_creates_audit_and_rule(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(db_session)
    _login(client)

    resp = client.post(
        f"/admin/transactions/{tx.id}/update",
        data={
            "category": "Outros",
            "transaction_kind": "expense",
            "notes": "ajuste manual",
            "return_to": "/admin/transactions",
            "rule_action": "create",
            "rule_pattern": "uber",
            "rule_match_mode": "contains",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.refresh(tx)
    assert tx.category == "Outros"
    assert tx.manual_override is True

    rule = db_session.scalar(select(CategorizationRule).where(CategorizationRule.pattern == "uber"))
    assert rule is not None

    audit = db_session.scalar(select(TransactionAuditLog).where(TransactionAuditLog.transaction_id == tx.id))
    assert audit is not None
    assert audit.origin == "manual_edit"
    assert audit.new_category == "Outros"


def test_admin_reapply_rules_updates_transactions_and_runs_analysis(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(db_session, description="UBER BV", normalized="uber bv")
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="uber",
            category_name="Transporte",
            kind_mode="flow",
            priority=0,
            is_active=True,
        )
    )
    db_session.commit()
    _login(client)

    preview = client.post(
        "/admin/reapply/preview",
        data={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    )
    assert preview.status_code == 200
    assert "v\u00e3o mudar" in preview.text

    resp = client.post(
        "/admin/reapply",
        data={
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "run_analysis_after": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.refresh(tx)
    assert tx.category == "Transporte"
    assert tx.categorization_method == "rule"

    audit = db_session.scalar(
        select(TransactionAuditLog).where(TransactionAuditLog.transaction_id == tx.id).order_by(TransactionAuditLog.id.desc())
    )
    assert audit is not None
    assert audit.origin == "admin_reapply"

    run = db_session.scalar(select(AnalysisRun))
    assert run is not None


def test_admin_reapply_preview_and_apply_can_limit_selected_rules(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(db_session, description="UBER CABIFY", normalized="uber cabify")
    uber_rule = CategorizationRule(
        rule_type="contains",
        pattern="uber",
        category_name="Transporte",
        kind_mode="flow",
        priority=0,
        is_active=True,
    )
    cabify_rule = CategorizationRule(
        rule_type="contains",
        pattern="cabify",
        category_name="Outros",
        kind_mode="flow",
        priority=1,
        is_active=True,
    )
    db_session.add_all([uber_rule, cabify_rule])
    db_session.commit()
    _login(client)

    preview = client.post(
        "/admin/reapply/preview",
        data={
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "selected_rule_ids": str(cabify_rule.id),
        },
    )
    assert preview.status_code == 200
    assert "N\u00e3o Categorizado" in preview.text
    assert "Outros" in preview.text
    assert "cabify" in preview.text

    resp = client.post(
        "/admin/reapply",
        data={
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "selected_rule_ids": str(cabify_rule.id),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.refresh(tx)
    assert tx.category == "Outros"


def test_admin_reapply_can_skip_specific_transactions(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    first_tx = _seed_transaction(db_session, description="CABIFY A", normalized="cabify a")
    second_tx = _seed_transaction(db_session, description="CABIFY B", normalized="cabify b")
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="cabify",
            category_name="Outros",
            kind_mode="flow",
            priority=0,
            is_active=True,
        )
    )
    db_session.commit()
    _login(client)

    resp = client.post(
        "/admin/reapply",
        data={
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "selected_transaction_ids": str(first_tx.id),
            "selection_present": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.refresh(first_tx)
    db_session.refresh(second_tx)
    assert first_tx.category == "Outros"
    assert second_tx.category != "Outros"


def test_admin_transactions_first_load_shows_latest_closed_month_records(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    monkeypatch.setattr(
        "app.web.routes.admin.transactions.latest_closed_month_with_transactions",
        lambda db: (date(2026, 2, 1), date(2026, 2, 28)),
    )
    _seed_categories(db_session)
    feb_tx = _seed_transaction(db_session, description="UBER FEVEREIRO", normalized="uber fevereiro")
    feb_tx.transaction_date = date(2026, 2, 10)
    feb_tx.competence_month = "2026-02"
    march_tx = _seed_transaction(db_session, description="UBER MARCO", normalized="uber marco")
    march_tx.transaction_date = date(2026, 3, 10)
    march_tx.competence_month = "2026-03"
    db_session.commit()

    _login(client)
    response = client.get("/admin/transactions")

    assert response.status_code == 200
    assert "UBER FEVEREIRO" in response.text
    assert "UBER MARCO" not in response.text
    assert "2026-02-01" in response.text
    assert "2026-02-28" in response.text


def test_admin_reapply_without_period_uses_whole_base(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    feb_tx = _seed_transaction(db_session, description="CABIFY FEV", normalized="cabify fev")
    feb_tx.transaction_date = date(2026, 2, 10)
    feb_tx.competence_month = "2026-02"
    mar_tx = _seed_transaction(db_session, description="CABIFY MAR", normalized="cabify mar")
    mar_tx.transaction_date = date(2026, 3, 10)
    mar_tx.competence_month = "2026-03"
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="cabify",
            category_name="Outros",
            kind_mode="flow",
            priority=0,
            is_active=True,
        )
    )
    db_session.commit()
    _login(client)

    preview = client.post("/admin/reapply/preview", data={})
    assert preview.status_code == 200
    assert "CABIFY FEV" in preview.text
    assert "CABIFY MAR" in preview.text

    resp = client.post(
        "/admin/reapply",
        data={
            "selected_transaction_ids": [str(feb_tx.id), str(mar_tx.id)],
            "selection_present": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.refresh(feb_tx)
    db_session.refresh(mar_tx)
    assert feb_tx.category == "Outros"
    assert mar_tx.category == "Outros"



def test_admin_reapply_preview_links_to_rule_editor(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session, description="UBER EDIT RULE", normalized="uber edit rule")
    rule = CategorizationRule(
        rule_type="contains",
        pattern="uber",
        category_name="Transporte",
        kind_mode="flow",
        priority=0,
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()
    _login(client)

    reapply_page = client.get("/admin/reapply")
    assert reapply_page.status_code == 200
    assert "data-loading-button" in reapply_page.text

    preview = client.post("/admin/reapply/preview", data={})
    assert preview.status_code == 200
    assert f'/admin/rules?open_rule_id={rule.id}#rule-{rule.id}' in preview.text

    rules_page = client.get(f"/admin/rules?open_rule_id={rule.id}")
    assert rules_page.status_code == 200
    assert f'id="rule-{rule.id}" class="rule-row accordion" open' in rules_page.text


def test_admin_reapply_preserves_existing_category_when_no_better_match(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(
        db_session,
        description="LOJA SEM REGRA",
        normalized="loja sem regra",
        category="Outros",
        transaction_kind="expense",
    )
    _login(client)

    reapply_page = client.get("/admin/reapply")
    assert reapply_page.status_code == 200
    assert "data-loading-button" in reapply_page.text

    preview = client.post("/admin/reapply/preview", data={})
    assert preview.status_code == 200
    assert "LOJA SEM REGRA" not in preview.text

    resp = client.post("/admin/reapply", data={}, follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(tx)
    assert tx.category == "Outros"
    assert tx.transaction_kind == "expense"


def test_admin_reapply_can_apply_valid_fallback_without_manual_rule(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(
        db_session,
        description="TED 102 0001 EDUARDO K C",
        normalized="ted 102 0001 eduardo k c",
        category="Outros",
        transaction_kind="expense",
    )
    _login(client)

    reapply_page = client.get("/admin/reapply")
    assert reapply_page.status_code == 200
    assert "data-loading-button" in reapply_page.text

    preview = client.post("/admin/reapply/preview", data={})
    assert preview.status_code == 200
    assert "TED 102 0001 EDUARDO K C" in preview.text
    assert "Transfer\u00eancias" in preview.text

    resp = client.post(
        "/admin/reapply",
        data={
            "selected_transaction_ids": str(tx.id),
            "selection_present": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.refresh(tx)
    assert tx.category == "Transfer\u00eancias"
    assert tx.transaction_kind == "transfer"


def test_admin_reapply_only_degrades_to_uncategorized_when_flag_is_enabled(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(
        db_session,
        description="COMPRA SEM MATCH",
        normalized="compra sem match",
        category="Outros",
        transaction_kind="expense",
    )
    _login(client)

    preview_without_flag = client.post("/admin/reapply/preview", data={})
    assert preview_without_flag.status_code == 200
    assert "COMPRA SEM MATCH" not in preview_without_flag.text

    preview_with_flag = client.post(
        "/admin/reapply/preview",
        data={"allow_degrade_to_uncategorized": "true"},
    )
    assert preview_with_flag.status_code == 200
    assert "COMPRA SEM MATCH" in preview_with_flag.text

    resp = client.post(
        "/admin/reapply",
        data={
            "allow_degrade_to_uncategorized": "true",
            "selected_transaction_ids": str(tx.id),
            "selection_present": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.refresh(tx)
    assert tx.category in {"N\u00e3o Categorizado", "Nao Categorizado"}


def test_admin_analysis_page_shows_empty_state_and_navigation(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session, description="SALARIO MAR", normalized="salario mar", amount=5000.0, transaction_kind="income", category="Sal\u00e1rio")
    _login(client)

    response = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Gerar nova análise" in response.text
    assert "Composição da leitura" in response.text
    assert "Conta no recorte" in response.text
    assert "Itens de fatura considerados" in response.text
    assert "data-loading-button" in response.text
    assert "Aplicando..." in response.text
    assert "Gerando análise..." in response.text


def test_admin_analysis_page_can_generate_and_render_latest_analysis(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session, description="SALARIO MAR", normalized="salario mar", amount=5000.0, transaction_kind="income", category="Sal\u00e1rio")
    _seed_transaction(db_session, description="UBER MAR", normalized="uber mar", amount=-120.0, transaction_kind="expense", category="Transporte")
    _seed_transaction(db_session, description="SEM CATEGORIA", normalized="sem categoria", amount=-80.0, transaction_kind="expense", category="N\u00e3o Categorizado")
    _login(client)

    run_resp = client.post(
        "/admin/analysis/run",
        data={
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "return_to": "/admin/analysis?period_start=2026-03-01&period_end=2026-03-31",
        },
        follow_redirects=False,
    )
    assert run_resp.status_code == 303

    page = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")
    assert page.status_code == 200
    assert "Visão conciliada" in page.text
    assert "Composição da leitura" in page.text
    assert "Conta no recorte" in page.text
    assert "Itens de fatura considerados" in page.text
    assert "Faturas do período" in page.text
    assert 'class="analysis-period-bar"' in page.text
    assert "Visão de Extrato" in page.text
    assert "Análise determinística renderizada" not in page.text
    assert "Visão bruta de apoio" not in page.text
    assert "chart.js" in page.text.lower()
    assert "conciliated-cashflow-chart" in page.text
    assert "conciliated-categories-chart" in page.text
    assert "R$" in page.text

    run = db_session.scalar(select(AnalysisRun).where(AnalysisRun.period_start == date(2026, 3, 1)))
    assert run is not None
    assert run.html_output
    assert "An\u00e1lise financeira determin\u00edstica" in run.html_output


def test_admin_conference_page_shows_auxiliary_conciliation_signals(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(
        db_session,
        description="PAGAMENTO FATURA MAR",
        normalized="pagamento fatura mar",
        amount=-120.0,
        transaction_kind="expense",
        category="Pagamento de Fatura",
    )
    _seed_conciliated_bank_payment(db_session, tx=tx)
    _login(client)

    response = client.get("/admin/conference/technical?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Auditoria técnica do extrato" in response.text
    assert "Sinais de conciliação" in response.text
    assert "Fora da leitura principal" in response.text
    assert "Pagamentos conciliados" in response.text
    assert "Créditos técnicos de fatura" in response.text
    assert "Nenhuma análise persistida para o recorte" in response.text



def test_admin_analysis_page_shows_conciliated_category_breakdown(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session, description="SALARIO MAR", normalized="salario mar", amount=5000.0, transaction_kind="income", category="Sal\u00e1rio")
    _seed_transaction(db_session, description="ALUGUEL MAR", normalized="aluguel mar", amount=-1800.0, transaction_kind="expense", category="Moradia")
    payment = _seed_transaction(
        db_session,
        description="PAGAMENTO FATURA MAR",
        normalized="pagamento fatura mar",
        amount=-120.45,
        transaction_kind="expense",
        category="Pagamento de Fatura",
    )

    invoice = _seed_credit_card_invoice(db_session, status="pending_review")
    invoice_items = db_session.scalars(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id).order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    invoice_items[0].category = "Supermercado"
    invoice_items[0].categorization_method = "manual"
    invoice_items[0].categorization_confidence = 1.0
    invoice_items[1].category = "Educa\u00e7\u00e3o"
    invoice_items[1].categorization_method = "manual"
    invoice_items[1].categorization_confidence = 1.0
    credit_item = CreditCardInvoiceItem(
        invoice_id=invoice.id,
        purchase_date=date(2026, 3, 8),
        description_raw="DESCONTO NA FATURA - PO",
        description_normalized="desconto na fatura - po",
        amount_brl="-10.00",
        installment_current=None,
        installment_total=None,
        is_installment=False,
        derived_note="credito tecnico",
        external_row_hash=f"row-hash-{invoice.id}-credit",
    )
    payment_item = CreditCardInvoiceItem(
        invoice_id=invoice.id,
        purchase_date=date(2026, 3, 9),
        description_raw="PAGAMENTO EFETUADO",
        description_normalized="pagamento efetuado",
        amount_brl="-120.45",
        installment_current=None,
        installment_total=None,
        is_installment=False,
        derived_note="pagamento tecnico",
        external_row_hash=f"row-hash-{invoice.id}-payment",
    )
    db_session.add_all([credit_item, payment_item])
    db_session.flush()
    conciliation = CreditCardInvoiceConciliation(
        invoice_id=invoice.id,
        status="conciliated",
        gross_amount_brl="130.45",
        invoice_credit_total_brl="10.00",
        bank_payment_total_brl="120.45",
        conciliated_total_brl="130.45",
        remaining_balance_brl="0.00",
    )
    db_session.add(conciliation)
    db_session.flush()
    db_session.add_all(
        [
            CreditCardInvoiceConciliationItem(
                conciliation_id=conciliation.id,
                item_type="invoice_credit",
                amount_brl="10.00",
                bank_transaction_id=None,
                invoice_item_id=credit_item.id,
                notes="credito tecnico",
            ),
            CreditCardInvoiceConciliationItem(
                conciliation_id=conciliation.id,
                item_type="bank_payment",
                amount_brl="120.45",
                bank_transaction_id=payment.id,
                invoice_item_id=None,
                notes="pagamento conciliado",
            ),
        ]
    )
    db_session.commit()
    _login(client)

    response = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Composição da leitura" in response.text
    assert "Supermercado" in response.text
    assert "Educa\u00e7\u00e3o" in response.text
    assert "Moradia" in response.text
    assert "Créditos de fatura" in response.text
    assert "Pagamentos bancários conciliados removidos" in response.text


def test_admin_analysis_page_anchors_card_consumption_by_purchase_date(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)

    payment = _seed_transaction(
        db_session,
        description="PAGAMENTO FATURA FEV",
        normalized="pagamento fatura fev",
        transaction_date=date(2026, 2, 18),
        amount=-800.0,
        transaction_kind="expense",
        category="Pagamento de Fatura",
    )
    invoice = _seed_credit_card_invoice(
        db_session,
        card_label="Itaú Visa final 7777",
        card_final="7777",
        billing_year=2026,
        billing_month=2,
        due_date=date(2026, 2, 20),
        closing_date=date(2026, 2, 12),
        total_amount="800.00",
        status="pending_review",
        item_specs=[
            ("SUPERMERCADO TESTE", "900.00", date(2026, 1, 28)),
            ("DESCONTO NA FATURA - PO", "-100.00", date(2026, 1, 29)),
            ("PAGAMENTO EFETUADO", "-800.00", date(2026, 2, 18)),
        ],
    )
    invoice_items = db_session.scalars(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id).order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    invoice_items[0].category = "Supermercado"
    invoice_items[0].categorization_method = "manual"
    invoice_items[0].categorization_confidence = 1.0
    conciliation = CreditCardInvoiceConciliation(
        invoice_id=invoice.id,
        status="conciliated",
        gross_amount_brl="900.00",
        invoice_credit_total_brl="100.00",
        bank_payment_total_brl="800.00",
        conciliated_total_brl="900.00",
        remaining_balance_brl="0.00",
    )
    db_session.add(conciliation)
    db_session.flush()
    db_session.add_all(
        [
            CreditCardInvoiceConciliationItem(
                conciliation_id=conciliation.id,
                item_type="invoice_credit",
                amount_brl="100.00",
                bank_transaction_id=None,
                invoice_item_id=invoice_items[1].id,
                notes="credito tecnico",
            ),
            CreditCardInvoiceConciliationItem(
                conciliation_id=conciliation.id,
                item_type="bank_payment",
                amount_brl="800.00",
                bank_transaction_id=payment.id,
                invoice_item_id=None,
                notes="pagamento conciliado",
            ),
        ]
    )
    db_session.commit()
    _login(client)

    january = client.get("/admin/analysis?period_start=2026-01-01&period_end=2026-01-31")
    february = client.get("/admin/analysis?period_start=2026-02-01&period_end=2026-02-28")

    assert january.status_code == 200
    assert "Composição da leitura" in january.text
    assert "Supermercado" in january.text
    assert "Créditos de fatura" in january.text
    assert february.status_code == 200
    assert "Composição da leitura" in february.text


def test_admin_analysis_page_shows_consumption_based_alerts_and_actions(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)

    _seed_transaction(
        db_session,
        description="SALARIO JAN",
        normalized="salario jan",
        transaction_date=date(2026, 1, 5),
        amount=5000.0,
        transaction_kind="income",
        category="Sal\u00e1rio",
    )
    payment = _seed_transaction(
        db_session,
        description="PAGAMENTO FATURA FEV",
        normalized="pagamento fatura fev",
        transaction_date=date(2026, 2, 18),
        amount=-800.0,
        transaction_kind="expense",
        category="Pagamento de Fatura",
    )
    invoice = _seed_credit_card_invoice(
        db_session,
        card_label="Ita\u00fa Visa final 7878",
        card_final="7878",
        billing_year=2026,
        billing_month=2,
        due_date=date(2026, 2, 20),
        closing_date=date(2026, 2, 12),
        total_amount="800.00",
        status="pending_review",
        item_specs=[
            ("SUPERMERCADO TESTE", "900.00", date(2026, 1, 28)),
            ("DESCONTO NA FATURA - PO", "-100.00", date(2026, 1, 29)),
            ("PAGAMENTO EFETUADO", "-800.00", date(2026, 2, 18)),
        ],
    )
    invoice_items = db_session.scalars(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id).order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    invoice_items[0].category = "Supermercado"
    invoice_items[0].categorization_method = "manual"
    invoice_items[0].categorization_confidence = 1.0
    conciliation = CreditCardInvoiceConciliation(
        invoice_id=invoice.id,
        status="conciliated",
        gross_amount_brl="900.00",
        invoice_credit_total_brl="100.00",
        bank_payment_total_brl="800.00",
        conciliated_total_brl="900.00",
        remaining_balance_brl="0.00",
    )
    db_session.add(conciliation)
    db_session.flush()
    db_session.add_all(
        [
            CreditCardInvoiceConciliationItem(
                conciliation_id=conciliation.id,
                item_type="invoice_credit",
                amount_brl="100.00",
                bank_transaction_id=None,
                invoice_item_id=invoice_items[1].id,
                notes="credito tecnico",
            ),
            CreditCardInvoiceConciliationItem(
                conciliation_id=conciliation.id,
                item_type="bank_payment",
                amount_brl="800.00",
                bank_transaction_id=payment.id,
                invoice_item_id=None,
                notes="pagamento conciliado",
            ),
        ]
    )
    db_session.commit()
    run_analysis(db_session, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), trigger_source_file_id=None)
    run_analysis(db_session, period_start=date(2026, 2, 1), period_end=date(2026, 2, 28), trigger_source_file_id=None)
    _login(client)

    january = client.get("/admin/analysis?period_start=2026-01-01&period_end=2026-01-31")
    february = client.get("/admin/analysis?period_start=2026-02-01&period_end=2026-02-28")

    assert january.status_code == 200
    assert "Composição da leitura" in january.text
    assert "Conta no recorte" in january.text
    assert "Itens de fatura considerados" in january.text
    assert "Revisar a categoria Supermercado" not in january.text
    assert february.status_code == 200
    assert "Revisar a categoria Supermercado" not in february.text


def test_admin_analysis_page_shows_conciliated_category_history(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)

    def seed_conciliated_month(
        *,
        billing_year: int,
        billing_month: int,
        moradia_amount: float,
        market_amount: str,
        education_amount: str | None,
        credit_amount: str,
        payment_amount: float,
        card_final: str,
    ):
        _seed_transaction(
            db_session,
            description=f"SALARIO {billing_month:02d}/{billing_year}",
            normalized=f"salario {billing_month:02d} {billing_year}",
            transaction_date=date(billing_year, billing_month, 5),
            amount=5000.0,
            transaction_kind="income",
            category="Salário",
        )
        _seed_transaction(
            db_session,
            description=f"ALUGUEL {billing_month:02d}/{billing_year}",
            normalized=f"aluguel {billing_month:02d} {billing_year}",
            transaction_date=date(billing_year, billing_month, 8),
            amount=-moradia_amount,
            transaction_kind="expense",
            category="Moradia",
        )
        payment = _seed_transaction(
            db_session,
            description=f"PAGAMENTO FATURA {billing_month:02d}/{billing_year}",
            normalized=f"pagamento fatura {billing_month:02d} {billing_year}",
            transaction_date=date(billing_year, billing_month, 18),
            amount=-payment_amount,
            transaction_kind="expense",
            category="Pagamento de Fatura",
        )
        item_specs = [("SUPERMERCADO TESTE", market_amount)]
        if education_amount is not None:
            item_specs.append(("CURSO ONLINE", education_amount))
        invoice = _seed_credit_card_invoice(
            db_session,
            card_label=f"Itaú Visa final {card_final}",
            card_final=card_final,
            billing_year=billing_year,
            billing_month=billing_month,
            due_date=date(billing_year, billing_month, 20),
            closing_date=date(billing_year, billing_month, 12),
            total_amount=f"{float(market_amount) + (float(education_amount) if education_amount else 0.0):.2f}",
            status="pending_review",
            item_specs=item_specs,
        )
        invoice_items = db_session.scalars(
            select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id).order_by(CreditCardInvoiceItem.id.asc())
        ).all()
        invoice_items[0].category = "Supermercado"
        invoice_items[0].categorization_method = "manual"
        invoice_items[0].categorization_confidence = 1.0
        if education_amount is not None:
            invoice_items[1].category = "Educação"
            invoice_items[1].categorization_method = "manual"
            invoice_items[1].categorization_confidence = 1.0
        credit_item = CreditCardInvoiceItem(
            invoice_id=invoice.id,
            purchase_date=date(billing_year, billing_month, 9),
            description_raw="DESCONTO NA FATURA - PO",
            description_normalized="desconto na fatura - po",
            amount_brl=f"-{credit_amount}",
            installment_current=None,
            installment_total=None,
            is_installment=False,
            derived_note="credito tecnico",
            external_row_hash=f"row-hash-{invoice.id}-credit-history",
        )
        db_session.add(credit_item)
        db_session.flush()
        gross_amount = float(market_amount) + (float(education_amount) if education_amount else 0.0)
        conciliation = CreditCardInvoiceConciliation(
            invoice_id=invoice.id,
            status="conciliated",
            gross_amount_brl=f"{gross_amount:.2f}",
            invoice_credit_total_brl=credit_amount,
            bank_payment_total_brl=f"{payment_amount:.2f}",
            conciliated_total_brl=f"{gross_amount:.2f}",
            remaining_balance_brl="0.00",
        )
        db_session.add(conciliation)
        db_session.flush()
        db_session.add_all(
            [
                CreditCardInvoiceConciliationItem(
                    conciliation_id=conciliation.id,
                    item_type="invoice_credit",
                    amount_brl=credit_amount,
                    bank_transaction_id=None,
                    invoice_item_id=credit_item.id,
                    notes="credito tecnico",
                ),
                CreditCardInvoiceConciliationItem(
                    conciliation_id=conciliation.id,
                    item_type="bank_payment",
                    amount_brl=f"{payment_amount:.2f}",
                    bank_transaction_id=payment.id,
                    invoice_item_id=None,
                    notes="pagamento conciliado",
                ),
            ]
        )
        db_session.commit()

    seed_conciliated_month(
        billing_year=2025,
        billing_month=3,
        moradia_amount=1500.0,
        market_amount="650.00",
        education_amount="120.00",
        credit_amount="30.00",
        payment_amount=740.0,
        card_final="2525",
    )
    seed_conciliated_month(
        billing_year=2026,
        billing_month=2,
        moradia_amount=1600.0,
        market_amount="700.00",
        education_amount=None,
        credit_amount="50.00",
        payment_amount=650.0,
        card_final="2626",
    )
    seed_conciliated_month(
        billing_year=2026,
        billing_month=3,
        moradia_amount=1800.0,
        market_amount="900.00",
        education_amount="300.00",
        credit_amount="100.00",
        payment_amount=1100.0,
        card_final="3636",
    )
    _login(client)

    response = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Categorias conciliadas em 12 meses" in response.text
    assert "mar/2026" in response.text
    assert "fev/2026" in response.text
    assert "Supermercado" in response.text
    assert "conciliated-categories-chart" in response.text


def test_admin_analysis_page_marks_category_history_gap_as_sem_base(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)

    def seed_conciliated_month(
        *,
        billing_year: int,
        billing_month: int,
        moradia_amount: float,
        market_amount: str,
        credit_amount: str,
        payment_amount: float,
        card_final: str,
    ):
        _seed_transaction(
            db_session,
            description=f"SALARIO {billing_month:02d}/{billing_year}",
            normalized=f"salario {billing_month:02d} {billing_year}",
            transaction_date=date(billing_year, billing_month, 5),
            amount=5000.0,
            transaction_kind="income",
            category="Salário",
        )
        _seed_transaction(
            db_session,
            description=f"ALUGUEL {billing_month:02d}/{billing_year}",
            normalized=f"aluguel {billing_month:02d} {billing_year}",
            transaction_date=date(billing_year, billing_month, 8),
            amount=-moradia_amount,
            transaction_kind="expense",
            category="Moradia",
        )
        payment = _seed_transaction(
            db_session,
            description=f"PAGAMENTO FATURA {billing_month:02d}/{billing_year}",
            normalized=f"pagamento fatura {billing_month:02d} {billing_year}",
            transaction_date=date(billing_year, billing_month, 18),
            amount=-payment_amount,
            transaction_kind="expense",
            category="Pagamento de Fatura",
        )
        invoice = _seed_credit_card_invoice(
            db_session,
            card_label=f"Itaú Visa final {card_final}",
            card_final=card_final,
            billing_year=billing_year,
            billing_month=billing_month,
            due_date=date(billing_year, billing_month, 20),
            closing_date=date(billing_year, billing_month, 12),
            total_amount=market_amount,
            status="pending_review",
            item_specs=[("SUPERMERCADO TESTE", market_amount)],
        )
        invoice_item = db_session.scalar(
            select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id)
        )
        assert invoice_item is not None
        invoice_item.category = "Supermercado"
        invoice_item.categorization_method = "manual"
        invoice_item.categorization_confidence = 1.0
        credit_item = CreditCardInvoiceItem(
            invoice_id=invoice.id,
            purchase_date=date(billing_year, billing_month, 9),
            description_raw="DESCONTO NA FATURA - PO",
            description_normalized="desconto na fatura - po",
            amount_brl=f"-{credit_amount}",
            installment_current=None,
            installment_total=None,
            is_installment=False,
            derived_note="credito tecnico",
            external_row_hash=f"row-hash-{invoice.id}-credit-gap",
        )
        db_session.add(credit_item)
        db_session.flush()
        conciliation = CreditCardInvoiceConciliation(
            invoice_id=invoice.id,
            status="conciliated",
            gross_amount_brl=market_amount,
            invoice_credit_total_brl=credit_amount,
            bank_payment_total_brl=f"{payment_amount:.2f}",
            conciliated_total_brl=market_amount,
            remaining_balance_brl="0.00",
        )
        db_session.add(conciliation)
        db_session.flush()
        db_session.add_all(
            [
                CreditCardInvoiceConciliationItem(
                    conciliation_id=conciliation.id,
                    item_type="invoice_credit",
                    amount_brl=credit_amount,
                    bank_transaction_id=None,
                    invoice_item_id=credit_item.id,
                    notes="credito tecnico",
                ),
                CreditCardInvoiceConciliationItem(
                    conciliation_id=conciliation.id,
                    item_type="bank_payment",
                    amount_brl=f"{payment_amount:.2f}",
                    bank_transaction_id=payment.id,
                    invoice_item_id=None,
                    notes="pagamento conciliado",
                ),
            ]
        )
        db_session.commit()

    seed_conciliated_month(
        billing_year=2025,
        billing_month=1,
        moradia_amount=1400.0,
        market_amount="470.00",
        credit_amount="20.00",
        payment_amount=450.0,
        card_final="1515",
    )
    seed_conciliated_month(
        billing_year=2026,
        billing_month=1,
        moradia_amount=1550.0,
        market_amount="530.00",
        credit_amount="30.00",
        payment_amount=500.0,
        card_final="1616",
    )
    seed_conciliated_month(
        billing_year=2026,
        billing_month=3,
        moradia_amount=1800.0,
        market_amount="900.00",
        credit_amount="80.00",
        payment_amount=820.0,
        card_final="3636",
    )
    _login(client)

    response = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Categorias conciliadas em 12 meses" in response.text
    assert "Supermercado" in response.text
    assert "conciliated-categories-chart" in response.text


def test_admin_analysis_page_supports_legacy_payload_without_conciliated_month(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session, description="SALARIO MAR", normalized="salario mar", amount=5000.0, transaction_kind="income", category="Sal\u00e1rio")

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
            "note": "legacy test",
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
    _login(client)

    response = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Visão conciliada" in response.text
    assert "Composição da leitura" in response.text
    assert "Conta no recorte" in response.text
    assert "Visão bruta de apoio" not in response.text
    assert "legacy html" not in response.text

def test_admin_summary_page_supports_legacy_payload_without_extended_primary_summary(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="SALARIO MAR",
        normalized="salario mar home legacy",
        amount=5000.0,
        transaction_kind="income",
        category="Sal\u00e1rio",
    )

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
            "note": "legacy home test",
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
            prompt="legacy_summary",
            html_output="<p>legacy html</p>",
            status="success",
        )
    )
    db_session.commit()
    _login(client)

    response = client.get("/admin?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Receitas reais" in response.text
    assert "Entradas totais:" in response.text
    assert "Saídas totais:" in response.text


def test_admin_transactions_page_marks_conciliated_bank_payment(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(
        db_session,
        description="PAGAMENTO FATURA MAR",
        normalized="pagamento fatura mar",
        amount=-120.0,
        transaction_kind="expense",
        category="Pagamento de Fatura",
    )
    _seed_conciliated_bank_payment(db_session, tx=tx)
    _login(client)

    response = client.get("/admin/transactions?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "bank_payment conciliado" in response.text
    assert "status conciliated" in response.text


def test_admin_transaction_detail_page_uses_detail_archetype(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    tx = _seed_transaction(
        db_session,
        description="ALUGUEL DETALHE",
        normalized="aluguel detalhe",
        amount=-1800.0,
        transaction_kind="expense",
        category="Moradia",
    )
    _login(client)

    response = client.get(f"/admin/transactions/{tx.id}")

    assert response.status_code == 200
    assert "Painel do lan" in response.text
    assert "O que d" in response.text
    assert "Editar lan" in response.text
    assert "Criar categoria rapidamente" in response.text
    assert "Reclassifica" in response.text


def test_admin_loading_buttons_are_exposed_in_reapply_and_analysis(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session)
    _login(client)

    reapply_page = client.get("/admin/reapply")
    assert reapply_page.status_code == 200
    assert "data-loading-button" in reapply_page.text

    analysis_page = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")
    assert analysis_page.status_code == 200
    assert analysis_page.text.count("data-loading-button") >= 2
    assert "Aplicando..." in analysis_page.text
    assert "Gerando análise..." in analysis_page.text





def _seed_credit_card_invoice(
    db_session,
    *,
    card_label: str = "Ita\u00fa Visa final 1234",
    card_final: str = "1234",
    billing_year: int = 2026,
    billing_month: int = 3,
    total_amount: str = "130.45",
    status: str = "imported",
    notes: str | None = "Fatura mar\u00e7o",
    due_date: date | None = None,
    closing_date: date | None = None,
    item_specs: list[tuple[str, str] | tuple[str, str, date]] | None = None,
):
    card = CreditCard(
        issuer="itau",
        card_label=card_label,
        card_final=card_final,
        brand="Visa",
        is_active=True,
    )
    db_session.add(card)
    db_session.flush()

    source_file = SourceFile(
        source_type="credit_card_bill",
        file_name=f"invoice-{card_final}-{billing_year}{billing_month:02d}.csv",
        file_path=f"upload://invoice-{card_final}-{billing_year}{billing_month:02d}.csv",
        file_hash=f"invoice-hash-{card_final}-{billing_year}{billing_month:02d}-{status}",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()

    invoice = CreditCardInvoice(
        source_file_id=source_file.id,
        card_id=card.id,
        issuer=card.issuer,
        card_final=card.card_final,
        billing_year=billing_year,
        billing_month=billing_month,
        due_date=due_date or date(billing_year, billing_month, 20),
        closing_date=closing_date or date(billing_year, billing_month, 12),
        total_amount_brl=total_amount,
        source_file_name=source_file.file_name,
        source_file_hash=source_file.file_hash,
        notes=notes,
        import_status=status,
    )
    db_session.add(invoice)
    db_session.flush()

    resolved_item_specs = item_specs or [
        ("SUPERMERCADO TESTE", "100.00"),
        ("CURSO PARCELADO", "30.45"),
    ]
    items = []
    for index, item_spec in enumerate(resolved_item_specs, start=1):
        if len(item_spec) == 3:
            description_raw, amount_brl, purchase_date = item_spec
        else:
            description_raw, amount_brl = item_spec
            purchase_date = date(billing_year, billing_month, 5 if index == 1 else min(7 + index - 2, 28))
        is_course_installment = description_raw == "CURSO PARCELADO"
        items.append(
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=purchase_date,
                description_raw=description_raw,
                description_normalized=description_raw.lower(),
                amount_brl=amount_brl,
                installment_current=2 if is_course_installment else None,
                installment_total=3 if is_course_installment else None,
                is_installment=is_course_installment,
                derived_note="parcela 2/3" if is_course_installment else None,
                external_row_hash=f"row-hash-{invoice.id}-{index}",
            )
        )
    db_session.add_all(items)
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


def test_admin_credit_card_invoice_list_shows_imported_invoices(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    conciliated_invoice = _seed_credit_card_invoice(
        db_session,
        card_label="Ita\u00fa Visa final 1234",
        card_final="1234",
        status="imported",
    )
    pending_invoice = _seed_credit_card_invoice(
        db_session,
        card_label="Ita\u00fa Mastercard final 5678",
        card_final="5678",
        billing_month=1,
        status="conflict",
    )
    _seed_credit_card_invoice(
        db_session,
        card_label="Ita\u00fa Visa final 9990",
        card_final="9990",
        billing_year=2025,
        billing_month=3,
        total_amount="200.00",
        status="imported",
    )
    db_session.add(
        CreditCardInvoiceConciliation(
            invoice_id=conciliated_invoice.id,
            status="conciliated",
            gross_amount_brl="130.45",
            invoice_credit_total_brl="0.00",
            bank_payment_total_brl="130.45",
            conciliated_total_brl="130.45",
            remaining_balance_brl="0.00",
        )
    )
    db_session.commit()
    _login(client)

    response = client.get("/admin/credit-card-invoices?selection_mode=custom&period_start=2026-01-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Visão de Faturas" in response.text
    assert "12 meses de fatura" in response.text
    assert "Categorias de fatura" in response.text
    assert "invoice-monthly-chart" in response.text
    assert "invoice-categories-chart" in response.text
    assert "Ita\u00fa Visa final 1234" in response.text
    assert "Itens de fatura" in response.text
    assert "Faturas do recorte" in response.text
    assert "Data da fatura" in response.text
    assert "Concilia" in response.text
    assert "R$ 130,45" in response.text
    assert "03/2026" in response.text
    assert "12/03/2026" in response.text
    assert "20/03/2026" in response.text
    assert "pending_review" in response.text
    assert "conciliated" in response.text
    assert f'/admin/credit-card-invoices/{pending_invoice.id}#invoice-conciliation-section' in response.text


def test_admin_operation_and_configuration_pages_show_shared_archetype(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(
        db_session,
        description="OPERACIONAL BASE",
        normalized="operacional base",
        transaction_date=date(2026, 3, 9),
        amount=-45.0,
        transaction_kind="expense",
        category="Transporte",
    )
    _seed_credit_card_invoice(db_session, card_label="Itaú Visa final 1111", card_final="1111", status="imported")
    _login(client)

    operations = client.get("/admin/operations")
    transactions = client.get("/admin/transactions")
    transactions_bulk = client.get("/admin/transactions/bulk")
    invoices = client.get("/admin/credit-card-invoices")
    invoices_manage = client.get("/admin/credit-card-invoices/manage")
    rules = client.get("/admin/rules")
    categories = client.get("/admin/categories")
    categories_manage = client.get("/admin/categories/manage")
    reapply = client.get("/admin/reapply")

    assert operations.status_code == 200
    assert "Painel operacional do admin" in operations.text
    assert "Entradas rápidas do hub" in operations.text

    assert transactions.status_code == 200
    assert "Base operacional de lançamentos" in transactions.text
    assert "Tabela operacional da base" in transactions.text
    assert "Abrir ações em lote" in transactions.text
    assert "Aplicar aos selecionados" not in transactions.text
    assert "Como ler esta página" not in transactions.text

    assert transactions_bulk.status_code == 200
    assert "Ações em lote" in transactions_bulk.text
    assert "Aplicar aos selecionados" in transactions_bulk.text
    assert "Voltar para lançamentos" in transactions_bulk.text

    assert invoices.status_code == 200
    assert "Painel principal das faturas" not in invoices.text
    assert "Atalhos de trabalho" not in invoices.text
    assert "Itens de fatura" in invoices.text
    assert "Faturas do recorte" in invoices.text
    assert "Importar fatura" not in invoices.text

    assert invoices_manage.status_code == 200
    assert "Administrar faturas" in invoices_manage.text
    assert "Importar fatura" in invoices_manage.text
    assert "Cargas feitas" in invoices_manage.text

    assert rules.status_code == 200
    assert "Painel de configuração das regras" in rules.text
    assert "Adicionar regra" in rules.text

    assert categories.status_code == 200
    assert "Composição da categoria" in categories.text
    assert "Painel de configuracao das categorias" not in categories.text
    assert "Criar categoria" not in categories.text

    assert categories_manage.status_code == 200
    assert "Administrar categorias" in categories_manage.text
    assert "Painel de configuracao das categorias" in categories_manage.text
    assert "Criar categoria" in categories_manage.text

    assert reapply.status_code == 200
    assert "Painel de reaplicação" in reapply.text
    assert "Escopo de reaplicação" in reapply.text
    assert "Como usar" not in reapply.text


def test_admin_credit_card_invoice_detail_shows_items_and_summary(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_credit_card_invoice(db_session, status="pending_review")
    _login(client)

    response = client.get(f"/admin/credit-card-invoices/{invoice.id}")

    assert response.status_code == 200
    assert "Painel da fatura" in response.text
    assert "Caminhos desta tela" in response.text
    assert f"Fatura #{invoice.id}" in response.text
    assert "pending_review" in response.text
    assert "Quantidade de lan\u00e7amentos" in response.text
    assert "Total de cobran\u00e7as" in response.text
    assert "Total de cr\u00e9ditos/descontos" in response.text
    assert "Total de pagamentos identificados" in response.text
    assert "Total composto da fatura" in response.text
    assert "Diferen\u00e7a para o total informado" in response.text
    assert "SUPERMERCADO TESTE" in response.text
    assert "CURSO PARCELADO" in response.text
    assert "parcela 2/3" in response.text
    assert "30.45" in response.text
    assert "2" in response.text
    assert "3" in response.text


def test_admin_credit_card_invoice_item_manual_category_flow_shows_preview_and_persists(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_credit_card_invoice(db_session, status="pending_review")
    item = db_session.scalar(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice.id, CreditCardInvoiceItem.description_raw == "SUPERMERCADO TESTE")
    )
    assert item is not None
    _login(client)

    detail = client.get(f"/admin/credit-card-invoices/{invoice.id}")
    assert detail.status_code == 200
    assert "Editar categoria" in detail.text

    edit_page = client.get(f"/admin/credit-card-invoices/{invoice.id}/items/{item.id}/category")
    assert edit_page.status_code == 200
    assert "Painel do item selecionado" in edit_page.text
    assert "Escopos poss" in edit_page.text
    assert "Gerar preview do impacto" in edit_page.text
    assert "Alterar somente este item" in edit_page.text
    assert "Aplicar na base" in edit_page.text
    assert "Não Categorizado" in edit_page.text

    preview = client.post(
        f"/admin/credit-card-invoices/{invoice.id}/items/{item.id}/category/preview",
        data={"category": "Outros"},
    )
    assert preview.status_code == 200
    assert "Preview antes de aplicar" in preview.text
    assert "Outros" in preview.text
    assert "Fluxo pontual" in preview.text
    assert "Confirmar alteração de categoria" in preview.text

    applied = client.post(
        f"/admin/credit-card-invoices/{invoice.id}/items/{item.id}/category/apply",
        data={"category": "Outros", "confirm_apply": "true"},
        follow_redirects=True,
    )
    assert applied.status_code == 200
    assert "Categoria do item de fatura atualizada." in applied.text
    assert "Outros" in applied.text

    db_session.expire_all()
    refreshed = db_session.get(CreditCardInvoiceItem, item.id)
    assert refreshed is not None
    assert refreshed.category == "Outros"
    assert refreshed.categorization_method == "manual"


def test_admin_credit_card_invoice_item_apply_to_base_shows_preview_and_persists_rule(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_credit_card_invoice(db_session, status="pending_review")
    second_invoice = _seed_credit_card_invoice(
        db_session,
        card_label="Itaú Visa final 5678",
        card_final="5678",
        billing_month=4,
        total_amount="130.45",
        status="conciliated",
    )
    first_item = db_session.scalar(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice.id, CreditCardInvoiceItem.description_raw == "SUPERMERCADO TESTE")
    )
    second_item = db_session.scalar(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == second_invoice.id, CreditCardInvoiceItem.description_raw == "SUPERMERCADO TESTE")
    )
    assert first_item is not None
    assert second_item is not None
    _login(client)

    preview = client.post(
        f"/admin/credit-card-invoices/{invoice.id}/items/{first_item.id}/category/preview",
        data={
            "category": "Outros",
            "apply_mode": "base",
            "rule_pattern": "supermercado teste",
            "rule_match_mode": "exact_normalized",
        },
    )

    assert preview.status_code == 200
    assert "Aplicar na base" in preview.text
    assert "Preview antes de aplicar na base" in preview.text
    assert "Itens impactados" in preview.text
    assert "Distribuição atual dos itens afetados" in preview.text
    assert "Importações futuras" in preview.text
    assert "supermercado teste" in preview.text
    assert "2" in preview.text

    applied = client.post(
        f"/admin/credit-card-invoices/{invoice.id}/items/{first_item.id}/category/apply",
        data={
            "category": "Outros",
            "apply_mode": "base",
            "rule_pattern": "supermercado teste",
            "rule_match_mode": "exact_normalized",
            "confirm_apply": "true",
        },
        follow_redirects=True,
    )

    assert applied.status_code == 200
    assert "Regra aplicada na base." in applied.text

    db_session.expire_all()
    refreshed_first = db_session.get(CreditCardInvoiceItem, first_item.id)
    refreshed_second = db_session.get(CreditCardInvoiceItem, second_item.id)
    assert refreshed_first is not None
    assert refreshed_second is not None
    assert refreshed_first.category == "Outros"
    assert refreshed_second.category == "Outros"
    assert refreshed_first.categorization_method == "rule"
    assert refreshed_second.categorization_method == "rule"


def test_admin_credit_card_invoice_item_manual_category_blocks_non_eligible_item(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_credit_card_invoice(db_session, status="pending_review")
    payment_item = CreditCardInvoiceItem(
        invoice_id=invoice.id,
        purchase_date=date(2026, 3, 9),
        description_raw="PAGAMENTO EFETUADO",
        description_normalized="pagamento efetuado",
        amount_brl="-130.45",
        installment_current=None,
        installment_total=None,
        is_installment=False,
        derived_note="pagamento tecnico",
        external_row_hash=f"row-hash-{invoice.id}-payment",
    )
    db_session.add(payment_item)
    db_session.commit()
    _login(client)

    response = client.post(
        f"/admin/credit-card-invoices/{invoice.id}/items/{payment_item.id}/category/preview",
        data={"category": "Outros"},
    )

    assert response.status_code == 422
    assert "Somente itens charge aceitam categoria manual de consumo." in response.text


def test_admin_credit_card_invoice_item_manual_category_requires_explicit_confirmation(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_credit_card_invoice(db_session, status="pending_review")
    item = db_session.scalar(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice.id, CreditCardInvoiceItem.description_raw == "SUPERMERCADO TESTE")
    )
    assert item is not None
    _login(client)

    response = client.post(
        f"/admin/credit-card-invoices/{invoice.id}/items/{item.id}/category/apply",
        data={"category": "Outros"},
    )

    assert response.status_code == 422
    assert "Confirme explicitamente a alteração antes de salvar." in response.text

    db_session.expire_all()
    refreshed = db_session.get(CreditCardInvoiceItem, item.id)
    assert refreshed is not None
    assert refreshed.category in (None, "Não Categorizado")
    assert refreshed.categorization_method is None


def test_admin_credit_card_invoice_item_manual_category_rejects_invalid_category(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_credit_card_invoice(db_session, status="pending_review")
    item = db_session.scalar(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice.id, CreditCardInvoiceItem.description_raw == "SUPERMERCADO TESTE")
    )
    assert item is not None
    _login(client)

    response = client.post(
        f"/admin/credit-card-invoices/{invoice.id}/items/{item.id}/category/preview",
        data={"category": "Categoria Fantasma"},
    )

    assert response.status_code == 422
    assert "Categoria inválida ou inativa para item de fatura." in response.text


def test_admin_credit_card_invoice_detail_returns_404_for_missing_invoice(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _login(client)

    response = client.get("/admin/credit-card-invoices/999999")

    assert response.status_code == 404
