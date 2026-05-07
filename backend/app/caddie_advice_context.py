from __future__ import annotations

import json
import math
import os
from typing import Any

from shapely.geometry import Point, shape
from shapely.ops import nearest_points

from .caddie_shot_intel import gather_shot_intel
from .legacy import weather
from .routes_caddie_compat import haversine_yards


def _lerp_lat_lon(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    t: float,
) -> tuple[float, float]:
    return (lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1))


def default_landing_point(
    player_lat: float,
    player_lon: float,
    gc_lat: float,
    gc_lon: float,
    bend_lat: float | None,
    bend_lon: float | None,
    frac: float | None = None,
) -> tuple[float, float]:
    if bend_lat is not None and bend_lon is not None:
        return (float(bend_lat), float(bend_lon))
    f = float(os.environ.get("CADDIE_LANDING_FRAC", str(frac if frac is not None else 0.65)))
    return _lerp_lat_lon(player_lat, player_lon, gc_lat, gc_lon, min(max(f, 0.15), 0.92))


def _golf_label(golf: str) -> str:
    return {
        "water_hazard": "water",
        "lateral_water_hazard": "lateral water",
        "lateral_water": "lateral water",
        "bunker": "bunker",
        "fairway": "fairway",
        "green": "green",
        "tee": "tee",
        "rough": "rough",
        "hole": "fairway line",
        "out_of_bounds": "OB",
    }.get(golf, golf or "feature")


def _nearest_distance_yds(
    feat_geom: Any,
    landing_lat: float,
    landing_lon: float,
) -> float | None:
    try:
        shp = shape(feat_geom)
    except Exception:
        return None
    p = Point(landing_lon, landing_lat)
    try:
        a, b = nearest_points(shp, p)
    except Exception:
        return None
    x, y = float(b.x), float(b.y)
    return float(haversine_yards(landing_lat, landing_lon, y, x))


def hazards_near_landing(
    features: dict[str, Any],
    landing_lat: float,
    landing_lon: float,
    max_yds: float = 58.0,
    limit: int = 10,
) -> list[str]:
    out: list[tuple[float, str]] = []
    for feat in features.get("features") or []:
        geom = feat.get("geometry")
        if not geom:
            continue
        d = _nearest_distance_yds(geom, landing_lat, landing_lon)
        if d is None or d > max_yds:
            continue
        golf = (feat.get("properties") or {}).get("golf", "")
        if golf in ("", "hole", "fairway", "rough", "green", "tee"):
            # focus on trouble / boundaries for advice
            continue
        lbl = _golf_label(str(golf))
        out.append((d, f"{lbl} (~{round(d)} yd from landing target)"))
    out.sort(key=lambda x: x[0])
    return [t[1] for t in out[:limit]]


def _ang_diff_deg(a: float, b: float) -> float:
    return ((a - b + 540) % 360) - 180


def green_miss_hint_text(
    hole: dict[str, Any],
    player_lat: float,
    player_lon: float,
) -> str:
    gc = hole["green_center"]
    gf = hole.get("green_front") or gc
    gb = hole.get("green_back") or gc
    plat, plon = float(player_lat), float(player_lon)
    gc_lat, gc_lon = float(gc["lat"]), float(gc["lon"])
    flt, fln = float(gf["lat"]), float(gf["lon"])
    blt, bln = float(gb["lat"]), float(gb["lon"])

    br_approach = float(weather.bearing_deg_lat_lon(plat, plon, gc_lat, gc_lon))
    br_run_ftb = float(weather.bearing_deg_lat_lon(flt, fln, blt, bln))
    delta = abs(_ang_diff_deg(br_run_ftb, br_approach))

    entry = "across"
    if delta < 35.0:
        entry = "along your approach line"
    elif delta > 125.0:
        entry = "mostly perpendicular to your approach (a side-on green)"

    # left/right: vector approach x (front->back) in local tangential sense
    # ENU-ish: dx = lon delta scaled, dy = lat delta
    mid_lat = math.radians((plat + gc_lat) / 2.0)
    scale_lon = math.cos(mid_lat)
    ax = (gc_lon - plon) * scale_lon
    ay = gc_lat - plat
    fx = (bln - fln) * scale_lon
    fy = blt - flt
    cross = ax * fy - ay * fx
    if abs(cross) < 1e-6:
        side_word = "Neither long side is strongly favored by geometry alone; use hazards to pick a miss."
    elif cross > 0:
        side_word = (
            "Geometrically, the green complex tends to your LEFT as you face the pin "
            "(green depth axis vs. your approach)."
        )
    else:
        side_word = (
            "Geometrically, the green complex tends to your RIGHT as you face the pin "
            "(green depth axis vs. your approach)."
        )

    return (
        f"Green orientation: depth runs {entry}. {side_word} "
        f"(Use this together with hazards and pin position — do not overfit pure geometry.)"
    )


def format_bag_lines(bag: dict[str, Any], limit: int = 24) -> str:
    pairs: list[tuple[str, float]] = []
    for k, v in (bag or {}).items():
        try:
            pairs.append((str(k), float(v)))
        except Exception:
            continue
    pairs.sort(key=lambda kv: kv[1], reverse=True)
    if not pairs:
        return "- (No bag saved — ask an experienced baseline and note the player should fill Settings.)"
    lines = [f"- {c}: {round(y)} yd carry" for c, y in pairs[:limit]]
    return "\n".join(lines)


def build_caddie_advice_context(
    course_id: str,
    course_name: str | None,
    hole: dict[str, Any],
    metrics: dict[str, Any],
    wx: dict[str, Any],
    features: dict[str, Any],
    player_lat: float,
    player_lon: float,
    landing_lat: float,
    landing_lon: float,
    landing_meta: dict[str, Any],
    lie: str,
    shot_shape: str,
    handicap: float,
    bag: dict[str, Any],
    shot_shapes: dict[str, Any] | None,
    lie_detect_meta: dict[str, Any] | None = None,
) -> str:
    intel = gather_shot_intel(
        hole=hole,
        features=features,
        player_lat=player_lat,
        player_lon=player_lon,
        landing_lat=landing_lat,
        landing_lon=landing_lon,
        landing_meta=dict(landing_meta),
        bag=bag,
        lie=lie,
        metrics=metrics,
        shot_shapes=shot_shapes,
        lie_detect_detail=lie_detect_meta,
    )
    hz_osm = hazards_near_landing(features, landing_lat, landing_lon)
    hz_static = hole.get("hazards") or []
    static_lines: list[str] = []
    for h in hz_static[:12]:
        if isinstance(h, dict):
            static_lines.append(f"- {h.get('type', 'hazard')}: {h.get('note', '')}".strip())
        else:
            static_lines.append(f"- {h}")

    green_txt = green_miss_hint_text(hole, player_lat, player_lon)

    wx_line = "N/A"
    if wx and not wx.get("error"):
        mph = wx.get("wind_mph")
        card = wx.get("wind_dir_card")
        wrel = metrics.get("wind_relation", "—")
        t = wx.get("temp_f")
        wx_line = f"{mph} mph from {card} ({wrel}); temp ~{t}°F"

    d_pin = metrics.get("distance_yd")
    plays = metrics.get("plays_like_yd")
    elev = metrics.get("elev_change_yd")
    wadj = metrics.get("wind_adjust_yd")
    gir = metrics.get("green_hit_pct")

    land_dist_gc = round(haversine_yards(landing_lat, landing_lon, float(hole["green_center"]["lat"]), float(hole["green_center"]["lon"])))

    parts = [
        "=== STRUCTURED_SHOT_INTEL (computed from map/OSM + blue-dot position; treat as facts) ===",
        json.dumps(intel, indent=2),
        "",
        "=== NARRATIVE_SUPPLEMENT (same hole, for readability) ===",
        f"COURSE: {course_name or course_id} ({course_id})",
        f"HOLE: {hole.get('number')} | Par {hole.get('par')} | Hdcp {hole.get('handicap')} | Card {hole.get('yards')} yd",
        "",
        "SHOT (next from current position):",
        f"  True distance to pin: {d_pin} yd",
        f"  Elevation adjustment:   {elev} yd (adds to plays-like)",
        f"  Wind adjustment:      {wadj} yd ({metrics.get('wind_relation', '—')})",
        f"  Plays-like distance:  {plays} yd",
        f"  Lie (from blue dot on map): {lie}",
        f"  Shot shape (Settings, {intel['shot_shape_from_settings']['club_category']} bucket): {shot_shape}",
        f"  Est. GIR (model):      {gir}% @ handicap {handicap:.1f}",
        "",
        "WEATHER:",
        f"  {wx_line}",
        "",
        "LANDING ZONE (used above + hazard search):",
        f"  ~{land_dist_gc} yd from pin; landing lat/lon: {landing_lat:.6f}, {landing_lon:.6f}",
        f"  How landing was set: {landing_meta.get('how', 'unknown')}",
        "",
        "OSM / COURSE FEATURES NEAR LANDING (approx.):",
        ("\n".join(f"- {x}" for x in hz_osm) if hz_osm else "- None flagged within ~60 yd of landing target"),
        "",
        "NOTE CARD / STATIC HAZARDS:",
        ("\n".join(static_lines) if static_lines else "- None recorded for this hole"),
        "",
        "GREEN & MISS SIDE (geometry hint):",
        green_txt,
        "",
        "PLAYER BAG (carry distances — club vs adjusted plays-like is computed in STRUCTURED_SHOT_INTEL):",
        format_bag_lines(bag),
        "",
        "CLUB VS ADJUSTED DISTANCE:",
        f"  See STRUCTURED_SHOT_INTEL.club_for_adjusted_plays_like — "
        f"recommended club is the smallest listed carry still >= {plays} yd plays-like.",
    ]
    return "\n".join(parts)
