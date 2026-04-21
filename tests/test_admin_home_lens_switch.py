import json
import re
from datetime import date

from app.core.config import settings
from app.repositories.models import Category, SourceFile, Transaction

_PERIOD = "period_start=2026-03-01&period_end=2026-03-31"


def _login(client):
    return client.post("/admin/login", data={"password": settings.admin_ui_password, "next": "/admin"})


def _seed_categories(db_session):
    for name, kind in [
        ("Não Categorizado", "expense"),
        ("Transporte", "expense"),
        ("Salário", "income"),
    ]:
        db_session.add(Category(name=name, transaction_kind=kind, is_active=True))
    db_session.commit()


def _seed_transaction(db_session) -> Transaction:
    source_file = SourceFile(
        source_type="bank_statement",
        file_name="lens-switch-test.ofx",
        file_path="upload://lens-switch-test.ofx",
        file_hash="lens-switch-test-hash",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()
    tx = Transaction(
        source_file_id=source_file.id,
        source_type="bank_statement",
        account_ref="default-account",
        external_id=None,
        canonical_hash="lens-switch-test-tx",
        transaction_date=date(2026, 3, 7),
        competence_month="2026-03",
        description_raw="UBER LENS SWITCH TEST",
        description_normalized="uber lens switch test",
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


def _assert_lens_resolved(response, lens: str, route: str) -> None:
    """Assert that the resolved home_lens for this response matches `lens`.

    The hidden period-form field ``name="home_lens"`` is rendered by
    analysis_topbar_period_control.html and is present on all three analysis
    routes.  The visual lens-switch (data-summary-home-lens) is only rendered
    on the summary page, so we rely on the hidden field for analysis/conference.
    """
    assert response.status_code == 200, f"{route}: expected 200, got {response.status_code}"
    assert "Internal Server Error" not in response.text, f"{route}: internal server error"
    match = re.search(
        rf'name="home_lens"\s+value="([^"]+)"',
        response.text,
    )
    assert match, f"{route}: expected hidden home_lens field, but none was found"
    assert match.group(1) == lens, (
        f"{route}: expected hidden home_lens field with value='{lens}', "
        f"got '{match.group(1)}'"
    )


def _assert_lens_switch_active(response, lens: str, route: str) -> None:
    """Assert that the visual lens-switch button for `lens` is aria-selected=true."""
    assert re.search(
        rf'aria-selected="true"\s+data-summary-home-lens="{lens}"',
        response.text,
    ), f"{route}: expected lens switch aria-selected=true for '{lens}'"


def test_home_lens_cash_renders_in_all_three_routes(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session)
    _login(client)

    summary = client.get(f"/admin/summary?{_PERIOD}&home_lens=cash")
    analysis = client.get(f"/admin/analysis?{_PERIOD}&home_lens=cash")
    conference = client.get(f"/admin/conference?{_PERIOD}&home_lens=cash")

    _assert_lens_resolved(summary, "cash", "/admin/summary")
    _assert_lens_resolved(analysis, "cash", "/admin/analysis")
    _assert_lens_resolved(conference, "cash", "/admin/conference")

    # Summary also exposes the visual switch — verify it marks the right tab
    _assert_lens_switch_active(summary, "cash", "/admin/summary")


def test_home_lens_competence_renders_in_all_three_routes(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session)
    _login(client)

    summary = client.get(f"/admin/summary?{_PERIOD}&home_lens=competence")
    analysis = client.get(f"/admin/analysis?{_PERIOD}&home_lens=competence")
    conference = client.get(f"/admin/conference?{_PERIOD}&home_lens=competence")

    _assert_lens_resolved(summary, "competence", "/admin/summary")
    _assert_lens_resolved(analysis, "competence", "/admin/analysis")
    _assert_lens_resolved(conference, "competence", "/admin/conference")

    # Summary also exposes the visual switch — verify it marks the right tab
    _assert_lens_switch_active(summary, "competence", "/admin/summary")


def test_home_lens_persists_from_summary_to_analysis(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session)
    _login(client)

    # Set lens to competence (non-default) via summary — persists to session
    client.get(f"/admin/summary?{_PERIOD}&home_lens=competence")

    # Navigate to analysis without home_lens param — session should restore competence
    analysis = client.get(f"/admin/analysis?{_PERIOD}")
    _assert_lens_switch_active(
        analysis,
        "competence",
        "/admin/analysis (after session persist from /admin/summary)",
    )


def test_home_lens_switch_is_visible_in_analysis_and_conference_topbars(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session)
    _login(client)

    analysis = client.get(f"/admin/analysis?{_PERIOD}&home_lens=competence")
    conference = client.get(f"/admin/conference?{_PERIOD}&home_lens=competence")

    assert 'data-summary-home-lens="cash"' in analysis.text
    assert 'data-summary-home-lens="competence"' in analysis.text
    assert 'data-summary-home-lens="cash"' in conference.text
    assert 'data-summary-home-lens="competence"' in conference.text


def test_home_lens_persists_from_analysis_and_conference_routes(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)
    _seed_transaction(db_session)
    _login(client)

    analysis_response = client.get(f"/admin/analysis?{_PERIOD}&home_lens=competence")
    conference_response = client.get(f"/admin/conference?{_PERIOD}&home_lens=competence")

    _assert_lens_resolved(
        analysis_response,
        "competence",
        "/admin/analysis (lens selection request)",
    )
    _assert_lens_resolved(
        conference_response,
        "competence",
        "/admin/conference (lens selection request)",
    )

    restored_analysis = client.get(f"/admin/analysis?{_PERIOD}")
    restored_conference = client.get(f"/admin/conference?{_PERIOD}")

    _assert_lens_resolved(
        restored_analysis,
        "competence",
        "/admin/analysis (after session persist from /admin/analysis)",
    )
    _assert_lens_resolved(
        restored_conference,
        "competence",
        "/admin/conference (after session persist from /admin/conference)",
    )


def test_home_lens_persistence_drives_categories_page_view_and_navigation(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_ui_password", "secret-123")
    _seed_categories(db_session)

    source_file = SourceFile(
        source_type="bank_statement",
        file_name="categories-lens-test.ofx",
        file_path="upload://categories-lens-test.ofx",
        file_hash="categories-lens-test-hash",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()
    db_session.add(
        Transaction(
            source_file_id=source_file.id,
            source_type="bank_statement",
            account_ref="default-account",
            external_id=None,
            canonical_hash="categories-lens-test-tx",
            transaction_date=date(2026, 2, 28),
            competence_month="2026-03",
            description_raw="MORADIA COMPETENCE TEST",
            description_normalized="moradia competence test",
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
    )
    db_session.commit()
    _login(client)

    client.get(f"/admin/analysis?{_PERIOD}&home_lens=competence")
    response = client.get(f"/admin/categories?selection_mode=month&month=2026-03&selected_category=Transporte")

    assert response.status_code == 200
    assert 'name="home_lens"' in response.text

    monthly_chart_match = re.search(r"const monthlyData = (\{.*?\});", response.text, re.S)
    assert monthly_chart_match is not None
    monthly_chart_payload = json.loads(monthly_chart_match.group(1))
    assert [dataset["label"] for dataset in monthly_chart_payload["datasets"]] == ["Transporte"]
    assert monthly_chart_payload["datasets"][0]["values"][-1] == 25.0
