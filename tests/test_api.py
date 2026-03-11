from datetime import date


def test_auth_required(client, sample_ofx_file):
    resp = client.post('/ingest/bank-statement', json={"file_name": "a.ofx", "file_path": str(sample_ofx_file)})
    assert resp.status_code == 401


def test_ingest_bank_statement_valid(client, auth_headers, sample_ofx_file):
    resp = client.post('/ingest/bank-statement', headers=auth_headers, json={"file_name": "a.ofx", "file_path": str(sample_ofx_file)})
    assert resp.status_code == 200
    assert resp.json()['status'] == 'processed'


def test_ingest_credit_card_valid(client, auth_headers, sample_csv_file):
    resp = client.post('/ingest/credit-card-bill', headers=auth_headers, json={"file_name": "a.csv", "file_path": str(sample_csv_file)})
    assert resp.status_code == 200


def test_duplicate_file(client, auth_headers, sample_csv_file):
    payload = {"file_name": "a.csv", "file_path": str(sample_csv_file)}
    client.post('/ingest/credit-card-bill', headers=auth_headers, json=payload)
    resp = client.post('/ingest/credit-card-bill', headers=auth_headers, json=payload)
    assert resp.json()['status'] == 'duplicate'


def test_invalid_file(client, auth_headers, tmp_path):
    bad = tmp_path / 'bad.ofx'
    bad.write_text('<OFX>bad</OFX>', encoding='utf-8')
    resp = client.post('/ingest/bank-statement', headers=auth_headers, json={"file_name": "bad.ofx", "file_path": str(bad)})
    assert resp.status_code == 422


def test_query_transactions_and_analysis(client, auth_headers, sample_csv_file):
    client.post('/ingest/credit-card-bill', headers=auth_headers, json={"file_name": "a.csv", "file_path": str(sample_csv_file)})
    resp = client.get(f"/transactions?period_start=2026-03-01&period_end=2026-03-31&limit=10&offset=0", headers=auth_headers)
    assert resp.status_code == 200
    run = client.post('/analysis/run', headers=auth_headers, json={"period_start": "2026-03-01", "period_end": "2026-03-31"})
    assert run.status_code == 200
