from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from .api_schemas import CreateUserRequest, ResetPasswordRequest, UserOut
from .deps import get_conn, require_admin
from .repos import create_user, get_user_by_id, get_user_by_username, update_user_password
from .security import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/users", response_model=UserOut, dependencies=[Depends(require_admin)])
def admin_create_user(
    body: CreateUserRequest,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> UserOut:
    existing = get_user_by_username(conn, body.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    uid = create_user(conn, body.username, hash_password(body.password), is_admin=body.is_admin)
    user = get_user_by_id(conn, uid)
    assert user is not None
    return UserOut(id=int(user["id"]), username=user["username"], is_admin=bool(user["is_admin"]))


@router.post("/users/{user_id}/reset_password", dependencies=[Depends(require_admin)])
def admin_reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> dict[str, str]:
    user = get_user_by_id(conn, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update_user_password(conn, user_id, hash_password(body.new_password))
    return {"status": "ok"}

