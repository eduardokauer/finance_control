import json
from math import isclose

import pytest
from sqlalchemy import case, func, select

from app.parsers.ofx_parser import parse_ofx
from app.repositories.models import AnalysisRun, RawTransaction, SourceFile, Transaction


def _expected_summary(real_ofx_file):
    parsed = parse_ofx(real_ofx_file.read_text(encoding="utf-8", errors="ignore"))
    return {
        "count": len(parsed),
        "first_date": min(item["date"] for item in parsed),
        "last_date": max(item["date"] for item in parsed),
        "net_amount": sum(item["amount"] for item in parsed),
        "credits": sum(item["amount"] for item in parsed if item["amount"] > 0),
        "debits": sum(item["amount"] for item in parsed if item["amount"] < 0),
        "external_ids": {item["external_id"] for item in parsed},
    }


@pytest.mark.e2e
def test_e2e_ofx_import_and_manual_reclassification(client, db_session, auth_headers, real_ofx_file):
    expected = _expected_summary(real_ofx_file)
    print(
        f"[e2e] expected summary: count={expected['count']} "
        f"period={expected['first_date']}..{expected['last_date']} "
        f"net={expected['net_amount']:.2f}"
    )

    ingest_response = client.post(
        "/ingest/bank-statement",
        headers=auth_headers,
        files={"file": (real_ofx_file.name, real_ofx_file.read_bytes(), "application/octet-stream")},
        data={"reference_id": "pytest-e2e-ofx"},
    )
    assert ingest_response.status_code == 200
    assert ingest_response.json()["status"] == "processed"
    assert ingest_response.json()["analysis_run_id"] is not None
    assert ingest_response.json()["period_start"] == str(expected["first_date"])
    assert ingest_response.json()["period_end"] == str(expected["last_date"])
    print(f"[e2e] ingest response: {ingest_response.json()}")

    db_session.expire_all()

    source_file = db_session.scalar(select(SourceFile))
    assert source_file is not None
    assert source_file.status == "processed"
    assert source_file.file_name == real_ofx_file.name

    raw_count, first_date, last_date, net_amount, credits, debits = db_session.execute(
        select(
            func.count(RawTransaction.id),
            func.min(RawTransaction.transaction_date),
            func.max(RawTransaction.transaction_date),
            func.sum(RawTransaction.amount),
            func.sum(case((RawTransaction.amount > 0, RawTransaction.amount), else_=0.0)),
            func.sum(case((RawTransaction.amount < 0, RawTransaction.amount), else_=0.0)),
        )
    ).one()
    tx_count = db_session.scalar(select(func.count(Transaction.id)))
    raw_external_ids = set(db_session.scalars(select(RawTransaction.external_id)).all())

    assert raw_count == expected["count"]
    assert tx_count == expected["count"]
    assert first_date == expected["first_date"]
    assert last_date == expected["last_date"]
    assert isclose(float(net_amount), expected["net_amount"], rel_tol=0, abs_tol=1e-9)
    assert isclose(float(credits), expected["credits"], rel_tol=0, abs_tol=1e-9)
    assert isclose(float(debits), expected["debits"], rel_tol=0, abs_tol=1e-9)
    assert raw_external_ids == expected["external_ids"]
    print(
        f"[e2e] persisted summary: raw={raw_count} treated={tx_count} "
        f"period={first_date}..{last_date} net={float(net_amount):.2f}"
    )

    uncategorized_before = db_session.scalar(
        select(func.count(Transaction.id)).where(Transaction.category.in_(["NÃ£o Categorizado", "Não Categorizado", "NÃƒÂ£o Categorizado"]))
    )
    assert uncategorized_before == 4
    print(f"[e2e] uncategorized before manual overrides: {uncategorized_before}")

    exception_transactions = db_session.scalars(
        select(Transaction).where(Transaction.description_raw.in_(
            [
                "PIX TRANSF Luis An02 02",
                "PIX TRANSF GUILHER04 02",
                "PIX TRANSF HELEN C05 02",
            ]
        ))
    ).all()
    by_description = {}
    for tx in exception_transactions:
        by_description.setdefault(tx.description_raw, []).append(tx)

    outgoing_ids = sorted(tx.id for tx in by_description["PIX TRANSF Luis An02 02"]) + [
        by_description["PIX TRANSF GUILHER04 02"][0].id
    ]
    reimbursement_id = by_description["PIX TRANSF HELEN C05 02"][0].id

    outgoing_override = client.post(
        "/transactions/reclassify",
        headers=auth_headers,
        json={
            "filters": {"transaction_ids": outgoing_ids},
            "category": "Outros",
            "transaction_kind": "expense",
            "should_count_in_spending": True,
            "notes": "Pytest e2e: accident-related outgoing exception",
        },
    )
    assert outgoing_override.status_code == 200
    assert outgoing_override.json() == {"updated_count": 3, "transaction_ids": outgoing_ids}
    print(f"[e2e] outgoing override: {outgoing_override.json()}")

    reimbursement_override = client.post(
        "/transactions/reclassify",
        headers=auth_headers,
        json={
            "filters": {"transaction_ids": [reimbursement_id]},
            "category": "Reembolsos",
            "transaction_kind": "income",
            "should_count_in_spending": False,
            "notes": "Pytest e2e: accident-related reimbursement exception",
        },
    )
    assert reimbursement_override.status_code == 200
    assert reimbursement_override.json() == {"updated_count": 1, "transaction_ids": [reimbursement_id]}
    print(f"[e2e] reimbursement override: {reimbursement_override.json()}")

    db_session.expire_all()

    uncategorized_after = db_session.scalar(
        select(func.count(Transaction.id)).where(Transaction.category == "NÃ£o Categorizado")
    )
    assert uncategorized_after == 0
    print(f"[e2e] uncategorized after manual overrides: {uncategorized_after}")

    overridden = db_session.scalars(
        select(Transaction).where(Transaction.id.in_(outgoing_ids + [reimbursement_id])).order_by(Transaction.id)
    ).all()
    assert all(tx.manual_override for tx in overridden)
    assert {tx.category for tx in overridden if tx.id in outgoing_ids} == {"Outros"}
    assert {tx.category for tx in overridden if tx.id == reimbursement_id} == {"Reembolsos"}
    assert all(tx.transaction_kind == "expense" for tx in overridden if tx.id in outgoing_ids)
    assert next(tx for tx in overridden if tx.id == reimbursement_id).should_count_in_spending is False

    analysis_response = client.post(
        "/analysis/run",
        headers=auth_headers,
        json={
            "period_start": str(expected["first_date"]),
            "period_end": str(expected["last_date"]),
            "trigger_source_file_id": source_file.id,
        },
    )
    assert analysis_response.status_code == 200

    db_session.expire_all()
    analysis_runs = db_session.scalars(select(AnalysisRun).order_by(AnalysisRun.id)).all()
    assert len(analysis_runs) == 2

    latest_run = analysis_runs[-1]
    payload = json.loads(latest_run.payload)
    assert payload["transactions"] == expected["count"]
    assert isclose(float(payload["total"]), -15601.14, rel_tol=0, abs_tol=1e-9)
    assert payload["summary"]["transaction_count"] == expected["count"]
    assert len(payload["monthly_series"]) == 12
    assert latest_run.status == "success"
    assert latest_run.prompt == "deterministic_html_analysis_v2"
    assert "Análise financeira determinística" in latest_run.html_output or "AnÃ¡lise financeira determinÃ­stica" in latest_run.html_output
    assert "Ações recomendadas" in latest_run.html_output or "AÃ§Ãµes recomendadas" in latest_run.html_output
    assert "Reembolsos" not in latest_run.html_output
    print(
        f"[e2e] analysis run: id={latest_run.id} status={latest_run.status} "
        f"transactions={payload['transactions']} total={float(payload['total']):.2f}"
    )




