from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.repositories import models  # noqa: F401


@pytest.fixture()
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.api_token", "test-token")
    return {"Authorization": "Bearer test-token"}


@pytest.fixture()
def sample_ofx_file(tmp_path: Path):
    content = """<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260307<TRNAMT>-10.50<NAME>ifood<FITID>1</STMTTRN></BANKTRANLIST></OFX>"""
    f = tmp_path / "sample.ofx"
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture()
def sample_csv_file(tmp_path: Path):
    content = "data,descricao,valor,tipo\n07/03/2026,Uber,-25,compra\n"
    f = tmp_path / "sample.csv"
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture()
def sample_credit_card_csv_file(tmp_path: Path):
    content = "data;lançamento;valor\n05/03/2026;SUPERMERCADO EXTRA 06/08;-120,45\n06/03/2026;ESTORNO LOJA; -10,00\n"
    f = tmp_path / "fatura_itau.csv"
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture()
def invalid_credit_card_csv_file(tmp_path: Path):
    content = "data;lançamento;valor\n05/03/2026;;-120,45\n"
    f = tmp_path / "fatura_invalida.csv"
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture()
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture()
def real_ofx_file(fixture_dir: Path) -> Path:
    return fixture_dir / "ofx" / "itau_statement_sample.ofx"


@pytest.fixture()
def real_credit_card_bill_file(fixture_dir: Path) -> Path:
    return fixture_dir / "credit_card" / "fatura-20260307.csv"


@pytest.fixture()
def real_layout_credit_card_csv_file(tmp_path: Path):
    content = (
        "data,lançamento,valor\n"
        "2026-02-27,KALUNGA-ALPH-CT LE,5.5\n"
        "2026-02-22,DESCONTO NA FATURA - PO,-646.28\n"
    )
    f = tmp_path / "fatura_real_itau.csv"
    f.write_text(content, encoding="utf-8")
    return f
