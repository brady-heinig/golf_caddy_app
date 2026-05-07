"""
OSM golf features per hole — mirrors ace docs/main.ts Overpass + grouping.
Caches full course GeoJSON under .cache/<course_id>.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import overpy
import requests
from requests import Response
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union

from course_data import COURSES

_CACHE_DIR = Path(__file__).resolve().parent / ".cache"

_AROUND_M = 5000
_CACHE_VERSION = 3
_OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _way_to_coords(way: overpy.Way) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for n in way.get_nodes(resolve_missing=True):
        out.append((float(n.lon), float(n.lat)))
    return out


def _coords_to_geojson_geometry(coords: list[tuple[float, float]], closed: bool) -> dict[str, Any]:
    if len(coords) < 2:
        return {"type": "Point", "coordinates": coords[0]}
    if closed and len(coords) >= 4 and coords[0] == coords[-1]:
        # Polygon outer ring (lon, lat)
        return {"type": "Polygon", "coordinates": [coords]}
    return {"type": "LineString", "coordinates": coords}


def _fetch_overpass_json(course_id: str, lat: float, lon: float) -> dict[str, Any]:
    osm_id = COURSES[course_id].get("osm_way_id")
    id_clause = f"nwr({int(osm_id)});" if osm_id else ""

    q = f"""
[out:json][timeout:120];
(
  way["golf"="hole"](around:{_AROUND_M},{lat},{lon});
  way["golf"="tee"](around:{_AROUND_M},{lat},{lon});
  nwr["golf"="fairway"](around:{_AROUND_M},{lat},{lon});
  way["golf"="bunker"](around:{_AROUND_M},{lat},{lon});
  way["golf"="green"](around:{_AROUND_M},{lat},{lon});
  way["golf"="driving_range"](around:{_AROUND_M},{lat},{lon});
  nwr["golf"="water_hazard"](around:{_AROUND_M},{lat},{lon});
  nwr["golf"="lateral_water_hazard"](around:{_AROUND_M},{lat},{lon});
  nwr["golf"="out_of_bounds"](around:{_AROUND_M},{lat},{lon});
  {id_clause}
);
out body;
>;
out skel qt;
"""

    headers = {
        # Overpass instances can return 406 if they dislike defaults;
        # sending a clear UA + accept header helps and is polite.
        "User-Agent": "golf-caddy-app/1.0 (streamlit; contact: local)",
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
    }

    last_err: Exception | None = None
    for api in _OVERPASS_ENDPOINTS:
        try:
            r: Response = requests.post(api, data={"data": q}, headers=headers, timeout=120)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            continue

    # If all endpoints fail, surface a single error.
    raise RuntimeError("All Overpass endpoints failed") from last_err


def _elements_to_geojson_features(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Parse Overpass JSON into GeoJSON features + course boundary polygon if found."""
    elems = {str(e["id"]): e for e in data.get("elements", []) if "id" in e}
    ways: dict[str, Any] = {}
    nodes: dict[str, tuple[float, float]] = {}
    relations: dict[str, Any] = {}
    for e in data.get("elements", []):
        t = e.get("type")
        if t == "node" and "lat" in e and "lon" in e:
            nodes[str(e["id"])] = (float(e["lon"]), float(e["lat"]))
        elif t == "way":
            ways[str(e["id"])] = e
        elif t == "relation":
            relations[str(e["id"])] = e

    course_bounds_geom: Any = None
    features: list[dict[str, Any]] = []

    def ring_coords(way_id: str) -> list[tuple[float, float]]:
        w = ways.get(way_id)
        if not w:
            return []
        out: list[tuple[float, float]] = []
        for nid in w.get("nodes", []):
            p = nodes.get(str(nid))
            if p:
                out.append(p)
        return out

    def _close_ring(r: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(r) >= 3 and r[0] != r[-1]:
            return r + [r[0]]
        return r

    # Relations (multipolygons) are common for greens/fairways.
    for rid, rel in relations.items():
        tags = rel.get("tags") or {}
        gtag = tags.get("golf")
        if gtag not in (
            "tee",
            "fairway",
            "bunker",
            "green",
            "driving_range",
            "water_hazard",
            "lateral_water_hazard",
            "out_of_bounds",
        ):
            continue
        if (tags.get("type") or "").lower() not in ("multipolygon", "boundary", ""):
            continue

        outers: list[list[tuple[float, float]]] = []
        inners: list[list[tuple[float, float]]] = []
        for m in rel.get("members", []) or []:
            if m.get("type") != "way":
                continue
            wid = str(m.get("ref"))
            role = (m.get("role") or "").lower()
            rc = ring_coords(wid)
            if len(rc) < 3:
                continue
            rc = _close_ring(rc)
            if role == "inner":
                inners.append(rc)
            else:
                outers.append(rc)

        if not outers:
            continue

        if len(outers) == 1:
            geom = {"type": "Polygon", "coordinates": [outers[0]] + inners}
        else:
            # If multiple outers, we don't reliably know which inners belong to which outer.
            # Use a MultiPolygon with outers only (still outlines greens/fairways correctly).
            geom = {"type": "MultiPolygon", "coordinates": [[o] for o in outers]}

        props = dict(tags)
        props["golf"] = gtag
        props["_osm_relation_id"] = int(rel.get("id", 0))
        features.append({"type": "Feature", "geometry": geom, "properties": props})

    for wid, w in ways.items():
        tags = w.get("tags") or {}
        gtag = tags.get("golf")
        leisure = tags.get("leisure")
        if leisure == "golf_course" and not gtag:
            rc = ring_coords(wid)
            if len(rc) >= 4:
                try:
                    poly = Polygon(rc)
                    if poly.is_valid:
                        course_bounds_geom = poly if course_bounds_geom is None else unary_union(
                            [course_bounds_geom, poly]
                        )
                except Exception:
                    pass
            continue

        if gtag not in (
            "hole",
            "tee",
            "fairway",
            "bunker",
            "green",
            "driving_range",
            "water_hazard",
            "lateral_water_hazard",
            "out_of_bounds",
        ):
            continue

        rc = ring_coords(wid)
        if len(rc) < 2:
            continue
        closed = rc[0] == rc[-1] and len(rc) > 3
        geom = _coords_to_geojson_geometry(rc, closed)
        props = dict(tags)
        props["golf"] = gtag
        props["_osm_way_id"] = int(w.get("id", 0))
        features.append({"type": "Feature", "geometry": geom, "properties": props})

    return features, course_bounds_geom


def _centroid(feat: dict[str, Any]) -> Point | None:
    try:
        g = shape(feat["geometry"])
        if g.is_empty:
            return None
        return g.representative_point()
    except Exception:
        return None


def _load_course_geojson(course_id: str) -> dict[str, Any]:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{course_id}.json"
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        meta = cached.get("meta") if isinstance(cached, dict) else None
        if isinstance(meta, dict) and int(meta.get("v", 0)) >= _CACHE_VERSION:
            return cached
        # Cache is from an older parser (no relations). Re-fetch.

    c = COURSES[course_id]
    lat = float(c["center_lat"])
    lon = float(c["center_lon"])
    raw = _fetch_overpass_json(course_id, lat, lon)
    feats, _course_geom = _elements_to_geojson_features(raw)

    bounds_poly = None
    if _course_geom is not None:
        try:
            bounds_poly = _course_geom if _course_geom.geom_type == "Polygon" else unary_union(
                _course_geom
            )
        except Exception:
            bounds_poly = None

    driving_polys: list[Any] = []
    filtered: list[dict[str, Any]] = []
    for feat in feats:
        tags = feat.get("properties") or {}
        if tags.get("golf") == "driving_range":
            try:
                g = shape(feat["geometry"])
                if g.geom_type == "Polygon":
                    driving_polys.append(g)
            except Exception:
                pass
            continue
        if bounds_poly is not None:
            ct = _centroid(feat)
            if ct is not None and not bounds_poly.contains(ct):
                continue
        filtered.append(feat)

    # Remove features on driving range
    if driving_polys:
        dr_union = unary_union(driving_polys)
        tmp: list[dict[str, Any]] = []
        for feat in filtered:
            ct = _centroid(feat)
            if ct is not None and dr_union.contains(ct):
                continue
            tmp.append(feat)
        filtered = tmp

    collection = {"type": "FeatureCollection", "features": filtered, "meta": {"v": _CACHE_VERSION}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(collection, f)
    return collection


def _hole_line_and_number(feat: dict[str, Any]) -> tuple[int, LineString] | None:
    props = feat.get("properties") or {}
    if props.get("golf") != "hole":
        return None
    ref = props.get("ref") or props.get("hole")
    hole_num: int | None = None
    if ref:
        try:
            hole_num = int(str(ref).split(";")[0].strip())
        except ValueError:
            hole_num = None
    try:
        g = shape(feat["geometry"])
        if g.geom_type != "LineString":
            return None
        ls = g
    except Exception:
        return None
    if hole_num is None:
        return None
    return hole_num, ls


def _nearest_hole_fallback(lat: float, lon: float, course_id: str) -> int | None:
    holes = COURSES[course_id]["holes"]
    best: tuple[float, int] | None = None
    for h in holes:
        mid_lat = (h["tee"]["lat"] + h["green_center"]["lat"]) / 2
        mid_lon = (h["tee"]["lon"] + h["green_center"]["lon"]) / 2
        d = _haversine_m(lat, lon, mid_lat, mid_lon)
        if best is None or d < best[0]:
            best = (d, int(h["number"]))
    return best[1] if best else None


def _group_features_by_hole(
    collection: dict[str, Any], course_id: str
) -> dict[int, list[dict[str, Any]]]:
    feats = collection.get("features") or []
    hole_lines: dict[int, tuple[dict[str, Any], LineString]] = {}
    non_hole: list[dict[str, Any]] = []

    for feat in feats:
        hn = _hole_line_and_number(feat)
        if hn:
            hole_num, ls = hn
            hole_lines[hole_num] = (feat, ls)
        else:
            non_hole.append(feat)

    grouped: dict[int, list[dict[str, Any]]] = {}
    for num, (feat, _) in hole_lines.items():
        grouped[num] = [feat]

    for feat in non_hole:
        ct = _centroid(feat)
        if ct is None:
            continue

        props = feat.get("properties") or {}
        gtag = props.get("golf")

        closest: int | None = None

        # Greens are the most commonly mis-assigned feature (adjacent holes often have
        # greens closer to tee boxes). Assign greens to the closest hole green_center.
        if gtag == "green":
            best: tuple[float, int] | None = None
            for h in COURSES[course_id]["holes"]:
                gc = h["green_center"]
                d = _haversine_m(ct.y, ct.x, float(gc["lat"]), float(gc["lon"]))
                if best is None or d < best[0]:
                    best = (d, int(h["number"]))
            closest = best[1] if best else None
        # Tee boxes: assign to closest hole tee point.
        elif gtag == "tee":
            best = None
            for h in COURSES[course_id]["holes"]:
                tee = h["tee"]
                d = _haversine_m(ct.y, ct.x, float(tee["lat"]), float(tee["lon"]))
                if best is None or d < best[0]:
                    best = (d, int(h["number"]))
            closest = best[1] if best else None
        else:
            # Other features (fairway/bunker/etc): nearest hole line within a loose cutoff.
            # Looser than ace's 100m to keep fairway polygons that don't hug the line.
            min_d = 250.0
            for hole_num, (_, ls) in hole_lines.items():
                try:
                    d = ls.distance(ct)
                except Exception:
                    d = float("inf")
                if d < min_d:
                    min_d = d
                    closest = hole_num
            if closest is None:
                closest = _nearest_hole_fallback(ct.y, ct.x, course_id)

        if closest is not None:
            grouped.setdefault(closest, []).append(feat)

    return grouped


def load_hole_feature_collection(course_id: str, hole_number: int) -> dict[str, Any]:
    """
    Return GeoJSON FeatureCollection for one hole (fairway/green/bunker/tee,
    water / lateral water / OOB outlines, + hole line).
    """
    collection = _load_course_geojson(course_id)
    grouped = _group_features_by_hole(collection, course_id)
    feats = grouped.get(int(hole_number), [])
    return {"type": "FeatureCollection", "features": feats}


def clear_cache(course_id: str | None = None) -> None:
    """Remove cached JSON for one course or entire .cache."""
    if not _CACHE_DIR.is_dir():
        return
    if course_id:
        p = _CACHE_DIR / f"{course_id}.json"
        if p.is_file():
            p.unlink()
    else:
        for p in _CACHE_DIR.glob("*.json"):
            p.unlink()
