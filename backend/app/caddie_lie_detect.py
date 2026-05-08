from __future__ import annotations

import math
import re
from typing import Any

from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union

from .routes_caddie_compat import haversine_yards


def _latlon_to_xy_m(ref_lat: float, ref_lon: float, lat: float, lon: float) -> tuple[float, float]:
    mid = math.radians((ref_lat + lat) / 2.0)
    scale = 111_320.0 * math.cos(mid)
    return ((lon - ref_lon) * scale, (lat - ref_lat) * 111_320.0)


def _geom_to_xy_m(geom: Any, ref_lat: float, ref_lon: float) -> Any:
    def _tr(x: float, y: float, _z: float | None = None) -> tuple[float, float]:
        return _latlon_to_xy_m(ref_lat, ref_lon, y, x)

    return transform(_tr, geom)


def _union_golf(features: dict[str, Any], golf: str) -> Any | None:
    geoms: list[Any] = []
    for feat in features.get("features") or []:
        if (feat.get("properties") or {}).get("golf") != golf:
            continue
        g = feat.get("geometry")
        if not g:
            continue
        try:
            s = shape(g)
            if s.is_empty:
                continue
            if s.geom_type in ("Polygon", "MultiPolygon"):
                geoms.append(s)
        except Exception:
            continue
    if not geoms:
        return None
    try:
        return unary_union(geoms)
    except Exception:
        return None


def classify_lie_from_blue_dot(
    player_lat: float,
    player_lon: float,
    hole: dict[str, Any],
    features: dict[str, Any],
    *,
    tee_marker_max_yds: float = 24.0,
    edge_tolerance_m: float = 7.0,
) -> tuple[str, dict[str, Any]]:
    """Map OSM polygons + tee marker to lie: bunker | tee | fairway | rough.

    Order: bunker → water → tee polygon/marker → green → fairway → rough.
    """
    plat, plon = float(player_lat), float(player_lon)
    meta: dict[str, Any] = {"source": "map_geometry"}
    p_xy = Point(0.0, 0.0)

    bunk = _union_golf(features, "bunker")
    if bunk is not None:
        try:
            bx = _geom_to_xy_m(bunk, plat, plon)
            if bx.contains(p_xy) or bx.distance(p_xy) <= edge_tolerance_m:
                return "bunker", {**meta, "detail": "inside_or_edge_bunker"}
        except Exception:
            pass

    for water_g in ("water_hazard", "lateral_water_hazard"):
        wu = _union_golf(features, water_g)
        if wu is not None:
            try:
                wx = _geom_to_xy_m(wu, plat, plon)
                if wx.contains(p_xy) or wx.distance(p_xy) <= edge_tolerance_m * 0.85:
                    return "rough", {**meta, "detail": f"near_{water_g}", "note": "Ball in or tight to penalty area — confirm locally."}
            except Exception:
                pass

    tee_u = _union_golf(features, "tee")
    if tee_u is not None:
        try:
            tx = _geom_to_xy_m(tee_u, plat, plon)
            if tx.contains(p_xy) or tx.distance(p_xy) <= edge_tolerance_m:
                return "tee", {**meta, "detail": "osm_tee_polygon"}
        except Exception:
            pass

    tee_pt = hole.get("tee") or {}
    if tee_pt.get("lat") is not None and tee_pt.get("lon") is not None:
        d_tee = haversine_yards(plat, plon, float(tee_pt["lat"]), float(tee_pt["lon"]))
        if d_tee <= tee_marker_max_yds:
            return "tee", {**meta, "detail": "near_tee_marker", "distance_yds_from_marker": round(d_tee, 1)}

    green_u = _union_golf(features, "green")
    if green_u is not None:
        try:
            gx = _geom_to_xy_m(green_u, plat, plon)
            if gx.contains(p_xy) or gx.distance(p_xy) <= edge_tolerance_m * 0.75:
                return "fringe", {**meta, "detail": "on_or_around_green"}
        except Exception:
            pass

    fair_u = _union_golf(features, "fairway")
    if fair_u is not None:
        try:
            fx = _geom_to_xy_m(fair_u, plat, plon)
            if fx.contains(p_xy) or fx.distance(p_xy) <= edge_tolerance_m:
                return "fairway", {**meta, "detail": "fairway_polygon"}
        except Exception:
            pass

    return "rough", {**meta, "detail": "not_in_mapped_fairway_tee_bunker"}
