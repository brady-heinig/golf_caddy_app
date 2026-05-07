from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .legacy import benchmark_stats
from .legacy import course_data
from .legacy import course_features
from .legacy import elevation
from .legacy import weather

router = APIRouter(tags=["caddie-compat"])


def haversine_yards(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_earth = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    meters = r_earth * 2 * math.asin(math.sqrt(a))
    return meters * 1.09361


def _wind_for_segment(
    wx: dict[str, Any],
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
    baseline_yds: float,
) -> tuple[float, float, float, str]:
    if wx.get("error") or wx.get("wind_mph") is None or wx.get("wind_dir_deg") is None:
        return (0.0, 0.0, 0.0, "—")
    mph = float(wx["wind_mph"])
    wdeg = int(round(float(wx["wind_dir_deg"])))
    brg = weather.bearing_deg_lat_lon(lat_a, lon_a, lat_b, lon_b)
    along, cross = weather.wind_shot_along_cross(mph, wdeg, brg)
    w_add, w_sub = weather.wind_yard_head_tail_yds(along, baseline_yds)
    adj = w_add - w_sub
    rel = weather.wind_relation_label(along, cross, mph)
    return (adj, along, cross, rel)


@router.get("/courses")
def list_courses() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cid, c in course_data.COURSES.items():
        out.append(
            {
                "id": cid,
                "name": c.get("name"),
                "center_lat": c.get("center_lat"),
                "center_lon": c.get("center_lon"),
                "par": c.get("par"),
            }
        )
    return out


@router.get("/course/{course_id}")
def get_course(course_id: str) -> dict[str, Any]:
    course = course_data.COURSES.get(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Unknown course_id")
    holes = course.get("holes", []) or []
    return {
        "id": course_id,
        "name": course.get("name"),
        "par": course.get("par"),
        "holes": [
            {
                "number": h.get("number"),
                "par": h.get("par"),
                "yards": h.get("yards"),
                "handicap": h.get("handicap"),
            }
            for h in holes
        ],
    }


@router.get("/course/{course_id}/hole/{hole_number}")
def get_hole(
    course_id: str,
    hole_number: int,
    player_lat: float | None = None,
    player_lon: float | None = None,
    handicap: float | None = None,
    lie: str = "fairway",
) -> dict[str, Any]:
    course = course_data.COURSES.get(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Unknown course_id")
    holes = course.get("holes", []) or []
    if hole_number < 1 or hole_number > len(holes):
        raise HTTPException(status_code=404, detail="Unknown hole_number")

    hole = holes[hole_number - 1]
    try:
        features = course_features.load_hole_feature_collection(course_id, hole_number)
    except Exception:
        features = {"type": "FeatureCollection", "features": []}
    w = weather.get_weather(float(course["center_lat"]), float(course["center_lon"]))

    gc = hole["green_center"]
    if player_lat is not None and player_lon is not None:
        p_lat, p_lon = float(player_lat), float(player_lon)
    else:
        tee = hole["tee"]
        p_lat, p_lon = float(tee["lat"]), float(tee["lon"])

    el_pin_m, el_from_m = elevation.get_elevations_m([(gc["lat"], gc["lon"]), (p_lat, p_lon)])
    el_change_ft = elevation.elevation_change_ft(el_pin_m, el_from_m)
    dist_yd = haversine_yards(p_lat, p_lon, gc["lat"], gc["lon"])
    elev_adj_yd = el_change_ft / 3.0
    baseline = float(dist_yd) + elev_adj_yd
    w_adj, _a, _c, w_rel = _wind_for_segment(w, p_lat, p_lon, gc["lat"], gc["lon"], baseline)
    plays_like_yd = baseline + w_adj

    hcp = 15.0 if handicap is None else float(handicap)
    gir_pct, _ = benchmark_stats.expected_gir_model_percent(int(round(plays_like_yd)), hcp, lie)

    metrics: dict[str, Any] = {
        "hole_number": hole_number,
        "distance_yd": round(dist_yd),
        "plays_like_yd": round(plays_like_yd),
        "elev_change_yd": round(elev_adj_yd, 1),
        "wind_adjust_yd": round(w_adj, 1),
        "wind_relation": w_rel,
        "green_hit_pct": round(float(gir_pct), 2),
    }

    return {
        "course": {"id": course_id, "name": course.get("name")},
        "hole": hole,
        "features": features,
        "weather": w,
        "metrics": metrics,
    }


@router.get("/course/{course_id}/hole/{hole_number}/plays-like-path")
def get_plays_like_path(
    course_id: str,
    hole_number: int,
    player_lat: float,
    player_lon: float,
    bend_lat: float,
    bend_lon: float,
) -> dict[str, Any]:
    course = course_data.COURSES.get(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Unknown course_id")
    holes = course.get("holes", []) or []
    if hole_number < 1 or hole_number > len(holes):
        raise HTTPException(status_code=404, detail="Unknown hole_number")

    hole = holes[hole_number - 1]
    g_lat = float(hole["green_center"]["lat"])
    g_lon = float(hole["green_center"]["lon"])

    wx = weather.get_weather(float(course["center_lat"]), float(course["center_lon"]))

    h1 = haversine_yards(player_lat, player_lon, bend_lat, bend_lon)
    h2 = haversine_yards(bend_lat, bend_lon, g_lat, g_lon)
    el_p, el_b, el_g = elevation.get_elevations_m(
        [(player_lat, player_lon), (bend_lat, bend_lon), (g_lat, g_lon)]
    )
    leg1_ft = elevation.elevation_change_ft(el_b, el_p)
    leg2_ft = elevation.elevation_change_ft(el_g, el_b)
    base1 = elevation.plays_like_yards(h1, leg1_ft)
    base2 = elevation.plays_like_yards(h2, leg2_ft)
    w1, _a1, _c1, r1 = _wind_for_segment(wx, float(player_lat), float(player_lon), float(bend_lat), float(bend_lon), base1)
    w2, _a2, _c2, r2 = _wind_for_segment(wx, float(bend_lat), float(bend_lon), float(g_lat), float(g_lon), base2)
    leg1 = base1 + w1
    leg2 = base2 + w2

    return {
        "leg1_horiz_yd": round(h1),
        "leg2_horiz_yd": round(h2),
        "leg1_plays_like_yd": round(leg1),
        "leg2_plays_like_yd": round(leg2),
        "leg1_elev_change_yd": round(leg1_ft / 3.0, 1),
        "leg2_elev_change_yd": round(leg2_ft / 3.0, 1),
        "leg1_wind_adjust_yd": round(w1, 1),
        "leg2_wind_adjust_yd": round(w2, 1),
        "leg1_wind_relation": r1,
        "leg2_wind_relation": r2,
    }


class CaddieRequest(BaseModel):
    course_id: str
    hole_number: int
    distance_to_pin: int
    lie: str
    shot_shape: str
    player_lat: float | None = None
    player_lon: float | None = None


@router.post("/caddie")
def caddie_advice(_req: CaddieRequest) -> dict[str, Any]:
    # The Render/Supabase app already supports chat-per-round. This is a lightweight
    # compat endpoint so the caddie prototype UI can be hosted too.
    raise HTTPException(
        status_code=501,
        detail="Use /api/rounds/{round_id}/chat (round-based chat) in this hosted version.",
    )

