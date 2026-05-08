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


def _ang_diff_deg(a: float, b: float) -> float:
    return ((a - b + 540) % 360) - 180


def _max_long_club_carry_yds(bag: dict[str, Any]) -> float | None:
    """Longest listed carry among driver / fairway woods / hybrids."""
    best: float | None = None
    for k, v in (bag or {}).items():
        try:
            yd = float(v)
        except Exception:
            continue
        if yd <= 0:
            continue
        if club_shape_category(str(k)) not in ("driver", "woods"):
            continue
        best = yd if best is None else max(best, yd)
    return best


def _severe_corridor_endgame_risk(
    bunkers: list[dict[str, Any]],
    trouble: list[dict[str, Any]],
    nominal_carry_yds: float | None,
) -> tuple[bool, str]:
    """Heuristic: hazards tight to the landing / green end of the corridor."""
    if nominal_carry_yds and nominal_carry_yds > 35:
        tail_start = 0.52 * nominal_carry_yds
        hot_b = [
            b
            for b in bunkers
            if float(b.get("distance_to_shot_line_yds") or 999) <= 30
            and float(b.get("approx_along_carry_from_ball_yds") or 0) >= tail_start
        ]
        if len(hot_b) >= 2:
            return True, "Multiple bunkers pinch the landing zone."
        if hot_b and float(hot_b[0].get("distance_to_shot_line_yds") or 999) <= 18:
            return True, "Bunker tight to intended landing."
    for t in trouble:
        gt = str(t.get("golf_type", ""))
        dln = float(t.get("distance_to_shot_line_yds") or 999)
        if dln <= 42 and ("water" in gt or gt == "out_of_bounds"):
            return True, "Water or OB encroaches the playing corridor."
    return False, ""


def _ideal_approach_remain_yds(handicap: float | None) -> int:
    h = float(handicap if handicap is not None else 15.0)
    return int(round(min(145, max(88, 122.0 - (h - 12.0) * 1.5))))


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
    handicap: float | None = None,
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

    # Wind/elevation are folded into plays-like vs straight pin; apply same factor to carry-to-landing.
    ratio_plays = 1.0
    if dist_pin > 5.0:
        ratio_plays = plays_like / dist_pin
    ratio_plays = min(max(ratio_plays, 0.82), 1.22)

    meaningfully_short_landing = (
        carry_planned is not None
        and plays_like > 55.0
        and plays_like - float(carry_planned) >= 38.0
    )
    positional_play = meaningfully_short_landing

    if positional_play:
        club_distance_target = float(carry_planned) * ratio_plays
        club_basis = "adjusted_carry_to_intended_landing"
    else:
        club_distance_target = plays_like
        club_basis = "adjusted_plays_like_to_pin"

    positional_note: str | None = None
    if positional_play and carry_planned is not None:
        pn_parts = [
            f"Landing/target ~{int(round(float(carry_planned)))} yd carry vs ~{int(round(plays_like))} yd plays-like "
            f"to pin — recommend clubs that fit the **fairway target**, not driver-at-green "
            f"(often trees, routing, or doglegs block a straight long club)."
        ]
        if str(landing_meta.get("how") or "") == "map_bend":
            pn_parts.append("White aim point on map confirms positional layup into fairway.")
        positional_note = " ".join(pn_parts)

    current_club_pick = pick_club_for_plays_like_yards(bag, club_distance_target)
    next_club_pick = pick_club_for_plays_like_yards(bag, float(rem_pin))
    next_seed = str(next_club_pick["club"])
    shapes_norm = normalize_shot_shapes(shot_shapes)
    cur_club_name = str(current_club_pick["club"])
    eff_shape = shot_shape_for_club(cur_club_name, shapes_norm)
    shape_bucket = club_shape_category(cur_club_name)
    par_int = par

    max_long = _max_long_club_carry_yds(bag)
    reachable_long = max_long is not None and plays_like <= float(max_long) * 0.93

    bunkers_green = hazards_along_corridor(
        features,
        player_lat,
        player_lon,
        gclat,
        gclon,
        ("bunker",),
        cross_max_yds=58.0,
    )
    trouble_green = hazards_along_corridor(
        features,
        player_lat,
        player_lon,
        gclat,
        gclon,
        ("water_hazard", "lateral_water_hazard", "out_of_bounds"),
        cross_max_yds=82.0,
    )
    nominal_green_carry = plays_like * 0.92 if plays_like > 0 else None
    green_risk, green_risk_why = _severe_corridor_endgame_risk(
        bunkers_green,
        trouble_green,
        nominal_green_carry,
    )

    lie_blocks_long = lie_l in ("bunker",)
    long_club_territory = shot_type == "tee_par4_or_5" or (
        shot_type == "fairway_approach" and plays_like >= 215.0
    )
    go_for_it = bool(
        reachable_long
        and not positional_play
        and not lie_blocks_long
        and par_int != 3
        and long_club_territory
        and not green_risk
    )

    br_tee_pin = float(weather.bearing_deg_lat_lon(tlat, tlon, gclat, gclon))
    br_pl_pin = float(weather.bearing_deg_lat_lon(player_lat, player_lon, gclat, gclon))
    dogleg_turn_deg = abs(_ang_diff_deg(br_pl_pin, br_tee_pin))

    ideal_remain = _ideal_approach_remain_yds(handicap)
    ideal_second: int | None = None
    suggested_layup_carry: float | None = None

    if par_int >= 4 and near_tee and dogleg_turn_deg >= 26.0:
        ideal_second = ideal_remain
        suggested_layup_carry = round(max(125.0, min(dist_pin - ideal_remain, dist_pin * 0.72)), 1)

    if not go_for_it and reachable_long and green_risk:
        ideal_second = ideal_second or ideal_remain
        cap = float(max_long or dist_pin * 0.58)
        suggested_layup_carry = suggested_layup_carry or round(max(140.0, min(dist_pin - ideal_remain, cap)), 1)

    if positional_play and carry_planned is not None:
        ideal_second = ideal_second or int(round(float(rem_pin)))
        suggested_layup_carry = suggested_layup_carry or round(float(carry_planned), 1)

    if go_for_it:
        go_expl = (
            "Listed driver/wood carry can get you home or very close and the modeled line to the green "
            "does not show severe hazard tight to the landing zone."
        )
    else:
        bits: list[str] = []
        if positional_note:
            bits.append(positional_note)
        if par_int == 3:
            bits.append("Par 3: treat this as a green attack with an appropriate scoring club, not a driver decision.")
        elif not reachable_long:
            bits.append("Pin plays beyond realistic driver/wood carry for this bag.")
        if green_risk:
            bits.append(green_risk_why)
        if lie_blocks_long:
            bits.append("Poor lie — forcing a long club to reach the green is usually unwise.")
        if par_int >= 4 and near_tee and dogleg_turn_deg >= 26.0:
            bits.append(f"Dogleg geometry (~{dogleg_turn_deg:.0f}° vs tee line) often favors a positional tee ball.")
        if not bits:
            bits.append("Prefer the positional play implied by hazards, landing width, and bag distances.")
        go_expl = " ".join(bits)

    club_recommendation: dict[str, Any] = {
        "go_for_it": go_for_it,
        "go_for_it_explanation": go_expl,
        "positional_play_to_landing": positional_play,
        "positional_note": positional_note,
        "club_distance_basis": club_basis,
        "club_distance_basis_yds": round(float(club_distance_target), 1),
        "ideal_second_shot_distance_yds": ideal_second,
        "suggested_layup_carry_yds": suggested_layup_carry,
        "dogleg_turn_vs_tee_line_deg": round(dogleg_turn_deg, 1),
        "reachable_with_long_club_per_bag": reachable_long,
        "severe_hazard_on_green_line": green_risk,
        "club_for_adjusted_plays_like": current_club_pick,
        "selection_notes": (
            "If positional_play_to_landing is true (or club_distance_basis is adjusted_carry_to_intended_landing), "
            "the stroke is to the fairway / white target carry — typically irons or fairway metals, **not** driver at "
            "the pin, even when plays-like yardage to the green would fit driver (trees, routing, etc.). "
            "Otherwise weigh go_for_it, dogleg / ideal layup, hazards, lie, and wind/elevation; pick bag-distance club "
            "for the chosen target or less club for safety."
        ),
    }

    if shot_type == "tee_par4_or_5" and carry_planned:
        next_lbl = (
            f"If this tee ball covers ~{int(carry_planned)} yd as intended, next shot is roughly "
            f"{int(rem_pin)} yd to the pin — often a {next_seed} from a fairway lie."
        )
    elif shot_type == "tee_par3":
        next_lbl = "Par 3: this stroke is your green attack; there is no separate ‘next tee shot’."
    else:
        next_lbl = (
            f"If you find the intended zone, you’d have about {int(rem_pin)} yd left; bag heuristic suggests "
            f"{next_seed} as a starting point."
        )

    return {
        "shot_shape_from_settings": {
            "club_category": shape_bucket,
            "shape": eff_shape,
            "driver_woods_irons_settings": shapes_norm,
        },
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
        "club_recommendation": club_recommendation,
        "next_shot_if_plan_works": {
            "remaining_distance_to_pin_yds": round(rem_pin),
            "club_pick_same_rule": next_club_pick,
            "summary": next_lbl,
        },
    }
