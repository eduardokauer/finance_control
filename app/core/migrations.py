from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import psycopg

from app.core.config import settings


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


@lru_cache(maxsize=1)
def _load_migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


@lru_cache(maxsize=None)
def _load_migration_sql(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


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
            cur.execute("select version from schema_migrations")
            applied_versions = {row[0] for row in cur.fetchall()}

            for migration_file in migration_files:
                version = migration_file.name
                if version in applied_versions:
                    continue

                sql = _load_migration_sql(str(migration_file))
                with conn.transaction():
                    cur.execute(sql)
                    cur.execute("insert into schema_migrations(version) values (%s)", (version,))
                applied.append(version)
                applied_versions.add(version)

    return applied
