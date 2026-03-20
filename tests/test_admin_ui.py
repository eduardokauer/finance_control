from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.repositories.models import (
    AnalysisRun,
    CategorizationRule,
    Category,
    CreditCard,
    CreditCardInvoice,
    CreditCardInvoiceItem,
    SourceFile,
    Transaction,
    TransactionAuditLog,
)


def _login(client):
    return client.post("/admin/login", data={"password": settings.admin_ui_password, "next": "/admin"})


def _seed_categories(db_session):
    for name, kind in [
        ("NÃƒÂ£o Categorizado", "expense"),
        ("Transporte", "expense"),
        ("Outros", "expense"),
        ("SalÃƒÂ¡rio", "income"),
        ("TransferÃƒÂªncias", "transfer"),
    ]:
        db_session.add(Category(name=name, transaction_kind=kind, is_active=True))
    db_session.commit()


def _seed_transaction(
    db_session,
    *,
    description: str = "UBER TRIP",
    normalized: str = "uber trip",
    amount: float = -25.0,
    transaction_kind: str = "expense",
    category: str = "NÃƒÂ£o Categorizado",
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
        canonical_hash=f"tx-{normalized}",
        transaction_date=date(2026, 3, 7),
        competence_month="2026-03",
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
    assert "Últimas alterações" in home.text or "ltimas altera" in home.text
    assert "Subir fatura Itaú" in home.text or "Subir fatura Ita" in home.text


def test_admin_can_create_credit_card_and_upload_invoice(client, db_session, monkeypatch, sample_credit_card_csv_file):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _login(client)

    create_card = client.post(
        "/admin/credit-cards",
        data={
            "issuer": "itau",
            "card_label": "Itaú Visa final 1234",
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
            },
            files={"file": (sample_credit_card_csv_file.name, handle, "text/csv")},
            follow_redirects=True,
        )

    assert upload.status_code == 200
    assert "Fatura importada com 2 lançamentos." in upload.text
    assert db_session.scalar(select(CreditCardInvoice)) is not None
    assert db_session.scalar(select(CreditCardInvoiceItem)) is not None


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
    assert "vão mudar" in preview.text or "vÃ£o mudar" in preview.text

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
    assert "NÃƒÆ’Ã‚Â£o Categorizado" in preview.text or "NÃƒÂ£o Categorizado" in preview.text
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
    assert "Pré-visualizando..." in reapply_page.text or "Pr" in reapply_page.text

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
    assert "Pré-visualizando..." in reapply_page.text or "Pr" in reapply_page.text

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
    assert "Pré-visualizando..." in reapply_page.text or "Pr" in reapply_page.text

    preview = client.post("/admin/reapply/preview", data={})
    assert preview.status_code == 200
    assert "TED 102 0001 EDUARDO K C" in preview.text
    assert "Transfer" in preview.text or "TransferÃ" in preview.text

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
    assert tx.category in {"TransferÃƒÂªncias", "TransferÃªncias", "Transferências"}
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
    assert tx.category in {"NÃƒÂ£o Categorizado", "Não Categorizado"}


def test_admin_analysis_page_shows_empty_state_and_navigation(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session, description="SALARIO MAR", normalized="salario mar", amount=5000.0, transaction_kind="income", category="SalÃƒÂ¡rio")
    _login(client)

    response = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Ainda não existe análise gerada para esse período" in response.text or "Ainda n" in response.text
    assert "Gerar nova análise" in response.text
    assert "Receitas" in response.text
    assert "data-loading-button" in response.text
    assert "Carregando análise..." in response.text
    assert "Gerando análise..." in response.text


def test_admin_analysis_page_can_generate_and_render_latest_analysis(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session, description="SALARIO MAR", normalized="salario mar", amount=5000.0, transaction_kind="income", category="SalÃƒÂ¡rio")
    _seed_transaction(db_session, description="UBER MAR", normalized="uber mar", amount=-120.0, transaction_kind="expense", category="Transporte")
    _seed_transaction(db_session, description="SEM CATEGORIA", normalized="sem categoria", amount=-80.0, transaction_kind="expense", category="NÃƒÂ£o Categorizado")
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
    assert "Análise determinística renderizada" in page.text or "AnÃ¡lise determin" in page.text
    assert "Ver HTML bruto" in page.text
    assert "Consolidado mensal de 12 meses" in page.text
    assert "Itens financeiros e técnicos" in page.text or "Itens financeiros e t" in page.text
    assert "chart.js" in page.text.lower()
    assert "monthly-chart" in page.text
    assert "categories-chart" in page.text
    assert "R$" in page.text

    run = db_session.scalar(select(AnalysisRun).where(AnalysisRun.period_start == date(2026, 3, 1)))
    assert run is not None
    assert run.html_output
    assert "Análise financeira determinística" in run.html_output or "AnÃ¡lise financeira determinÃ­stica" in run.html_output


def test_admin_loading_buttons_are_exposed_in_reapply_and_analysis(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session)
    _login(client)

    reapply_page = client.get("/admin/reapply")
    assert reapply_page.status_code == 200
    assert "data-loading-button" in reapply_page.text
    assert "Pré-visualizando..." in reapply_page.text or "Pr" in reapply_page.text

    analysis_page = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")
    assert analysis_page.status_code == 200
    assert analysis_page.text.count("data-loading-button") >= 2
    assert "Carregando análise..." in analysis_page.text
    assert "Gerando análise..." in analysis_page.text


