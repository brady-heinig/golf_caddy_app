from __future__ import annotations

# Minimal benchmark implementation used by backend chat/context.


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

_LIE_DEEP = frozenset({"deep_rough", "rough"})


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
    d = max(25, min(250, distance_yards))
    xs = [a[0] for a in _FAIRWAY_ANCHORS]
    gir = [a[1] for a in _FAIRWAY_ANCHORS]
    prox = [a[2] for a in _FAIRWAY_ANCHORS]
    return _interp(float(d), [float(x) for x in xs], gir), _interp(float(d), [float(x) for x in xs], prox)


def handicap_adjust(tour_gir_pct: float, tour_prox_ft: float, handicap_index: float) -> tuple[float, float]:
    h = max(0.0, min(54.0, float(handicap_index)))
    miss = max(0.001, (100.0 - tour_gir_pct) / 100.0)
    miss_boost = 1.0 + 0.045 * h + 0.00035 * h * h
    adj_miss = min(0.96, miss * miss_boost)
    gir_adj = max(3.0, 100.0 * (1.0 - adj_miss))

    prox_mult = 1.0 + 0.026 * h + 0.00025 * h * h
    prox_adj = tour_prox_ft * prox_mult
    return gir_adj, prox_adj


def lie_gir_factor(lie: str) -> float:
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


def expected_gir_model_percent(distance_yards: int, handicap_index: float, lie: str) -> tuple[float, float]:
    tour_gir, tour_px = pga_tour_fairway_baseline(int(distance_yards))
    g_adj, _ = handicap_adjust(tour_gir, tour_px, handicap_index)
    f = lie_gir_factor(lie)
    gir = max(2.0, min(98.5, g_adj * f))
    return gir, tour_gir

