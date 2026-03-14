from __future__ import annotations

from pathlib import Path

import psycopg

from app.core.config import settings


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def _load_migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def run_sql_migrations() -> list[str]:
    migration_files = _load_migration_files()
    if not migration_files:
        return []

    applied: list[str] = []
    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    with psycopg.connect(dsn) as conn:
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

            for migration_file in migration_files:
                version = migration_file.name
                cur.execute("select 1 from schema_migrations where version = %s", (version,))
                if cur.fetchone():
                    continue

                sql = migration_file.read_text(encoding="utf-8")
                with conn.transaction():
                    cur.execute(sql)
                    cur.execute("insert into schema_migrations(version) values (%s)", (version,))
                applied.append(version)

    return applied
