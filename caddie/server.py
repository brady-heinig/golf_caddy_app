from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import benchmark_stats
import caddie
import course_data
import course_features
import elevation
import shot_log
import weather

app = FastAPI(title="AI Caddie API")


def _wind_for_segment(
    wx: dict[str, Any],
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
    baseline_yds: float,
) -> tuple[float, float, float, str]:
    """
    Wind effect on plays-like: baseline − headwind_add + tailwind_subtract (inverted vs raw add/sub parts).
    wind_adjust_yd is net (subtract − add from head/tail decomposition), negative when headwind dominates.
    """
    if wx.get("error") or wx.get("wind_mph") is None or wx.get("wind_dir_deg") is None:
        return (0.0, 0.0, 0.0, "—")
    mph = float(wx["wind_mph"])
    wdeg = int(round(float(wx["wind_dir_deg"])))
    brg = weather.bearing_deg_lat_lon(lat_a, lon_a, lat_b, lon_b)
    along, cross = weather.wind_shot_along_cross(mph, wdeg, brg)
    w_add, w_sub = weather.wind_yard_head_tail_yds(along, baseline_yds)
    adj = w_sub - w_add
    rel = weather.wind_relation_label(along, cross, mph)
    return (adj, along, cross, rel)


# Dev-friendly CORS; lock down for production if needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/courses")
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


@app.get("/api/course/{course_id}/hole/{hole_number}")
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
    if hole_number < 1 or hole_number > len(course.get("holes", [])):
        raise HTTPException(status_code=404, detail="Unknown hole_number")

    hole = course["holes"][hole_number - 1]
    features = course_features.load_hole_feature_collection(course_id, hole_number)

    w = weather.get_weather(course["center_lat"], course["center_lon"])
    gc = hole["green_center"]
    if player_lat is not None and player_lon is not None:
        p_lat, p_lon = float(player_lat), float(player_lon)
    else:
        tee = hole["tee"]
        p_lat, p_lon = float(tee["lat"]), float(tee["lon"])

    el_pin_m, el_from_m = elevation.get_elevations_m(
        [(gc["lat"], gc["lon"]), (p_lat, p_lon)]
    )
    el_change_ft = elevation.elevation_change_ft(el_pin_m, el_from_m)

    dist_yd = caddie.haversine_yards(
        p_lat,
        p_lon,
        gc["lat"],
        gc["lon"],
    )
    elev_adj_yd = el_change_ft / 3.0
    baseline = float(dist_yd) + elev_adj_yd
    w_adj, _w_along, _w_cross, w_rel = _wind_for_segment(
        w, p_lat, p_lon, gc["lat"], gc["lon"], baseline
    )
    # baseline is elev-adjusted; plays_like applies inverted net wind vs head/tail decomposition
    plays_like_yd = baseline + w_adj

    hcp = 15.0 if handicap is None else float(handicap)
    # Use plays-like yards (elevation + wind) for GIR benchmark.
    gir_model_pct, tour_gir_pct = benchmark_stats.expected_gir_model_percent(
        int(round(plays_like_yd)), hcp, lie
    )

    metrics: dict[str, Any] = {
        "hole_number": hole_number,
        "distance_yd": round(dist_yd),
        "plays_like_yd": round(plays_like_yd),
        "elev_change_yd": round(elev_adj_yd, 1),
        "wind_adjust_yd": round(w_adj, 1),
        "wind_relation": w_rel,
        "green_hit_pct": round(float(tour_gir_pct), 2),
        "green_hit_pct_model": round(float(gir_model_pct), 2),
    }

    return {
        "course": {
            "id": course_id,
            "name": course.get("name"),
        },
        "hole": hole,
        "features": features,
        "weather": w,
        "metrics": metrics,
    }


@app.get("/api/course/{course_id}/hole/{hole_number}/plays-like-path")
def get_plays_like_path(
    course_id: str,
    hole_number: int,
    player_lat: float,
    player_lon: float,
    bend_lat: float,
    bend_lon: float,
) -> dict[str, Any]:
    """Yardages for player→bend and bend→green with the same elevation rule as metrics."""
    course = course_data.COURSES.get(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Unknown course_id")
    if hole_number < 1 or hole_number > len(course.get("holes", [])):
        raise HTTPException(status_code=404, detail="Unknown hole_number")

    hole = course["holes"][hole_number - 1]
    g_lat = hole["green_center"]["lat"]
    g_lon = hole["green_center"]["lon"]

    wx = weather.get_weather(course["center_lat"], course["center_lon"])

    h1 = caddie.haversine_yards(player_lat, player_lon, bend_lat, bend_lon)
    h2 = caddie.haversine_yards(bend_lat, bend_lon, g_lat, g_lon)
    el_p, el_b, el_g = elevation.get_elevations_m(
        [(player_lat, player_lon), (bend_lat, bend_lon), (g_lat, g_lon)]
    )
    leg1_ft = elevation.elevation_change_ft(el_b, el_p)
    leg2_ft = elevation.elevation_change_ft(el_g, el_b)
    base1 = elevation.plays_like_yards(h1, leg1_ft)
    base2 = elevation.plays_like_yards(h2, leg2_ft)
    w1, _a1, _c1, r1 = _wind_for_segment(
        wx,
        float(player_lat),
        float(player_lon),
        float(bend_lat),
        float(bend_lon),
        base1,
    )
    w2, _a2, _c2, r2 = _wind_for_segment(
        wx,
        float(bend_lat),
        float(bend_lon),
        float(g_lat),
        float(g_lon),
        base2,
    )
    # Each leg: elev baseline + inverted net wind (w_sub − w_add)
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


@app.get("/api/course/{course_id}")
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


class CaddieRequest(BaseModel):
    course_id: str
    hole_number: int
    distance_to_pin: int
    lie: str
    shot_shape: str
    player_lat: float | None = None
    player_lon: float | None = None


@app.post("/api/caddie")
def caddie_advice(req: CaddieRequest) -> dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY not set")

    course = course_data.COURSES.get(req.course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Unknown course_id")
    if req.hole_number < 1 or req.hole_number > len(course.get("holes", [])):
        raise HTTPException(status_code=404, detail="Unknown hole_number")

    hole = course["holes"][req.hole_number - 1]

    conn = shot_log.init_db()
    similar = shot_log.get_shots_at_distance(conn, int(req.distance_to_pin), tolerance=15, limit=50)
    history_str = shot_log.format_history_for_prompt(similar)
    hcp = 15.0
    bench_block = benchmark_stats.format_benchmark_for_prompt(
        int(req.distance_to_pin),
        req.lie,
        hcp,
        similar,
    )
    w = weather.get_weather(course["center_lat"], course["center_lon"])

    gc = hole["green_center"]
    if req.player_lat is not None and req.player_lon is not None:
        el_pin_m, el_from_m = elevation.get_elevations_m(
            [(gc["lat"], gc["lon"]), (req.player_lat, req.player_lon)]
        )
    else:
        tee = hole["tee"]
        el_pin_m, el_from_m = elevation.get_elevations_m(
            [(gc["lat"], gc["lon"]), (tee["lat"], tee["lon"])]
        )
    el_change_ft = elevation.elevation_change_ft(el_pin_m, el_from_m)
    elev_adj_yd = el_change_ft / 3.0
    baseline = float(req.distance_to_pin) + elev_adj_yd
    w_adj, _, _, _ = _wind_for_segment(
        w,
        float(req.player_lat) if req.player_lat is not None else float(hole["tee"]["lat"]),
        float(req.player_lon) if req.player_lon is not None else float(hole["tee"]["lon"]),
        gc["lat"],
        gc["lon"],
        baseline,
    )
    plays_like_yd = int(round(baseline + w_adj))  # signed w_adj (inverted vs old add−sub convention)

    advice = caddie.get_caddie_advice(
        distance_to_pin=int(req.distance_to_pin),
        lie=req.lie,
        shot_shape=req.shot_shape,
        weather=w if isinstance(w, dict) and not w.get("error") else None,
        hole_data=hole,
        shot_history=history_str,
        player_lat=req.player_lat,
        player_lon=req.player_lon,
        benchmark_block=bench_block,
        plays_like_yds=plays_like_yd,
        el_change_ft=el_change_ft,
    )
    return {"advice": advice}

