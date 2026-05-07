from __future__ import annotations

from datetime import datetime
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .deps import get_conn, get_current_user

router = APIRouter(prefix="/rounds", tags=["rounds"])


class RoundCreateIn(BaseModel):
    course_id: str = Field(min_length=1, max_length=64)


class RoundOut(BaseModel):
    id: int
    course_id: str
    status: str
    current_hole: int
    started_at: str
    updated_at: str
    notes: str | None = None


class RoundUpdateIn(BaseModel):
    current_hole: int | None = Field(default=None, ge=1, le=18)
    notes: str | None = Field(default=None, max_length=2000)


def _iso(v) -> str:
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _row_to_round(row) -> RoundOut:
    return RoundOut(
        id=int(row["id"]),
        course_id=row["course_id"],
        status=row["status"],
        current_hole=int(row["current_hole"]),
        started_at=_iso(row["started_at"]),
        updated_at=_iso(row["updated_at"]),
        notes=row["notes"],
    )


@router.post("", response_model=RoundOut)
def create_round(
    body: RoundCreateIn,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> RoundOut:
    cur = conn.execute(
        """
        INSERT INTO rounds (user_id, course_id, status, current_hole, started_at, updated_at)
        VALUES (%s, %s, 'active', 1, now(), now())
        RETURNING id
        """,
        (int(user["id"]), body.course_id),
    )
    conn.commit()
    row_id = cur.fetchone()
    assert row_id is not None
    rid = int(row_id["id"])
    row = conn.execute(
        "SELECT * FROM rounds WHERE id = %s AND user_id = %s", (rid, int(user["id"]))
    ).fetchone()
    assert row is not None
    return _row_to_round(row)


@router.get("", response_model=list[RoundOut])
def list_rounds(
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    status_filter: str | None = None,
) -> list[RoundOut]:
    q = "SELECT * FROM rounds WHERE user_id = %s"
    args: list = [int(user["id"])]
    if status_filter:
        q += " AND status = %s"
        args.append(status_filter)
    q += " ORDER BY updated_at DESC"
    rows = conn.execute(q, tuple(args)).fetchall()
    return [_row_to_round(r) for r in rows]


@router.get("/{round_id}", response_model=RoundOut)
def get_round(
    round_id: int,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> RoundOut:
    row = conn.execute(
        "SELECT * FROM rounds WHERE id = %s AND user_id = %s",
        (round_id, int(user["id"])),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Round not found")
    return _row_to_round(row)


@router.put("/{round_id}", response_model=RoundOut)
def update_round(
    round_id: int,
    body: RoundUpdateIn,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> RoundOut:
    row = conn.execute(
        "SELECT * FROM rounds WHERE id = %s AND user_id = %s",
        (round_id, int(user["id"])),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Round not found")
    if row["status"] != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Round not active")

    current_hole = body.current_hole if body.current_hole is not None else int(row["current_hole"])
    notes = body.notes if body.notes is not None else row["notes"]
    conn.execute(
        """
        UPDATE rounds
        SET current_hole = %s, notes = %s, updated_at = now()
        WHERE id = %s AND user_id = %s
        """,
        (current_hole, notes, round_id, int(user["id"])),
    )
    conn.commit()
    updated = conn.execute(
        "SELECT * FROM rounds WHERE id = %s AND user_id = %s",
        (round_id, int(user["id"])),
    ).fetchone()
    assert updated is not None
    return _row_to_round(updated)


@router.post("/{round_id}/finish", response_model=RoundOut)
def finish_round(
    round_id: int,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> RoundOut:
    conn.execute(
        """
        UPDATE rounds
        SET status = 'finished', updated_at = now()
        WHERE id = %s AND user_id = %s AND status = 'active'
        """,
        (round_id, int(user["id"])),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM rounds WHERE id = %s AND user_id = %s", (round_id, int(user["id"]))
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Round not found")
    return _row_to_round(row)


@router.delete("/{round_id}")
def delete_round(
    round_id: int,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> dict[str, str]:
    # Soft delete: keep rows for audit; chat/shots will remain unless we later cascade/purge.
    conn.execute(
        """
        UPDATE rounds
        SET status = 'deleted', updated_at = now()
        WHERE id = %s AND user_id = %s
        """,
        (round_id, int(user["id"])),
    )
    conn.commit()
    return {"status": "ok"}

