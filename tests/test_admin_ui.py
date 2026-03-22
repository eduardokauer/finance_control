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
        ("NÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â£o Categorizado", "expense"),
        ("Transporte", "expense"),
        ("Outros", "expense"),
        ("SalÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡rio", "income"),
        ("TransferÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âªncias", "transfer"),
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
    category: str = "NÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â£o Categorizado",
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
    assert "ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ltimas alteraÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âµes" in home.text or "ltimas altera" in home.text
    assert "Subir fatura ItaÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âº" in home.text or "Subir fatura Ita" in home.text


def test_admin_can_create_credit_card_and_upload_invoice(client, db_session, monkeypatch, sample_credit_card_csv_file):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _login(client)

    create_card = client.post(
        "/admin/credit-cards",
        data={
            "issuer": "itau",
            "card_label": "ItaÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âº Visa final 1234",
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
    assert "Fatura importada com 2 lan\u00e7amentos." in upload.text or "Fatura importada com 2 lancamentos." in upload.text
    assert "Faturas importadas" in upload.text
    assert "03/2026" in upload.text
    assert "ItaÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âº Visa final 1234" in upload.text or "Ita" in upload.text
    assert "2 lan\u00e7amento(s)" in upload.text or "2 lancamento(s)" in upload.text
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
    assert "v\u00e3o mudar" in preview.text or "vao mudar" in preview.text

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
    assert "NÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â£o Categorizado" in preview.text or "NÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â£o Categorizado" in preview.text
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
    assert "PrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©-visualizando..." in reapply_page.text or "Pr" in reapply_page.text

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
    assert "PrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©-visualizando..." in reapply_page.text or "Pr" in reapply_page.text

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
    assert "PrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©-visualizando..." in reapply_page.text or "Pr" in reapply_page.text

    preview = client.post("/admin/reapply/preview", data={})
    assert preview.status_code == 200
    assert "TED 102 0001 EDUARDO K C" in preview.text
    assert "Transfer" in preview.text or "TransferÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢" in preview.text

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
    assert tx.category in {"Transfer\u00eancias", "Transferencias"}
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
    _seed_transaction(db_session, description="SALARIO MAR", normalized="salario mar", amount=5000.0, transaction_kind="income", category="SalÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡rio")
    _login(client)

    response = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")

    assert response.status_code == 200
    assert "Ainda nÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â£o existe anÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡lise gerada para esse perÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­odo" in response.text or "Ainda n" in response.text
    assert "Gerar nova an\u00e1lise" in response.text or "Gerar nova analise" in response.text
    assert "Receitas" in response.text
    assert "data-loading-button" in response.text
    assert "Carregando an\u00e1lise..." in response.text or "Carregando analise..." in response.text
    assert "Gerando an\u00e1lise..." in response.text or "Gerando analise..." in response.text


def test_admin_analysis_page_can_generate_and_render_latest_analysis(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session, description="SALARIO MAR", normalized="salario mar", amount=5000.0, transaction_kind="income", category="SalÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡rio")
    _seed_transaction(db_session, description="UBER MAR", normalized="uber mar", amount=-120.0, transaction_kind="expense", category="Transporte")
    _seed_transaction(db_session, description="SEM CATEGORIA", normalized="sem categoria", amount=-80.0, transaction_kind="expense", category="NÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â£o Categorizado")
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
    assert (
        "An\u00e1lise determin\u00edstica renderizada" in page.text
        or "Analise deterministica renderizada" in page.text
        or "An\u00e1lise deterministica renderizada" in page.text
    )
    assert "Ver HTML bruto" in page.text
    assert "Consolidado mensal de 12 meses" in page.text
    assert "Itens financeiros e tÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©cnicos" in page.text or "Itens financeiros e t" in page.text
    assert "chart.js" in page.text.lower()
    assert "monthly-chart" in page.text
    assert "categories-chart" in page.text
    assert "R$" in page.text

    run = db_session.scalar(select(AnalysisRun).where(AnalysisRun.period_start == date(2026, 3, 1)))
    assert run is not None
    assert run.html_output
    assert (
        "An\u00e1lise financeira determin\u00edstica" in run.html_output
        or "Analise financeira deterministica" in run.html_output
        or "An\u00e1lise financeira deterministica" in run.html_output
    )


def test_admin_loading_buttons_are_exposed_in_reapply_and_analysis(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session)
    _login(client)

    reapply_page = client.get("/admin/reapply")
    assert reapply_page.status_code == 200
    assert "data-loading-button" in reapply_page.text
    assert "PrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©-visualizando..." in reapply_page.text or "Pr" in reapply_page.text

    analysis_page = client.get("/admin/analysis?period_start=2026-03-01&period_end=2026-03-31")
    assert analysis_page.status_code == 200
    assert analysis_page.text.count("data-loading-button") >= 2
    assert "Carregando an\u00e1lise..." in analysis_page.text or "Carregando analise..." in analysis_page.text
    assert "Gerando an\u00e1lise..." in analysis_page.text or "Gerando analise..." in analysis_page.text





def _seed_credit_card_invoice(
    db_session,
    *,
    card_label: str = "ItaÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âº Visa final 1234",
    card_final: str = "1234",
    billing_year: int = 2026,
    billing_month: int = 3,
    total_amount: str = "130.45",
    status: str = "imported",
    notes: str | None = "Fatura marÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§o",
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
        due_date=date(2026, 3, 20),
        closing_date=date(2026, 3, 12),
        total_amount_brl=total_amount,
        source_file_name=source_file.file_name,
        source_file_hash=source_file.file_hash,
        notes=notes,
        import_status=status,
    )
    db_session.add(invoice)
    db_session.flush()

    db_session.add_all(
        [
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 3, 5),
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
                purchase_date=date(2026, 3, 7),
                description_raw="CURSO PARCELADO",
                description_normalized="curso parcelado",
                amount_brl="30.45",
                installment_current=2,
                installment_total=3,
                is_installment=True,
                derived_note="parcela 2/3",
                external_row_hash=f"row-hash-{invoice.id}-2",
            ),
        ]
    )
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


def test_admin_credit_card_invoice_list_shows_imported_invoices(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_credit_card_invoice(db_session, card_label="ItaÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âº Visa final 1234", card_final="1234", status="imported")
    _seed_credit_card_invoice(db_session, card_label="ItaÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âº Mastercard final 5678", card_final="5678", billing_month=2, status="conflict")
    _login(client)

    response = client.get("/admin/credit-card-invoices")

    assert response.status_code == 200
    assert "Faturas importadas" in response.text
    assert "ItaÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âº Visa final 1234" in response.text or "Ita" in response.text
    assert "03/2026" in response.text
    assert "imported" in response.text
    assert "conflict" in response.text
    assert "Ver detalhe" in response.text


def test_admin_credit_card_invoice_detail_shows_items_and_summary(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    invoice = _seed_credit_card_invoice(db_session, status="pending_review")
    _login(client)

    response = client.get(f"/admin/credit-card-invoices/{invoice.id}")

    assert response.status_code == 200
    assert f"Fatura #{invoice.id}" in response.text
    assert "pending_review" in response.text
    assert "Quantidade de lan\u00e7amentos" in response.text or "Quantidade de lancamentos" in response.text
    assert "Total de cobran\u00e7as" in response.text or "Total de cobrancas" in response.text
    assert "Total de cr\u00e9ditos/descontos" in response.text or "Total de creditos/descontos" in response.text
    assert "Total de pagamentos identificados" in response.text
    assert "Total composto da fatura" in response.text
    assert "Diferen\u00e7a para o total informado" in response.text or "Diferenca para o total informado" in response.text
    assert "SUPERMERCADO TESTE" in response.text
    assert "CURSO PARCELADO" in response.text
    assert "parcela 2/3" in response.text
    assert "30.45" in response.text
    assert "2" in response.text
    assert "3" in response.text


def test_admin_credit_card_invoice_detail_returns_404_for_missing_invoice(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _login(client)

    response = client.get("/admin/credit-card-invoices/999999")

    assert response.status_code == 404
