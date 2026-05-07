"""
fetch_osm.py
Queries Overpass API for golf course features and saves to shots.db.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import warnings
from datetime import datetime, timezone
from typing import Any

import overpy

from course_data import COURSES
from shot_log import init_db


def polygon_centroid(nodes: list[dict[str, float]]) -> tuple[float, float]:
    """Given a list of {"lat": float, "lon": float} dicts, return (lat, lon) centroid."""
    if not nodes:
        return 0.0, 0.0
    lat = sum(n["lat"] for n in nodes) / len(nodes)
    lon = sum(n["lon"] for n in nodes) / len(nodes)
    return lat, lon


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _nearest_hole(lat: float, lon: float, course_id: str = "stevens_golf_course") -> int | None:
    holes = COURSES[course_id]["holes"]
    best: tuple[float, int] | None = None
    for h in holes:
        mid_lat = (h["tee"]["lat"] + h["green_center"]["lat"]) / 2
        mid_lon = (h["tee"]["lon"] + h["green_center"]["lon"]) / 2
        d = _haversine_km(lat, lon, mid_lat, mid_lon)
        if best is None or d < best[0]:
            best = (d, int(h["number"]))
    return best[1] if best else None


def _way_nodes(way: overpy.Way) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for n in way.get_nodes(resolve_missing=True):
        out.append({"lat": float(n.lat), "lon": float(n.lon)})
    return out


def run_fetch(
    course_name: str,
    bbox: str,
    db_path: str = "shots.db",
    course_id: str = "stevens_golf_course",
) -> None:
    if course_id not in COURSES:
        print(f"Unknown course_id {course_id!r}; keys: {list(COURSES)}", file=sys.stderr)
        sys.exit(1)
    init_db(db_path)
    parts = [float(x.strip()) for x in bbox.split(",")]
    if len(parts) != 4:
        print("bbox must be south,west,north,east", file=sys.stderr)
        sys.exit(1)
    south, west, north, east = parts

    query = f"""
    [out:json][timeout:90];
    (
      way["leisure"="golf_course"]({south},{west},{north},{east});
      way["golf"="green"]({south},{west},{north},{east});
      way["golf"="fairway"]({south},{west},{north},{east});
      way["golf"="bunker"]({south},{west},{north},{east});
      way["golf"="water_hazard"]({south},{west},{north},{east});
      way["golf"="tee"]({south},{west},{north},{east});
      node["golf"="pin"]({south},{west},{north},{east});
    );
    out geom;
    """

    api = overpy.Overpass()
    try:
        result = api.query(query)
    except Exception as e:
        print(f"Overpass query failed: {e}", file=sys.stderr)
        sys.exit(1)

    greens = 0
    fairways = 0
    bunkers = 0
    tees = 0
    water = 0
    pins = 0

    osm_holes: dict[int, list[dict[str, Any]]] = {}

    for way in result.ways:
        tags = way.tags or {}
        if tags.get("leisure") == "golf_course":
            continue
        gtag = tags.get("golf")
        nodes = _way_nodes(way)
        if not nodes:
            continue
        lat, lon = polygon_centroid(nodes)
        if gtag == "green":
            greens += 1
        elif gtag == "fairway":
            fairways += 1
        elif gtag == "bunker":
            bunkers += 1
        elif gtag == "tee":
            tees += 1
        elif gtag == "water_hazard":
            water += 1
        ref = tags.get("ref") or tags.get("hole")
        hole_num: int | None = None
        if ref:
            try:
                hole_num = int(str(ref).split(";")[0].strip())
            except ValueError:
                hole_num = None
        if hole_num is None:
            hole_num = _nearest_hole(lat, lon)
        if hole_num is None:
            continue
        feat = {
            "type": gtag or "unknown",
            "centroid_lat": lat,
            "centroid_lon": lon,
            "tags": dict(tags),
        }
        osm_holes.setdefault(hole_num, []).append(feat)

    for node in result.nodes:
        tags = node.tags or {}
        if tags.get("golf") == "pin":
            pins += 1
            lat, lon = float(node.lat), float(node.lon)
            hole_num = _nearest_hole(lat, lon)
            if hole_num:
                osm_holes.setdefault(hole_num, []).append(
                    {
                        "type": "pin",
                        "centroid_lat": lat,
                        "centroid_lon": lon,
                        "tags": dict(tags),
                    }
                )

    base = json.loads(json.dumps(COURSES[course_id]))
    for hn, feats in osm_holes.items():
        for h in base["holes"]:
            if h["number"] == hn:
                h.setdefault("osm_features", []).extend(feats)

    payload = {
        "name": course_name,
        "course_id": course_id,
        "bbox": {"south": south, "west": west, "north": north, "east": east},
        "merged_course": base,
    }
    raw_json = json.dumps(payload)
    updated_at = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO courses (course_id, name, raw_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(course_id) DO UPDATE SET
          name = excluded.name,
          raw_json = excluded.raw_json,
          updated_at = excluded.updated_at
        """,
        (course_id, course_name, raw_json, updated_at),
    )
    conn.commit()
    conn.close()

    print(
        f"Summary: greens={greens}, fairways={fairways}, bunkers={bunkers}, "
        f"tees={tees}, water_hazards={water}, pins={pins}, holes_with_features={len(osm_holes)}"
    )
    if greens + fairways + bunkers + tees == 0:
        warnings.warn(
            "OSM returned few or no golf features; keeping static course_data.py as primary source.",
            UserWarning,
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch OSM golf data into shots.db")
    p.add_argument("--course", required=True, help='Course display name, e.g. "Stevens Golf Course"')
    p.add_argument(
        "--course-id",
        default="stevens_golf_course",
        help="Key in course_data.COURSES (default: stevens_golf_course)",
    )
    p.add_argument("--bbox", required=True, help="Bounding box south,west,north,east")
    p.add_argument("--db", default="shots.db", help="SQLite path")
    args = p.parse_args()
    run_fetch(args.course, args.bbox, args.db, course_id=args.course_id)


if __name__ == "__main__":
    main()
