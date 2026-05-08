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
from .caddie_shot_intel import (
    _driver_or_longest_wood_yds,
    fairway_width_at_landing_yds,
    gather_shot_intel,
    hazards_along_corridor,
    resolve_intended_landing,
)
from .caddie_target_agent import (
    build_facts_payload,
    center_target_in_fairway,
    compact_intel_slice,
    finalize_target_coordinates,
    point_ball_to_green_with_offset,
    run_white_target_agent,
)
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


class SuggestTargetIn(BaseModel):
    course_id: str = Field(min_length=1, max_length=128)
    hole_number: int = Field(ge=1, le=18)
    player_lat: float = Field(ge=-90, le=90)
    player_lon: float = Field(ge=-180, le=180)


class SuggestTargetOut(BaseModel):
    target_lat: float
    target_lon: float
    rationale_short: str | None = None
    used_agent: bool = True


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


@router.post("/suggest-target", response_model=SuggestTargetOut)
def caddie_suggest_target(
    body: SuggestTargetIn,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> SuggestTargetOut:
    """Anthropic-powered placement of white map target before caddie advice runs."""
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
    gclat, gclon = float(gc["lat"]), float(gc["lon"])
    tee = hole["tee"]
    tlat, tlon = float(tee["lat"]), float(tee["lon"])
    metrics = payload["metrics"]
    dist_pin = float(metrics.get("distance_yd") or 0.0)
    plays_like = float(metrics.get("plays_like_yd") or dist_pin)

    fb_lat, fb_lon, fb_meta = resolve_intended_landing(
        body.player_lat,
        body.player_lon,
        gclat,
        gclon,
        None,
        None,
        bag,
        hole,
        lie_auto,
        dist_pin,
    )

    features = payload["features"]
    intel = gather_shot_intel(
        hole=hole,
        features=features,
        player_lat=body.player_lat,
        player_lon=body.player_lon,
        landing_lat=fb_lat,
        landing_lon=fb_lon,
        landing_meta=dict(fb_meta),
        bag=bag,
        lie=lie_auto,
        metrics=metrics,
        shot_shapes=shot_shapes_norm,
        lie_detect_detail=lie_meta,
        handicap=hcp,
    )

    # Deterministic shortcut for clearly-open tee shots: if driver landing appears wide/clear,
    # set the marker there so the agent doesn't invent a conservative layup on open holes.
    try:
        pp = intel.get("player_position") or {}
        near_tee_box = bool(pp.get("near_tee_box"))
        par_int = int(hole.get("par") or 4)
    except Exception:
        near_tee_box = False
        par_int = int(hole.get("par") or 4)

    drv = _driver_or_longest_wood_yds(bag)
    if near_tee_box and par_int >= 4 and drv and dist_pin > 120:
        # Put target ~90% of driver carry up the hole.
        t_drv = min(0.92, max(0.28, (float(drv) * 0.90) / max(float(dist_pin), 1.0)))
        cand_lat, cand_lon = point_ball_to_green_with_offset(
            body.player_lat, body.player_lon, gclat, gclon, t_drv, offset_right_m=0.0
        )
        fw_drv = fairway_width_at_landing_yds(features, body.player_lat, body.player_lon, cand_lat, cand_lon)
        trouble_drv = hazards_along_corridor(
            features,
            body.player_lat,
            body.player_lon,
            cand_lat,
            cand_lon,
            ("water_hazard", "lateral_water_hazard", "out_of_bounds"),
            cross_max_yds=70.0,
        )
        inside = bool((fw_drv or {}).get("landing_inside_fairway_polygon")) if fw_drv else False
        width = (fw_drv or {}).get("width_yds") if fw_drv else None
        if inside and (width is None or float(width) >= 24.0) and not trouble_drv:
            centered = center_target_in_fairway(
                features=features,
                player_lat=body.player_lat,
                player_lon=body.player_lon,
                target_lat=float(cand_lat),
                target_lon=float(cand_lon),
            )
            if centered:
                cand_lat, cand_lon = centered
            return SuggestTargetOut(
                target_lat=float(cand_lat),
                target_lon=float(cand_lon),
                rationale_short="Auto target: driver landing (open/wide corridor).",
                used_agent=False,
            )

    facts = build_facts_payload(
        hole_par=int(hole.get("par") or 4),
        card_yards=hole.get("yards"),
        player_lat=body.player_lat,
        player_lon=body.player_lon,
        gc_lat=gclat,
        gc_lon=gclon,
        tee_lat=tlat,
        tee_lon=tlon,
        plays_like_yds=plays_like,
        straight_pin_yds=dist_pin,
        lie=str(lie_auto).lower(),
        bag=bag,
        handicap=hcp,
        intel_compressed=compact_intel_slice(intel),
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return SuggestTargetOut(
            target_lat=fb_lat,
            target_lon=fb_lon,
            rationale_short=None,
            used_agent=False,
        )

    model = os.environ.get("ANTHROPIC_CADDIE_TARGET_MODEL") or os.environ.get(
        "ANTHROPIC_CADDIE_MODEL", "claude-haiku-4-5"
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        parsed = run_white_target_agent(client=client, model=model, facts_json=facts)
        cr = (intel.get("club_recommendation") or {}) if isinstance(intel, dict) else {}
        pp = (intel.get("player_position") or {}) if isinstance(intel, dict) else {}
        aggressive = (
            bool(cr.get("go_for_it"))
            and not bool(cr.get("positional_play_to_landing"))
            and bool(pp.get("near_tee_box"))
            and int(hole.get("par") or 4) >= 4
        )
        # When go-for-it is true on a wide-open tee shot, allow the marker and line to live off fairway a bit
        # (e.g. open right rough) so we don't force a conservative layup just because trees aren't tagged.
        max_off_fw = 42.0 if aggressive else 18.0
        tlat_out, tlon_out = finalize_target_coordinates(
            parsed,
            player_lat=body.player_lat,
            player_lon=body.player_lon,
            gc_lat=gclat,
            gc_lon=gclon,
            hole_features=features,
            fallback_lat=fb_lat,
            fallback_lon=fb_lon,
            max_off_fairway_yd=max_off_fw,
        )
        rationale = parsed.get("rationale_short")
        rationale_s = str(rationale).strip()[:300] if rationale is not None else None
        if aggressive or (near_tee_box and par_int >= 4):
            centered = center_target_in_fairway(
                features=features,
                player_lat=body.player_lat,
                player_lon=body.player_lon,
                target_lat=float(tlat_out),
                target_lon=float(tlon_out),
            )
            if centered:
                tlat_out, tlon_out = centered
        return SuggestTargetOut(
            target_lat=tlat_out,
            target_lon=tlon_out,
            rationale_short=rationale_s or None,
            used_agent=True,
        )
    except Exception:
        return SuggestTargetOut(
            target_lat=fb_lat,
            target_lon=fb_lon,
            rationale_short=None,
            used_agent=False,
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

