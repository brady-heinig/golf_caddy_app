"""Static course GPS data — Stevens Golf Course (from OSM hole ways)."""

from __future__ import annotations

import math
from typing import Any

def _green_edges(tee: dict[str, float], green_center: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    """Front toward tee, back away from tee; ~0.00008° along tee line."""
    dlat = tee["lat"] - green_center["lat"]
    dlon = tee["lon"] - green_center["lon"]
    h = math.hypot(dlat, dlon)
    if h < 1e-12:
        dlat, dlon, h = 0.0001, 0.0, 0.0001
    u_lat = dlat / h
    u_lon = dlon / h
    k = 0.00008
    green_front = {
        "lat": green_center["lat"] + u_lat * k,
        "lon": green_center["lon"] + u_lon * k,
    }
    green_back = {
        "lat": green_center["lat"] - u_lat * k,
        "lon": green_center["lon"] - u_lon * k,
    }
    return green_front, green_back


_RAW: list[tuple] = [
    (1, 5, 419, 8, 32.7557752, -96.8471386, 32.7559012, -96.85123, [], 'Long par 5 — favor position off the tee; avoid short-siding the green.'),
    (2, 4, 295, 16, 32.755995, -96.8515273, 32.7553941, -96.8543173, [], 'Par 4 — play to the wide side of the fairway and take dead aim on the approach.'),
    (3, 4, 244, 10, 32.7557808, -96.8547449, 32.7540912, -96.8560362, [], 'Par 4 — play to the wide side of the fairway and take dead aim on the approach.'),
    (4, 3, 149, 18, 32.7539662, -96.8564588, 32.7551495, -96.8560858, [], 'Par 3 — pick club for the full carry; center of the green is a good miss.'),
    (5, 4, 395, 6, 32.7561078, -96.8570855, 32.7593466, -96.857377, [], 'Strong par 4 — placement off the tee sets up the best angle into the green.'),
    (6, 5, 487, 4, 32.759621, -96.8583684, 32.7556546, -96.8577073, [], 'Long par 5 — favor position off the tee; avoid short-siding the green.'),
    (7, 3, 151, 12, 32.7556652, -96.8564781, 32.7559094, -96.8550276, [], 'Par 3 — pick club for the full carry; center of the green is a good miss.'),
    (8, 3, 167, 14, 32.7557075, -96.8545025, 32.7564341, -96.8531183, [], 'Par 3 — pick club for the full carry; center of the green is a good miss.'),
    (9, 5, 580, 2, 32.756693, -96.8533694, 32.7564942, -96.8476989, [], 'Long par 5 — favor position off the tee; avoid short-siding the green.'),
    (10, 5, 483, 3, 32.7568178, -96.8473318, 32.7569569, -96.8520541, [], 'Long par 5 — favor position off the tee; avoid short-siding the green.'),
    (11, 4, 342, 9, 32.7568956, -96.8530312, 32.758399, -96.850208, [], 'Par 4 — play to the wide side of the fairway and take dead aim on the approach.'),
    (12, 3, 162, 15, 32.7584507, -96.8507388, 32.7596578, -96.8500735, [], 'Par 3 — pick club for the full carry; center of the green is a good miss.'),
    (13, 4, 273, 11, 32.7602568, -96.8498181, 32.7605307, -96.847173, [], 'Par 4 — play to the wide side of the fairway and take dead aim on the approach.'),
    (14, 3, 196, 7, 32.7610026, -96.8466889, 32.760432, -96.8484781, [], 'Par 3 — pick club for the full carry; center of the green is a good miss.'),
    (15, 4, 387, 5, 32.7604908, -96.8495692, 32.7619226, -96.84619, [], 'Strong par 4 — placement off the tee sets up the best angle into the green.'),
    (16, 5, 447, 1, 32.7625969, -96.8453983, 32.7616593, -96.8496215, [], 'Long par 5 — favor position off the tee; avoid short-siding the green.'),
    (17, 3, 139, 17, 32.7613432, -96.848643, 32.7607208, -96.849785, [], 'Par 3 — pick club for the full carry; center of the green is a good miss.'),
    (18, 4, 304, 13, 32.7589205, -96.849999, 32.7571672, -96.8478862, [], 'Par 4 — play to the wide side of the fairway and take dead aim on the approach.'),
]

def _build_holes() -> list[dict[str, Any]]:
    holes: list[dict[str, Any]] = []
    for row in _RAW:
        num, par, yds, hdcp, tlat, tlon, glat, glon, hazards, notes = row
        tee = {"lat": tlat, "lon": tlon}
        gc = {"lat": glat, "lon": glon}
        gf, gb = _green_edges(tee, gc)
        holes.append(
            {
                "number": num,
                "par": par,
                "yards": yds,
                "handicap": hdcp,
                "tee": tee,
                "green_center": gc,
                "green_front": gf,
                "green_back": gb,
                "hazards": hazards,
                "notes": notes,
            }
        )
    return holes


COURSES: dict[str, Any] = {
    "stevens_golf_course": {
        "name": "Stevens Golf Course",
        "address": "1005 North Montclair Ave, Dallas, TX 75208",
        "par": 71,
        "center_lat": 32.758606,
        "center_lon": -96.850431,
        "osm_way_id": 32490345,
        "holes": _build_holes(),
    }
}