from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .bag_selection import normalize_shot_shapes
from .deps import get_conn, get_current_user

router = APIRouter(prefix="/me", tags=["me"])


class UserSettingsOut(BaseModel):
    handicap_index: float | None = None
    bag: dict[str, Any] | None = None
    shot_shapes: dict[str, Any] | None = None


class UserSettingsIn(BaseModel):
    handicap_index: float | None = Field(default=None, ge=0.0, le=54.0)
    bag: dict[str, Any] | None = None
    shot_shapes: dict[str, Any] | None = None


class ShotHistoryItem(BaseModel):
    id: int
    round_id: int | None = None
    course_id: str
    hole: int
    shot_number: int
    club: str
    distance_to_pin_before: int | None = None
    distance_achieved: int | None = None
    lie: str | None = None
    shot_shape: str | None = None
    result: str | None = None
    notes: str | None = None
    proximity_ft: int | None = None
    logged_at: str
    recommended_club: str | None = None
    advised_plays_like_yd: float | None = None
    feedback_transcript: str | None = None


def _iso(ts: datetime | Any) -> str:
    if ts is None:
        return ""
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


@router.get("/shots", response_model=list[ShotHistoryItem])
def list_shot_history(
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[ShotHistoryItem]:
    """Logged shots for the current user (caddie feedback, round shots, newest first).

    Requires migration `004_shot_feedback_postgres.sql` for optional columns; otherwise use base `shots` columns only.
    """
    uid = int(user["id"])
    try:
        rows = conn.execute(
            """
            SELECT id, round_id, course_id, hole, shot_number, club,
                   distance_to_pin_before, distance_achieved, lie, shot_shape, result, notes, proximity_ft, logged_at,
                   recommended_club, advised_plays_like_yd, feedback_transcript
            FROM shots
            WHERE user_id = %s
            ORDER BY logged_at DESC
            LIMIT %s
            """,
            (uid, limit),
        ).fetchall()
    except Exception as e:
        err = str(e).lower()
        if "undefined_column" not in err and "does not exist" not in err:
            raise
        rows = conn.execute(
            """
            SELECT id, round_id, course_id, hole, shot_number, club,
                   distance_to_pin_before, distance_achieved, lie, shot_shape, result, notes, proximity_ft, logged_at,
                   NULL::text AS recommended_club,
                   NULL::double precision AS advised_plays_like_yd,
                   NULL::text AS feedback_transcript
            FROM shots
            WHERE user_id = %s
            ORDER BY logged_at DESC
            LIMIT %s
            """,
            (uid, limit),
        ).fetchall()
    out: list[ShotHistoryItem] = []
    for r in rows:
        adv = r.get("advised_plays_like_yd")
        out.append(
            ShotHistoryItem(
                id=int(r["id"]),
                round_id=int(r["round_id"]) if r.get("round_id") is not None else None,
                course_id=str(r["course_id"]),
                hole=int(r["hole"]),
                shot_number=int(r["shot_number"]),
                club=str(r["club"]),
                distance_to_pin_before=r.get("distance_to_pin_before"),
                distance_achieved=r.get("distance_achieved"),
                lie=r.get("lie"),
                shot_shape=r.get("shot_shape"),
                result=r.get("result"),
                notes=r.get("notes"),
                proximity_ft=r.get("proximity_ft"),
                logged_at=_iso(r.get("logged_at")),
                recommended_club=r.get("recommended_club"),
                advised_plays_like_yd=float(adv) if adv is not None else None,
                feedback_transcript=r.get("feedback_transcript"),
            )
        )
    return out


@router.get("/settings", response_model=UserSettingsOut)
def get_settings(
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> UserSettingsOut:
    row = conn.execute(
        "SELECT handicap_index, bag_json, shot_shapes_json FROM user_settings WHERE user_id = %s",
        (int(user["id"]),),
    ).fetchone()
    if not row:
        return UserSettingsOut(
            handicap_index=None,
            bag=None,
            shot_shapes=normalize_shot_shapes(None),
        )
    bag = json.loads(row["bag_json"]) if row["bag_json"] else None
    shot_shapes = json.loads(row["shot_shapes_json"]) if row["shot_shapes_json"] else None
    return UserSettingsOut(
        handicap_index=row["handicap_index"],
        bag=bag,
        shot_shapes=normalize_shot_shapes(shot_shapes),
    )


@router.put("/settings", response_model=UserSettingsOut)
def put_settings(
    body: UserSettingsIn,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> UserSettingsOut:
    bag_json = json.dumps(body.bag) if body.bag is not None else None
    shot_shapes_json = json.dumps(body.shot_shapes) if body.shot_shapes is not None else None
    conn.execute(
        """
        INSERT INTO user_settings (user_id, handicap_index, bag_json, shot_shapes_json, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT(user_id) DO UPDATE SET
          handicap_index = excluded.handicap_index,
          bag_json = excluded.bag_json,
          shot_shapes_json = COALESCE(excluded.shot_shapes_json, user_settings.shot_shapes_json),
          updated_at = now()
        """,
        (int(user["id"]), body.handicap_index, bag_json, shot_shapes_json),
    )
    conn.commit()
    out_shapes = normalize_shot_shapes(body.shot_shapes) if body.shot_shapes is not None else None
    return UserSettingsOut(
        handicap_index=body.handicap_index,
        bag=body.bag,
        shot_shapes=out_shapes,
    )

