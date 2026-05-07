from __future__ import annotations

import json
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends
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

