from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

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
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Rain showers (slight)",
    81: "Rain showers (moderate)",
    82: "Rain showers (violent)",
    95: "Thunderstorm",
}


def degrees_to_cardinal(deg: int) -> str:
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(deg / 22.5) % 16
    return directions[idx]


def bearing_tee_to_green(tee: dict, green: dict) -> float:
    lat1, lon1 = math.radians(tee["lat"]), math.radians(tee["lon"])
    lat2, lon2 = math.radians(green["lat"]), math.radians(green["lon"])
    dlon = math.radians(green["lon"] - tee["lon"])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return float((math.degrees(math.atan2(x, y)) + 360) % 360)


def wind_relative_to_hole(wind_dir_deg: int, hole_bearing_deg: float) -> str:
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


def get_weather(lat: float, lon: float) -> dict[str, Any]:
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
        r = requests.get(OPEN_METEO_URL, params=params, timeout=15)
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

