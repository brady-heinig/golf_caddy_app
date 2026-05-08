from __future__ import annotations

import json
import os
import re
from typing import Annotated, Any

import anthropic
import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .caddie_advice_context import build_caddie_advice_context
from .caddie_lie_detect import classify_lie_from_blue_dot
from .caddie_shot_intel import resolve_intended_landing
from .elevenlabs_tts import synthesize_speech_mp3
from .legacy import course_data as course_data_mod
from .legacy import course_features
from .routes_caddie_compat import get_course, get_hole, get_plays_like_path, list_courses
from .bag_selection import (
    normalize_shot_shapes,
    pick_club_for_plays_like_yards,
    shot_shape_for_club,
)
from .caddie_advice_llm import run_caddie_advice_chain
from .deps import get_conn, get_current_user

router = APIRouter(prefix="/caddie", tags=["caddie"])

# Matches "SUMMARY:" with optional markdown bold; model often emits **SUMMARY:** on its own line.
_CADDIE_SUMMARY_HEAD = re.compile(
    r"(?:^|[\r\n])\s*(?:#{1,6}\s+)?\*{0,2}\s*SUMMARY\s*:\s*\*{0,2}\s*",
    re.IGNORECASE,
)


def tts_text_summary_only(text: str) -> str:
    """ElevenLabs should speak only the SUMMARY paragraph when present (strip labeled briefing above)."""
    t = (text or "").strip()
    if not t:
        return t
    m = _CADDIE_SUMMARY_HEAD.search(t)
    if not m:
        return t
    rest = t[m.end() :].strip()
    return rest if rest else t


class CaddieAdviceIn(BaseModel):
    course_id: str = Field(min_length=1, max_length=128)
    hole_number: int = Field(ge=1, le=18)
    player_lat: float = Field(ge=-90, le=90)
    player_lon: float = Field(ge=-180, le=180)
    bend_lat: float | None = Field(default=None)
    bend_lon: float | None = Field(default=None)
    message: str | None = Field(default=None, max_length=2000)


class CaddieAdviceOut(BaseModel):
    briefing: str = Field(description="Eight labeled briefing lines (shown behind dropdown in app)")
    summary: str = Field(description="Single spoken paragraph for display and TTS")
    assistant: str = Field(
        description="Full legacy text: briefing + --- + SUMMARY: summary (for older clients)",
    )


class CaddieTtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice_id: str | None = Field(default=None, max_length=64)


def _get_user_settings(conn: psycopg.Connection, user_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT handicap_index, bag_json, shot_shapes_json FROM user_settings WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    if not row:
        return {"handicap_index": 15.0, "bag": {}, "shot_shapes": {}}
    bag = json.loads(row["bag_json"]) if row["bag_json"] else {}
    h = row["handicap_index"] if row["handicap_index"] is not None else 15.0
    shot_shapes = json.loads(row["shot_shapes_json"]) if row["shot_shapes_json"] else {}
    return {"handicap_index": float(h), "bag": bag, "shot_shapes": shot_shapes}


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
    shot_shapes_store = s.get("shot_shapes") or {}
    shot_shapes_norm = normalize_shot_shapes(shot_shapes_store if isinstance(shot_shapes_store, dict) else {})

    course = course_data_mod.COURSES.get(body.course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Unknown course_id")
    holes = course.get("holes") or []
    if body.hole_number < 1 or body.hole_number > len(holes):
        raise HTTPException(status_code=404, detail="Invalid hole_number")
    hole_dict = holes[body.hole_number - 1]
    try:
        features_for_lie = course_features.load_hole_feature_collection(body.course_id, body.hole_number)
    except Exception:
        features_for_lie = {"type": "FeatureCollection", "features": []}

    lie_auto, lie_meta = classify_lie_from_blue_dot(
        body.player_lat,
        body.player_lon,
        hole_dict,
        features_for_lie,
    )

    payload = get_hole(
        course_id=body.course_id,
        hole_number=body.hole_number,
        player_lat=body.player_lat,
        player_lon=body.player_lon,
        handicap=hcp,
        lie=lie_auto,
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
        lie_auto,
        dist_pin,
    )

    wx = payload["weather"]
    features = payload["features"]
    course_nm = (payload.get("course") or {}).get("name")

    plays_like = float(metrics.get("plays_like_yd") or 0.0)
    club_pick = pick_club_for_plays_like_yards(bag, plays_like)
    eff_shape = shot_shape_for_club(str(club_pick["club"]), shot_shapes_norm)

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
        lie=lie_auto.lower(),
        shot_shape=eff_shape,
        handicap=hcp,
        bag=bag,
        shot_shapes=shot_shapes_norm,
        lie_detect_meta=lie_meta,
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
        briefing, summary_plain = run_caddie_advice_chain(
            ctx=ctx,
            user_line=user_line,
            client=client,
            model=model,
        )
        assistant = f"{briefing}\n---\nSUMMARY: {summary_plain}"
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Caddie unavailable: {e}",
        ) from e

    return CaddieAdviceOut(briefing=briefing, summary=summary_plain, assistant=assistant)


@router.post("/tts")
def caddie_text_to_speech(
    body: CaddieTtsIn,
    _user: Annotated[dict, Depends(get_current_user)],
) -> Response:
    """Convert text to speech via ElevenLabs. API key, model, speed, default voice: environment variables on Render."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ELEVENLABS_API_KEY is not configured on the server",
        )
    voice = (body.voice_id or os.environ.get("ELEVENLABS_VOICE_ID") or "").strip()
    if not voice:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Set ELEVENLABS_VOICE_ID on the server (or pass voice_id). Pick a voice ID from elevenlabs.io → Voices.",
        )

    try:
        spoken = tts_text_summary_only(body.text.strip())
        audio = synthesize_speech_mp3(
            spoken,
            api_key=api_key,
            voice_id=voice,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_friendly_tts_error(str(e)),
        ) from e

    return Response(content=audio, media_type="audio/mpeg")


def _friendly_tts_error(message: str) -> str:
    m = (message or "").lower()
    if "unusual activity" in m or ("free tier" in m and "disabled" in m):
        return (
            "ElevenLabs could not complete this request. Try Device voice or check your account and billing on "
            "elevenlabs.io."
        )
    if "401" in message or "unauthorized" in m:
        return "ElevenLabs API key rejected. Check ELEVENLABS_API_KEY on the server."
    if len(message) > 500:
        return message[:500] + "…"
    return message

