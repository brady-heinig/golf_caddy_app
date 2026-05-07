from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter

from .legacy import elevation as elev_mod
from .legacy import weather as wx_mod

from .routes_caddie_compat import get_course, get_hole, get_plays_like_path, list_courses

router = APIRouter(prefix="/caddie", tags=["caddie"])


@router.get("/courses")
def caddie_list_courses() -> list[dict[str, Any]]:
    return list_courses()


@router.get("/course/{course_id}")
def caddie_get_course(course_id: str) -> dict[str, Any]:
    return get_course(course_id)


@router.get("/course/{course_id}/hole/{hole_number}")
def caddie_get_hole(
    course_id: str,
    hole_number: int,
    player_lat: float | None = None,
    player_lon: float | None = None,
    handicap: float | None = None,
    lie: str = "fairway",
) -> dict[str, Any]:
    return get_hole(
        course_id=course_id,
        hole_number=hole_number,
        player_lat=player_lat,
        player_lon=player_lon,
        handicap=handicap,
        lie=lie,
    )


@router.get("/course/{course_id}/hole/{hole_number}/plays-like-path")
def caddie_get_plays_like_path(
    course_id: str,
    hole_number: int,
    player_lat: float,
    player_lon: float,
    bend_lat: float,
    bend_lon: float,
) -> dict[str, Any]:
    return get_plays_like_path(
        course_id=course_id,
        hole_number=hole_number,
        player_lat=player_lat,
        player_lon=player_lon,
        bend_lat=bend_lat,
        bend_lon=bend_lon,
    )


@router.get("/_debug/open-meteo")
def debug_open_meteo(lat: float = 32.758606, lon: float = -96.850431) -> dict[str, Any]:
    """
    Runs the backend's Open‑Meteo weather + elevation calls from this server.
    Use this to verify Render egress/SSL/DNS in production.
    """
    out: dict[str, Any] = {"lat": lat, "lon": lon}

    t0 = time.time()
    wx = wx_mod.get_weather(float(lat), float(lon))
    out["weather_elapsed_ms"] = int((time.time() - t0) * 1000)
    out["weather"] = wx

    t1 = time.time()
    try:
        e = elev_mod.get_elevations_m([(float(lat), float(lon))])
        out["elevation_elapsed_ms"] = int((time.time() - t1) * 1000)
        out["elevation_m"] = e[0] if e else 0.0
        out["elevation_ok"] = True
    except Exception as ex:
        out["elevation_elapsed_ms"] = int((time.time() - t1) * 1000)
        out["elevation_ok"] = False
        out["elevation_error"] = str(ex)

    out["ok"] = not bool(wx.get("error")) and bool(out.get("elevation_ok"))
    return out

