from __future__ import annotations

from typing import Annotated

import os

import psycopg
from fastapi import Cookie, Depends, HTTPException, Response, status

from .config import load_settings
from .db import connect
from .repos import get_session_user_id, get_user_by_id
from .security import token_hash

SESSION_COOKIE = "ac_session"


def session_cookie_security() -> tuple[bool, str]:
    """Returns (secure, samesite) for API session cookie.

    Split hosting (e.g. Vercel frontend + Fly API) requires SameSite=None and Secure=True
    so the browser attaches the cookie on cross-origin fetch(..., credentials: 'include').
    Local dev typically uses SECURE_COOKIES=0 and default SameSite=Lax on http://localhost.
    """
    secure = os.environ.get("SECURE_COOKIES", "1").strip() != "0"
    raw = os.environ.get("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    if raw not in ("lax", "strict", "none"):
        raw = "lax"
    if raw == "none" and not secure:
        raw = "lax"
    return secure, raw


def get_conn():
    settings = load_settings()
    conn = connect(settings.database_url)
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    ac_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict:
    if not ac_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    uid = get_session_user_id(conn, token_hash(ac_session))
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    user = get_user_by_id(conn, uid)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    return user


def require_admin(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if not bool(user.get("is_admin")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


def clear_session_cookie(resp: Response) -> None:
    secure_cookie, samesite = session_cookie_security()
    resp.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=secure_cookie,
        samesite=samesite,
        path="/",
    )

