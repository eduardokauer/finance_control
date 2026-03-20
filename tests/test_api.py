from decimal import Decimal

from app.api.routes import credit_card_bills as credit_card_bill_routes


def test_auth_required(client, sample_ofx_file):
    with sample_ofx_file.open("rb") as handle:
        resp = client.post(
            "/ingest/bank-statement",
            files={"file": (sample_ofx_file.name, handle, "application/octet-stream")},
        )
    assert resp.status_code == 401


def test_ingest_bank_statement_valid(client, auth_headers, sample_ofx_file):
    with sample_ofx_file.open("rb") as handle:
        resp = client.post(
            "/ingest/bank-statement",
            headers=auth_headers,
            files={"file": (sample_ofx_file.name, handle, "application/octet-stream")},
            data={"reference_id": "api-test-ofx"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"
    assert resp.json()["analysis_run_id"] is not None
    assert resp.json()["period_start"] == "2026-03-07"
    assert resp.json()["period_end"] == "2026-03-07"


def test_ingest_bank_statement_duplicate_upload(client, auth_headers, sample_ofx_file):
    with sample_ofx_file.open("rb") as handle:
        first = client.post(
            "/ingest/bank-statement",
            headers=auth_headers,
            files={"file": (sample_ofx_file.name, handle, "application/octet-stream")},
        )
    with sample_ofx_file.open("rb") as handle:
        second = client.post(
            "/ingest/bank-statement",
            headers=auth_headers,
            files={"file": (sample_ofx_file.name, handle, "application/octet-stream")},
        )
    assert first.status_code == 200
    assert first.json()["status"] == "processed"
    assert first.json()["period_start"] == "2026-03-07"
    assert first.json()["period_end"] == "2026-03-07"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["analysis_run_id"] is None
    assert second.json()["period_start"] == "2026-03-07"
    assert second.json()["period_end"] == "2026-03-07"


def test_ingest_bank_statement_invalid_extension(client, auth_headers, tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("not ofx", encoding="utf-8")
    with bad.open("rb") as handle:
        resp = client.post(
            "/ingest/bank-statement",
            headers=auth_headers,
            files={"file": (bad.name, handle, "text/plain")},
        )
    assert resp.status_code == 422


def test_invalid_file(client, auth_headers, tmp_path):
    bad = tmp_path / "bad.ofx"
    bad.write_text("<OFX>bad</OFX>", encoding="utf-8")
    with bad.open("rb") as handle:
        resp = client.post(
            "/ingest/bank-statement",
            headers=auth_headers,
            files={"file": (bad.name, handle, "application/octet-stream")},
        )
    assert resp.status_code == 422


def test_query_transactions_and_analysis(client, auth_headers, sample_ofx_file):
    with sample_ofx_file.open("rb") as handle:
        client.post(
            "/ingest/bank-statement",
            headers=auth_headers,
            files={"file": (sample_ofx_file.name, handle, "application/octet-stream")},
        )
    resp = client.get(
        "/transactions?period_start=2026-03-01&period_end=2026-03-31&limit=10&offset=0",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    run = client.post(
        "/analysis/run",
        headers=auth_headers,
        json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
    )
    assert run.status_code == 200
    runs = client.get("/analysis/runs", headers=auth_headers)
    assert runs.status_code == 200
    assert runs.headers["content-type"].startswith("application/json; charset=utf-8")
    raw_body = runs.content.decode("utf-8")
    assert "An\u00e1lise financeira determin\u00edstica" in raw_body or "AnÃ¡lise financeira determinÃ­stica" in raw_body
    assert "Per\u00edodo" in raw_body or "PerÃ­odo" in raw_body
    assert "A\u00e7\u00f5es recomendadas" in raw_body or "AÃ§Ãµes recomendadas" in raw_body
    html_output = runs.json()[0]["html_output"]
    assert "An\u00e1lise financeira determin\u00edstica" in html_output or "AnÃ¡lise financeira determinÃ­stica" in html_output
    assert "Per\u00edodo:" in html_output or "PerÃ­odo:" in html_output
    assert "A\u00e7\u00f5es recomendadas" in html_output or "AÃ§Ãµes recomendadas" in html_output
    assert '<meta charset="UTF-8">' in html_output


def test_manual_reclassify_transactions(client, auth_headers, sample_ofx_file):
    with sample_ofx_file.open("rb") as handle:
        client.post(
            "/ingest/bank-statement",
            headers=auth_headers,
            files={"file": (sample_ofx_file.name, handle, "application/octet-stream")},
        )
    listed = client.get(
        "/transactions?period_start=2026-03-01&period_end=2026-03-31&limit=10&offset=0",
        headers=auth_headers,
    )
    tx_id = listed.json()[0]["id"]

    resp = client.post(
        "/transactions/reclassify",
        headers=auth_headers,
        json={
            "filters": {"transaction_ids": [tx_id]},
            "category": "Ajustes e Estornos",
            "transaction_kind": "adjustment",
            "notes": "manual exception",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 1

    listed_after = client.get(
        "/transactions?period_start=2026-03-01&period_end=2026-03-31&limit=10&offset=0",
        headers=auth_headers,
    )
    tx = listed_after.json()[0]
    assert tx["category"] == "Ajustes e Estornos"
    assert tx["transaction_kind"] == "adjustment"
    assert tx["should_count_in_spending"] is False



def test_ingest_credit_card_bill_http_flow_does_not_trigger_analysis(
    client,
    db_session,
    auth_headers,
    sample_credit_card_csv_file,
    monkeypatch,
):
    from app.services.credit_card_bills import create_credit_card
    from app.services import analysis as analysis_service

    card = create_credit_card(
        db_session,
        issuer="itau",
        card_label="Itau Visa final 1234",
        card_final="1234",
        brand="Visa",
        is_active=True,
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_analysis should not be called for credit card bill upload")

    monkeypatch.setattr(analysis_service, "run_analysis", fail_if_called)

    with sample_credit_card_csv_file.open("rb") as handle:
        response = client.post(
            "/ingest/credit-card-bill",
            headers=auth_headers,
            data={
                "billing_month": "3",
                "billing_year": "2026",
                "due_date": "2026-03-20",
                "card_id": str(card.id),
                "total_amount_brl": "130.45",
            },
            files={"file": (sample_credit_card_csv_file.name, handle, "text/csv")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert "analysis_run_id" not in body
    assert "period_start" not in body
    assert "period_end" not in body
    assert "source_file_id" not in body


def test_ingest_credit_card_bill_http_flow_uses_only_multipart_contract(
    client,
    db_session,
    auth_headers,
    sample_credit_card_csv_file,
    monkeypatch,
):
    from app.services.credit_card_bills import CreditCardBillUploadInput, create_credit_card

    card = create_credit_card(
        db_session,
        issuer="itau",
        card_label="Itau Visa final 1234",
        card_final="1234",
        brand="Visa",
        is_active=True,
    )

    captured: dict[str, object] = {}

    def fake_import_credit_card_bill(*, db, file_name, raw_content, upload_input):
        captured["file_name"] = file_name
        captured["raw_content"] = raw_content
        captured["upload_input"] = upload_input
        return {
            "status": "processed",
            "message": "ok",
            "invoice_id": 123,
            "imported_items": 2,
        }

    monkeypatch.setattr(credit_card_bill_routes, "import_credit_card_bill", fake_import_credit_card_bill)

    with sample_credit_card_csv_file.open("rb") as handle:
        response = client.post(
            "/ingest/credit-card-bill",
            headers=auth_headers,
            data={
                "billing_month": "3",
                "billing_year": "2026",
                "due_date": "2026-03-20",
                "card_id": str(card.id),
                "total_amount_brl": "130.45",
                "closing_date": "2026-03-12",
                "notes": "Teste",
            },
            files={"file": (sample_credit_card_csv_file.name, handle, "text/csv")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "processed",
        "message": "ok",
        "invoice_id": 123,
        "imported_items": 2,
    }
    assert captured["file_name"] == sample_credit_card_csv_file.name
    assert captured["raw_content"]
    assert isinstance(captured["upload_input"], CreditCardBillUploadInput)
    assert captured["upload_input"].card_id == card.id
    assert captured["upload_input"].billing_month == 3
    assert captured["upload_input"].billing_year == 2026
    assert str(captured["upload_input"].due_date) == "2026-03-20"
    assert str(captured["upload_input"].closing_date) == "2026-03-12"
    assert captured["upload_input"].total_amount_brl == Decimal("130.45")
    assert captured["upload_input"].notes == "Teste"







