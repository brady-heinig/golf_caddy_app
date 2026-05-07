from __future__ import annotations

from pathlib import Path

from . import db


def run_migrations(conn, migrations_dir: str | Path) -> None:
    migrations_path = Path(migrations_dir)
    # Prefer Postgres-specific migrations when present.
    pg = sorted(migrations_path.glob("*_postgres.sql"))
    migrations = pg if pg else sorted(migrations_path.glob("*.sql"))
    applied = db.applied_versions(conn)
    for m in migrations:
        version = m.name
        if version in applied:
            continue
        sql = m.read_text(encoding="utf-8")
        db.apply_sql(conn, sql)
        db.record_applied(conn, version)

