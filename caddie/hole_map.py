"""Hole map embed: Apple MapKit JS, Google Maps, or Leaflet + OSM (fallback)."""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from urllib.parse import quote

# Apple MapKit JS: https://developer.apple.com/documentation/mapkitjs
# Requires Apple Developer Program, Maps identifier, and a .p8 private key.


def tee_to_green_bearing_deg(
    tee: dict[str, float],
    green: dict[str, float],
) -> float:
    """Initial bearing from tee to green, degrees clockwise from north (0–360)."""
    φ1 = math.radians(tee["lat"])
    φ2 = math.radians(green["lat"])
    Δλ = math.radians(green["lon"] - tee["lon"])
    y = math.sin(Δλ) * math.cos(φ2)
    x = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(Δλ)
    θ = math.degrees(math.atan2(y, x))
    return (θ + 360) % 360


def _base_styles(embed_height_px: int, embed_width_px: int | None) -> str:
    """Pixel height + optional width so the map fills Streamlit's iframe."""
    h = max(200, int(embed_height_px))
    if embed_width_px is None or embed_width_px <= 0:
        wrules = "width: 100%;\n  min-width: 100%;\n  max-width: 100%;"
        frame_w = "width: 100%;\n  min-width: 100%;\n  max-width: 100%;"
    else:
        w = max(240, int(embed_width_px))
        wrules = f"width: {w}px;\n  min-width: {w}px;\n  max-width: {w}px;"
        frame_w = f"width: {w}px;\n  min-width: {w}px;\n  max-width: {w}px;"
    return f"""
html, body {{
  height: {h}px;
  min-height: {h}px;
  max-height: {h}px;
  {wrules}
  margin: 0;
  padding: 0;
  overflow: hidden;
  background: transparent;
}}
#frame {{
  position: relative;
  {frame_w}
  height: {h}px;
  min-height: {h}px;
  box-sizing: border-box;
  overflow: hidden;
}}
#map {{
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  z-index: 1;
  background: transparent;
}}
.hud-top{{
  position:absolute;top:0;left:0;right:0;z-index:600;
  padding:12px 14px 28px;
  background:linear-gradient(180deg,rgba(13,17,23,0.85) 0%,rgba(13,17,23,0) 100%);
  color:#f6f8fa;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  pointer-events:none;
}}
.hud-title{{margin:0;font-size:1.05rem;font-weight:600;letter-spacing:0.02em;line-height:1.2;}}
.hud-sub{{margin-top:6px;font-size:0.82rem;opacity:0.92;font-weight:400;line-height:1.35;}}
.hud-sub.hud-tight{{margin-top:3px;}}
.hud-bottom{{
  position:absolute;bottom:0;left:0;right:0;z-index:600;
  padding:20px 14px 12px;
  background:linear-gradient(0deg,rgba(13,17,23,0.78) 0%,rgba(13,17,23,0) 100%);
  color:rgba(246,248,250,0.88);font-size:0.72rem;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  pointer-events:none;text-align:center;letter-spacing:0.04em;text-transform:uppercase;
}}
.meas-marker-icon{{
  background:rgba(200,80,50,0.95);border:2px solid #fff;border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:700;color:#fff;width:26px;height:26px;
  box-shadow:0 2px 6px rgba(0,0,0,0.4);
}}
.meas-marker-icon span{{line-height:1;}}
.leaflet-popup-content-wrapper{{border-radius:10px;font-size:0.85rem;}}
.wind-widget{{
  position:absolute;top:10px;right:10px;z-index:650;
  display:flex;align-items:center;gap:10px;
  padding:10px 10px;border-radius:12px;
  background:rgba(255,255,255,0.90);backdrop-filter:blur(8px);
  border:1px solid rgba(0,0,0,0.08);
  box-shadow:0 6px 18px rgba(0,0,0,0.22);
  pointer-events:none;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
}}
.wind-arrow{{
  width:30px;height:30px;position:relative;flex:0 0 auto;
}}
.wind-arrow:before{{
  content:"";position:absolute;left:50%;top:50%;
  width:0;height:0;
  border-left:10px solid transparent;
  border-right:10px solid transparent;
  border-bottom:18px solid #111827;
  transform:translate(-50%,-60%) rotate(var(--wind-rot, 0deg));
  transform-origin:50% 60%;
}}
.wind-text{{
  display:flex;flex-direction:column;gap:2px;
  color:#111827;
}}
.wind-line1{{font-size:0.80rem;font-weight:700;line-height:1.0;}}
.wind-line2{{font-size:0.72rem;font-weight:600;opacity:0.85;line-height:1.0;}}
"""


def _hud_shell() -> str:
    return """<div id="frame">
  <div class="hud-top">
    <div class="hud-title" id="hud-title"></div>
    <div class="hud-sub" id="hud-sub1"></div>
    <div class="hud-sub hud-tight" id="hud-sub2"></div>
  </div>
  <div class="wind-widget" id="wind-widget" style="display:none;">
    <div class="wind-arrow" id="wind-arrow"></div>
    <div class="wind-text">
      <div class="wind-line1" id="wind-line1"></div>
      <div class="wind-line2" id="wind-line2"></div>
    </div>
  </div>
  <div id="map"></div>
  <div class="hud-bottom">Pan & zoom · Tee bottom / green top</div>
</div>"""


def _fill_hud_script() -> str:
    return """
function __fillHud(DATA){
  var H = (DATA && DATA.hud) ? DATA.hud : {};
  var title = document.getElementById("hud-title");
  var s1 = document.getElementById("hud-sub1");
  var s2 = document.getElementById("hud-sub2");
  if (title) title.textContent = (H.course || "") + " · Hole " + (H.hole != null ? H.hole : "");
  if (s1) s1.textContent = "Par " + (H.par != null ? H.par : "") + " · "
    + (H.yards != null ? H.yards : "") + " yds"
    + (H.hdcp != null ? " · Hcp " + H.hdcp : "");
  if (s2) {
    s2.textContent = H.weather || "";
    s2.style.display = H.weather ? "block" : "none";
  }
}

function __windToScreenDeg(windFromDeg, mapBearingDeg){
  // wind_direction is "from" (meteorological). Arrow should point "to".
  var toDeg = ((windFromDeg || 0) + 180) % 360;
  var bearing = (mapBearingDeg || 0) % 360;
  return ((toDeg - bearing) + 360) % 360;
}

function __fillWind(DATA){
  try {
    var ww = document.getElementById("wind-widget");
    if (!ww) return;
    var w = DATA && DATA.wind ? DATA.wind : null;
    var wx = DATA && DATA.wx ? DATA.wx : null;
    if (!w || w.dir_deg_from == null || w.mph == null || !wx) return;
    var rot = __windToScreenDeg(Number(w.dir_deg_from), Number(DATA.bearing_deg || 0));
    var arrow = document.getElementById("wind-arrow");
    if (arrow) arrow.style.setProperty("--wind-rot", rot + "deg");
    var l1 = document.getElementById("wind-line1");
    var l2 = document.getElementById("wind-line2");
    if (l1) l1.textContent = Math.round(Number(w.mph)) + " mph wind";
    var tf = wx.temp_f;
    var hu = wx.humidity_pct;
    if (l2) l2.textContent = (tf != null ? Math.round(Number(tf)) + "°F" : "") + (hu != null ? " · " + Number(hu) + "% RH" : "");
    ww.style.display = "flex";
  } catch (e) {}
}
"""


def _payload(
    hole_data: dict[str, Any],
    player_lat: float | None,
    player_lon: float | None,
    course_name: str,
    weather_caption: str | None,
    weather_data: dict[str, Any] | None,
    hole_features: dict[str, Any] | None,
) -> dict[str, Any]:
    hz = hole_data.get("hazards") or []
    hazards_out = [
        {"lat": h["lat"], "lon": h["lon"], "note": (h.get("note") or "")[:80]}
        for h in hz[:25]
    ]
    bearing = tee_to_green_bearing_deg(
        hole_data["tee"],
        hole_data["green_center"],
    )
    out: dict[str, Any] = {
        "hole": hole_data["number"],
        "tee": {"lat": hole_data["tee"]["lat"], "lon": hole_data["tee"]["lon"]},
        "green": {
            "lat": hole_data["green_center"]["lat"],
            "lon": hole_data["green_center"]["lon"],
        },
        "front": {
            "lat": hole_data["green_front"]["lat"],
            "lon": hole_data["green_front"]["lon"],
        },
        "back": {
            "lat": hole_data["green_back"]["lat"],
            "lon": hole_data["green_back"]["lon"],
        },
        "hazards": hazards_out,
        "bearing_deg": round(bearing, 2),
        "hud": {
            "course": course_name,
            "hole": hole_data["number"],
            "par": hole_data["par"],
            "yards": hole_data["yards"],
            "hdcp": hole_data["handicap"],
            "weather": (weather_caption or "").strip() or None,
        },
    }
    if weather_data and not weather_data.get("error"):
        out["wind"] = {
            "mph": weather_data.get("wind_mph"),
            "dir_deg_from": weather_data.get("wind_dir_deg"),
        }
        out["wx"] = {
            "temp_f": weather_data.get("temp_f"),
            "humidity_pct": weather_data.get("humidity_pct"),
        }
    if player_lat is not None and player_lon is not None:
        out["player"] = {"lat": player_lat, "lon": player_lon}
    out["holeFeatures"] = hole_features or {"type": "FeatureCollection", "features": []}
    return out


def _try_mapkit_jwt() -> str | None:
    """
    Build short-lived JWT for MapKit JS (ES256).
    Env:
      APPLE_MAPKIT_TEAM_ID  — 10-char Team ID
      APPLE_MAPKIT_KEY_ID   — Key ID from the .p8 download
      APPLE_MAPKIT_PRIVATE_KEY_PATH — path to AuthKey_XXX.p8
      APPLE_MAPKIT_ORIGIN   — optional; domain or origin per Apple docs (omit for localhost)
    """
    team = os.environ.get("APPLE_MAPKIT_TEAM_ID", "").strip()
    kid = os.environ.get("APPLE_MAPKIT_KEY_ID", "").strip()
    key_path = os.environ.get("APPLE_MAPKIT_PRIVATE_KEY_PATH", "").strip()
    origin = os.environ.get("APPLE_MAPKIT_ORIGIN", "").strip()
    if not team or not kid or not key_path:
        return None
    try:
        with open(key_path, encoding="utf-8") as f:
            pem = f.read()
    except OSError:
        return None
    try:
        import jwt
    except ImportError:
        return None
    now = int(time.time())
    exp = now + 30 * 60
    payload: dict[str, Any] = {"iss": team, "iat": now, "exp": exp}
    if origin:
        payload["origin"] = origin
    headers = {"alg": "ES256", "kid": kid, "typ": "JWT"}
    try:
        tok = jwt.encode(payload, pem, algorithm="ES256", headers=headers)
        return tok.decode("utf-8") if isinstance(tok, bytes) else str(tok)
    except Exception:
        return None


def build_embed_html(
    hole_data: dict[str, Any],
    player_lat: float | None,
    player_lon: float | None,
    google_api_key: str | None,
    *,
    course_name: str,
    weather_caption: str | None = None,
    weather_data: dict[str, Any] | None = None,
    hole_features: dict[str, Any] | None = None,
    embed_height_px: int = 620,
    embed_width_px: int | None = None,
) -> tuple[str, str]:
    """
    Returns (html, provider) where provider is mapkit | google | osm.

    Default is **OpenStreetMap** (Leaflet). Use env ``MAP_PROVIDER`` to pick
    another backend: ``google``, ``mapkit``, or ``osm`` (explicit default).
    Google needs ``GOOGLE_MAPS_API_KEY``; MapKit needs Apple JWT env vars.

    ``embed_height_px`` should match the Streamlit ``components.html(..., height=…)``
    value so the map div gets a real size inside the iframe.
    """
    data = _payload(
        hole_data,
        player_lat,
        player_lon,
        course_name,
        weather_caption,
        weather_data,
        hole_features,
    )
    data_js = json.dumps(data, separators=(",", ":"))
    h = embed_height_px
    w = embed_width_px
    w_mapkit = w if w is not None and w > 0 else 500

    prov = os.environ.get("MAP_PROVIDER", "").strip().lower()

    if prov == "google":
        if google_api_key and google_api_key.strip():
            return _google_maps_html(data_js, google_api_key.strip(), h, w_mapkit), "google"
        return _leaflet_html(data_js, h, w), "osm"

    if prov == "mapkit":
        mk = _try_mapkit_jwt()
        if mk:
            return _mapkit_js_html(data_js, mk, h, w_mapkit), "mapkit"
        return _leaflet_html(data_js, h, w), "osm"

    # Default and explicit OSM: Leaflet + OpenStreetMap tiles
    if prov in ("osm", "openstreetmap", "leaflet", ""):
        return _leaflet_html(data_js, h, w), "osm"

    return _leaflet_html(data_js, h, w), "osm"


def _mapkit_js_html(data_js: str, jwt_token: str, embed_height_px: int, embed_width_px: int) -> str:
    jwt_js = json.dumps(jwt_token)
    hud = _hud_shell()
    fs = _fill_hud_script()
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover"/>
<style>{_base_styles(embed_height_px, embed_width_px)}</style>
<script src="https://cdn.apple-mapkit.com/mkjs/mapkit/v3/mapkit.js"></script>
</head><body>
{hud}
<script>
const DATA = {data_js};
{fs}
__fillHud(DATA);
const MAPKIT_JWT = {jwt_js};
mapkit.init({{
  authorizationCallback: function(done) {{ done(MAPKIT_JWT); }},
}});
const map = new mapkit.Map("map");
map.mapType = mapkit.Map.MapTypes.Hybrid;
const annotations = [];
annotations.push(new mapkit.MarkerAnnotation(
  new mapkit.Coordinate(DATA.tee.lat, DATA.tee.lon),
  {{ title: "Tee", glyphText: "T", color: "#58A6FF" }}
));
annotations.push(new mapkit.MarkerAnnotation(
  new mapkit.Coordinate(DATA.green.lat, DATA.green.lon),
  {{ title: "Green", glyphText: "G", color: "#3FB950" }}
));
annotations.push(new mapkit.MarkerAnnotation(
  new mapkit.Coordinate(DATA.front.lat, DATA.front.lon),
  {{ title: "Green front", glyphText: "F", color: "#8B949E" }}
));
annotations.push(new mapkit.MarkerAnnotation(
  new mapkit.Coordinate(DATA.back.lat, DATA.back.lon),
  {{ title: "Green back", glyphText: "B", color: "#8B949E" }}
));
(DATA.hazards || []).forEach(function(h) {{
  annotations.push(new mapkit.MarkerAnnotation(
    new mapkit.Coordinate(h.lat, h.lon),
    {{ title: h.note || "Hazard", color: "#D29922" }}
  ));
}});
if (DATA.player) {{
  annotations.push(new mapkit.MarkerAnnotation(
    new mapkit.Coordinate(DATA.player.lat, DATA.player.lon),
    {{ title: "You (GPS)", glyphText: "You", color: "#58A6FF" }}
  ));
}}
const line = new mapkit.PolylineOverlay([
  new mapkit.Coordinate(DATA.tee.lat, DATA.tee.lon),
  new mapkit.Coordinate(DATA.green.lat, DATA.green.lon),
], {{ style: new mapkit.Style({{ strokeColor: "#F0F6FC", lineWidth: 3 }}) }});
map.addOverlay(line);
annotations.forEach(function(a) {{ map.addAnnotation(a); }});
map.showItems(annotations, {{ animate: false }});
if (typeof DATA.bearing_deg === "number" && !isNaN(DATA.bearing_deg)) {{
  try {{
    if (typeof map.setRotationAnimated === "function") {{
      map.setRotationAnimated(DATA.bearing_deg, false);
    }} else {{
      map.rotation = DATA.bearing_deg * Math.PI / 180;
    }}
  }} catch (e) {{}}
}}
</script>
</body></html>"""


def _google_maps_html(data_js: str, api_key: str, embed_height_px: int, embed_width_px: int) -> str:
    hud = _hud_shell()
    fs = _fill_hud_script()
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover"/>
<style>{_base_styles(embed_height_px, embed_width_px)}</style>
</head><body>
{hud}
<script>
const DATA = {data_js};
{fs}
__fillHud(DATA);
function initMap() {{
  const map = new google.maps.Map(document.getElementById("map"), {{
    mapTypeId: "hybrid",
    gestureHandling: "greedy",
    rotateControl: false,
    tilt: 0,
  }});
  const bounds = new google.maps.LatLngBounds();
  const tee = new google.maps.Marker({{
    position: {{ lat: DATA.tee.lat, lng: DATA.tee.lon }},
    map,
    label: "T",
    title: "Tee",
  }});
  bounds.extend(tee.getPosition());
  const green = new google.maps.Marker({{
    position: {{ lat: DATA.green.lat, lng: DATA.green.lon }},
    map,
    label: "G",
    title: "Green (center)",
    icon: "http://maps.google.com/mapfiles/ms/icons/green-dot.png",
  }});
  bounds.extend(green.getPosition());
  new google.maps.Marker({{
    position: {{ lat: DATA.front.lat, lng: DATA.front.lon }},
    map,
    label: "F",
    title: "Green front",
    opacity: 0.85,
  }});
  bounds.extend(new google.maps.LatLng(DATA.front.lat, DATA.front.lon));
  new google.maps.Marker({{
    position: {{ lat: DATA.back.lat, lng: DATA.back.lon }},
    map,
    label: "B",
    title: "Green back",
    opacity: 0.85,
  }});
  bounds.extend(new google.maps.LatLng(DATA.back.lat, DATA.back.lon));
  new google.maps.Polyline({{
    path: [
      {{ lat: DATA.tee.lat, lng: DATA.tee.lon }},
      {{ lat: DATA.green.lat, lng: DATA.green.lon }},
    ],
    strokeColor: "#f0f6fc",
    strokeOpacity: 0.95,
    strokeWeight: 3,
    map,
  }});
  (DATA.hazards || []).forEach(function(h) {{
    new google.maps.Marker({{
      position: {{ lat: h.lat, lng: h.lon }},
      map,
      title: h.note || "Hazard",
      icon: "http://maps.google.com/mapfiles/ms/icons/yellow-dot.png",
    }});
  }});
  if (DATA.player) {{
    new google.maps.Marker({{
      position: {{ lat: DATA.player.lat, lng: DATA.player.lon }},
      map,
      title: "You (GPS)",
      icon: "http://maps.google.com/mapfiles/ms/icons/blue-dot.png",
    }});
  }}
  /* Same framing as Leaflet: tee→green only (hazards/player omitted from fit) */
  map.fitBounds(bounds, {{ padding: 10 }});
  google.maps.event.addListenerOnce(map, "bounds_changed", function() {{
    if (map.getZoom() > 19) map.setZoom(19);
  }});
  if (typeof DATA.bearing_deg === "number" && !isNaN(DATA.bearing_deg)) {{
    map.setHeading(DATA.bearing_deg);
  }}
}}
</script>
<script async defer
  src="https://maps.googleapis.com/maps/api/js?key={quote(api_key, safe='')}&callback=initMap"></script>
</body></html>"""


def _leaflet_html(data_js: str, embed_height_px: int, embed_width_px: int | None) -> str:
    hud = _hud_shell()
    fs = _fill_hud_script()
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/leaflet-rotate@0.2.0/dist/leaflet-rotate.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@turf/turf@6.5.0/turf.min.js"></script>
<style>{_base_styles(embed_height_px, embed_width_px)}</style>
</head><body>
{hud}
<script>
(function() {{
const DATA = {data_js};
{fs}
__fillHud(DATA);
var mapEl = document.getElementById("map");
var GOLF_LINE = {{
  // More contrast between green + fairway
  green: "#2ee6a8",
  bunker: "#cbc103",
  fairway: "#0b6b2a",
  tee: "#777777",
  hole: "#f0f6fc",
  driving_range: "#666666",
  water_hazard: "#2096f3",
  lateral_water_hazard: "#ff5252",
  out_of_bounds: "#fafafa"
}};
function buildFeatureCollection() {{
  var hf = DATA.holeFeatures;
  if (hf && hf.features && hf.features.length) {{
    return hf;
  }}
  return turf.featureCollection([
    turf.lineString([
      [DATA.tee.lon, DATA.tee.lat],
      [DATA.green.lon, DATA.green.lat]
    ], {{ golf: "hole" }})
  ]);
}}
function holeAxisBearing(fc) {{
  var hl = (fc.features || []).filter(function(f) {{
    return f.properties && f.properties.golf === "hole" &&
      f.geometry && f.geometry.type === "LineString";
  }})[0];
  var a, b;
  if (hl) {{
    var cc = hl.geometry.coordinates;
    a = turf.point(cc[0]);
    b = turf.point(cc[cc.length - 1]);
  }} else {{
    a = turf.point([DATA.tee.lon, DATA.tee.lat]);
    b = turf.point([DATA.green.lon, DATA.green.lat]);
  }}
  return turf.bearing(a, b);
}}
function styleGolfFeature(f) {{
  var g = (f.properties && f.properties.golf) || "";
  var col = GOLF_LINE[g] || "#cccccc";
  // Hide the static OSM hole centerline; only keep our dynamic dashed line.
  if (g === "hole") {{
    return {{ color: col, weight: 0, opacity: 0.0, fillOpacity: 0, fill: false }};
  }}
  // Thinner strokes overall; still slightly emphasize fairway + green + hazards.
  var w = (g === "fairway" || g === "green") ? 2.25
    : (g === "water_hazard" || g === "lateral_water_hazard" || g === "out_of_bounds") ? 2.1
    : 1.75;
  var op = (g === "out_of_bounds") ? 0.88 : 0.92;
  return {{ color: col, weight: w, opacity: op, fillOpacity: 0, fill: false }};
}}
var fc = buildFeatureCollection();
var holeBearing = holeAxisBearing(fc);
var map = L.map(mapEl, {{
  preferCanvas: true,
  zoomControl: true,
  rotate: true,
  bearing: 0,
  rotateControl: false,
  touchRotate: false,
  shiftKeyRotate: false,
  zoomSnap: 0.25,
  zoomDelta: 0.25,
  maxZoom: 19
}}).setView([DATA.tee.lat, DATA.tee.lon], 16);
var baseLayer = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
  {{ maxZoom: 19, attribution: "Imagery &copy; Esri" }}
).addTo(map);
L.geoJSON(fc, {{
  style: styleGolfFeature
}}).addTo(map);
L.marker([DATA.tee.lat, DATA.tee.lon]).addTo(map).bindPopup("Tee");
L.marker([DATA.green.lat, DATA.green.lon]).addTo(map).bindPopup("Green center");
(DATA.hazards || []).forEach(function(h) {{
  L.circleMarker([h.lat, h.lon], {{ radius: 6, color: "#d29922", fillOpacity: 0.75 }})
    .addTo(map).bindPopup(h.note || "Hazard");
}});
if (DATA.player) {{
  L.marker([DATA.player.lat, DATA.player.lon]).addTo(map).bindPopup("Your location (GPS)");
}}

// Dynamic bend marker along the hole line, with distances on each side.
// Marker can be dragged; labels update live for:
//  - start side: from tee (or player, if present) to marker
//  - end side: from marker to green center
function initHoleBendMarker() {{
  var holeFeat = (fc.features || []).find(function(f) {{
    return f.properties && f.properties.golf === "hole" &&
      f.geometry && (f.geometry.type === "LineString" || f.geometry.type === "MultiLineString");
  }});
  if (!holeFeat) return;

  // Build LatLngs from the hole geometry.
  var holeCoords = [];
  if (holeFeat.geometry.type === "LineString") {{
    holeCoords = holeFeat.geometry.coordinates;
  }} else if (holeFeat.geometry.type === "MultiLineString" &&
             holeFeat.geometry.coordinates.length > 0) {{
    holeCoords = holeFeat.geometry.coordinates[0];
  }}
  if (!holeCoords || holeCoords.length < 2) return;

  var startLL = L.latLng(DATA.tee.lat, DATA.tee.lon);
  if (DATA.player) {{
    startLL = L.latLng(DATA.player.lat, DATA.player.lon);
  }}
  var greenLL = L.latLng(DATA.green.lat, DATA.green.lon);

  var idxMid = Math.floor(holeCoords.length / 2);
  var midCoord = holeCoords[idxMid];
  var bendLL = L.latLng(midCoord[1], midCoord[0]);

  var bendMarker = L.marker(bendLL, {{ draggable: true }}).addTo(map);

  // Dynamic polyline that moves with the bend marker: start -> marker -> green.
  var holeDynLine = L.polyline(
    [startLL, bendLL, greenLL],
    {{
      color: "#f0f6fc",
      weight: 2.0,
      opacity: 0.9,
      dashArray: "4 4",
      lineCap: "round",
    }}
  ).addTo(map);

  function makeDistIcon(text) {{
    return L.divIcon({{
      className: "hole-dist-label",
      html: "<div style='padding:2px 6px;border-radius:10px;background:rgba(13,17,23,0.85);"
          + "color:#f6f8fa;font-size:11px;font-weight:600;white-space:nowrap;'>"
          + text + "</div>",
      iconSize: null
    }});
  }}

  var seg1Label = L.marker(bendLL, {{ interactive: false, icon: makeDistIcon("") }}).addTo(map);
  var seg2Label = L.marker(bendLL, {{ interactive: false, icon: makeDistIcon("") }}).addTo(map);

  function updateDistances() {{
    var m = bendMarker.getLatLng();
    if (!m) return;
    // Prefer player as start if present (player on the hole).
    var start = startLL;
    if (DATA.player) {{
      var playerLL = L.latLng(DATA.player.lat, DATA.player.lon);
      start = playerLL;
    }}
    var d1 = haversineYards(start.lat, start.lng, m.lat, m.lng);
    var d2 = haversineYards(m.lat, m.lng, greenLL.lat, greenLL.lng);

    // Update dynamic polyline geometry to follow the marker and (if applicable) the player.
    holeDynLine.setLatLngs([start, m, greenLL]);

    var mid1 = L.latLng((start.lat + m.lat) / 2, (start.lng + m.lng) / 2);
    var mid2 = L.latLng((m.lat + greenLL.lat) / 2, (m.lng + greenLL.lng) / 2);

    seg1Label.setLatLng(mid1);
    seg1Label.setIcon(makeDistIcon(Math.round(d1) + " yd"));
    seg2Label.setLatLng(mid2);
    seg2Label.setIcon(makeDistIcon(Math.round(d2) + " yd"));
  }}

  bendMarker.on("drag", updateDistances);
  bendMarker.on("dragend", updateDistances);
  updateDistances();
}}

initHoleBendMarker();

function fitHoleAceStyle() {{
  try {{
    var center = turf.center(fc);
    var pivot = center.geometry.coordinates;
    var rotated = turf.transformRotate(fc, -holeBearing, {{ pivot: pivot }});
    var bb = turf.bbox(rotated);
    var southWest = L.latLng(bb[1], bb[0]);
    var northEast = L.latLng(bb[3], bb[2]);
    var bounds = L.latLngBounds(southWest, northEast);
    var z = map.getBoundsZoom(bounds, false);
    z = Math.max(map.getMinZoom(), Math.min(19, z - 0.3));
    var ctr = center.geometry.coordinates;
    map.setView(L.latLng(ctr[1], ctr[0]), z);
    // Ensure green is visually above tee. Bearing sign differs across rotate plugins,
    // so we set a candidate bearing then verify on-screen.
    function applyBearingEnsureGreenTop(bearingDeg) {{
      if (typeof map.setBearing !== "function") return bearingDeg;
      map.setBearing(bearingDeg);
      // After applying bearing, confirm green is above tee in container space.
      var teePt = map.latLngToContainerPoint(L.latLng(DATA.tee.lat, DATA.tee.lon));
      var greenPt = map.latLngToContainerPoint(L.latLng(DATA.green.lat, DATA.green.lon));
      if (greenPt && teePt && greenPt.y > teePt.y) {{
        var flipped = (bearingDeg + 180) % 360;
        map.setBearing(flipped);
        return flipped;
      }}
      return bearingDeg;
    }}

    function recenterAndZoomTeeGreen(finalBearing) {{
      // Goal:
      // 1) Keep tee->green line perfectly vertical and centered on screen.
      // 2) Zoom so tee is pad px from bottom and green is pad px from top.
      var sz0 = map.getSize();
      if (!sz0) return;
      var pad = Math.max(8, sz0.y * 0.10); // equal distance from top and bottom

      var teePt = map.latLngToContainerPoint(L.latLng(DATA.tee.lat, DATA.tee.lon));
      var greenPt = map.latLngToContainerPoint(L.latLng(DATA.green.lat, DATA.green.lon));
      if (!teePt || !greenPt) return;

      // Re-enforce green on top.
      var bearing = finalBearing;
      if (greenPt.y > teePt.y && typeof map.setBearing === "function") {{
        bearing = (bearing + 180) % 360;
        map.setBearing(bearing);
        teePt = map.latLngToContainerPoint(L.latLng(DATA.tee.lat, DATA.tee.lon));
        greenPt = map.latLngToContainerPoint(L.latLng(DATA.green.lat, DATA.green.lon));
      }}

      var sepY = teePt.y - greenPt.y; // positive when green above tee
      if (!(sepY > 10)) {{
        __fillWind(Object.assign({{}}, DATA, {{ bearing_deg: bearing }}));
        return;
      }}

      var targetSepY = sz0.y - pad - pad;
      var scale = targetSepY / sepY;
      if (!(scale > 0)) scale = 1;
      var dz = Math.log(scale) / Math.LN2; // log2(scale)
      var z = map.getZoom() + dz;
      z = Math.max(map.getMinZoom(), Math.min(19, z));

      // Use geographic midpoint; then pan to exact screen margins.
      var mid = L.latLng(
        (DATA.tee.lat + DATA.green.lat) / 2,
        (DATA.tee.lon + DATA.green.lon) / 2
      );
      map.setView(mid, z);
      if (typeof map.setBearing === "function") map.setBearing(bearing);

      requestAnimationFrame(function() {{
        var sz1 = map.getSize();
        var teePt1 = map.latLngToContainerPoint(L.latLng(DATA.tee.lat, DATA.tee.lon));
        if (!sz1 || !teePt1) {{
          __fillWind(Object.assign({{}}, DATA, {{ bearing_deg: bearing }}));
          return;
        }}
        var dx = (sz1.x / 2) - teePt1.x;
        var dy = (sz1.y - pad) - teePt1.y; // tee pad-from-bottom
        map.panBy(L.point(dx, dy), {{ animate: false }});

        requestAnimationFrame(function() {{
          __fillWind(Object.assign({{}}, DATA, {{ bearing_deg: bearing }}));
        }});
      }});
    }}
    function snapTeeGreenToVerticalAsync(startBearingDeg) {{
      // Iteratively adjust bearing until tee->green is vertical (dx ~= 0).
      // We measure after requestAnimationFrame so container points reflect the new rotation.
      if (typeof map.setBearing !== "function") {{
        __fillWind(Object.assign({{}}, DATA, {{ bearing_deg: startBearingDeg }}));
        return;
      }}
      var bearing = startBearingDeg;
      var tries = 0;
      function step() {{
        tries += 1;
        map.setBearing(bearing);
        requestAnimationFrame(function() {{
          var teePt = map.latLngToContainerPoint(L.latLng(DATA.tee.lat, DATA.tee.lon));
          var greenPt = map.latLngToContainerPoint(L.latLng(DATA.green.lat, DATA.green.lon));
          if (!teePt || !greenPt) {{
            __fillWind(Object.assign({{}}, DATA, {{ bearing_deg: bearing }}));
            return;
          }}
          var dx = greenPt.x - teePt.x;
          var dy = greenPt.y - teePt.y;
          // Keep green above tee.
          if (greenPt.y > teePt.y) {{
            bearing = (bearing + 180) % 360;
            map.setBearing(bearing);
            requestAnimationFrame(step);
            return;
          }}
          // If already vertical enough, stop.
          if (Math.abs(dx) <= 0.5 || tries >= 6) {{
            recenterAndZoomTeeGreen(bearing);
            return;
          }}
          // Angle off vertical (degrees). Positive if green is to the right of tee.
          var theta = Math.atan2(dx, -dy) * 180 / Math.PI;
          if (!isFinite(theta)) {{
            __fillWind(Object.assign({{}}, DATA, {{ bearing_deg: bearing }}));
            return;
          }}
          // Apply correction (subtract to reduce dx).
          bearing = (bearing - theta + 360) % 360;
          step();
        }});
      }}
      step();
    }}
    var effectiveBearing = applyBearingEnsureGreenTop(holeBearing);
    snapTeeGreenToVerticalAsync(effectiveBearing);
  }} catch (e) {{
    var holeBounds = L.latLngBounds(
      [DATA.tee.lat, DATA.tee.lon],
      [DATA.green.lat, DATA.green.lon]
    );
    holeBounds.extend([DATA.front.lat, DATA.front.lon]);
    holeBounds.extend([DATA.back.lat, DATA.back.lon]);
    holeBounds = holeBounds.pad(0.06);
    map.fitBounds(holeBounds, {{ maxZoom: 19, animate: false }});
    var fb = (typeof DATA.bearing_deg === "number") ? Number(DATA.bearing_deg) : 0;
    var fallbackBearing = (fb + 180) % 360;
    if (typeof map.setBearing === "function") map.setBearing(fallbackBearing);
    // Verify/flip if needed even in fallback path.
    if (typeof map.setBearing === "function") {{
      var teePt2 = map.latLngToContainerPoint(L.latLng(DATA.tee.lat, DATA.tee.lon));
      var greenPt2 = map.latLngToContainerPoint(L.latLng(DATA.green.lat, DATA.green.lon));
      if (greenPt2 && teePt2 && greenPt2.y > teePt2.y) {{
        fallbackBearing = (fallbackBearing + 180) % 360;
        map.setBearing(fallbackBearing);
      }}
    }}
    __fillWind(Object.assign({{}}, DATA, {{ bearing_deg: fallbackBearing }}));
    // Best-effort: still recenter/zoom for consistent top/bottom spacing.
    try {{ recenterAndZoomTeeGreen(fallbackBearing); }} catch (e2) {{}}
  }}
}}

map.whenReady(function() {{
  try {{ map.invalidateSize({{ animate: false }}); }} catch (e0) {{}}
  fitHoleAceStyle();
  try {{ map.invalidateSize({{ animate: false }}); }} catch (e1) {{}}
  fitHoleAceStyle();
}});

var elevCache = new Map();
function getElevation(lon, lat) {{
  return new Promise(function(resolve) {{
    var k = lon.toFixed(5) + "," + lat.toFixed(5);
    if (elevCache.has(k)) {{
      resolve(elevCache.get(k));
      return;
    }}
    var url = "https://api.open-meteo.com/v1/elevation?latitude=" + encodeURIComponent(Number(lat).toFixed(5))
      + "&longitude=" + encodeURIComponent(Number(lon).toFixed(5));
    fetch(url).then(function(r) {{ return r.json(); }}).then(function(j) {{
      var z = (j.elevation && j.elevation.length) ? parseFloat(j.elevation[0]) : 0;
      if (isNaN(z)) z = 0;
      elevCache.set(k, z);
      resolve(z);
    }}).catch(function() {{ resolve(0); }});
  }});
}}

function haversineYards(lat1, lon1, lat2, lon2) {{
  var R = 6371008.8;
  var r1 = lat1 * Math.PI / 180, r2 = lat2 * Math.PI / 180;
  var dLat = (lat2 - lat1) * Math.PI / 180, dLon = (lon2 - lon1) * Math.PI / 180;
  var a = Math.sin(dLat/2) * Math.sin(dLat/2) + Math.cos(r1) * Math.cos(r2) * Math.sin(dLon/2) * Math.sin(dLon/2);
  var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return (R * c) * 1.0936133;
}}

var measMarkers = [];
var measureLine = L.polyline([], {{
  color: "#ffa657", weight: 4, opacity: 0.95, dashArray: "8 10", lineCap: "round",
}}).addTo(map);
function measIcon(i) {{
  return L.divIcon({{
    className: "meas-marker-icon",
    html: "<span>" + (i + 1) + "</span>",
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  }});
}}

function refreshMeasNumbers() {{
  measMarkers.forEach(function(m, idx) {{
    m.setIcon(measIcon(idx));
  }});
}}

function removeMeasMarker(marker) {{
  var ix = measMarkers.indexOf(marker);
  if (ix < 0) return;
  map.removeLayer(marker);
  measMarkers.splice(ix, 1);
  refreshMeasNumbers();
  measureLine.setLatLngs(measMarkers.map(function(m) {{ return m.getLatLng(); }}));
}}

function formatMeasLegHtml(yd, elYd, plays) {{
  var ey = Math.round(elYd * 10) / 10;
  var es = (ey >= 0 ? "+" : "") + ey;
  return "<div style='font-size:12px;line-height:1.35;margin-bottom:6px'>" +
    "<div>" + Math.round(yd) + " yd</div>" +
    "<div>" + es + " yd elev</div>" +
    "<div>" + Math.round(plays) + " yd plays</div></div>";
}}

function addMeasurePoint(latlng) {{
  var idx = measMarkers.length;
  var m = L.marker(latlng, {{ draggable: true, icon: measIcon(idx) }});
  m.addTo(map);
  m.on("dragend", function() {{
    measureLine.setLatLngs(measMarkers.map(function(x) {{ return x.getLatLng(); }}));
  }});
  m.on("click", function(ev) {{
    L.DomEvent.stopPropagation(ev);
    var ix = measMarkers.indexOf(m);
    var inner = "<div style='min-width:150px'><div style='font-size:12px'>…</div>";
    if (ix > 0) {{
      inner = "<div style='min-width:150px'><div style='font-size:12px'>Loading…</div>";
    }}
    inner += "<div style='font-size:11px;opacity:0.85;margin-bottom:6px'>Drag pin to move.</div>" +
      "<button type='button' class='meas-rmb' style='padding:6px 10px;border-radius:6px;border:none;" +
      "background:#da3633;color:#fff;cursor:pointer;font-weight:600;'>Remove pin</button></div>";
    m.bindPopup(inner).openPopup();
    if (ix > 0) {{
      var a = measMarkers[ix-1].getLatLng(), b = m.getLatLng();
      var yd = haversineYards(a.lat, a.lng, b.lat, b.lng);
      Promise.all([getElevation(a.lng, a.lat), getElevation(b.lng, b.lat)]).then(function(vals) {{
        var e1 = vals[0], e2 = vals[1];
        var elFt = (e2 - e1) * 3.28084;
        var elYd = elFt / 3;
        var plays = yd + elFt / 3;
        var html = "<div style='min-width:150px'>" + formatMeasLegHtml(yd, elYd, plays) +
          "<div style='font-size:11px;opacity:0.85;margin-bottom:6px'>Drag pin to move.</div>" +
          "<button type='button' class='meas-rmb' style='padding:6px 10px;border-radius:6px;border:none;" +
          "background:#da3633;color:#fff;cursor:pointer;font-weight:600;'>Remove pin</button></div>";
        m.setPopupContent(html);
      }});
    }}
  }});
  m.on("popupopen", function() {{
    var el = m.getPopup().getElement();
    var b = el && el.querySelector(".meas-rmb");
    if (b) b.onclick = function() {{ removeMeasMarker(m); map.closePopup(); }};
  }});
  measMarkers.push(m);
  measureLine.setLatLngs(measMarkers.map(function(x) {{ return x.getLatLng(); }}));
}}

map.on("click", function(e) {{
  addMeasurePoint(e.latlng);
}});

map.whenReady(function() {{
  try {{ baseLayer.bringToBack(); }} catch (x) {{}}
  try {{ measureLine.bringToFront(); }} catch (x) {{}}
}});

function fixSize() {{
  try {{ map.invalidateSize({{ animate: false }}); }} catch (e) {{}}
}}
map.whenReady(function() {{
  fixSize();
  requestAnimationFrame(fixSize);
  setTimeout(fixSize, 50);
  setTimeout(fixSize, 300);
}});
if (typeof ResizeObserver !== "undefined" && mapEl) {{
  var ro = new ResizeObserver(function() {{ fixSize(); }});
  ro.observe(mapEl);
}}
}})();
</script>
</body></html>"""
