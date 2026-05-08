from __future__ import annotations

import math
from typing import Any

from shapely.geometry import LineString, Point, shape
from shapely.ops import nearest_points, transform, unary_union

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


def _geom_to_xy(geom: Any, ref_lat: float, ref_lon: float) -> Any:
    def _tr(x: float, y: float, _z: float | None = None) -> tuple[float, float]:
        return _latlon_to_xy_m(ref_lat, ref_lon, y, x)

    return transform(_tr, geom)


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


def _collect_golf_polygons(features: dict[str, Any], golf: str) -> list[Any]:
    """Explode MultiPolygon OSM greens/fairways into individual Polygon parts."""
    out: list[Any] = []
    for feat in features.get("features") or []:
        if (feat.get("properties") or {}).get("golf") != golf:
            continue
        g = feat.get("geometry")
        if not g:
            continue
        try:
            s = shape(g)
        except Exception:
            continue
        if getattr(s, "is_empty", True):
            continue
        if s.geom_type == "Polygon":
            out.append(s)
        elif s.geom_type == "MultiPolygon":
            for part in s.geoms:
                if getattr(part, "is_empty", True):
                    continue
                out.append(part)
    return out


def _geom_min_dist_yds_to_point(geom: Any, lat: float, lon: float) -> float:
    """Haversine yards from lat/lon to nearest point on polygon boundary (0 if inside/covered)."""
    try:
        p = Point(float(lon), float(lat))
        if geom.covers(p):
            return 0.0
        a, _b = nearest_points(geom, p)
        return float(haversine_yards(lat, lon, float(a.y), float(a.x)))
    except Exception:
        return float("inf")


def primary_green_geometry_for_hole(
    features: dict[str, Any],
    gc_lat: float,
    gc_lon: float,
    *,
    max_near_center_yd: float = 52.0,
    clear_second_gap_yd: float = 14.0,
    loose_max_first_yd: float = 110.0,
    loose_gap_yd: float = 28.0,
) -> Any | None:
    """Drop OSM polygons tagged golf=green that are not tied to this hole's official green_center.

    Course data picks the scoring green; stray shapes (temporary greens, tees, mowing errors, etc.)
    stay out of unary_union snapping so targets don't steer to the wrong surface.
    """
    polys = _collect_golf_polygons(features, "green")
    if not polys:
        return None
    p_gc = Point(float(gc_lon), float(gc_lat))
    containing: list[Any] = []
    for g in polys:
        try:
            if g.covers(p_gc):
                containing.append(g)
        except Exception:
            continue
    if len(containing) == 1:
        return containing[0]
    if len(containing) > 1:
        try:
            return unary_union(containing)
        except Exception:
            return containing[0]

    scored = [(_geom_min_dist_yds_to_point(g, gc_lat, gc_lon), g) for g in polys]
    scored.sort(key=lambda x: x[0])
    d0, g0 = scored[0]
    if math.isinf(d0):
        return None
    if len(scored) == 1:
        return g0

    d1 = scored[1][0]
    if d0 <= max_near_center_yd and (d1 - d0) >= clear_second_gap_yd:
        return g0
    if d0 <= loose_max_first_yd and (d1 - d0) >= loose_gap_yd:
        return g0
    # Ambiguous clustering: still prefer geometry closest to the scorecard green center over unioning extras.
    return g0


def _snap_to_union_nearest(lat: float, lon: float, union_geom: Any) -> tuple[float, float] | None:
    try:
        p = Point(lon, lat)
        a, b = nearest_points(union_geom, p)
        return (float(a.y), float(a.x))  # nearest point on union (a)
    except Exception:
        return None


def _lerp_lat_lon(lat1: float, lon1: float, lat2: float, lon2: float, t: float) -> tuple[float, float]:
    tt = float(min(max(t, 0.0), 1.0))
    return (lat1 + tt * (lat2 - lat1), lon1 + tt * (lon2 - lon1))


def _line_respects_fairway_corridor(
    player_lat: float,
    player_lon: float,
    target_lat: float,
    target_lon: float,
    fairway_union: Any,
    *,
    max_off_fairway_yd: float = 18.0,
    samples: int = 9,
) -> bool:
    """Without explicit tree data, approximate 'don't go over trees' by keeping the shot line near fairway.

    We sample points along the straight shot line; if any point is far from the nearest fairway polygon
    (beyond max_off_fairway_yd), we treat the line as an unrealistic corner-cut.
    """
    if fairway_union is None or getattr(fairway_union, "is_empty", True):
        return True
    n = max(3, int(samples))
    for i in range(1, n):
        t = i / n
        lat, lon = _lerp_lat_lon(player_lat, player_lon, target_lat, target_lon, t)
        try:
            p = Point(float(lon), float(lat))
            a, _b = nearest_points(fairway_union, p)
            d = haversine_yards(float(lat), float(lon), float(a.y), float(a.x))
        except Exception:
            continue
        if d > float(max_off_fairway_yd):
            return False
    return True


def center_target_in_fairway(
    *,
    features: dict[str, Any],
    player_lat: float,
    player_lon: float,
    target_lat: float,
    target_lon: float,
    half_width_m: float = 240.0,
) -> tuple[float, float] | None:
    """Shift a target to the fairway midpoint across its width at that station.

    This approximates "aim middle of fairway, equal distance from each side" for tee shots.
    """
    fw = _features_union(features, "fairway")
    if fw is None or fw.is_empty:
        return None
    try:
        fw_xy = _geom_to_xy(fw, player_lat, player_lon)
    except Exception:
        return None

    tx, ty = _latlon_to_xy_m(player_lat, player_lon, target_lat, target_lon)
    px, py = _latlon_to_xy_m(player_lat, player_lon, player_lat, player_lon)
    dx, dy = tx - px, ty - py
    seg = math.hypot(dx, dy)
    if seg < 1.0:
        return None
    ux, uy = dx / seg, dy / seg
    # Perpendicular to shot direction.
    vx, vy = -uy, ux

    cut = LineString([(tx - vx * half_width_m, ty - vy * half_width_m), (tx + vx * half_width_m, ty + vy * half_width_m)])
    try:
        inter = cut.intersection(fw_xy)
    except Exception:
        return None
    if inter.is_empty:
        return None

    # Reduce to a single longest segment and take its midpoint.
    segs: list[LineString] = []
    if inter.geom_type == "LineString":
        segs = [inter]
    elif inter.geom_type == "MultiLineString":
        segs = [g for g in inter.geoms if g.geom_type == "LineString"]
    elif inter.geom_type == "GeometryCollection":
        segs = [g for g in inter.geoms if g.geom_type == "LineString"]
    if not segs:
        return None
    segs.sort(key=lambda g: float(g.length), reverse=True)
    best = segs[0]
    mid = best.interpolate(0.5, normalized=True)
    return _xy_m_to_latlon(player_lat, player_lon, float(mid.x), float(mid.y))


def _two_leg_respects_corridor(
    player_lat: float,
    player_lon: float,
    bend_lat: float,
    bend_lon: float,
    gc_lat: float,
    gc_lon: float,
    fairway_union: Any,
    *,
    max_off_fairway_yd: float,
    samples: int = 9,
) -> bool:
    """Ensure both ball→bend and bend→green legs don't 'cut corners' far from fairway.

    For the approach (bend→green), allow leaving fairway near the end (last ~18% of samples)
    since a proper approach often finishes on green.
    """
    if not _line_respects_fairway_corridor(
        player_lat,
        player_lon,
        bend_lat,
        bend_lon,
        fairway_union,
        max_off_fairway_yd=max_off_fairway_yd,
        samples=samples,
    ):
        return False

    if fairway_union is None or getattr(fairway_union, "is_empty", True):
        return True
    n = max(3, int(samples))
    for i in range(1, n):
        t = i / n
        if t >= 0.82:
            continue
        lat, lon = _lerp_lat_lon(bend_lat, bend_lon, gc_lat, gc_lon, t)
        try:
            p = Point(float(lon), float(lat))
            a, _b = nearest_points(fairway_union, p)
            d = haversine_yards(float(lat), float(lon), float(a.y), float(a.x))
        except Exception:
            continue
        if d > float(max_off_fairway_yd):
            return False
    return True


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
    max_off_fairway_yd: float = 18.0,
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

    fairway_union = _features_union(hole_features, "fairway")
    green_union = primary_green_geometry_for_hole(hole_features, gc_lat, gc_lon)
    if green_union is None:
        green_union = _features_union(hole_features, "green")

    def _dist_to_fairway_yd(llat: float, llon: float) -> float | None:
        if fairway_union is None or getattr(fairway_union, "is_empty", True):
            return None
        try:
            p = Point(float(llon), float(llat))
            a, _b = nearest_points(fairway_union, p)
            return float(haversine_yards(float(llat), float(llon), float(a.y), float(a.x)))
        except Exception:
            return None

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
        # If we have a green polygon, always snap onto it (trees aren't tagged, but green usually is).
        if green_union is not None and not green_union.is_empty:
            snapped_green = _snap_to_union_nearest(cand_lat, cand_lon, green_union)
            if snapped_green:
                cand_lat, cand_lon = snapped_green
    else:
        base_t = float(min(max(t, 0.08), 0.965))
        cand_lat, cand_lon = point_ball_to_green_with_offset(
            player_lat, player_lon, gc_lat, gc_lon, base_t, offset_right_m=off_m
        )
        # If we have fairway polygons, keep BOTH the marker and the shot line in a fairway corridor.
        if fairway_union is not None and not fairway_union.is_empty:
            # If the agent picked an extreme lateral offset, dial it back until the routing is realistic.
            off_seq = [off_m, off_m * 0.7, off_m * 0.45, off_m * 0.25, 0.0]
            for off_try in off_seq:
                for k in range(0, 7):
                # Back off toward the player if the line corner-cuts outside fairway.
                    t_eff = max(0.14, base_t * (0.88**k))
                    cand_lat, cand_lon = point_ball_to_green_with_offset(
                        player_lat, player_lon, gc_lat, gc_lon, t_eff, offset_right_m=off_try
                    )
                    try:
                        inside = bool(fairway_union.contains(Point(cand_lon, cand_lat)))
                    except Exception:
                        inside = False
                    if not inside:
                        snapped_fw = _snap_to_union_nearest(cand_lat, cand_lon, fairway_union)
                        if snapped_fw:
                            cand_lat, cand_lon = snapped_fw
                    # If the marker is only slightly off fairway, allow it (wide-open rough right/left is often playable).
                    d_fw = _dist_to_fairway_yd(cand_lat, cand_lon)
                    if d_fw is not None and d_fw <= max_off_fairway_yd:
                        inside = True
                    if _two_leg_respects_corridor(
                        player_lat,
                        player_lon,
                        cand_lat,
                        cand_lon,
                        gc_lat,
                        gc_lon,
                        fairway_union,
                        max_off_fairway_yd=max_off_fairway_yd,
                        samples=9,
                    ):
                        break
                else:
                    continue
                break

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

    use_lat, use_lon = (cand_lat, cand_lon)
    # Ball→hole path snapping is for fairway routing only; replacing a green aim with the hole line
    # pulls the marker off the putting surface (bad on par 3s and short approaches).
    if (
        not green_mode
        and snapped
        and fairway_union is not None
        and not fairway_union.is_empty
    ):
        # Only snap to centerline if it doesn't reintroduce a corner-cut.
        if _two_leg_respects_corridor(
            player_lat,
            player_lon,
            float(snapped[0]),
            float(snapped[1]),
            gc_lat,
            gc_lon,
            fairway_union,
            max_off_fairway_yd=max_off_fairway_yd,
            samples=9,
        ):
            use_lat, use_lon = float(snapped[0]), float(snapped[1])
    if not _ok(use_lat, use_lon):
        return (fallback_lat, fallback_lon)
    if not (-90 <= use_lat <= 90 and -180 <= use_lon <= 180):
        return (fallback_lat, fallback_lon)
    return (float(use_lat), float(use_lon))
