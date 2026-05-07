from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


def connect(database_url: str) -> psycopg.Connection[Any]:
    # dict_row makes cursor fetches return plain dict-like rows (matches old sqlite Row usage).
    return psycopg.connect(database_url, row_factory=dict_row)


def ensure_migrations_table(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    conn.commit()


def applied_versions(conn: psycopg.Connection[Any]) -> set[str]:
    ensure_migrations_table(conn)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {str(r["version"]) for r in rows}


def record_applied(conn: psycopg.Connection[Any], version: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version) VALUES (%s)",
        (version,),
    )
    conn.commit()


def apply_sql(conn: psycopg.Connection[Any], sql: str) -> None:
    # psycopg doesn't support multi-statement execute() like sqlite executescript().
    # Our migrations are simple DDL, so a naive splitter is sufficient here.
    stmts: list[str] = []
    for part in sql.split(";"):
        s = part.strip()
        if s:
            stmts.append(s + ";")
    for stmt in stmts:
        conn.execute(stmt)
    conn.commit()

