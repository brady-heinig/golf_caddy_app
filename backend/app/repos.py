from __future__ import annotations

from typing import Any

import psycopg

def get_user_by_username(conn: psycopg.Connection, username: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, username, password_hash, is_admin, created_at FROM users WHERE username = %s",
        (username,),
    ).fetchone()
    return dict(row) if row else None


def get_user_by_id(conn: psycopg.Connection, user_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, username, is_admin, created_at FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def create_user(
    conn: psycopg.Connection,
    username: str,
    password_hash: str,
    is_admin: bool = False,
) -> int:
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s) RETURNING id",
        (username, password_hash, bool(is_admin)),
    )
    conn.commit()
    row = cur.fetchone()
    assert row is not None
    return int(row["id"])


def update_user_password(conn: psycopg.Connection, user_id: int, password_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))
    conn.commit()


def create_session(
    conn: psycopg.Connection,
    user_id: int,
    token_hash: str,
    expires_at_iso: str,
) -> None:
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (user_id, token_hash, expires_at_iso),
    )
    conn.commit()


def delete_session(conn: psycopg.Connection, token_hash: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash,))
    conn.commit()


def get_session_user_id(conn: psycopg.Connection, token_hash: str) -> int | None:
    row = conn.execute(
        """
        SELECT user_id
        FROM sessions
        WHERE token_hash = %s
          AND expires_at > now()
        """,
        (token_hash,),
    ).fetchone()
    return int(row["user_id"]) if row else None


def cleanup_expired_sessions(conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM sessions WHERE expires_at <= now()")
    conn.commit()

