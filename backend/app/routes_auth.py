from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

import psycopg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from .api_schemas import LoginRequest, UserOut
from .deps import SESSION_COOKIE, clear_session_cookie, get_conn, session_cookie_security
from .repos import create_session, delete_session, get_user_by_username
from .security import expires_at, new_session_token, token_hash, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest,
    resp: Response,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> UserOut:
    user = get_user_by_username(conn, body.username)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    tok = new_session_token()
    exp = expires_at()
    create_session(conn, int(user["id"]), token_hash(tok), exp.isoformat())
    now = datetime.now(timezone.utc)
    max_age = int((exp - now).total_seconds())

    secure_cookie, samesite = session_cookie_security()
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=tok,
        httponly=True,
        secure=secure_cookie,
        samesite=samesite,
        max_age=max_age,
        path="/",
    )
    return UserOut(id=int(user["id"]), username=user["username"], is_admin=bool(user["is_admin"]))


@router.post("/logout")
def logout(
    resp: Response,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    ac_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, str]:
    if ac_session:
        delete_session(conn, token_hash(ac_session))
    clear_session_cookie(resp)
    return {"status": "ok"}

