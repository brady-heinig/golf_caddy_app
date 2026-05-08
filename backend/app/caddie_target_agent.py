from __future__ import annotations

import json
import math
import re
from typing import Any

import anthropic
from shapely.geometry import LineString, Point

from .routes_caddie_compat import haversine_yards


def _latlon_to_xy_m(ref_lat: float, ref_lon: float, lat: float, lon: float) -> tuple[float, float]:
    mid = math.radians((ref_lat + lat) / 2.0)
    scale = 111_320.0 * math.cos(mid)
    x = (lon - ref_lon) * scale
    y = (lat - ref_lat) * 111_320.0
    return (x, y)


def _xy_m_to_latlon(ref_lat: float, ref_lon: float, x: float, y: float) -> tuple[float, float]:
    mid = math.radians(ref_lat + y / 222_640.0)
    lat = ref_lat + y / 111_320.0
    lon = ref_lon + x / (111_320.0 * math.cos(mid))
    return (lat, lon)


def point_ball_to_green_with_offset(
    player_lat: float,
    player_lon: float,
    gc_lat: float,
    gc_lon: float,
    t_along: float,
    *,
    offset_right_m: float = 0.0,
) -> tuple[float, float]:
    """t_along toward green center; offset_right_m = right-handed from ball facing green."""
    t = float(min(max(t_along, 0.04), 0.997))
    ax, ay = _latlon_to_xy_m(player_lat, player_lon, player_lat, player_lon)
    bx, by = _latlon_to_xy_m(player_lat, player_lon, gc_lat, gc_lon)
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 0.01:
        return (player_lat, player_lon)
    ux, uy = dx / length, dy / length
    px = ax + t * dx + offset_right_m * (-uy)
    py = ay + t * dy + offset_right_m * ux
    return _xy_m_to_latlon(player_lat, player_lon, px, py)


def _nearest_on_hole_coords(lat: float, lon: float, coords_lon_lat: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(coords_lon_lat) < 2:
        return None
    try:
        line = LineString(coords_lon_lat)
        pxy = Point(lon, lat)
        near = line.interpolate(line.project(pxy))
        return (float(near.y), float(near.x))
    except Exception:
        return None


def extract_hole_path_coords_lon_lat(features: dict[str, Any]) -> list[tuple[float, float]]:
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


TARGET_AGENT_SYSTEM = (
    "You are a PGA-level course-management agent. Choose where the app's white target marker should sit for the "
    "PLAYER'S NEXT swing so routing is realistic and sensible.\n"
    "You receive FACTS_JSON (GPS, distances, hole par, structured shot intelligence, bag driver/wood distances). "
    "Use FACTS_JSON as ground truth; do not contradict positional_play_to_landing, go_for_it, or hazard previews.\n\n"
    "Rules:\n"
    "- Tee par 4/5: if a confident driver corridor exists (wide fairway / no positional layup hint), marker ~85–92% "
    "of player's listed driver carry toward the hole along ball→green. Dogleg/tree/positional_note → shorter t "
    "for iron/hybrid tee into fairway (often 0.32–0.58).\n"
    "- Fairway with long yards left (> fairway-wood carries for this bag): place marker so remainder is wedge/short iron "
    "when possible (~70–115 yd feel via t).\n"
    "- Short approach: green_aim_mode true — sit near green toward safe side vs bunkers in intel (~t 0.95–1.0).\n"
    "- Par 3 from tee: green_aim_mode true, small offset away from bunker side.\n\n"
    "Respond with ONLY a compact JSON object, no prose or markdown fences:\n"
    "{\n"
    '  "green_aim_mode": boolean,\n'
    '  "t_along_ball_to_green_center": number,\n'
    '  "offset_right_yards": number,\n'
    '  "rationale_short": string\n'
    "}\n"
    "green_aim_mode false ⇒ t typically 0.12–0.93 for carry target in fairway. offset_right_yards ∈ [-45,45]. "
    "green_aim_mode true ⇒ t usually 0.90–1.0; lateral offset yds avoids trouble."
)


def compact_intel_slice(intel: dict[str, Any]) -> dict[str, Any]:
    cr = intel.get("club_recommendation") or {}
    bunkers = intel.get("bunkers_near_tee_shot_corridor") or []
    trouble = intel.get("major_trouble_near_corridor") or []
    return {
        "player_position": intel.get("player_position"),
        "lie_and_situation": intel.get("lie_and_situation"),
        "club_recommendation": {
            "go_for_it": cr.get("go_for_it"),
            "positional_play_to_landing": cr.get("positional_play_to_landing"),
            "positional_note": cr.get("positional_note"),
            "ideal_second_shot_distance_yds": cr.get("ideal_second_shot_distance_yds"),
            "suggested_layup_carry_yds": cr.get("suggested_layup_carry_yds"),
            "dogleg_turn_vs_tee_line_deg": cr.get("dogleg_turn_vs_tee_line_deg"),
        },
        "fairway_at_landing": intel.get("fairway_at_landing"),
        "corridor_preview": {
            "bunkers_count": len(bunkers),
            "bunkers_sides_sample": [b.get("side") for b in bunkers[:6]],
            "trouble_water_ob_count": len(trouble),
        },
        "next_shot_preview": intel.get("next_shot_if_plan_works"),
    }


def build_facts_payload(
    *,
    hole_par: int,
    card_yards: Any,
    player_lat: float,
    player_lon: float,
    gc_lat: float,
    gc_lon: float,
    tee_lat: float,
    tee_lon: float,
    plays_like_yds: float,
    straight_pin_yds: float,
    lie: str,
    bag: dict[str, Any],
    handicap: float,
    intel_compressed: dict[str, Any],
) -> dict[str, Any]:
    from .caddie_shot_intel import _driver_or_longest_wood_yds, _max_long_club_carry_yds

    drv = _driver_or_longest_wood_yds(bag)
    max_long = _max_long_club_carry_yds(bag)
    return {
        "hole": {"par": hole_par, "card_yds": card_yards},
        "player_ll": {"lat": round(player_lat, 7), "lon": round(player_lon, 7)},
        "reference": {
            "tee_ll": {"lat": tee_lat, "lon": tee_lon},
            "green_center_ll": {"lat": gc_lat, "lon": gc_lon},
        },
        "distances_yd": {
            "plays_like_to_pin": round(plays_like_yds),
            "straight_to_pin": round(straight_pin_yds),
        },
        "lie": lie,
        "handicap_index": handicap,
        "bag_long_clubs_carry_yd": {
            "estimated_driver_carry": round(drv, 1) if drv else None,
            "max_long_wood_carry": round(max_long, 1) if max_long else None,
        },
        "intel": intel_compressed,
    }


def _message_assistant_text(msg: object) -> str:
    parts: list[str] = []
    for block in getattr(msg, "content", ()) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


def parse_target_agent_json(txt: str) -> dict[str, Any]:
    t = (txt or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```\s*$", "", t)

    decoded: dict[str, Any] | None = None
    try:
        cand = json.loads(t)
        if isinstance(cand, dict):
            decoded = cand
    except json.JSONDecodeError:
        pass
    if decoded is None:
        brace = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", t, re.DOTALL)
        if brace:
            try:
                cand = json.loads(brace.group(0))
                if isinstance(cand, dict):
                    decoded = cand
            except json.JSONDecodeError:
                decoded = None
    if decoded is None:
        raise ValueError("Target agent did not return a JSON object")
    return decoded


def run_white_target_agent(
    *,
    client: anthropic.Anthropic,
    model: str,
    facts_json: dict[str, Any],
) -> dict[str, Any]:
    payload = json.dumps(facts_json, indent=2)
    user = (
        "FACTS_JSON (ground truth):\n\n"
        f"{payload}\n\n"
        "Respond with ONLY the JSON object specified in your system instructions."
    )
    msg = client.messages.create(
        model=model,
        max_tokens=500,
        system=TARGET_AGENT_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    raw = _message_assistant_text(msg)
    return parse_target_agent_json(raw)


def finalize_target_coordinates(
    parsed: dict[str, Any],
    *,
    player_lat: float,
    player_lon: float,
    gc_lat: float,
    gc_lon: float,
    hole_features: dict[str, Any],
    fallback_lat: float,
    fallback_lon: float,
) -> tuple[float, float]:
    gm = parsed.get("green_aim_mode")
    green_mode = gm is True or (isinstance(gm, str) and gm.strip().lower() in ("true", "yes"))

    try:
        t = float(parsed.get("t_along_ball_to_green_center", 0.65))
    except (TypeError, ValueError):
        t = 0.65
    try:
        off_y = float(parsed.get("offset_right_yards", 0) or 0)
    except (TypeError, ValueError):
        off_y = 0.0

    off_m = max(-49.0, min(49.0, off_y * 0.9144))

    if green_mode:
        t_eff = float(min(max(t, 0.88), 0.997))
        off_m_green = max(-44.0, min(44.0, off_m))
        cand_lat, cand_lon = point_ball_to_green_with_offset(
            player_lat, player_lon, gc_lat, gc_lon, t_eff, offset_right_m=off_m_green
        )
        dpin = haversine_yards(cand_lat, cand_lon, gc_lat, gc_lon)
        if dpin > 54.0:
            cand_lat, cand_lon = point_ball_to_green_with_offset(
                player_lat, player_lon, gc_lat, gc_lon, 0.985, offset_right_m=off_m_green * 0.6
            )
    else:
        t_eff = float(min(max(t, 0.08), 0.965))
        cand_lat, cand_lon = point_ball_to_green_with_offset(
            player_lat, player_lon, gc_lat, gc_lon, t_eff, offset_right_m=off_m
        )

    path = extract_hole_path_coords_lon_lat(hole_features)
    snapped = _nearest_on_hole_coords(cand_lat, cand_lon, path)

    plat, plon = float(player_lat), float(player_lon)
    d_ball_pin = max(1.0, haversine_yards(plat, plon, gc_lat, gc_lon))

    def _ok(llat: float, llon: float) -> bool:
        d_from_ball = haversine_yards(plat, plon, llat, llon)
        if d_from_ball > d_ball_pin + 60.0:
            return False
        d_to_pin = haversine_yards(llat, llon, gc_lat, gc_lon)
        if d_from_ball + d_to_pin > d_ball_pin * 1.35 and d_to_pin > 180:
            return False
        return True

    use_lat, use_lon = (snapped if snapped else (cand_lat, cand_lon))
    if not _ok(use_lat, use_lon):
        return (fallback_lat, fallback_lon)
    if not (-90 <= use_lat <= 90 and -180 <= use_lon <= 180):
        return (fallback_lat, fallback_lon)
    return (float(use_lat), float(use_lon))
