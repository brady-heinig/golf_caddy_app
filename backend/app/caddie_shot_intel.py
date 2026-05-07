from __future__ import annotations

import math
import re
from typing import Any

from shapely.geometry import LineString, Point, shape
from shapely.ops import transform, unary_union

from .bag_selection import (
    club_shape_category,
    normalize_shot_shapes,
    pick_club_for_plays_like_yards,
    shot_shape_for_club,
)
from .legacy import weather
from .routes_caddie_compat import haversine_yards

YDS_PER_M = 1.0936133


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


def _geom_to_xy(geom: Any, ref_lat: float, ref_lon: float) -> Any:
    def _tr(x: float, y: float, _z: float | None = None) -> tuple[float, float]:
        return _latlon_to_xy_m(ref_lat, ref_lon, y, x)

    return transform(_tr, geom)


def _driver_or_longest_wood_yds(bag: dict[str, Any]) -> float | None:
    pairs: list[tuple[str, float]] = []
    for k, v in (bag or {}).items():
        try:
            yd = float(v)
        except Exception:
            continue
        if yd <= 0:
            continue
        pairs.append((str(k), yd))
    if not pairs:
        return None

    def score(name: str, yd: float) -> tuple[int, float]:
        n = name.lower()
        if "driver" in n or re.match(r"^d\s*$", n):
            return (100, yd)
        if "wood" in n or re.search(r"\b\d+w\b", n):
            return (90, yd)
        if re.search(r"\b[1-6]w\b", n):
            return (88, yd)
        return (0, yd)

    pairs.sort(key=lambda kv: (-score(kv[0], kv[1])[0], -kv[1]))
    top = pairs[0][1]
    return top if top > 120 else None


def resolve_intended_landing(
    player_lat: float,
    player_lon: float,
    gc_lat: float,
    gc_lon: float,
    bend_lat: float | None,
    bend_lon: float | None,
    bag: dict[str, Any],
    hole: dict[str, Any],
    lie: str,
    distance_to_pin_yds: float,
) -> tuple[float, float, dict[str, Any]]:
    """Pick landing lat/lon used for hazard/fairway intel."""
    meta: dict[str, Any] = {"how": "map_bend", "source": "player_map_target"}
    if bend_lat is not None and bend_lon is not None:
        return (float(bend_lat), float(bend_lon), meta)

    tee = hole["tee"]
    tlat, tlon = float(tee["lat"]), float(tee["lon"])
    dist_tee = haversine_yards(player_lat, player_lon, tlat, tlon)
    par = int(hole.get("par") or 4)
    near_tee = dist_tee <= 42.0
    lie_l = (lie or "").lower()
    on_tee_situation = near_tee and lie_l in ("tee", "fairway", "")

    if on_tee_situation and par >= 4 and distance_to_pin_yds > 220:
        drv = _driver_or_longest_wood_yds(bag)
        if drv is not None:
            frac = min(0.92, max(0.35, (drv * 0.9) / max(distance_to_pin_yds, 1.0)))
            llat, llon = _lerp_ll(player_lat, player_lon, gc_lat, gc_lon, frac)
            return (
                llat,
                llon,
                {
                    "how": "modeled_tee_carry",
                    "assumed_carry_club_yd": round(drv),
                    "fraction_along_pin_vector": round(frac, 3),
                },
            )

    if on_tee_situation and par == 3:
        llat, llon = _lerp_ll(player_lat, player_lon, gc_lat, gc_lon, 0.88)
        return (llat, llon, {"how": "tee_par3_toward_green"})

    f = 0.65
    llat, llon = _lerp_ll(player_lat, player_lon, gc_lat, gc_lon, f)
    return (llat, llon, {"how": "default_fraction_along_pin", "fraction": f})


def _lerp_ll(
    lat1: float, lon1: float, lat2: float, lon2: float, t: float,
) -> tuple[float, float]:
    t = min(max(t, 0.05), 0.98)
    return (lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1))


def _features_union(features: dict[str, Any], golf: str) -> Any | None:
    polys: list[Any] = []
    for feat in features.get("features") or []:
        if (feat.get("properties") or {}).get("golf") != golf:
            continue
        g = feat.get("geometry")
        if not g:
            continue
        try:
            polys.append(shape(g))
        except Exception:
            continue
    if not polys:
        return None
    try:
        return unary_union(polys)
    except Exception:
        return None


def _line_length_m_xy(geom: Any) -> float:
    if geom.geom_type == "LineString":
        return float(geom.length)
    if geom.geom_type == "MultiLineString":
        return max((float(g.length) for g in geom.geoms), default=0.0)
    if geom.geom_type == "GeometryCollection":
        return max((_line_length_m_xy(g) for g in geom.geoms), default=0.0)
    return 0.0


def fairway_width_at_landing_yds(
    features: dict[str, Any],
    player_lat: float,
    player_lon: float,
    landing_lat: float,
    landing_lon: float,
) -> dict[str, Any] | None:
    fair = _features_union(features, "fairway")
    if fair is None or fair.is_empty:
        return None

    plx, ply = _latlon_to_xy_m(player_lat, player_lon, player_lat, player_lon)
    lx, ly = _latlon_to_xy_m(player_lat, player_lon, landing_lat, landing_lon)
    dx, dy = lx - plx, ly - ply
    seg_len = math.hypot(dx, dy)
    if seg_len < 1.0:
        return None
    ux, uy = dx / seg_len, dy / seg_len
    px, py = -uy, ux

    try:
        fair_xy = _geom_to_xy(fair, player_lat, player_lon)
        pt_xy = Point(lx, ly)
        half_m = 220.0
        cut = LineString([(lx - px * half_m, ly - py * half_m), (lx + px * half_m, ly + py * half_m)])
        inter = cut.intersection(fair_xy)
        if inter.is_empty:
            inside = fair_xy.contains(pt_xy) or fair_xy.distance(pt_xy) < 3.0
            return {
                "width_yds": None,
                "landing_inside_fairway_polygon": inside,
                "note": "Could not measure cross-fairway width at landing (geometry).",
            }
        w_m = _line_length_m_xy(inter)
        w_yd = w_m * YDS_PER_M
        inside = fair_xy.contains(pt_xy) or fair_xy.distance(pt_xy) < 4.0
        return {
            "width_yds": round(w_yd),
            "landing_inside_fairway_polygon": bool(inside),
            "note": "Approximate fairway width on line perpendicular to your shot at the landing target.",
        }
    except Exception:
        return None


def _project_along_m(
    px: float,
    py: float,
    vx: float,
    vy: float,
    qx: float,
    qy: float,
) -> float:
    """Scalar projection of (q-p) onto unit direction v; v need not be unit — returns distance along v in same units as coords."""
    vlen = math.hypot(vx, vy)
    if vlen < 1e-6:
        return 0.0
    ux, uy = vx / vlen, vy / vlen
    return (qx - px) * ux + (qy - py) * uy


def hazards_along_corridor(
    features: dict[str, Any],
    player_lat: float,
    player_lon: float,
    landing_lat: float,
    landing_lon: float,
    golf_types: tuple[str, ...],
    cross_max_yds: float = 52.0,
    corridor_length_overrun: float = 1.02,
) -> list[dict[str, Any]]:
    plx, ply = _latlon_to_xy_m(player_lat, player_lon, player_lat, player_lon)
    lx, ly = _latlon_to_xy_m(player_lat, player_lon, landing_lat, landing_lon)
    dx, dy = lx - plx, ly - ply
    seg_len_m = math.hypot(dx, dy) * corridor_length_overrun
    if seg_len_m < 2.0:
        return []

    line = LineString([(plx, ply), (lx, ly)])
    buf_m = cross_max_yds / YDS_PER_M
    corridor = line.buffer(buf_m)

    out: list[dict[str, Any]] = []
    for feat in features.get("features") or []:
        gtype = (feat.get("properties") or {}).get("golf", "")
        if gtype not in golf_types:
            continue
        geom = feat.get("geometry")
        if not geom:
            continue
        try:
            shp = shape(geom)
            shp_xy = _geom_to_xy(shp, player_lat, player_lon)
        except Exception:
            continue
        if shp_xy.is_empty:
            continue
        if not corridor.intersects(shp_xy):
            continue
        try:
            d_line_m = float(line.distance(shp_xy))
        except Exception:
            d_line_m = 9999.0
        centroid = shp_xy.centroid
        cx, cy = float(centroid.x), float(centroid.y)
        cross = dx * cy - dy * cx
        along = _project_along_m(plx, ply, dx, dy, cx, cy)
        along = min(max(along, 0.0), math.hypot(dx, dy) * 1.05)

        c_lat, c_lon = _xy_m_to_latlon(player_lat, player_lon, cx, cy)
        out.append(
            {
                "golf_type": gtype,
                "side": "left" if cross > 5.0 else ("right" if cross < -5.0 else "centerline"),
                "distance_to_shot_line_yds": round(d_line_m * YDS_PER_M),
                "approx_along_carry_from_ball_yds": round(along * YDS_PER_M),
                "centroid_approx_lat": round(c_lat, 6),
                "centroid_approx_lon": round(c_lon, 6),
            }
        )

    out.sort(key=lambda r: (r["distance_to_shot_line_yds"], r["approx_along_carry_from_ball_yds"]))
    return out[:14]


def _trouble_severe_along_line_to_green(
    features: dict[str, Any],
    player_lat: float,
    player_lon: float,
    gc_lat: float,
    gc_lon: float,
) -> tuple[bool, str]:
    trouble_pin = hazards_along_corridor(
        features,
        player_lat,
        player_lon,
        gc_lat,
        gc_lon,
        ("water_hazard", "lateral_water_hazard", "out_of_bounds"),
        cross_max_yds=72.0,
    )
    worst = []
    for h in trouble_pin:
        d = h["distance_to_shot_line_yds"]
        gt = h["golf_type"]
        if gt == "out_of_bounds" and d < 40:
            worst.append(f"OB within ~{d} yards of the line to the green")
        elif gt in ("water_hazard", "lateral_water_hazard") and d < 32:
            worst.append(f"Water within ~{d} yards of the line to the green")
    if worst:
        return True, "; ".join(worst[:3])
    return False, ""


def _compute_go_for_it(
    *,
    long_carry_yd: float | None,
    plays_like_yd: float,
    shot_type: str,
    lie_l: str,
    near_tee: bool,
    severe_to_green: bool,
    severe_note: str,
) -> tuple[bool, str]:
    if long_carry_yd is None or long_carry_yd < 175:
        return False, (
            "Cannot flag go-for-it: no driver/wood carry on file (or carry too short) to compare to distance."
        )
    if shot_type == "tee_par3":
        return False, "Not applicable from a par-3 tee — you are playing into the green on this stroke."
    long_band_max = long_carry_yd * 0.98
    if plays_like_yd > long_band_max:
        return (
            False,
            f"About {plays_like_yd:.0f} yards adjusted plays-like exceeds about {long_carry_yd:.0f} yards long-wood carry; "
            "reaching the green in one with driver/fairway wood is not realistic.",
        )
    # Only flag when a wood/driver could plausibly be the club to finish (or nearly finish) on the green — not wedge range.
    if plays_like_yd < 125:
        return (
            False,
            "Inside hybrid / iron / wedge range to the green; ‘go for it’ with driver/wood does not apply.",
        )
    if severe_to_green:
        return False, (
            "Severe hazard tight on the line to the green — "
            f"{severe_note or 'favor position over forcing the carry.'}"
        )
    if lie_l in ("bunker", "rough", "trees") and not near_tee:
        return False, "Penal lie from the fairway; trying to reach the green in one is usually the wrong risk."
    return (
        True,
        "Long wood can realistically reach the green in one from here, without severe hazard tucked on that line.",
    )


def _ideal_remaining_yds_next_shot(
    *,
    go_for_it: bool,
    shot_type: str,
    near_tee: bool,
    par: int,
    rem_after_modeled_landing_yd: float,
    plays_like_yd: float,
) -> tuple[int | None, str]:
    """Yards to pin you'd like to leave after a positional layup (dogleg / strategy)."""
    if go_for_it:
        return None, (
            "N/A — you are playing to finish or get as close as the situation allows."
        )

    r = float(rem_after_modeled_landing_yd)

    def _tee_par45_ideal() -> tuple[int, str]:
        awkward = r < 62 and plays_like_yd > 260
        if awkward:
            target = int(min(max(105, round(plays_like_yd * 0.34)), 148))
            return (
                target,
                "Modeled landing would leave a very short partial wedge; a shorter tee club to leave about "
                f"{target} yards is often cleaner.",
            )
        target = int(min(max(round(r), 85), 160))
        return (
            target,
            "After a solid positional tee shot, many players like roughly this much left "
            f"(about {target} yards from the modeled landing). Adjust for wind and slope.",
        )

    if shot_type == "tee_par4_or_5" and near_tee:
        t, msg = _tee_par45_ideal()
        return t, msg

    if shot_type == "tee_par3":
        return None, "Par 3: this stroke targets the green — no separate lay-up yardage target."

    if shot_type not in ("fairway_approach", "bunker", "recovery"):
        return None, "Ideal leave distance does not apply for this situation."

    if shot_type == "fairway_approach" and par < 5 and plays_like_yd < 175:
        return None, "Approach-range shot on a par 4 — ideal lay-up yardage for a later shot does not apply."

    if par <= 3 and plays_like_yd < 120:
        return None, "Short iron or wedge range into the green — ideal lay-up yardage does not apply."

    if plays_like_yd < 95:
        return None, "Close enough that ideal yards-left for a later shot is not the main question."

    awkward_f = r < 58 and plays_like_yd > 165
    if awkward_f:
        target = int(min(max(100, round(plays_like_yd * 0.36)), 145))
        ctx = (
            "From the fairway"
            if shot_type == "fairway_approach"
            else "From this lie"
        )
        return (
            target,
            f"{ctx}, the modeled landing leaves an awkward in-between yardage; laying back to leave about "
            f"{target} yards for the next full shot can simplify the hole.",
        )

    target = int(min(max(round(r), 82), 165))
    ctx = (
        "From the fairway"
        if shot_type == "fairway_approach"
        else "From this recovery position"
    )
    return (
        target,
        f"{ctx}, if you play for the intended lay-up zone, about {target} yards remaining is a reasonable "
        "stock yardage for the following shot (adjust for hazards and pin).",
    )


def gather_shot_intel(
    *,
    hole: dict[str, Any],
    features: dict[str, Any],
    player_lat: float,
    player_lon: float,
    landing_lat: float,
    landing_lon: float,
    landing_meta: dict[str, Any],
    bag: dict[str, Any],
    lie: str,
    metrics: dict[str, Any],
    shot_shapes: dict[str, Any] | None,
    lie_detect_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tee = hole["tee"]
    gc = hole["green_center"]
    tlat, tlon = float(tee["lat"]), float(tee["lon"])
    gclat, gclon = float(gc["lat"]), float(gc["lon"])

    dist_tee = haversine_yards(player_lat, player_lon, tlat, tlon)
    dist_pin = float(metrics.get("distance_yd") or haversine_yards(player_lat, player_lon, gclat, gclon))
    brg_pin = float(weather.bearing_deg_lat_lon(player_lat, player_lon, gclat, gclon))

    par = int(hole.get("par") or 4)
    lie_l = (lie or "").lower()
    near_tee = dist_tee <= 42.0
    if near_tee and lie_l == "fairway":
        lie_note = "GPS is near the tee box; treating this as a tee shot for planning even though lie is 'fairway'."
    else:
        lie_note = ""

    if near_tee and par >= 4:
        shot_type = "tee_par4_or_5"
    elif near_tee and par == 3:
        shot_type = "tee_par3"
    elif lie_l in ("bunker",):
        shot_type = "bunker"
    elif lie_l in ("rough", "trees"):
        shot_type = "recovery"
    else:
        shot_type = "fairway_approach"

    carry_planned: float | None = None
    try:
        carry_planned = round(haversine_yards(player_lat, player_lon, landing_lat, landing_lon), 1)
    except Exception:
        pass

    bunkers = hazards_along_corridor(
        features,
        player_lat,
        player_lon,
        landing_lat,
        landing_lon,
        ("bunker",),
        cross_max_yds=55.0,
    )
    trouble = hazards_along_corridor(
        features,
        player_lat,
        player_lon,
        landing_lat,
        landing_lon,
        ("water_hazard", "lateral_water_hazard", "out_of_bounds"),
        cross_max_yds=70.0,
    )

    fw = fairway_width_at_landing_yds(features, player_lat, player_lon, landing_lat, landing_lon)

    rem_pin = haversine_yards(landing_lat, landing_lon, gclat, gclon)
    plays_like = float(metrics.get("plays_like_yd") or metrics.get("distance_yd") or 0.0)
    current_club_pick = pick_club_for_plays_like_yards(bag, plays_like)
    next_club_pick = pick_club_for_plays_like_yards(bag, float(rem_pin))
    next_seed = str(next_club_pick["club"])
    shapes_norm = normalize_shot_shapes(shot_shapes)
    cur_club_name = str(current_club_pick["club"])
    eff_shape = shot_shape_for_club(cur_club_name, shapes_norm)
    shape_bucket = club_shape_category(cur_club_name)
    par_int = par
    if shot_type == "tee_par4_or_5" and carry_planned:
        next_lbl = (
            f"If this tee ball covers about {int(carry_planned)} yards as intended, next shot is roughly "
            f"{int(rem_pin)} yards to the pin — often a {next_seed} from a fairway lie."
        )
    elif shot_type == "tee_par3":
        next_lbl = "Par 3: this stroke is your green attack; there is no separate ‘next tee shot’."
    else:
        next_lbl = (
            f"If you find the intended zone, you’d have about {int(rem_pin)} yards left; bag heuristic suggests "
            f"{next_seed} as a starting point."
        )

    long_wood = _driver_or_longest_wood_yds(bag)
    severe_green, severe_green_detail = _trouble_severe_along_line_to_green(
        features, player_lat, player_lon, gclat, gclon
    )
    go_for_it, go_for_it_note = _compute_go_for_it(
        long_carry_yd=long_wood,
        plays_like_yd=plays_like,
        shot_type=shot_type,
        lie_l=lie_l,
        near_tee=near_tee,
        severe_to_green=severe_green,
        severe_note=severe_green_detail,
    )
    ideal_rem, ideal_note = _ideal_remaining_yds_next_shot(
        go_for_it=go_for_it,
        shot_type=shot_type,
        near_tee=near_tee,
        par=par_int,
        rem_after_modeled_landing_yd=rem_pin,
        plays_like_yd=plays_like,
    )

    club_suggestion = {
        "bag_match_for_adjusted_plays_like": current_club_pick,
        "longest_driver_or_wood_carry_yds": round(long_wood, 1) if long_wood is not None else None,
        "go_for_it": go_for_it,
        "go_for_it_rationale": go_for_it_note,
        "hazard_check_full_line_to_green": {
            "severe_hazard_tight_to_direct_line": severe_green,
            "detail": severe_green_detail or None,
        },
        "ideal_remaining_yds_next_shot": ideal_rem,
        "ideal_remaining_note": ideal_note,
        "instruction": (
            "Synthesize ONE final club call only after weighing lie, wind/plays-like, corridor bunkers/water, "
            "fairway width at landing, shot shape, and whether go_for_it is sensible. Prefer bag_match_for_adjusted_plays_like "
            "unless safety, dogleg/position, or a knockdown clearly warrants less club."
        ),
    }

    return {
        "player_position": {
            "player_lat": round(player_lat, 6),
            "player_lon": round(player_lon, 6),
            "distance_from_tee_marker_yds": round(dist_tee, 1),
            "near_tee_box": near_tee,
            "distance_to_pin_yds": round(dist_pin),
            "bearing_to_pin_deg": round(brg_pin, 1),
            "blue_dot_matches": "These coordinates are the player / ‘blue dot’ position from the app.",
        },
        "lie_and_situation": {
            "lie": lie_l,
            "lie_inferred_from_blue_dot": True,
            "lie_detection": lie_detect_detail or {},
            "par": par_int,
            "shot_type": shot_type,
            "note": lie_note,
        },
        "intended_landing_target": {
            "lat": round(landing_lat, 6),
            "lon": round(landing_lon, 6),
            "modeled_carry_distance_yds": carry_planned,
            **landing_meta,
        },
        "bunkers_near_tee_shot_corridor": bunkers,
        "major_trouble_near_corridor": trouble,
        "fairway_at_landing": fw,
        "shot_shape_from_settings": {
            "club_category": shape_bucket,
            "shape": eff_shape,
            "driver_woods_irons_settings": shapes_norm,
        },
        "club_suggestion": club_suggestion,
        "next_shot_if_plan_works": {
            "remaining_distance_to_pin_yds": round(rem_pin),
            "club_pick_same_rule": next_club_pick,
            "summary": next_lbl,
        },
    }
