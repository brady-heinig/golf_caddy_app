from __future__ import annotations

from typing import Any


def pick_club_for_plays_like_yards(bag: dict[str, Any], plays_like_yds: float) -> dict[str, Any]:
    """Choose a club from the bag for an *adjusted* plays-like distance (wind + elevation, etc.).

    Rule (matches “highest loft / most club that still carries the number”):
    among clubs whose *listed carry* is >= the target plays-like yards, pick the one with the
    **smallest** listed carry (e.g. at 155 yd use 8i listed 155 or 160 before 7i listed 170).

    If no club reaches the target, return the **longest** club in the bag with a note.
    """
    target = float(plays_like_yds)
    pairs: list[tuple[str, float]] = []
    for k, v in (bag or {}).items():
        try:
            yd = float(v)
        except (TypeError, ValueError):
            continue
        if yd <= 0:
            continue
        pairs.append((str(k), yd))

    base = {
        "adjusted_plays_like_yds": round(target, 1),
        "selection_rule": (
            "Pick the club with minimum listed carry that is still >= adjusted plays-like yards "
            "(most lofted reasonable club for that distance)."
        ),
    }

    if not pairs:
        return {
            **base,
            "club": "Unknown",
            "listed_carry_yds": None,
            "fallback": "empty_bag",
        }

    pairs.sort(key=lambda kv: (kv[1], kv[0]))
    for club, yd in pairs:
        if yd + 1e-6 >= target:
            return {
                **base,
                "club": club,
                "listed_carry_yds": round(yd, 1),
                "fallback": None,
            }

    longest_club, longest_yd = pairs[-1]
    return {
        **base,
        "club": longest_club,
        "listed_carry_yds": round(longest_yd, 1),
        "fallback": "no_club_reaches_target_use_longest",
        "note": "No club in Settings lists carry >= adjusted distance; using longest club as best effort.",
    }


def club_name_for_plays_like_yards(bag: dict[str, Any], plays_like_yds: float) -> str:
    return str(pick_club_for_plays_like_yards(bag, plays_like_yds)["club"])
