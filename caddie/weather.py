"""Open-Meteo weather for the AI Golf Caddie."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather interpretation codes (WW) — simplified day conditions
_WMO_CONDITIONS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle (light)",
    57: "Freezing drizzle (dense)",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Freezing rain (light)",
    67: "Freezing rain (heavy)",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers (slight)",
    81: "Rain showers (moderate)",
    82: "Rain showers (violent)",
    85: "Snow showers (slight)",
    86: "Snow showers (heavy)",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def degrees_to_cardinal(deg: int) -> str:
    """Convert 0–360 degrees to cardinal string (N, NNE, NE, … NNW)."""
    directions = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    idx = round(deg / 22.5) % 16
    return directions[idx]


def bearing_tee_to_green(tee: dict, green: dict) -> float:
    """
    Calculate compass bearing in degrees from tee to green_center.
    tee and green are dicts with "lat" and "lon" keys.
    Returns float 0–360.
    """
    lat1, lon1 = math.radians(tee["lat"]), math.radians(tee["lon"])
    lat2, lon2 = math.radians(green["lat"]), math.radians(green["lon"])
    dlon = math.radians(green["lon"] - tee["lon"])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brng = (math.degrees(math.atan2(x, y)) + 360) % 360
    return float(brng)


def bearing_deg_lat_lon(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from (lat1, lon1) toward (lat2, lon2), degrees in [0, 360)."""
    lat1r, lon1r = math.radians(lat1), math.radians(lon1)
    lat2r, lon2r = math.radians(lat2), math.radians(lon2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def wind_shot_along_cross(
    wind_mph: float, wind_from_deg: float, bearing_shot_deg: float
) -> tuple[float, float]:
    """
    Project wind onto the shot direction (toward the target at bearing_shot_deg).

    Meteorological wind FROM (deg) → air motion toward (from+180) °, same
    clockwise-from-north convention as initial bearing (player → target).

    along_mph: positive = tailwind (subtract from plays-like); negative = headwind (add).
    cross_mph: positive = air motion is to the right of the shot direction.
    """
    wind_to = (float(wind_from_deg) + 180.0) % 360.0
    rad = math.radians(wind_to - float(bearing_shot_deg))
    w = float(wind_mph)
    along = w * math.cos(rad)
    cross = w * math.sin(rad)
    return along, cross


def wind_yard_head_tail_yds(along_mph: float, baseline_yds: float) -> tuple[float, float]:
    """
    Non-negative yard effects vs the elev-adjusted baseline (horizontal + Δelev/3).

    Returns (headwind_yds_to_add, tailwind_yds_to_subtract).
    plays_like_yd = baseline + headwind_yds_to_add - tailwind_yds_to_subtract

    along_mph: from wind_shot_along_cross (positive = tailwind, negative = headwind).
    """
    if baseline_yds <= 0:
        return (0.0, 0.0)
    b = float(baseline_yds)
    head_mph = max(0.0, -float(along_mph))
    tail_mph = max(0.0, float(along_mph))
    return (b * 0.01 * head_mph, b * 0.005 * tail_mph)


def wind_yard_adjust_along_baseline(along_mph: float, baseline_yds: float) -> float:
    """Signed net wind yards (inverted vs add−sub: tailwind term minus headwind term)."""
    add, sub = wind_yard_head_tail_yds(along_mph, baseline_yds)
    return sub - add


def classify_wind_table_category(
    along_mph: float, cross_mph: float, wind_mph: float
) -> str:
    """
    Map along/cross components to a table row: headwind, tailwind,
    quartering head/tail, crosswind, or calm.
    """
    if wind_mph < 0.5:
        return "calm"
    a, c = abs(along_mph), abs(cross_mph)
    if a < 0.08 and c < 0.08:
        return "calm"
    ang = math.degrees(math.atan2(c, a))
    if ang >= 67.5:
        return "crosswind"
    if ang <= 22.5:
        return "headwind" if along_mph < 0 else "tailwind"
    return "quartering_headwind" if along_mph < 0 else "quartering_tailwind"


def wind_relation_label(along_mph: float, cross_mph: float, wind_mph: float) -> str:
    """UI label for wind vs shot (head / tail / cross / quartering)."""
    cat = classify_wind_table_category(along_mph, cross_mph, wind_mph)
    if cat == "calm":
        return "Calm"
    if cat == "headwind":
        return "Headwind"
    if cat == "tailwind":
        return "Tailwind"
    if cat == "quartering_headwind":
        return "Quartering headwind"
    if cat == "quartering_tailwind":
        return "Quartering tailwind"
    if cross_mph > 0:
        return "Crosswind (L→R)"
    return "Crosswind (R→L)"


def wind_relative_to_hole(wind_dir_deg: int, hole_bearing_deg: float) -> str:
    """
    Given wind FROM direction and the compass bearing from ball to target
    (e.g. tee→green or player→green), return a coarse head/tail/cross label.
    """
    relative = (wind_dir_deg - hole_bearing_deg) % 360
    if relative <= 45 or relative >= 315:
        return "headwind"
    if 45 < relative <= 135:
        return "right-to-left crosswind"
    if 135 < relative <= 225:
        return "tailwind"
    return "left-to-right crosswind"


def _empty_error_dict(err: str) -> dict[str, Any]:
    return {
        "temp_f": None,
        "humidity_pct": None,
        "wind_mph": None,
        "wind_dir_deg": None,
        "wind_dir_card": None,
        "precip_mm": None,
        "condition": None,
        "fetched_at": None,
        "error": err,
    }


def get_weather(lat: float, lon: float) -> dict:
    """
    Call Open-Meteo current weather endpoint.
    On any HTTP or parse error, return dict with None values and "error" key.
    Never raises.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "wind_speed_10m",
                "wind_direction_10m",
                "precipitation",
                "weather_code",
            ]
        ),
        "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit",
        "forecast_days": 1,
    }
    try:
        # Avoid broken/locked-down proxy envs (common on campus networks / managed machines).
        s = requests.Session()
        s.trust_env = False
        r = s.get(OPEN_METEO_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        cur = data.get("current") or {}
        wc = int(cur.get("weather_code", 0))
        wind_deg = int(round(float(cur.get("wind_direction_10m", 0))))
        fetched = datetime.now(timezone.utc).isoformat()
        return {
            "temp_f": float(cur.get("temperature_2m", 0)),
            "humidity_pct": int(round(float(cur.get("relative_humidity_2m", 0)))),
            "wind_mph": float(cur.get("wind_speed_10m", 0)),
            "wind_dir_deg": wind_deg,
            "wind_dir_card": degrees_to_cardinal(wind_deg),
            "precip_mm": float(cur.get("precipitation", 0)),
            "condition": _WMO_CONDITIONS.get(wc, f"Weather code {wc}"),
            "fetched_at": fetched,
        }
    except Exception as e:
        return _empty_error_dict(str(e))
