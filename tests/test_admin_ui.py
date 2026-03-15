from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.repositories.models import AnalysisRun, CategorizationRule, Category, SourceFile, Transaction, TransactionAuditLog


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


def _seed_transaction(db_session, *, description: str = "UBER TRIP", normalized: str = "uber trip"):
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
        amount=-25.0,
        direction="debit",
        transaction_kind="expense",
        category="NÃƒÂ£o Categorizado",
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
            transaction_kind="expense",
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
        transaction_kind="expense",
        priority=0,
        is_active=True,
    )
    cabify_rule = CategorizationRule(
        rule_type="contains",
        pattern="cabify",
        category_name="Outros",
        transaction_kind="expense",
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
            transaction_kind="expense",
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
            transaction_kind="expense",
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
        transaction_kind="expense",
        priority=0,
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()
    _login(client)

    preview = client.post("/admin/reapply/preview", data={})
    assert preview.status_code == 200
    assert f'/admin/rules?open_rule_id={rule.id}#rule-{rule.id}' in preview.text

    rules_page = client.get(f"/admin/rules?open_rule_id={rule.id}")
    assert rules_page.status_code == 200
    assert f'id="rule-{rule.id}" class="rule-row accordion" open' in rules_page.text

