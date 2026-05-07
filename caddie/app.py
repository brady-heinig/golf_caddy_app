"""Streamlit entrypoint — AI Golf Caddie."""

from __future__ import annotations

import html
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import quote as url_quote

import streamlit as st
from dotenv import load_dotenv

import benchmark_stats
import caddie
import course_data
import course_features
import elevation
import hole_map
import shot_log
import weather

load_dotenv()

# Phone-like dashboard — target an iPhone-style viewport (~390px wide, no scroll).
PHONE_SHELL_MAX_W = 390
PHONE_HEADER_H_PX = 68
PHONE_FOOTER_H_PX = 72
PHONE_DASHBOARD_H_PX = 844
PHONE_MAP_HEIGHT_PX = PHONE_DASHBOARD_H_PX - PHONE_HEADER_H_PX - PHONE_FOOTER_H_PX

PHONE_MAIN_CSS = """
<style>
    /* Lock page to a phone-like viewport: no scroll */
    html, body {{
        height: min(100dvh, {dash_h}px);
        overflow: hidden !important;
        margin: 0 auto;
    }}
    div[data-testid="stAppViewContainer"] {{
        height: min(100dvh, {dash_h}px);
        overflow: hidden !important;
    }}
    div[data-testid="stAppViewContainer"] section.main {{
        height: min(100dvh, {dash_h}px);
        overflow: hidden !important;
    }}
    div[data-testid="stAppViewContainer"] section.main .block-container {{
        height: min(100dvh, {dash_h}px);
        overflow: hidden !important;
        width: min(100vw, {shell_w}px);
        max-width: min(100vw, {shell_w}px);
        margin-left: auto !important;
        margin-right: auto !important;
        padding-top: 0.25rem;
        padding-bottom: 0.25rem;
        padding-left: 0 !important;
        padding-right: 0 !important;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.5rem;
        container-type: size;
    }}

    /* Force element containers to the same phone width (prevents iframe narrowing). */
    div[data-testid="stElementContainer"] {{
        width: min(100vw, {shell_w}px) !important;
        max-width: min(100vw, {shell_w}px) !important;
        margin-left: auto !important;
        margin-right: auto !important;
        padding: 0 !important;
    }}
    /* Hide Streamlit default extra vertical spacing around blocks */
    div[data-testid="stVerticalBlock"] {{ gap: 0.5rem; }}
    /* Remove default bottom margin that can cause scroll */
    div[data-testid="stVerticalBlock"] > div {{ margin-bottom: 0 !important; }}

    .phone-bar {{
        width: min(100vw, {shell_w}px);
        max-width: min(100vw, {shell_w}px);
        background: #ffffff;
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 14px;
        box-shadow: 0 10px 28px rgba(0,0,0,0.18);
        padding: 10px 12px;
        box-sizing: border-box;
        color: #0b1220;
        font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    }}
    .phone-header {{
        height: {header_h}px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
    }}
    .metric-left {{ display: flex; flex-direction: column; gap: 2px; }}
    .metric-label {{ font-size: 0.70rem; opacity: 0.68; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }}
    .metric-value {{ font-size: 1.20rem; font-weight: 800; line-height: 1.0; }}
    .metric-sub {{ font-size: 0.80rem; opacity: 0.80; font-weight: 700; }}

    .phone-footer {{
        height: {footer_h}px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
    }}

    /* Style the REAL Streamlit rows that follow our markers */
    .phone-header-marker + div[data-testid="stHorizontalBlock"] {{
        width: min(100vw, {shell_w}px) !important;
        max-width: min(100vw, {shell_w}px) !important;
        background: #ffffff;
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 14px;
        box-shadow: 0 10px 28px rgba(0,0,0,0.18);
        padding: 10px 12px;
        box-sizing: border-box;
    }}
    .phone-footer-marker + div[data-testid="stHorizontalBlock"] {{
        width: min(100vw, {shell_w}px) !important;
        max-width: min(100vw, {shell_w}px) !important;
        background: #ffffff;
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 14px;
        box-shadow: 0 10px 28px rgba(0,0,0,0.18);
        padding: 10px 12px;
        box-sizing: border-box;
    }}

    /* Make footer buttons look like footer controls */
    .phone-footer-marker + div[data-testid="stHorizontalBlock"] button {{
        height: 44px !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
        white-space: nowrap !important;
    }}

    /* HTML map iframe (fixed width) stays centered */
    /* Streamlit component iframe wrapper */
    div[data-testid="stIFrame"], div[data-testid="stIframe"] {{
        width: min(100vw, {shell_w}px) !important;
        max-width: min(100vw, {shell_w}px) !important;
        padding: 0 !important;
        margin: 0 !important;
    }}
    div[data-testid="stIFrame"] iframe, div[data-testid="stIframe"] iframe {{
        width: 100% !important;
        max-width: 100% !important;
    }}
    /* Fallback: target the component iframe directly */
    iframe[title^="streamlit.components"] {{
        width: min(100vw, {shell_w}px) !important;
        max-width: min(100vw, {shell_w}px) !important;
    }}
    section.main iframe {{
        display: block !important;
        margin-left: auto !important;
        margin-right: auto !important;
        float: none !important;
        border-radius: 14px;
        box-shadow: 0 16px 40px rgba(0,0,0,0.22);
        border: 0 !important;
        overflow: hidden;
    }}
</style>
""".format(
    header_h=PHONE_HEADER_H_PX,
    footer_h=PHONE_FOOTER_H_PX,
    shell_w=PHONE_SHELL_MAX_W,
    dash_h=PHONE_DASHBOARD_H_PX,
)

st.set_page_config(
    page_title="AI Caddie",
    page_icon="⛳",
    layout="centered",
    initial_sidebar_state="collapsed",
)

if "conn" not in st.session_state:
    st.session_state.conn = shot_log.init_db()

if "current_hole" not in st.session_state:
    st.session_state.current_hole = 1

if "current_course" not in st.session_state:
    st.session_state.current_course = "stevens_golf_course"

if "handicap_index" not in st.session_state:
    st.session_state.handicap_index = 15.0

if "weather" not in st.session_state:
    st.session_state.weather = None

if "advice" not in st.session_state:
    st.session_state.advice = None

if "player_lat" not in st.session_state:
    st.session_state.player_lat = None

if "player_lon" not in st.session_state:
    st.session_state.player_lon = None

if "caddie_error" not in st.session_state:
    st.session_state.caddie_error = None

if "round_started" not in st.session_state:
    st.session_state.round_started = False


def inject_gps_component() -> None:
    gps_html = """
    <script>
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(function(pos) {
            const lat = pos.coords.latitude.toFixed(6);
            const lon = pos.coords.longitude.toFixed(6);
            const url = new URL(window.parent.location.href);
            if (url.searchParams.get('lat') !== lat) {
                url.searchParams.set('lat', lat);
                url.searchParams.set('lon', lon);
                window.parent.history.replaceState(null, '', url.toString());
                window.parent.location.reload();
            }
        }, function(err) { console.warn('GPS error:', err.message); });
    }
    </script>
    """
    # Streamlit iframe height must be positive; keep it visually hidden.
    st.iframe("data:text/html;charset=utf-8," + url_quote(gps_html), height=1)


inject_gps_component()
params = st.query_params
if "lat" in params and "lon" in params:
    try:
        st.session_state.player_lat = float(params["lat"])
        st.session_state.player_lon = float(params["lon"])
    except (TypeError, ValueError):
        pass


def _lie_for_model(lie_label: str) -> str:
    return lie_label.lower().replace(" ", "_")


def _result_for_db(result_label: str) -> str:
    return result_label.split("(")[0].strip().lower()


def _weather_hud_line(w: dict | None) -> str | None:
    if not w or w.get("error"):
        return None
    return (
        f"{w['temp_f']:.0f}°F · {w['wind_mph']:.0f} mph {w['wind_dir_card']}"
        f" · {w.get('condition', '')}"
    )


def _render_welcome() -> None:
    st.markdown(PHONE_MAIN_CSS, unsafe_allow_html=True)
    st.title("AI Golf Caddie")
    st.caption("Choose your course and handicap, then play with the map-first yardage view.")

    with st.form("welcome_form"):
        labels = {
            k: course_data.COURSES[k]["name"] for k in course_data.COURSES
        }
        pick = st.selectbox(
            "Course",
            options=list(labels.keys()),
            format_func=lambda k: labels[k],
            index=list(labels.keys()).index(st.session_state.current_course)
            if st.session_state.current_course in labels
            else 0,
        )
        hcp_w = st.number_input(
            "Handicap index",
            min_value=0.0,
            max_value=54.0,
            value=float(st.session_state.get("handicap_index", 15.0)),
            step=0.5,
            help="World Handicap System index — drives benchmarks and GIR estimates.",
        )
        start = st.form_submit_button(
            "Start round",
            type="primary",
            use_container_width=True,
        )

    if start:
        st.session_state.current_course = pick
        st.session_state.handicap_index = hcp_w
        st.session_state.current_hole = 1
        st.session_state.round_started = True
        st.session_state.weather = None
        st.session_state.advice = None
        st.session_state.caddie_error = None
        st.rerun()


if not st.session_state.round_started:
    _render_welcome()
    st.stop()

st.markdown(PHONE_MAIN_CSS, unsafe_allow_html=True)

current_course = st.session_state.current_course
course = course_data.COURSES[current_course]

current_hole = int(st.session_state.current_hole)
hole_data = course["holes"][current_hole - 1]

if st.session_state.weather is None:
    st.session_state.weather = weather.get_weather(
        course["center_lat"],
        course["center_lon"],
    )

w = st.session_state.weather
weather_line = _weather_hud_line(w)

# Sidebar controls (keeps the main dashboard non-scrollable)
with st.sidebar:
    st.subheader("Round")
    st.select_slider(
        "Hole",
        options=list(range(1, 19)),
        key="current_hole",
    )
    st.number_input(
        "Handicap index",
        min_value=0.0,
        max_value=54.0,
        step=0.5,
        key="handicap_index",
    )
    st.selectbox(
        "Lie",
        ["Tee", "Fairway", "Light rough", "Deep rough", "Bunker", "Fringe"],
        key="ui_lie",
        index=1,
    )
    st.selectbox(
        "Shot shape",
        ["Straight", "Draw", "Fade"],
        key="ui_shape",
        index=0,
    )
    st.slider(
        "Distance override (yds)",
        10,
        300,
        int(st.session_state.get("dist_slider", 150)),
        step=5,
        key="dist_slider",
        help="Used when GPS isn't available; GPS auto-overrides when present.",
    )

    if st.button("End round", use_container_width=True):
        st.session_state.round_started = False
        st.session_state.advice = None
        st.rerun()

# Header metrics (distance + GIR)
lie_label = str(st.session_state.get("ui_lie", "Fairway"))
shape_label = str(st.session_state.get("ui_shape", "Straight"))
lie_m = _lie_for_model(lie_label)
shape_m = shape_label.lower()

distance_for_ui = int(st.session_state.get("dist_slider", 150))
gps_dist = None
if st.session_state.player_lat is not None and st.session_state.player_lon is not None:
    gps_dist = caddie.haversine_yards(
        st.session_state.player_lat,
        st.session_state.player_lon,
        hole_data["green_center"]["lat"],
        hole_data["green_center"]["lon"],
    )
    distance_for_ui = int(gps_dist)

el_pin_m = elevation.get_elevation_m(
    hole_data["green_center"]["lat"],
    hole_data["green_center"]["lon"],
)
if st.session_state.player_lat is not None and st.session_state.player_lon is not None:
    el_player_m = elevation.get_elevation_m(
        float(st.session_state.player_lat),
        float(st.session_state.player_lon),
    )
    el_change_ft = elevation.elevation_change_ft(el_pin_m, el_player_m)
else:
    el_tee_m = elevation.get_elevation_m(
        hole_data["tee"]["lat"],
        hole_data["tee"]["lon"],
    )
    el_change_ft = elevation.elevation_change_ft(el_pin_m, el_tee_m)

plays_like_yds = int(
    round(elevation.plays_like_yards(float(distance_for_ui), el_change_ft))
)

_cache_course = Path(__file__).resolve().parent / ".cache" / f"{current_course}.json"
hole_fc: dict = {"type": "FeatureCollection", "features": []}
try:
    if not _cache_course.is_file():
        with st.spinner("Fetching course data from OpenStreetMap…"):
            hole_fc = course_features.load_hole_feature_collection(
                current_course, int(current_hole)
            )
    else:
        hole_fc = course_features.load_hole_feature_collection(
            current_course, int(current_hole)
        )
except Exception:
    # Overpass is best-effort; keep the round playable even if the API rejects us.
    st.warning("Course feature borders unavailable (Overpass error). Retrying later.")
    hole_fc = {"type": "FeatureCollection", "features": []}

_similar_shots = shot_log.get_shots_at_distance(
    st.session_state.conn, distance_for_ui, tolerance=15, limit=50
)
hcp = float(st.session_state.get("handicap_index", 15.0))
gir_disp = benchmark_stats.expected_gir_display(distance_for_ui, hcp, lie_m, _similar_shots)

st.markdown('<div class="phone-header-marker"></div>', unsafe_allow_html=True)
hc1, hc2 = st.columns([1.2, 1.0], vertical_alignment="center")
with hc1:
    st.markdown(
        f"""
<div class="metric-left">
  <div class="metric-label">Distance to hole</div>
  <div class="metric-value">{distance_for_ui} yd</div>
  <div class="metric-sub">Plays ~{plays_like_yds} yd ({el_change_ft / 3.0:+.1f} yd elev)</div>
</div>
""",
        unsafe_allow_html=True,
    )
with hc2:
    st.markdown(
        f"""
<div class="metric-left" style="text-align:right;">
  <div class="metric-label">Hit green</div>
  <div class="metric-value">{gir_disp['blended_pct']:.0f}%</div>
  <div class="metric-sub">HCP {hcp:.1f} · {lie_label}</div>
</div>
""",
        unsafe_allow_html=True,
    )

# Map overlay caption for the in-map HUD
hud_parts: list[str] = []
if weather_line:
    hud_parts.append(weather_line)
if gps_dist is not None:
    hud_parts.append(f"GPS ~{gps_dist:.0f} yd to pin")
hud_caption = " · ".join(hud_parts) if hud_parts else None

_gkey = os.environ.get("GOOGLE_MAPS_API_KEY")
_map_html, _map_provider = hole_map.build_embed_html(
    hole_data,
    st.session_state.player_lat,
    st.session_state.player_lon,
    _gkey,
    course_name=course["name"],
    weather_caption=hud_caption,
    weather_data=w if isinstance(w, dict) else None,
    hole_features=hole_fc,
    embed_height_px=PHONE_MAP_HEIGHT_PX,
    embed_width_px=None,
)
_map_src = "data:text/html;charset=utf-8," + url_quote(_map_html)
st.iframe(
    _map_src,
    width=PHONE_SHELL_MAX_W,
    height=PHONE_MAP_HEIGHT_PX,
)

# Footer interactions: scorecard + talk with caddie
if "scores_by_hole" not in st.session_state:
    st.session_state.scores_by_hole = {i: None for i in range(1, 19)}
if "scorecard_hole" not in st.session_state:
    st.session_state.scorecard_hole = 1

pars_by_hole = {h["number"]: int(h["par"]) for h in course["holes"]}
total_par = sum(pars_by_hole.values())
entered_scores = {
    int(k): v
    for k, v in (st.session_state.scores_by_hole or {}).items()
    if v is not None
}
total_strokes = sum(int(v) for v in entered_scores.values())
par_for_entered = sum(pars_by_hole.get(int(h), 0) for h in entered_scores.keys())
to_par = total_strokes - par_for_entered
score_str = "E" if to_par == 0 else (f"+{to_par}" if to_par > 0 else str(to_par))

def _footer_prev_hole() -> None:
    st.session_state.current_hole = max(1, int(st.session_state.current_hole) - 1)


def _footer_next_hole() -> None:
    st.session_state.current_hole = min(18, int(st.session_state.current_hole) + 1)


st.markdown('<div class="phone-footer-marker"></div>', unsafe_allow_html=True)
f_score, f_prev, f_hole, f_next, f_caddie = st.columns(
    [1.1, 0.55, 0.9, 0.55, 1.5], vertical_alignment="center"
)
with f_score:
    open_score = st.button(score_str, key="open_scorecard", use_container_width=True)
with f_prev:
    st.button(
        "◀",
        key="footer_prev_hole",
        use_container_width=True,
        on_click=_footer_prev_hole,
    )
with f_hole:
    _ = st.button(f"Hole {int(current_hole)}", key="footer_hole", use_container_width=True)
with f_next:
    st.button(
        "▶",
        key="footer_next_hole",
        use_container_width=True,
        on_click=_footer_next_hole,
    )
with f_caddie:
    open_caddie = st.button(
        "Talk with caddie",
        key="open_caddie",
        type="primary",
        use_container_width=True,
    )

if open_score:
    st.session_state._show_scorecard = True
    st.rerun()
if open_caddie:
    st.session_state._show_caddie = True
    st.rerun()

if st.session_state.get("_show_scorecard"):
    st.session_state._show_scorecard = False
    with st.dialog("Scorecard"):
        st.caption("Tap a hole square to edit. Default is par; swipe/scroll the slider to change strokes.")
        holes = list(range(1, 19))
        rows = [holes[i : i + 6] for i in range(0, 18, 6)]
        for r in rows:
            cols = st.columns(len(r))
            for h, col in zip(r, cols):
                cur = st.session_state.scores_by_hole.get(h)
                label = str(cur) if cur is not None else "—"
                with col:
                    if st.button(f"{h}\n{label}", key=f"hole_btn_{h}", use_container_width=True):
                        st.session_state.scorecard_hole = h
                        st.rerun()

        edit_hole = int(st.session_state.scorecard_hole)
        par_h = pars_by_hole.get(edit_hole, 4)
        default_score = (
            int(st.session_state.scores_by_hole.get(edit_hole))
            if st.session_state.scores_by_hole.get(edit_hole) is not None
            else int(par_h)
        )
        st.divider()
        st.subheader(f"Hole {edit_hole} (Par {par_h})")
        new_score = st.select_slider(
            "Strokes",
            options=list(range(1, 11)),
            value=default_score,
        )
        csa, csb = st.columns([1, 1])
        with csa:
            if st.button("Save", type="primary", use_container_width=True):
                st.session_state.scores_by_hole[edit_hole] = int(new_score)
                st.rerun()
        with csb:
            if st.button("Clear hole", use_container_width=True):
                st.session_state.scores_by_hole[edit_hole] = None
                st.rerun()

if st.session_state.get("_show_caddie"):
    st.session_state._show_caddie = False
    with st.dialog("AI Caddie"):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.error("API key not set. Add ANTHROPIC_API_KEY to .env")
            st.stop()

        st.caption(
            f"Hole {int(current_hole)} · {distance_for_ui} yd "
            f"(plays ~{plays_like_yds}) · {lie_label} · {shape_label}"
        )
        if st.button("Get advice", type="primary", use_container_width=True):
            with st.spinner("Thinking..."):
                try:
                    history_str = shot_log.format_history_for_prompt(_similar_shots)
                    bench_block = benchmark_stats.format_benchmark_for_prompt(
                        distance_for_ui,
                        lie_m,
                        hcp,
                        _similar_shots,
                    )
                    w_use = st.session_state.weather
                    if w_use and w_use.get("error"):
                        w_use = None
                    advice = caddie.get_caddie_advice(
                        distance_to_pin=distance_for_ui,
                        lie=lie_m,
                        shot_shape=shape_m,
                        weather=w_use,
                        hole_data=hole_data,
                        shot_history=history_str,
                        player_lat=st.session_state.player_lat,
                        player_lon=st.session_state.player_lon,
                        benchmark_block=bench_block,
                        plays_like_yds=plays_like_yds,
                        el_change_ft=el_change_ft,
                    )
                    st.session_state._last_advice = advice
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    st.session_state._last_advice = None
                    st.error("Caddie unavailable — try again")

        advice_out = st.session_state.get("_last_advice")
        if advice_out:
            lines = str(advice_out).split("\n")
            for line in lines[:8]:
                if line.startswith("CLUB:") or line.startswith("AIM:"):
                    label, _, value = line.partition(":")
                    st.markdown(f"**{label.strip()}:** {value.strip()}")
            st.divider()
            st.write("\n".join(lines))

# Main dashboard is intentionally locked to phone-size (no further content).
st.stop()

distance = st.slider(
    "Distance to pin (yds)",
    10,
    300,
    150,
    step=5,
    key="dist_slider",
)

col1, col2 = st.columns(2)
with col1:
    lie = st.selectbox(
        "Lie",
        ["Tee", "Fairway", "Light rough", "Deep rough", "Bunker", "Fringe"],
    )
with col2:
    shape = st.selectbox("Shot shape", ["Straight", "Draw", "Fade"])

gps_dist = None
gps_dist_front = None
gps_dist_back = None
if st.session_state.player_lat is not None and st.session_state.player_lon is not None:
    h = hole_data
    gps_dist = caddie.haversine_yards(
        st.session_state.player_lat,
        st.session_state.player_lon,
        h["green_center"]["lat"],
        h["green_center"]["lon"],
    )
    gps_dist_front = caddie.haversine_yards(
        st.session_state.player_lat,
        st.session_state.player_lon,
        h["green_front"]["lat"],
        h["green_front"]["lon"],
    )
    gps_dist_back = caddie.haversine_yards(
        st.session_state.player_lat,
        st.session_state.player_lon,
        h["green_back"]["lat"],
        h["green_back"]["lon"],
    )
    st.caption(
        f"📍 GPS distance to green center: **{gps_dist:.0f} yds** "
        f"(front: {gps_dist_front:.0f} | back: {gps_dist_back:.0f})"
    )
    distance = int(gps_dist)

lie_m = _lie_for_model(lie)
shape_m = shape.lower()

_similar_shots = shot_log.get_shots_at_distance(
    st.session_state.conn, distance, tolerance=15, limit=50
)

with st.expander("Handicap & green probability", expanded=False):
    hcp_col1, hcp_col2 = st.columns([1, 2])
    with hcp_col1:
        st.number_input(
            "Your handicap index",
            min_value=0.0,
            max_value=54.0,
            value=float(st.session_state.get("handicap_index", 15.0)),
            step=0.5,
            key="handicap_index",
            help="WHS-style handicap index. Drives benchmarks and GIR estimate below.",
        )

    hcp = float(st.session_state.handicap_index)
    gir_disp = benchmark_stats.expected_gir_display(distance, hcp, lie_m, _similar_shots)
    with hcp_col2:
        st.metric(
            "Chance to hit the green",
            f"{gir_disp['blended_pct']:.0f}%",
            help="Estimated from PGA Tour fairway table, adjusted for your handicap and lie, "
            "then blended with your logged results when you have enough similar shots.",
        )
    st.caption(
        f"Handicap + lie model: **~{gir_disp['model_pct']:.0f}%** · "
        f"PGA Tour (fairway) at ~{distance} yd: **~{gir_disp['tour_pct']:.0f}%** · "
        f"Lie factor ×{gir_disp['lie_factor']:.2f}. "
        + (
            f"Includes your last **{gir_disp['n_gir_shots']}** comparable shots "
            f"(**{gir_disp['w_gir']:.0%}** toward your actual rate)."
            if gir_disp["w_gir"] > 0
            else "Log **≥3** fairway/tee approaches at similar yardage to blend in your real GIR rate."
        )
    )

w = st.session_state.weather
if w and w.get("error"):
    st.caption("Weather unavailable — check connection")
elif w and not w.get("error"):
    wcol1, wcol2, wcol3, wcol4 = st.columns(4)
    wcol1.metric("Temp", f"{w['temp_f']:.0f}°F")
    wcol2.metric("Wind", f"{w['wind_mph']:.0f} mph")
    wcol3.metric("Direction", w["wind_dir_card"])
    wcol4.metric("Humidity", f"{w['humidity_pct']}%")
    fa = w.get("fetched_at") or ""
    st.caption(f"Conditions: {w['condition']} — fetched {fa[:16]}")

if st.button("Refresh weather"):
    st.session_state.weather = weather.get_weather(
        course["center_lat"],
        course["center_lon"],
    )
    st.rerun()

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.error("API key not set. Add ANTHROPIC_API_KEY to .env")

if st.session_state.caddie_error:
    st.error(st.session_state.caddie_error)
    if st.button("Retry caddie"):
        st.session_state.caddie_error = None
        st.rerun()

if st.button("⛳ Ask the caddie", type="primary", use_container_width=True):
    st.session_state.caddie_error = None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.session_state.caddie_error = "API key not set. Add ANTHROPIC_API_KEY to .env"
    else:
        with st.spinner("Thinking..."):
            try:
                shots = _similar_shots
                hcp = float(st.session_state.handicap_index)
                history_str = shot_log.format_history_for_prompt(shots)
                bench_block = benchmark_stats.format_benchmark_for_prompt(
                    distance,
                    lie_m,
                    hcp,
                    shots,
                )
                w_use = st.session_state.weather
                if w_use and w_use.get("error"):
                    w_use = None
                st.session_state.advice = caddie.get_caddie_advice(
                    distance_to_pin=distance,
                    lie=lie_m,
                    shot_shape=shape_m,
                    weather=w_use,
                    hole_data=hole_data,
                    shot_history=history_str,
                    player_lat=st.session_state.player_lat,
                    player_lon=st.session_state.player_lon,
                    benchmark_block=bench_block,
                )
            except Exception:
                st.session_state.caddie_error = "Caddie unavailable — try again"
                traceback.print_exc(file=sys.stderr)
                st.session_state.advice = None

if st.session_state.advice:
    lines = st.session_state.advice.split("\n")
    for line in lines[:6]:
        if line.startswith("CLUB:") or line.startswith("AIM:"):
            label, _, value = line.partition(":")
            st.markdown(f"**{label.strip()}:** {value.strip()}")
    st.divider()
    rationale_start = next(
        (i + 1 for i, ln in enumerate(lines) if ln.strip() == "---"),
        2,
    )
    st.write("\n".join(lines[rationale_start:]))

    with st.expander("Log this shot result"):
        result = st.selectbox(
            "Result",
            [
                "Green (hit)",
                "Fringe",
                "Fairway",
                "Rough",
                "Bunker",
                "Water",
                "OB",
                "Short",
            ],
            key="log_result",
        )
        club_used = st.text_input("Club used (override if different)", key="log_club")
        dist_achieved = st.number_input(
            "Distance achieved (yds, optional)", 0, 400, 0, key="log_dist"
        )
        proximity_ft = st.number_input(
            "Proximity to hole (feet, optional)",
            0,
            300,
            0,
            step=1,
            key="log_prox",
            help="After the ball stops: pace or estimate feet to the cup. "
            "Logging this (≥3 shots at similar yardages) personalizes expected proximity.",
        )
        notes_input = st.text_input("Notes (optional)", key="log_notes")

        if st.button("Save shot"):
            try:
                hcp = float(st.session_state.handicap_index)
                shot_log.log_shot(
                    conn=st.session_state.conn,
                    course_id=current_course,
                    hole=int(current_hole),
                    shot_number=1,
                    club=club_used or "Unknown",
                    distance_to_pin_before=distance,
                    lie=lie_m,
                    shot_shape=shape_m,
                    result=_result_for_db(result),
                    distance_achieved=dist_achieved if dist_achieved > 0 else None,
                    notes=notes_input or None,
                    proximity_ft=int(proximity_ft) if proximity_ft > 0 else None,
                )
                st.success("Shot logged!")
                st.session_state.advice = None
                st.rerun()
            except Exception:
                traceback.print_exc(file=sys.stderr)
                st.warning("Shot not saved")

with st.sidebar:
    if st.button("End round", use_container_width=True):
        st.session_state.round_started = False
        st.session_state.advice = None
        st.rerun()

    st.header("My stats")

    hcp = float(st.session_state.get("handicap_index", 15.0))
    st.caption(f"Handicap: **{hcp:.1f}** (adjust in expander above)")

    bm = benchmark_stats.sidebar_summary(distance, hcp, _similar_shots, lie=lie_m)
    st.caption(
        f"Benchmark @ **{distance} yds** (HCP {hcp:.1f}, current lie): "
        f"~{bm['blend_gir']:.0f}% GIR · ~{bm['blend_prox_ft']:.0f} ft proximity "
        f"(Tour ~{bm['tour_gir']:.0f}% / ~{bm['tour_prox_ft']:.0f} ft)"
    )
    if bm["w_gir"] > 0 or bm["w_prox"] > 0:
        st.caption(
            f"Blended with your logs: GIR weight {bm['w_gir']:.0%}, "
            f"proximity weight {bm['w_prox']:.0%}."
        )
    st.caption(
        "Tour table + handicap model; log **feet to hole** on saves to personalize proximity."
    )

    st.subheader(f"Hole {int(current_hole)} history")
    hole_shots = shot_log.get_shots_for_hole(
        st.session_state.conn, current_course, int(current_hole)
    )
    if hole_shots:
        for s in hole_shots[:5]:
            px = s.get("proximity_ft")
            px_bit = f" | {px} ft" if px is not None else ""
            st.caption(
                f"{s['club']} | {s['distance_to_pin_before']} yds | {s.get('result')}{px_bit}"
            )
    else:
        st.caption("No history yet for this hole.")

    st.divider()

    st.subheader("Club lookup")
    club_input = st.text_input("Club name", placeholder="e.g. 7-iron")
    if club_input:
        stats = shot_log.get_club_stats(st.session_state.conn, club_input)
        if stats["shot_count"] > 0:
            st.metric("Avg distance", f"{stats['average_distance']:.0f} yds")
            st.metric("Shots tracked", stats["shot_count"])
        else:
            st.caption("No shots logged with this club yet.")
