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
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["analysis_run_id"] is None


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


def test_ingest_credit_card_valid(client, auth_headers, sample_csv_file):
    resp = client.post('/ingest/credit-card-bill', headers=auth_headers, json={"file_name": "a.csv", "file_path": str(sample_csv_file)})
    assert resp.status_code == 200
    assert resp.json()["analysis_run_id"] is not None


def test_duplicate_file(client, auth_headers, sample_csv_file):
    payload = {"file_name": "a.csv", "file_path": str(sample_csv_file)}
    client.post('/ingest/credit-card-bill', headers=auth_headers, json=payload)
    resp = client.post('/ingest/credit-card-bill', headers=auth_headers, json=payload)
    assert resp.json()['status'] == 'duplicate'
    assert resp.json()["analysis_run_id"] is None


def test_query_transactions_and_analysis(client, auth_headers, sample_csv_file):
    client.post('/ingest/credit-card-bill', headers=auth_headers, json={"file_name": "a.csv", "file_path": str(sample_csv_file)})
    resp = client.get("/transactions?period_start=2026-03-01&period_end=2026-03-31&limit=10&offset=0", headers=auth_headers)
    assert resp.status_code == 200
    run = client.post('/analysis/run', headers=auth_headers, json={"period_start": "2026-03-01", "period_end": "2026-03-31"})
    assert run.status_code == 200
    runs = client.get("/analysis/runs", headers=auth_headers)
    assert runs.status_code == 200
    html_output = runs.json()[0]["html_output"]
    assert "Análise Financeira" in html_output
    assert "Período:" in html_output
    assert "Mês anterior:" in html_output
    assert '<meta charset="UTF-8">' in html_output


def test_manual_reclassify_transactions(client, auth_headers, sample_csv_file):
    client.post('/ingest/credit-card-bill', headers=auth_headers, json={"file_name": "a.csv", "file_path": str(sample_csv_file)})
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
