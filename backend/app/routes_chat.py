from __future__ import annotations

import json
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .bag_selection import club_name_for_plays_like_yards as _club_suggestion_from_bag
from .deps import get_conn, get_current_user
from .legacy import benchmark_stats as bench_mod
from .legacy import course_data
from .legacy import weather as weather_mod

router = APIRouter(prefix="/rounds", tags=["chat"])


SYSTEM_PROMPT = (
    "You are an expert golf caddie assistant. You give concise, actionable advice.\n\n"
    "When recommending a club and shot:\n"
    "- Lead with the club name and aim point on the FIRST line\n"
    "- Follow with 2–4 sentences of reasoning\n"
    "- Account for wind, lie, shot shape tendency, and hazard positions\n"
    "- Reference the player's handicap-adjusted green/proximity expectations\n"
    "- For club vs distance: use the **most lofted club in their bag whose listed carry is still >=** the "
    "plays-like yards (same rule as SEED CLUB in context)\n"
    "- Keep total response under 140 words — the player is on the course\n\n"
    "Format your response exactly like this:\n"
    "CLUB: [club name]\n"
    "AIM: [aim point description]\n"
    "---\n"
    "[short rationale]\n"
)


class ChatGetOut(BaseModel):
    round_id: int
    hole: int
    messages: list[dict[str, Any]]


class ChatPostIn(BaseModel):
    hole: int = Field(ge=1, le=18)
    distance_to_pin_yd: int = Field(ge=1, le=500)
    elevation_adjust_yd: float = 0.0
    lie: str = Field(default="fairway", max_length=32)
    shot_shape: str = Field(default="straight", max_length=16)
    message: str = Field(min_length=1, max_length=2000)


class ChatPostOut(BaseModel):
    assistant: str


def _get_round(conn: psycopg.Connection, user_id: int, round_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM rounds WHERE id = %s AND user_id = %s AND status != 'deleted'",
        (round_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Round not found")
    return dict(row)


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


def _build_context(
    course_id: str,
    hole_num: int,
    distance_yd: int,
    elev_adj_yd: float,
    lie: str,
    shot_shape: str,
    handicap_index: float,
    bag: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    course = course_data.COURSES.get(course_id)
    if not course:
        raise HTTPException(status_code=400, detail="Unknown course_id")
    hole = course["holes"][hole_num - 1]

    wx = weather_mod.get_weather(float(course["center_lat"]), float(course["center_lon"]))
    bearing = weather_mod.bearing_tee_to_green(hole["tee"], hole["green_center"])
    wind_rel = (
        weather_mod.wind_relative_to_hole(int(wx["wind_dir_deg"]), float(bearing))
        if wx and not wx.get("error") and wx.get("wind_dir_deg") is not None
        else "unknown"
    )
    wind_mph = wx.get("wind_mph") if wx and not wx.get("error") else None
    wind_card = wx.get("wind_dir_card") if wx and not wx.get("error") else None

    plays_like = float(distance_yd) + float(elev_adj_yd)
    # simple wind plays-like: +1 yd per 1 mph headwind, -1 yd per 2 mph tailwind (heuristic)
    if wind_mph is not None and wind_rel != "unknown":
        if wind_rel == "headwind":
            plays_like += 1.0 * float(wind_mph)
        elif wind_rel == "tailwind":
            plays_like -= 0.5 * float(wind_mph)

    gir_model, tour_gir = bench_mod.expected_gir_model_percent(int(round(plays_like)), handicap_index, lie)
    club_seed = _club_suggestion_from_bag(bag, plays_like)

    hazards = hole.get("hazards", [])
    hz_lines = "\n".join(f"- {h.get('type','hazard')}: {h.get('note','')}" for h in hazards[:12])

    context = f"""
COURSE: {course.get('name')} ({course_id})
HOLE: {hole_num} | Par {hole.get('par')} | Hdcp {hole.get('handicap')} | Card yds {hole.get('yards')}

SHOT:
  Distance to pin: {distance_yd} yds
  Elevation adj:   {elev_adj_yd:+.1f} yds
  Plays-like:      {plays_like:.0f} yds (incl. wind heuristic)
  Lie:             {lie}
  Shot shape:      {shot_shape}

WEATHER:
  Wind: {wind_mph if wind_mph is not None else 'N/A'} mph from {wind_card or 'N/A'} ({wind_rel})
  Temp: {wx.get('temp_f') if wx and not wx.get('error') else 'N/A'} F

BENCHMARKS (handicap-adjusted):
  Est. GIR chance: ~{gir_model:.0f}% (Tour fairway baseline ~{tour_gir:.0f}% @ this distance)

SEED CLUB (from user's bag): {club_seed}

HAZARDS:
{hz_lines if hz_lines else "- None recorded"}
""".strip()

    meta = {
        "plays_like_yd": plays_like,
        "seed_club": club_seed,
        "gir_pct": float(gir_model),
    }
    return context, meta


@router.get("/{round_id}/chat", response_model=ChatGetOut)
def get_chat(
    round_id: int,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    hole: int = 1,
) -> ChatGetOut:
    _get_round(conn, int(user["id"]), round_id)
    rows = conn.execute(
        """
        SELECT role, content, created_at
        FROM chat_messages
        WHERE round_id = %s AND hole = %s
        ORDER BY id ASC
        """,
        (round_id, hole),
    ).fetchall()
    msgs = [dict(r) for r in rows]
    return ChatGetOut(round_id=round_id, hole=hole, messages=msgs)


@router.post("/{round_id}/chat", response_model=ChatPostOut)
def post_chat(
    round_id: int,
    body: ChatPostIn,
    user: Annotated[dict, Depends(get_current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
) -> ChatPostOut:
    r = _get_round(conn, int(user["id"]), round_id)
    if r["status"] != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Round not active")

    s = _get_user_settings(conn, int(user["id"]))
    ctx, _meta = _build_context(
        course_id=r["course_id"],
        hole_num=int(body.hole),
        distance_yd=int(body.distance_to_pin_yd),
        elev_adj_yd=float(body.elevation_adjust_yd),
        lie=body.lie.lower(),
        shot_shape=body.shot_shape.lower(),
        handicap_index=float(s["handicap_index"]),
        bag=dict(s["bag"] or {}),
    )

    # Persist user message
    conn.execute(
        "INSERT INTO chat_messages (round_id, hole, role, content) VALUES (%s, %s, 'user', %s)",
        (round_id, int(body.hole), body.message),
    )
    conn.commit()

    # Build short chat transcript (last N)
    rows = conn.execute(
        """
        SELECT role, content
        FROM chat_messages
        WHERE round_id = %s AND hole = %s
        ORDER BY id DESC
        LIMIT 12
        """,
        (round_id, int(body.hole)),
    ).fetchall()
    transcript = list(reversed([dict(r) for r in rows]))

    # Claude call
    try:
        import anthropic
        import os

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY missing on backend")

        client = anthropic.Anthropic(api_key=api_key)
        # Inject context as a system message at the start of this call, plus transcript as user/assistant turns.
        messages = []
        messages.append(
            {"role": "user", "content": f"CONTEXT\n{ctx}\n\nNow continue the caddie chat."}
        )
        for m in transcript:
            role = m["role"]
            if role not in ("user", "assistant"):
                continue
            messages.append({"role": role, "content": m["content"]})
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        assistant = msg.content[0].text
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Caddie unavailable: {e}")

    conn.execute(
        "INSERT INTO chat_messages (round_id, hole, role, content) VALUES (%s, %s, 'assistant', %s)",
        (round_id, int(body.hole), assistant),
    )
    conn.commit()
    return ChatPostOut(assistant=assistant)

