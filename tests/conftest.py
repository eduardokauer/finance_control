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
