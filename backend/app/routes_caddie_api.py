from __future__ import annotations

import json
import os
from typing import Annotated, Any

import anthropic
import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .caddie_advice_context import build_caddie_advice_context
from .caddie_shot_intel import resolve_intended_landing
from .deps import get_conn, get_current_user
from .routes_caddie_compat import get_course, get_hole, get_plays_like_path, list_courses

router = APIRouter(prefix="/caddie", tags=["caddie"])

CADDIE_ADVICE_SYSTEM = (
    "You are an experienced on-course golf caddie. The user message includes STRUCTURED_SHOT_INTEL JSON: "
    "player vs tee, shot_type, intended landing, bunkers/trouble along the corridor to that landing, "
    "fairway width at landing, and a next-shot preview. Treat that JSON as ground truth from the map/geometry.\n"
    "If STRUCTURED_SHOT_INTEL conflicts with narrative text, trust the JSON.\n"
    "For a tee shot on par 4/5: say drive vs fairway-wood vs 3W if relevant, which bunkers/water to respect, "
    "whether the fairway looks wide enough at the modeled landing, and one sentence on what the follow-up shot "
    "likely looks like (distance/club class).\n"
    "If the bag is empty or incomplete, say so briefly and still give safe guidance.\n"
    "STRUCTURED_SHOT_INTEL.club_for_adjusted_plays_like picks the club using the player's bag: "
    "the **smallest listed carry** that is still >= adjusted plays-like yards (most loft for the number). "
    "Default your CLUB line to that club (plus shot type, e.g. 3/4 swing) unless you explicitly recommend "
    "less club for safety or a knockdown.\n\n"
    "Format your answer EXACTLY like this:\n"
    "CURRENT_SHOT: [e.g. tee ball par-4, layup, approach from fairway]\n"
    "CLUB: [club + shot type]\n"
    "AIM: [start line / curve; reference bunkers left/right from JSON]\n"
    "TROUBLE: [what to avoid from bunkers/water lists, or 'clear']\n"
    "FAIRWAY: [use fairway_at_landing width + inside polygon, e.g. 'wide enough' or 'favor X to keep width']\n"
    "NEXT_SHOT: [from next_shot_if_plan_works.summary — shorten if needed]\n"
    "---\n"
    "[2–4 short sentences, under 150 words total]\n"
)


class CaddieAdviceIn(BaseModel):
    course_id: str = Field(min_length=1, max_length=128)
    hole_number: int = Field(ge=1, le=18)
    player_lat: float = Field(ge=-90, le=90)
    player_lon: float = Field(ge=-180, le=180)
    bend_lat: float | None = Field(default=None)
    bend_lon: float | None = Field(default=None)
    lie: str = Field(default="fairway", max_length=48)
    shot_shape: str = Field(default="straight", max_length=24)
    message: str | None = Field(default=None, max_length=2000)


class CaddieAdviceOut(BaseModel):
    assistant: str


def _get_user_settings(conn: psycopg.Connection, user_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT handicap_index, bag_json FROM user_settings WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    if not row:
        return {"handicap_index": 15.0, "bag": {}}
    bag = json.loads(row["bag_json"]) if row["bag_json"] else {}
    h = row["handicap_index"] if row["handicap_index"] is not None else 15.0
    return {"handicap_index": float(h), "bag": bag}


def _validate_bend(body: CaddieAdviceIn) -> None:
    has_b = body.bend_lat is not None or body.bend_lon is not None
    if not has_b:
        return
    if body.bend_lat is None or body.bend_lon is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide both bend_lat and bend_lon, or omit both.",
        )


@router.get("/courses")
def caddie_list_courses() -> list[dict[str, Any]]:
    return list_courses()


@router.get("/course/{course_id}")
def caddie_get_course(course_id: str) -> dict[str, Any]:
    return get_course(course_id)


@router.get("/course/{course_id}/hole/{hole_number}")
def caddie_get_hole(
    course_id: str,
    hole_number: int,
    player_lat: float | None = None,
    player_lon: float | None = None,
    handicap: float | None = None,
    lie: str = "fairway",
) -> dict[str, Any]:
    return get_hole(
        course_id=course_id,
        hole_number=hole_number,
        player_lat=player_lat,
        player_lon=player_lon,
        handicap=handicap,
        lie=lie,
    )


@router.get("/course/{course_id}/hole/{hole_number}/plays-like-path")
def caddie_get_plays_like_path(
    course_id: str,
    hole_number: int,
    player_lat: float,
    player_lon: float,
    bend_lat: float,
    bend_lon: float,
) -> dict[str, Any]:
    return get_plays_like_path(
        course_id=course_id,
        hole_number=hole_number,
        player_lat=player_lat,
        player_lon=player_lon,
        bend_lat=bend_lat,
        bend_lon=bend_lon,
    )


@router.post("/advice", response_model=CaddieAdviceOut)
def caddie_advice(
    body: CaddieAdviceIn,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> CaddieAdviceOut:
    _validate_bend(body)
    uid = int(user["id"])
    s = _get_user_settings(conn, uid)
    hcp = float(s["handicap_index"])
    bag = dict(s["bag"] or {})

    payload = get_hole(
        course_id=body.course_id,
        hole_number=body.hole_number,
        player_lat=body.player_lat,
        player_lon=body.player_lon,
        handicap=hcp,
        lie=body.lie,
    )

    hole = payload["hole"]
    gc = hole["green_center"]
    metrics = payload["metrics"]
    dist_pin = float(metrics.get("distance_yd") or 0.0)
    llat, llon, lmeta = resolve_intended_landing(
        body.player_lat,
        body.player_lon,
        float(gc["lat"]),
        float(gc["lon"]),
        body.bend_lat,
        body.bend_lon,
        bag,
        hole,
        body.lie,
        dist_pin,
    )

    wx = payload["weather"]
    features = payload["features"]
    course_nm = (payload.get("course") or {}).get("name")
    ctx = build_caddie_advice_context(
        course_id=body.course_id,
        course_name=course_nm,
        hole=hole,
        metrics=metrics,
        wx=wx,
        features=features,
        player_lat=body.player_lat,
        player_lon=body.player_lon,
        landing_lat=llat,
        landing_lon=llon,
        landing_meta=lmeta,
        lie=body.lie.lower(),
        shot_shape=body.shot_shape.lower(),
        handicap=hcp,
        bag=bag,
    )

    user_line = (body.message or "").strip()
    if not user_line:
        user_line = "What club and shot should I hit here, and where should I aim?"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY missing on backend")

    # Default: Haiku (fast); override with ANTHROPIC_CADDIE_MODEL, e.g. claude-haiku-4-5-20251001
    model = os.environ.get("ANTHROPIC_CADDIE_MODEL", "claude-haiku-4-5")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=500,
            system=CADDIE_ADVICE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"COURSE CONTEXT\n{ctx}\n\nPLAYER QUESTION\n{user_line}",
                },
            ],
        )
        assistant = msg.content[0].text
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Caddie unavailable: {e}",
        ) from e

    return CaddieAdviceOut(assistant=assistant)

