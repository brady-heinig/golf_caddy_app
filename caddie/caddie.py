"""Claude API prompt builder and caller for the AI Golf Caddie."""

from __future__ import annotations

import math
import os
from typing import Any

import anthropic

from weather import bearing_tee_to_green, wind_relative_to_hole

SYSTEM_PROMPT = """
You are an expert golf caddie assistant. You give concise, actionable advice.

When recommending a club and shot:
- Lead with the club name and aim point on the FIRST line
- Follow with 2–3 sentences of reasoning
- Account for wind, lie, shot shape tendency, and hazard positions
- Reference the player's actual shot history when available
- Use the handicap-adjusted PGA benchmark block when present — it estimates typical GIR % and proximity for this distance; do not contradict it unless user history clearly differs
- Keep total response under 120 words — the player is on the course

Format your response exactly like this:
CLUB: [club name]
AIM: [aim point description, e.g. "center of green", "5 yds left of pin"]
---
[2–3 sentence rationale]
"""


def haversine_yards(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in yards between two lat/lon points."""
    r_earth = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    meters = r_earth * 2 * math.asin(math.sqrt(a))
    return meters * 1.09361


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Forward azimuth (bearing) from point 1 to point 2, degrees 0–360."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def haversine_yards_from_player(
    player_position: dict[str, float] | None, point: dict[str, float]
) -> float | None:
    if player_position is None:
        return None
    return haversine_yards(
        player_position["lat"],
        player_position["lon"],
        point["lat"],
        point["lon"],
    )


def build_user_prompt(
    distance_to_pin: int,
    lie: str,
    shot_shape: str,
    weather: dict[str, Any] | None,
    hole_data: dict[str, Any],
    shot_history: str,
    player_lat: float | None,
    player_lon: float | None,
    benchmark_block: str = "",
    *,
    plays_like_yds: int | None = None,
    el_change_ft: float | None = None,
) -> str:
    w = weather or {}
    wind_deg = w.get("wind_dir_deg")
    tee_to_green_brg = bearing_tee_to_green(hole_data["tee"], hole_data["green_center"])
    if wind_deg is not None:
        # Match weather along-shot math: bearing from golfer to pin (not tee-only line).
        if player_lat is not None and player_lon is not None:
            gc = hole_data["green_center"]
            shot_brg = bearing_degrees(player_lat, player_lon, gc["lat"], gc["lon"])
        else:
            shot_brg = tee_to_green_brg
        wind_desc = wind_relative_to_hole(int(wind_deg), float(shot_brg))
    else:
        wind_desc = "unknown"

    hazard_lines = "\n".join(
        f"  - {h['type'].upper()} ({h['note']})" for h in hole_data.get("hazards", [])
    )

    gf = hole_data["green_front"]
    gb = hole_data["green_back"]
    green_depth = haversine_yards(gf["lat"], gf["lon"], gb["lat"], gb["lon"])

    player_position: dict[str, float] | None = None
    if player_lat is not None and player_lon is not None:
        player_position = {"lat": player_lat, "lon": player_lon}

    yd_front = haversine_yards_from_player(player_position, hole_data["green_front"])
    yd_back = haversine_yards_from_player(player_position, hole_data["green_back"])

    def _fmt_yards(v: float | None) -> str:
        return f"{v:.0f} yds (approx)" if v is not None else "N/A (set distance manually)"

    temp_s = f"{w['temp_f']:.0f}°F" if w.get("temp_f") is not None else "N/A"
    wind_mph_s = f"{w['wind_mph']:.0f} mph" if w.get("wind_mph") is not None else "N/A"
    card = w.get("wind_dir_card") or "N/A"
    hum_s = f"{w['humidity_pct']}%" if w.get("humidity_pct") is not None else "N/A"
    cond_s = w.get("condition") or "N/A"

    pl_line = ""
    if plays_like_yds is not None and el_change_ft is not None:
        el_yd = el_change_ft / 3.0
        pl_line = (
            f"\n  Plays-like:       {plays_like_yds} yds "
            f"(elev change {el_yd:+.1f} yd)"
        )

    return f"""
HOLE {hole_data['number']} — Par {hole_data['par']} — {hole_data['yards']} yds
Hole notes: {hole_data.get('notes', 'N/A')}

CURRENT SHOT:
  Distance to pin:  {distance_to_pin} yds{pl_line}
  Green front edge: {_fmt_yards(yd_front)}
  Green back edge:  {_fmt_yards(yd_back)}
  Green depth:      {green_depth:.0f} yds
  Lie:              {lie}
  Shot shape:       {shot_shape}

WEATHER:
  Temp:      {temp_s}
  Wind:      {wind_mph_s} — {wind_desc} ({card})
  Humidity:  {hum_s}
  Condition: {cond_s}

HAZARDS ON THIS HOLE:
{hazard_lines if hazard_lines else "  None recorded"}

PLAYER'S RECENT HISTORY (similar distances):
{shot_history if shot_history else "  No history yet for this distance range."}

HANDICAP-ADJUSTED BENCHMARK (fairway approach table, blended with user logs when enough data):
{benchmark_block if benchmark_block.strip() else "  (Unavailable)"}

What club and aim point do you recommend?
"""


def call_claude(system: str, user: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text


def get_caddie_advice(
    distance_to_pin: int,
    lie: str,
    shot_shape: str,
    weather: dict[str, Any] | None,
    hole_data: dict[str, Any],
    shot_history: str,
    player_lat: float | None = None,
    player_lon: float | None = None,
    benchmark_block: str = "",
    *,
    plays_like_yds: int | None = None,
    el_change_ft: float | None = None,
) -> str:
    """
    Build context prompt and call Claude API.
    Returns the assistant's text response as a string.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY missing")

    user_prompt = build_user_prompt(
        distance_to_pin,
        lie,
        shot_shape,
        weather,
        hole_data,
        shot_history,
        player_lat,
        player_lon,
        benchmark_block,
        plays_like_yds=plays_like_yds,
        el_change_ft=el_change_ft,
    )
    return call_claude(SYSTEM_PROMPT, user_prompt)
