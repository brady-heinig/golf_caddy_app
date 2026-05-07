"""Elevation for plays-like yardages (Copernicus DEM via Open-Meteo)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import requests

# Open-Meteo: Copernicus GLO-90 (~90 m). ArcGIS Terrain3D /identify often returns one
# coarse value across entire metro areas, so tee and green read as flat.
_OPEN_METEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"


def _round_coord(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 5), round(lon, 5))


# Bump to invalidate lru_cache when provider or parsing changes.
_ELEV_CACHE_REV = 3


def _open_meteo_get(url: str) -> dict[str, Any] | None:
    """GET JSON from Open-Meteo; None on HTTP/network/parse failure."""
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "golf-caddie/1.0"},
            timeout=12,
        )
        if r.status_code != 200:
            return None
        out = r.json()
        return out if isinstance(out, dict) else None
    except (requests.RequestException, ValueError):
        return None


@lru_cache(maxsize=4096)
def _get_elevation_m_cached(lat_r: float, lon_r: float, _rev: int) -> float:
    """Return elevation in meters (orthometric, Copernicus DEM) or 0.0 on failure."""
    params: dict[str, str] = {
        "latitude": str(lat_r),
        "longitude": str(lon_r),
    }
    url = f"{_OPEN_METEO_ELEVATION}?{urlencode(params)}"
    data = _open_meteo_get(url)
    if data is None:
        return 0.0

    if data.get("error") is True:
        return 0.0
    elev = data.get("elevation")
    if isinstance(elev, list) and elev:
        try:
            return float(elev[0])
        except (TypeError, ValueError):
            pass
    return 0.0


def get_elevation_m(lat: float, lon: float) -> float:
    lat_r, lon_r = _round_coord(lat, lon)
    return _get_elevation_m_cached(lat_r, lon_r, _ELEV_CACHE_REV)


def get_elevations_m(coords: list[tuple[float, float]]) -> list[float]:
    """
    Batch lookup (one HTTP call, up to 100 points per Open-Meteo docs).
    Preserves order; on failure returns zeros for missing entries.
    """
    if not coords:
        return []
    lats: list[str] = []
    lons: list[str] = []
    for lat, lon in coords:
        lat_r, lon_r = _round_coord(lat, lon)
        lats.append(str(lat_r))
        lons.append(str(lon_r))
    params = {"latitude": ",".join(lats), "longitude": ",".join(lons)}
    url = f"{_OPEN_METEO_ELEVATION}?{urlencode(params)}"
    data = _open_meteo_get(url)
    if data is None:
        return [0.0] * len(coords)
    if data.get("error") is True:
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


def plays_like_yards(dist_yd: float, el_change_ft: float) -> float:
    """ace main.ts: playsLikeYd = distanceYd + elChangeFt / 3"""
    return float(dist_yd) + float(el_change_ft) / 3.0


def plays_like_segment_yds(
    lat1: float, lon1: float, lat2: float, lon2: float, horiz_yds: float
) -> float:
    """
    Plays-like yards along one map segment (horizontal distance + elevation rule).
    el_change_ft: positive when point 2 is higher than point 1 (plays longer).
    """
    e1 = get_elevation_m(lat1, lon1)
    e2 = get_elevation_m(lat2, lon2)
    el_change_ft = elevation_change_ft(e2, e1)
    return plays_like_yards(horiz_yds, el_change_ft)


def elevation_change_ft(elev_pin_m: float, elev_player_m: float) -> float:
    """Signed feet: positive = pin higher than player (plays longer)."""
    return (elev_pin_m - elev_player_m) * 3.28084
