from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import anthropic
import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from shapely.geometry import LineString, Point
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
from .caddie_voice_llm import (
    best_bag_key_for_extraction,
    extract_shot_feedback_json,
    format_voice_hole_situation,
    generate_last_shot_question,
    refine_bag_carry,
    voice_followup_answer,
    voice_thread_reply,
)
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
    recommended_club: str = Field(default="Unknown", description="Club label from bag selection for plays-like yards")
    plays_like_context_yd: float = Field(default=0.0, ge=0.0, description="Adjusted plays-like context for that hint")


class CaddieTtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice_id: str | None = Field(default=None, max_length=64)


class PrepLastShotIn(BaseModel):
    course_id: str = Field(min_length=1, max_length=128)
    hole_number: int = Field(ge=1, le=18)
    recommended_club: str = Field("", max_length=64)
    plays_like_context_yd: float = Field(ge=0.0, le=700.0)


class PrepLastShotOut(BaseModel):
    question: str


class LogShotFeedbackIn(BaseModel):
    course_id: str = Field(min_length=1, max_length=128)
    hole_number: int = Field(ge=1, le=18)
    transcript: str = Field(min_length=1, max_length=4000)
    prior_recommended_club: str = Field("", max_length=64)
    prior_plays_like_yd: float = Field(ge=0.0, le=700.0)


class LogShotFeedbackOut(BaseModel):
    logged: bool
    club_normalized: str | None = None
    outcome: str | None = None
    bag_updated: bool = False


class VoiceFollowupIn(BaseModel):
    course_id: str = Field(min_length=1, max_length=128)
    hole_number: int = Field(ge=1, le=18)
    player_lat: float = Field(ge=-90, le=90)
    player_lon: float = Field(ge=-180, le=180)
    bend_lat: float | None = Field(default=None)
    bend_lon: float | None = Field(default=None)
    question: str = Field(min_length=2, max_length=2000)
    advice_summary_recent: str | None = Field(default=None, max_length=2000)


class VoiceFollowupOut(BaseModel):
    answer_summary: str


class VoiceConvMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class VoiceConversationTurnIn(BaseModel):
    course_id: str = Field(min_length=1, max_length=128)
    hole_number: int = Field(ge=1, le=18)
    player_lat: float = Field(ge=-90, le=90)
    player_lon: float = Field(ge=-180, le=180)
    bend_lat: float | None = Field(default=None)
    bend_lon: float | None = Field(default=None)
    messages: list[VoiceConvMessageIn] = Field(..., min_length=1, max_length=48)


class VoiceConversationTurnOut(BaseModel):
    answer_summary: str


class SuggestTargetIn(BaseModel):
    course_id: str = Field(min_length=1, max_length=128)
    hole_number: int = Field(ge=1, le=18)
    player_lat: float = Field(ge=-90, le=90)
    player_lon: float = Field(ge=-180, le=180)


class SuggestTargetOut(BaseModel):
    target_lat: float
    target_lon: float
    rationale_short: str | None = None
    used_agent: bool = False  # Legacy field; LLM map target agent removed — always heuristic.


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


def _next_feedback_shot_number(conn: psycopg.Connection, user_id: int, course_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(shot_number), 0) + 1 AS n
        FROM shots
        WHERE user_id = %s AND course_id = %s AND round_id IS NULL
        """,
        (user_id, course_id),
    ).fetchone()
    return int(row["n"]) if row else 1


_LANDING_HINT: dict[str, str] = {
    "map_bend": "Target is your mapped white aiming point.",
    "modeled_tee_carry": "Tee shot carry corridor.",
    "tee_par3_toward_green": "Par-three into the green.",
    "default_fraction_along_pin": "Default fractional target toward the pin.",
}


def _landing_hint_human(meta: dict[str, Any]) -> str:
    how = str(meta.get("how") or "")
    return _LANDING_HINT.get(how, "Current aiming plan from the hole map.")[:160]


@dataclass(frozen=True)
class _VoiceGrounding:
    course_name: str | None
    hole_number: int
    par: int | None
    plays_like_yds: float
    lie_label: str
    landing_hint: str


def _resolve_voice_grounding(
    conn: psycopg.Connection,
    user_id: int,
    *,
    course_id: str,
    hole_number: int,
    player_lat: float,
    player_lon: float,
    bend_lat: float | None,
    bend_lon: float | None,
) -> _VoiceGrounding:
    s = _get_user_settings(conn, user_id)
    bag = dict(s["bag"] or {})
    hcp = float(s["handicap_index"])
    course = course_data_mod.COURSES.get(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Unknown course_id")
    holes = course.get("holes") or []
    if hole_number < 1 or hole_number > len(holes):
        raise HTTPException(status_code=404, detail="Invalid hole_number")
    hole_dict = holes[hole_number - 1]
    try:
        features_for_lie = course_features.load_hole_feature_collection(course_id, hole_number)
    except Exception:
        features_for_lie = {"type": "FeatureCollection", "features": []}
    lie_auto, _lm = classify_lie_from_blue_dot(
        player_lat,
        player_lon,
        hole_dict,
        features_for_lie,
    )
    payload = get_hole(
        course_id=course_id,
        hole_number=hole_number,
        player_lat=player_lat,
        player_lon=player_lon,
        handicap=hcp,
        lie=lie_auto,
    )
    hole_full = payload["hole"]
    metrics = payload["metrics"]
    gc = hole_full["green_center"]
    plays_like_val = metrics.get("plays_like_yd")
    plays_like = float(plays_like_val) if plays_like_val is not None else 0.0
    _llat, _llon, lmeta = resolve_intended_landing(
        player_lat,
        player_lon,
        float(gc["lat"]),
        float(gc["lon"]),
        bend_lat,
        bend_lon,
        bag,
        hole_full,
        lie_auto,
        float(metrics.get("distance_yd") or 0.0),
    )
    crs_nm = (payload.get("course") or {}).get("name")
    landing_h = _landing_hint_human(lmeta if isinstance(lmeta, dict) else {})
    par_hint = hole_full.get("par")
    par_out = int(par_hint) if isinstance(par_hint, (int, float)) else None
    club_ctx_yd = plays_like
    if bend_lat is not None and bend_lon is not None:
        try:
            plp = get_plays_like_path(
                course_id=course_id,
                hole_number=hole_number,
                player_lat=float(player_lat),
                player_lon=float(player_lon),
                bend_lat=float(bend_lat),
                bend_lon=float(bend_lon),
            )
            leg1 = plp.get("leg1_plays_like_yd")
            if leg1 is not None and float(leg1) >= 1.0:
                club_ctx_yd = float(leg1)
        except Exception:
            pass
    return _VoiceGrounding(
        course_name=crs_nm or course.get("name"),
        hole_number=int(hole_number),
        par=par_out,
        plays_like_yds=club_ctx_yd,
        lie_label=str(lie_auto),
        landing_hint=landing_h,
    )


def _validate_bend(body: CaddieAdviceIn) -> None:
    has_b = body.bend_lat is not None or body.bend_lon is not None
    if not has_b:
        return
    if body.bend_lat is None or body.bend_lon is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide both bend_lat and bend_lon, or omit both.",
        )


def _validate_bend_pair(lat: float | None, lon: float | None) -> None:
    has_b = lat is not None or lon is not None
    if not has_b:
        return
    if lat is None or lon is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide both bend_lat and bend_lon, or omit both.",
        )


def _extract_osm_hole_path_lon_lat(features: dict[str, Any]) -> list[tuple[float, float]]:
    """Hole centerline from OSM (`golf=hole`) as (lon, lat) vertices."""
    out: list[tuple[float, float]] = []
    for feat in features.get("features") or []:
        if (feat.get("properties") or {}).get("golf") != "hole":
            continue
        g = feat.get("geometry") or {}
        gt = g.get("type")
        coords = g.get("coordinates") or []
        if gt == "LineString":
            out.extend([(float(c[0]), float(c[1])) for c in coords])
        elif gt == "MultiLineString" and coords:
            for linestring in coords:
                for pt in linestring:
                    out.append((float(pt[0]), float(pt[1])))
        break
    return out


def _snap_lat_lon_to_osm_hole_line(
    lat: float, lon: float, features: dict[str, Any]
) -> tuple[float, float] | None:
    """Project a point onto the mapped OSM hole line (keeps the bend on the same polyline as the map)."""
    path = _extract_osm_hole_path_lon_lat(features)
    if len(path) < 2:
        return None
    try:
        line = LineString(path)
        p = Point(float(lon), float(lat))
        near = line.interpolate(line.project(p))
        return (float(near.y), float(near.x))
    except Exception:
        return None


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
    """Heuristic landing from `resolve_intended_landing`, snapped onto the OSM hole centerline when present."""
    uid = int(user["id"])
    s = _get_user_settings(conn, uid)
    hcp = float(s["handicap_index"])
    bag = dict(s["bag"] or {})

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
    metrics = payload["metrics"]
    dist_pin = float(metrics.get("distance_yd") or 0.0)

    fb_lat, fb_lon, _fb_meta = resolve_intended_landing(
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

    features_fc = payload.get("features") or {}
    if isinstance(features_fc, dict):
        snapped = _snap_lat_lon_to_osm_hole_line(fb_lat, fb_lon, features_fc)
        if snapped is not None:
            fb_lat, fb_lon = snapped

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
    map_target_plays_like_yds: float | None = None
    if body.bend_lat is not None and body.bend_lon is not None:
        try:
            plp = get_plays_like_path(
                course_id=body.course_id,
                hole_number=body.hole_number,
                player_lat=float(body.player_lat),
                player_lon=float(body.player_lon),
                bend_lat=float(body.bend_lat),
                bend_lon=float(body.bend_lon),
            )
            leg1 = plp.get("leg1_plays_like_yd")
            if leg1 is not None and float(leg1) >= 1.0:
                map_target_plays_like_yds = float(leg1)
        except Exception:
            map_target_plays_like_yds = None

    club_context_yd = map_target_plays_like_yds if map_target_plays_like_yds is not None else plays_like
    club_pick = pick_club_for_plays_like_yards(bag, club_context_yd)
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
        map_target_plays_like_yds=map_target_plays_like_yds,
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
            hole_par=int(hole.get("par") or 4),
        )
        assistant = f"{briefing}\n---\nSUMMARY: {summary_plain}"
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Caddie unavailable: {e}",
        ) from e

    return CaddieAdviceOut(
        briefing=briefing,
        summary=summary_plain,
        assistant=assistant,
        recommended_club=str(club_pick.get("club") or "Unknown"),
        plays_like_context_yd=float(club_context_yd),
    )


@router.post("/prep-last-shot", response_model=PrepLastShotOut)
def prep_last_shot_feedback(
    body: PrepLastShotIn,
    _user: Annotated[dict, Depends(get_current_user)],
) -> PrepLastShotOut:
    crs = course_data_mod.COURSES.get(body.course_id)
    crs_nm = crs.get("name") if crs else None
    try:
        q = generate_last_shot_question(
            recommended_club=(body.recommended_club or "recommended club"),
            plays_like_yd=float(body.plays_like_context_yd),
            hole_number=int(body.hole_number),
            course_hint=crs_nm,
        )
    except Exception:
        q = (
            f"Quick one — last time on hole {body.hole_number} I lined you up at about "
            f"{body.plays_like_context_yd:.0f} yards: what'd you hit, and how'd it turn out?"
        )
    q = q.strip() or (
        "What club did you hit on that last swing, and how did the ball react?"
    )
    return PrepLastShotOut(question=q[:340])


@router.post("/log-last-shot-feedback", response_model=LogShotFeedbackOut)
def log_last_shot_feedback(
    body: LogShotFeedbackIn,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> LogShotFeedbackOut:
    uid = int(user["id"])
    s = _get_user_settings(conn, uid)
    bag_raw = dict(s["bag"] or {})
    bag_keys = sorted(str(k) for k in bag_raw.keys())

    extracted: dict[str, Any] = {}
    try:
        extracted = extract_shot_feedback_json(
            transcript=(body.transcript or "").strip(),
            recommended_club=str(body.prior_recommended_club or "unknown"),
            plays_like_yd=float(body.prior_plays_like_yd),
            allowed_bag_clubs=(bag_keys if bag_keys else ["Driver", "7i", "PW"]),
            hole_number=int(body.hole_number),
        )
        if not isinstance(extracted, dict):
            extracted = {}
    except Exception:
        extracted = {}

    cand = extracted.get("club_used_key") or extracted.get("club_used") or ""
    club_key_final = (
        best_bag_key_for_extraction(str(cand), bag_keys) if isinstance(cand, str) else None
    )
    if not club_key_final and isinstance(cand, str) and cand.strip():
        club_key_final = cand.strip()[:32]

    if not club_key_final:
        club_key_final = "Unknown"

    out_str = extracted.get("outcome")
    outcome_s = (
        str(out_str).strip()[:500]
        if out_str not in (None, "")
        else (body.transcript or "")[:500]
    )
    carry_est = extracted.get("estimated_carry_yards")
    dist_ach: int | None
    try:
        dist_ach = int(round(float(carry_est))) if carry_est not in (None, "") else None
    except (TypeError, ValueError):
        dist_ach = None

    sn = _next_feedback_shot_number(conn, uid, body.course_id)
    dist_before = int(round(min(700.0, max(0.0, float(body.prior_plays_like_yd)))))

    conn.execute(
        """
        INSERT INTO shots (
            user_id, round_id, course_id, hole, shot_number,
            club, distance_to_pin_before, distance_achieved, lie,
            shot_shape, result, notes,
            recommended_club, advised_plays_like_yd, feedback_transcript,
            proximity_ft
        )
        VALUES (
            %s, NULL, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            NULL
        )
        """,
        (
            uid,
            body.course_id,
            body.hole_number,
            sn,
            club_key_final,
            dist_before,
            dist_ach,
            "unknown",
            "unknown",
            outcome_s[:500],
            (body.transcript or "")[:3800],
            (body.prior_recommended_club or None),
            float(body.prior_plays_like_yd),
            (body.transcript or "")[:3800],
        ),
    )

    bag_updated = False
    if club_key_final in bag_raw and isinstance(bag_raw, dict) and dist_ach not in (None, 0):
        new_bag, flipped = refine_bag_carry(dict(bag_raw), club_key_final, float(dist_ach))
        if flipped:
            conn.execute(
                "UPDATE user_settings SET bag_json = %s, updated_at = now() WHERE user_id = %s",
                (json.dumps(new_bag), uid),
            )
            bag_updated = True

    conn.commit()

    return LogShotFeedbackOut(
        logged=True,
        club_normalized=club_key_final,
        outcome=outcome_s or None,
        bag_updated=bag_updated,
    )


@router.post("/voice-followup", response_model=VoiceFollowupOut)
def caddie_voice_followup(
    body: VoiceFollowupIn,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> VoiceFollowupOut:
    _validate_bend_pair(body.bend_lat, body.bend_lon)
    uid = int(user["id"])
    g = _resolve_voice_grounding(
        conn,
        uid,
        course_id=body.course_id,
        hole_number=body.hole_number,
        player_lat=body.player_lat,
        player_lon=body.player_lon,
        bend_lat=body.bend_lat,
        bend_lon=body.bend_lon,
    )
    ans = voice_followup_answer(
        question=body.question,
        course_name=g.course_name,
        hole_number=g.hole_number,
        par=g.par,
        plays_like_yds=g.plays_like_yds,
        lie_label=g.lie_label,
        landing_hint=g.landing_hint,
        brief_advice_snippet=body.advice_summary_recent,
    )
    return VoiceFollowupOut(answer_summary=ans.strip())


@router.post("/voice-conversation-turn", response_model=VoiceConversationTurnOut)
def caddie_voice_conversation_turn(
    body: VoiceConversationTurnIn,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> VoiceConversationTurnOut:
    _validate_bend_pair(body.bend_lat, body.bend_lon)
    if body.messages[-1].role != "user":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The last message in `messages` must be from the player (role: user).",
        )
    total_chars = sum(len(m.content) for m in body.messages)
    if total_chars > 24_000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conversation is too long; close and open a new ask session.",
        )
    uid = int(user["id"])
    g = _resolve_voice_grounding(
        conn,
        uid,
        course_id=body.course_id,
        hole_number=body.hole_number,
        player_lat=body.player_lat,
        player_lon=body.player_lon,
        bend_lat=body.bend_lat,
        bend_lon=body.bend_lon,
    )
    situation = format_voice_hole_situation(
        course_name=g.course_name,
        hole_number=g.hole_number,
        par=g.par,
        plays_like_yds=g.plays_like_yds,
        lie_label=g.lie_label,
        landing_hint=g.landing_hint,
    )
    transcript = [(m.role, m.content) for m in body.messages]
    ans = voice_thread_reply(situation=situation, transcript=transcript)
    return VoiceConversationTurnOut(answer_summary=ans.strip())


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

