from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.repositories.models import AnalysisRun, CategorizationRule, Category, SourceFile, Transaction, TransactionAuditLog


def _login(client):
    return client.post("/admin/login", data={"password": settings.admin_ui_password, "next": "/admin"})


def _seed_categories(db_session):
    for name, kind in [
        ("NÃ£o Categorizado", "expense"),
        ("Transporte", "expense"),
        ("Outros", "expense"),
        ("SalÃ¡rio", "income"),
        ("TransferÃªncias", "transfer"),
    ]:
        db_session.add(Category(name=name, transaction_kind=kind, is_active=True))
    db_session.commit()


def _seed_transaction(db_session, *, description: str = "UBER TRIP", normalized: str = "uber trip"):
    source_file = SourceFile(
        source_type="bank_statement",
        file_name="manual.ofx",
        file_path="upload://manual.ofx",
        file_hash="hash-admin-ui",
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
        category="NÃ£o Categorizado",
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
    assert "NÃ£o categorizados" in home.text or "Não categorizados" in home.text


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
    assert "lançamento(s) serão avaliados" in preview.text

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
