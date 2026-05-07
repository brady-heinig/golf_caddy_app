"""
PGA Tour fairway approach benchmarks (GIR %, avg proximity) by distance,
handicap-adjusted and blendable with the player's logged shots.

Anchors follow published PGA Tour / strokes-gained style tables (e.g. fairway
proximity charts). Interpolation fills gaps; handicap scaling uses smooth
multipliers calibrated so mid-handicap expectations stay plausible vs scratch.
"""

from __future__ import annotations

from typing import Any

# (yards_to_pin, GIR %, avg proximity all shots in feet) — PGA Tour–level
_FAIRWAY_ANCHORS: list[tuple[int, float, float]] = [
    (25, 95.0, 8.0),
    (50, 88.5, 15.33),
    (75, 84.0, 18.5),
    (100, 81.0, 20.5),
    (125, 78.5, 22.5),
    (150, 76.1, 25.25),
    (175, 66.7, 31.92),
    (200, 54.0, 42.0),
    (225, 38.0, 58.0),
    (250, 20.2, 85.08),
]

_LIE_FAIRWAY = frozenset({"fairway", "light_rough", "tee", "fringe"})
_LIE_DEEP = frozenset({"deep_rough", "rough"})
_HIT_GREEN = frozenset({"green", "fringe"})


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


def pga_tour_fairway_baseline(distance_yards: int) -> tuple[float, float]:
    """Return (gir_pct 0-100, avg_proximity_ft) for PGA Tour from fairway."""
    d = max(25, min(250, distance_yards))
    xs = [a[0] for a in _FAIRWAY_ANCHORS]
    gir = [_a[1] for _a in _FAIRWAY_ANCHORS]
    px = [_a[2] for _a in _FAIRWAY_ANCHORS]
    return _interp(float(d), [float(x) for x in xs], gir), _interp(float(d), [float(x) for x in xs], px)


def handicap_adjust(
    tour_gir_pct: float,
    tour_prox_ft: float,
    handicap_index: float,
) -> tuple[float, float]:
    """
    Scale Tour numbers toward typical amateur performance by handicap index (0–36+).

    GIR: scale miss rate upward with handicap (longer clubs penalized slightly more).
    Proximity: multiplicative widening with handicap and distance baked into tour number.
    """
    h = max(0.0, min(54.0, float(handicap_index)))
    # Miss-rate inflation: scratch keeps Tour GIR; higher HCP loses greens progressively
    miss = max(0.001, (100.0 - tour_gir_pct) / 100.0)
    # Stronger effect when Tour already misses more (long irons)
    miss_boost = 1.0 + 0.045 * h + 0.00035 * h * h
    adj_miss = min(0.96, miss * miss_boost)
    gir_adj = max(3.0, 100.0 * (1.0 - adj_miss))

    # Proximity feet: wider dispersion for higher handicap
    prox_mult = 1.0 + 0.026 * h + 0.00025 * h * h
    prox_adj = tour_prox_ft * prox_mult
    return gir_adj, prox_adj


def lie_gir_factor(lie: str) -> float:
    """Scale fairway-based GIR % down for worse lies (approximate)."""
    low = lie.lower().replace(" ", "_")
    if low in ("fairway", "tee", "fringe"):
        return 1.0
    if low == "light_rough":
        return 0.90
    if low in _LIE_DEEP or ("rough" in low and low != "light_rough"):
        return 0.72
    if low == "bunker":
        return 0.55
    return 0.88


def lie_adjustment_factor(lie: str) -> tuple[float, str]:
    """
    Chart is fairway; nudge expectations for other lies (multiplier on proximity; GIR note).
    """
    low = lie.lower().replace(" ", "_")
    if low in _LIE_FAIRWAY or low == "tee":
        return 1.0, "fairway-level"
    if low in _LIE_DEEP or "rough" in low:
        return 1.22, "rough (expect ~20% wider proximity vs fairway)"
    if low == "bunker":
        return 1.45, "bunker (expect materially wider proximity)"
    return 1.08, "other lie"


def expected_gir_model_percent(
    distance_yards: int,
    handicap_index: float,
    lie: str,
) -> tuple[float, float]:
    """
    Estimated chance of hitting the green (in reg sense: ball on green surface)
    from this yardage for the given handicap and lie.

    Returns (percent 0–100, tour_baseline_gir_same_distance).
    """
    d = int(distance_yards)
    tour_gir, tour_px = pga_tour_fairway_baseline(d)
    g_adj, _ = handicap_adjust(tour_gir, tour_px, handicap_index)
    f = lie_gir_factor(lie)
    gir = max(2.0, min(98.5, g_adj * f))
    return gir, tour_gir


def expected_gir_display(
    distance_yards: int,
    handicap_index: float,
    lie: str,
    shots_similar: list[dict] | None,
) -> dict[str, Any]:
    """
    Model GIR % plus blend with logged shots (same rules as caddie prompt).
    Keys: model_pct, blended_pct, tour_pct, w_gir, n_gir_shots, lie_factor.
    """
    model_pct, tour_pct = expected_gir_model_percent(
        distance_yards, handicap_index, lie
    )
    shots_similar = shots_similar or []
    n_gir, u_rate = user_fairway_sample_stats(shots_similar)
    lie_factor = lie_gir_factor(lie)
    if u_rate is None or n_gir < 3:
        return {
            "model_pct": model_pct,
            "blended_pct": model_pct,
            "tour_pct": tour_pct,
            "w_gir": 0.0,
            "n_gir_shots": n_gir,
            "lie_factor": lie_factor,
        }
    w = min(0.85, n_gir / (n_gir + 12.0))
    blended = (1.0 - w) * model_pct + w * (100.0 * u_rate)
    blended = max(1.0, min(99.0, blended))
    return {
        "model_pct": model_pct,
        "blended_pct": blended,
        "tour_pct": tour_pct,
        "w_gir": w,
        "n_gir_shots": n_gir,
        "lie_factor": lie_factor,
    }


def _comparable_shots(shots: list[dict]) -> list[dict]:
    """Prefer fairway / light rough / tee for chart comparison."""
    fair: list[dict] = []
    for s in shots:
        lie = (s.get("lie") or "").lower().replace(" ", "_")
        if lie in ("fairway", "light_rough", "tee"):
            fair.append(s)
    return fair if len(fair) >= 3 else shots


def user_fairway_sample_stats(shots: list[dict]) -> tuple[int, float | None]:
    """Green or fringe rate from comparable logged shots (prefer fairway/tee tags)."""
    use = _comparable_shots(shots)
    if not use:
        return 0, None
    hits = sum(1 for s in use if (s.get("result") or "").lower().strip() in _HIT_GREEN)
    return len(use), hits / len(use)


def user_proximity_sample_stats(shots: list[dict]) -> tuple[int, float | None]:
    """Mean proximity (feet to hole) when logged; need ≥3 readings to blend."""
    use = _comparable_shots(shots)
    vals: list[float] = []
    for s in use:
        px = s.get("proximity_ft")
        if px is not None:
            try:
                vals.append(float(px))
            except (TypeError, ValueError):
                continue
    if len(vals) < 3:
        return len(vals), None
    return len(vals), sum(vals) / len(vals)


def blend_benchmark_with_user(
    bench_gir: float,
    bench_prox: float,
    user_gir_rate: float | None,
    n_gir: int,
    user_prox_ft: float | None,
    n_prox: int,
) -> tuple[float, float, float, float]:
    """
    Blend handicap benchmark with logged GIR rate and mean proximity (feet).
    Returns (g_final, prox_final, w_gir, w_prox).
    """
    w_gir = 0.0
    g_final = bench_gir
    if user_gir_rate is not None and n_gir >= 3:
        w_gir = min(0.85, n_gir / (n_gir + 12.0))
        g_final = (1.0 - w_gir) * bench_gir + w_gir * (100.0 * user_gir_rate)

    w_prox = 0.0
    px_final = bench_prox
    if user_prox_ft is not None and n_prox >= 3:
        w_prox = min(0.85, n_prox / (n_prox + 12.0))
        px_final = (1.0 - w_prox) * bench_prox + w_prox * user_prox_ft

    return g_final, px_final, w_gir, w_prox


def format_benchmark_for_prompt(
    distance_yards: int,
    lie: str,
    handicap_index: float,
    shots_similar: list[dict],
) -> str:
    """Compact block for Claude: Tour baseline, adjusted, optional user blend."""
    tour_gir, tour_px = pga_tour_fairway_baseline(distance_yards)
    g_adj, px_adj = handicap_adjust(tour_gir, tour_px, handicap_index)
    lie_m, lie_note = lie_adjustment_factor(lie)
    px_lie = px_adj * lie_m

    n_gir, u_rate = user_fairway_sample_stats(shots_similar)
    n_px, u_prox = user_proximity_sample_stats(shots_similar)
    g_final, px_final, w_gir, w_prox = blend_benchmark_with_user(
        g_adj, px_lie, u_rate, n_gir, u_prox, n_px
    )

    lines = [
        f"PGA Tour baseline (fairway, ~{distance_yards} yds): ~{tour_gir:.1f}% GIR, ~{_fmt_ft(tour_px)} avg proximity (all shots).",
        f"Handicap-adjusted fairway expectation (HCP {handicap_index:.0f}): ~{g_adj:.1f}% GIR, ~{_fmt_ft(px_adj)} avg proximity.",
        f"Current lie scaling for proximity ({lie_note}): ~{_fmt_ft(px_lie)} (×{lie_m:.2f}).",
        f"Blended expectation for advice: ~{g_final:.1f}% GIR, ~{_fmt_ft(px_final)} proximity.",
    ]
    if n_gir >= 3 and u_rate is not None:
        lines.append(
            f"Your GIR sample (±similar yds): {n_gir} shots, ~{100*u_rate:.0f}% green/fringe "
            f"(blend weight: {w_gir:.0%})."
        )
    elif n_gir > 0:
        lines.append(f"Logged shots at similar distance: {n_gir} (need ≥3 for GIR blend).")
    else:
        lines.append("No personal shots in this distance band yet — GIR from handicap model only.")

    if n_px >= 3 and u_prox is not None:
        lines.append(
            f"Your proximity sample: {n_px} logged distances, avg ~{u_prox:.1f} ft to hole "
            f"(blend weight: {w_prox:.0%})."
        )
    elif n_px > 0:
        lines.append(
            f"Proximity entries at this distance: {n_px} (need ≥3 with feet logged to blend proximity)."
        )
    else:
        lines.append("Log feet to hole on saved shots to personalize expected proximity.")
    return "\n".join(lines)


def _fmt_ft(ft: float) -> str:
    if ft < 0:
        return "?"
    whole = int(ft)
    inch = round((ft - whole) * 12)
    if inch >= 12:
        whole += 1
        inch = 0
    return f"{whole}'{inch:02d}\""


def sidebar_summary(
    distance_yards: int,
    handicap_index: float,
    shots_similar: list[dict] | None = None,
    lie: str = "fairway",
) -> dict[str, Any]:
    """Metrics for Streamlit sidebar; optional shots apply same blend as the caddie prompt."""
    tg, tp = pga_tour_fairway_baseline(distance_yards)
    ga, pa = handicap_adjust(tg, tp, handicap_index)
    lie_m, _ = lie_adjustment_factor(lie)
    px_lie_base = pa * lie_m
    out: dict[str, Any] = {
        "tour_gir": tg,
        "tour_prox_ft": tp,
        "adj_gir": ga,
        "adj_prox_ft": pa,
        "blend_gir": ga,
        "blend_prox_ft": px_lie_base,
        "w_gir": 0.0,
        "w_prox": 0.0,
    }
    if not shots_similar:
        return out
    px_lie = px_lie_base
    n_gir, u_rate = user_fairway_sample_stats(shots_similar)
    n_px, u_prox = user_proximity_sample_stats(shots_similar)
    g_b, px_b, w_g, w_p = blend_benchmark_with_user(
        ga, px_lie, u_rate, n_gir, u_prox, n_px
    )
    out["blend_gir"] = g_b
    out["blend_prox_ft"] = px_b
    out["w_gir"] = w_g
    out["w_prox"] = w_p
    out["n_prox_logged"] = n_px
    return out
