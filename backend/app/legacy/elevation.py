"""Elevation and plays-like yardages (Open-Meteo Copernicus DEM)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import requests

_OPEN_METEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"


def _round_coord(lat: float, lon: float) -> tuple[float, float]:
    return (round(float(lat), 5), round(float(lon), 5))


_ELEV_CACHE_REV = 1


def _open_meteo_get(url: str) -> dict[str, Any] | None:
    try:
        r = requests.get(url, headers={"User-Agent": "golf-caddy-app/1.0"}, timeout=12)
        if r.status_code != 200:
            return None
        out = r.json()
        return out if isinstance(out, dict) else None
    except (requests.RequestException, ValueError):
        return None


@lru_cache(maxsize=4096)
def _get_elevation_m_cached(lat_r: float, lon_r: float, _rev: int) -> float:
    url = f"{_OPEN_METEO_ELEVATION}?{urlencode({'latitude': str(lat_r), 'longitude': str(lon_r)})}"
    data = _open_meteo_get(url)
    if not data or data.get("error") is True:
        return 0.0
    elev = data.get("elevation")
    if isinstance(elev, list) and elev:
        try:
            return float(elev[0])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def get_elevation_m(lat: float, lon: float) -> float:
    lat_r, lon_r = _round_coord(lat, lon)
    return _get_elevation_m_cached(lat_r, lon_r, _ELEV_CACHE_REV)


def get_elevations_m(coords: list[tuple[float, float]]) -> list[float]:
    if not coords:
        return []
    lats: list[str] = []
    lons: list[str] = []
    for lat, lon in coords:
        lat_r, lon_r = _round_coord(lat, lon)
        lats.append(str(lat_r))
        lons.append(str(lon_r))
    url = f"{_OPEN_METEO_ELEVATION}?{urlencode({'latitude': ','.join(lats), 'longitude': ','.join(lons)})}"
    data = _open_meteo_get(url)
    if not data or data.get("error") is True:
        return [0.0] * len(coords)
    elev = data.get("elevation")
    if not isinstance(elev, list) or len(elev) != len(coords):
        return [0.0] * len(coords)
    out: list[float] = []
    for v in elev:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def elevation_change_ft(elev_to_m: float, elev_from_m: float) -> float:
    """Signed feet: positive when 'to' is higher than 'from'."""
    return (float(elev_to_m) - float(elev_from_m)) * 3.28084


def plays_like_yards(dist_yd: float, el_change_ft: float) -> float:
    """Rule used by the caddie app: playsLikeYd = distanceYd + elChangeFt / 3."""
    return float(dist_yd) + float(el_change_ft) / 3.0

