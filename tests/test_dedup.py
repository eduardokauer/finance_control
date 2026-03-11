from sqlalchemy import select

from app.repositories.models import SourceFile, Transaction
from app.services.ingestion import ingest_file


def test_file_dedup(db_session, sample_ofx_file):
    first = ingest_file(db_session, "bank_statement", "a.ofx", str(sample_ofx_file), None)
    second = ingest_file(db_session, "bank_statement", "a.ofx", str(sample_ofx_file), None)
    assert first["status"] == "processed"
    assert second["status"] == "duplicate"


def test_transaction_dedup(db_session, tmp_path):
    ofx1 = tmp_path / "1.ofx"
    ofx2 = tmp_path / "2.ofx"
    content = "<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260307<TRNAMT>-10<NAME>Uber<FITID>ABC</STMTTRN></BANKTRANLIST></OFX>"
    ofx1.write_text(content, encoding="utf-8")
    ofx2.write_text(content.replace("ABC", "ABC"), encoding="utf-8")
    ingest_file(db_session, "bank_statement", "1.ofx", str(ofx1), None)
    ingest_file(db_session, "bank_statement", "2.ofx", str(ofx2), None)
    tx_count = len(db_session.scalars(select(Transaction)).all())
    assert tx_count == 1
