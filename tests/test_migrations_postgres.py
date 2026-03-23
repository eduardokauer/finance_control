from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from app.core.config import settings
from app.core.migrations import run_sql_migrations


def _to_psycopg_dsn(sqlalchemy_dsn: str) -> str:
    return sqlalchemy_dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _database_name_from_dsn(dsn: str) -> str:
    return dsn.rsplit("/", 1)[-1].split("?", 1)[0]


def _build_temp_database_url(base_url: str, database_name: str) -> str:
    prefix, _, suffix = base_url.rpartition("/")
    if not prefix:
        raise ValueError("Invalid DATABASE_URL")
    return f"{prefix}/{database_name}"


def _postgres_available() -> bool:
    return settings.database_url.startswith("postgresql+psycopg://")


def _migration_files() -> list[Path]:
    return sorted((Path(__file__).resolve().parents[1] / "supabase" / "migrations").glob("*.sql"))


@pytest.mark.skipif(not _postgres_available(), reason="requires postgres DATABASE_URL")
def test_sql_migrations_are_idempotent_in_postgres(monkeypatch):
    base_url = settings.database_url
    admin_dsn = _to_psycopg_dsn(base_url)
    admin_db = _database_name_from_dsn(admin_dsn)
    temp_db_name = f"fc_migrate_{uuid4().hex[:8]}"
    temp_url = _build_temp_database_url(base_url, temp_db_name)
    temp_dsn = _to_psycopg_dsn(temp_url)

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'create database "{temp_db_name}"')

    try:
        monkeypatch.setattr(settings, "database_url", temp_url)

        first_applied = run_sql_migrations()
        assert first_applied, "expected at least one migration to be applied in a fresh database"

        with psycopg.connect(temp_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from schema_migrations")
                first_schema_migrations = cur.fetchone()[0]

                cur.execute("select count(*) from categories")
                first_categories = cur.fetchone()[0]

                cur.execute("select count(*) from categories where transaction_kind is null")
                null_category_kinds = cur.fetchone()[0]

                cur.execute("select count(*) from categorization_rules")
                first_rules = cur.fetchone()[0]

                cur.execute("select count(*) from categorization_rules where kind_mode is null")
                null_rule_kinds = cur.fetchone()[0]

                cur.execute("select count(*) from transaction_audit_logs")
                audit_log_rows = cur.fetchone()[0]

        second_applied = run_sql_migrations()
        assert second_applied == []

        migration_files = _migration_files()
        assert first_schema_migrations == len(migration_files)
        assert first_categories > 0
        assert first_rules > 0
        assert null_category_kinds == 0
        assert null_rule_kinds == 0
        assert audit_log_rows == 0

        with psycopg.connect(temp_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from schema_migrations")
                assert cur.fetchone()[0] == first_schema_migrations

                cur.execute("select count(*) from categories")
                assert cur.fetchone()[0] == first_categories

                cur.execute("select count(*) from categorization_rules")
                assert cur.fetchone()[0] == first_rules

                cur.execute("select count(*) from categories where transaction_kind is null")
                assert cur.fetchone()[0] == 0

                cur.execute("select count(*) from categorization_rules where kind_mode is null")
                assert cur.fetchone()[0] == 0
    finally:
        monkeypatch.setattr(settings, "database_url", base_url)
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select pg_terminate_backend(pid)
                    from pg_stat_activity
                    where datname = %s and pid <> pg_backend_pid()
                    """,
                    (temp_db_name,),
                )
                cur.execute(f'drop database if exists "{temp_db_name}"')


@pytest.mark.skipif(not _postgres_available(), reason="requires postgres DATABASE_URL")
def test_rule_kind_mode_migration_converts_legacy_transaction_kind(monkeypatch):
    base_url = settings.database_url
    admin_dsn = _to_psycopg_dsn(base_url)
    temp_db_name = f"fc_kind_mode_{uuid4().hex[:8]}"
    temp_url = _build_temp_database_url(base_url, temp_db_name)
    temp_dsn = _to_psycopg_dsn(temp_url)
    migration_files = _migration_files()
    legacy_files = [migration for migration in migration_files if migration.name < "007_rule_kind_mode.sql"]

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'create database "{temp_db_name}"')

    try:
        with psycopg.connect(temp_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    create table if not exists schema_migrations (
                        version text primary key,
                        applied_at timestamptz not null default now()
                    )
                    """
                )
                conn.commit()
                for migration_file in legacy_files:
                    with conn.transaction():
                        cur.execute(migration_file.read_text(encoding="utf-8"))
                        cur.execute("insert into schema_migrations(version) values (%s)", (migration_file.name,))

                cur.execute(
                    "insert into categorization_rules(rule_type, pattern, category_name, transaction_kind, priority) values (%s, %s, %s, %s, %s)",
                    ("contains", "regra-flow-legada", "Outros", "expense", 999),
                )
                cur.execute(
                    "insert into categorization_rules(rule_type, pattern, category_name, transaction_kind, priority) values (%s, %s, %s, %s, %s)",
                    ("contains", "regra-transfer-legada", "Transferências", "transfer", 998),
                )
                conn.commit()

                cur.execute("select distinct transaction_kind from categorization_rules where pattern like %s", ("regra-%",))
                legacy_kinds = {row[0] for row in cur.fetchall()}
                assert legacy_kinds == {"expense", "transfer"}

        monkeypatch.setattr(settings, "database_url", temp_url)
        applied = run_sql_migrations()
        expected_applied = [migration.name for migration in migration_files if migration.name >= "007_rule_kind_mode.sql"]
        assert applied == expected_applied

        with psycopg.connect(temp_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from categorization_rules where kind_mode = 'flow'")
                flow_count = cur.fetchone()[0]

                cur.execute("select count(*) from categorization_rules where kind_mode = 'transfer'")
                transfer_count = cur.fetchone()[0]

                cur.execute("select count(*) from categorization_rules where kind_mode not in ('flow', 'transfer')")
                invalid_count = cur.fetchone()[0]

                cur.execute("select count(*) from information_schema.columns where table_name = 'categorization_rules' and column_name = 'kind_mode'")
                has_kind_mode = cur.fetchone()[0]

                cur.execute("select count(*) from information_schema.columns where table_name = 'categorization_rules' and column_name = 'transaction_kind'")
                has_legacy_column = cur.fetchone()[0]

        assert flow_count > 0
        assert transfer_count > 0
        assert invalid_count == 0
        assert has_kind_mode == 1
        assert has_legacy_column == 0
    finally:
        monkeypatch.setattr(settings, "database_url", base_url)
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select pg_terminate_backend(pid)
                    from pg_stat_activity
                    where datname = %s and pid <> pg_backend_pid()
                    """,
                    (temp_db_name,),
                )
                cur.execute(f'drop database if exists "{temp_db_name}"')


