from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import Depends

from .config import load_settings
from .db import connect
from .repos import ensure_default_user, get_user_by_id


def get_conn():
    settings = load_settings()
    conn = connect(settings.database_url)
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> dict:
    # Auth removed: operate as a single-user app backed by the DB.
    uid = ensure_default_user(conn)
    user = get_user_by_id(conn, uid)
    assert user is not None
    return user

