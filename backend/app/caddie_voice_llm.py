from __future__ import annotations

import json
import os
import re

import anthropic

_DEFAULT_MODEL = os.environ.get("ANTHROPIC_CADDIE_MODEL", "claude-haiku-4-5")


def _call_text(system: str, user: str, *, max_tokens: int = 400) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing")
    client = anthropic.Anthropic(api_key=api_key)
    model = _DEFAULT_MODEL
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    blk = msg.content[0]
    if getattr(blk, "type", None) != "text":
        raise RuntimeError("unexpected block type from Anthropic")
    return str(blk.text).strip()


def generate_last_shot_question(
    *,
    recommended_club: str,
    plays_like_yd: float,
    hole_number: int,
    course_hint: str | None = None,
) -> str:
    """One brief spoken sentence asking what club they hit and how it went."""
    cx = course_hint.strip() if course_hint else ""
    cx_line = f"Course: {cx}. " if cx else ""
    sys = (
        "You speak as a terse friendly golf caddie. Respond with ONE short sentence under 140 characters. "
        "No quotes, no preamble. Ask casually what club they hit on their LAST swing after your prior advice "
        "and briefly how it went (result / contact). Mention the approximate yardage (~"
        + f"{plays_like_yd:.0f} yds"
        ") or suggested club lightly if natural."
    )
    usr = (
        f"{cx_line}Hole {hole_number}. Your suggestion was roughly suited to hitting about {plays_like_yd:.0f} yards "
        f"(recommended bag club label: {recommended_club}). One question only."
    )
    return _call_text(sys, usr, max_tokens=120)


def extract_shot_feedback_json(
    *,
    transcript: str,
    recommended_club: str,
    plays_like_yd: float,
    allowed_bag_clubs: list[str],
    hole_number: int,
) -> dict:
    sys = (
        "You extract structured facts from golfer speech AFTER the caddie asked about their last swing.\n"
        "Reply with ONLY compact JSON:\n"
        '{"club_used_key": "<string or empty>", '
        '"outcome": "<few words describing result: long short pin_high good bad etc>", '
        '"estimated_carry_yards": <integer or null>}\n'
        "club_used_key MUST be copied exactly from the allowed list when possible; "
        'if ambiguous use "".\nNo markdown, no explanation.'
    )
    usr = (
        f"Allowed bag club keys (pick one or \"\"):\n{json.dumps(allowed_bag_clubs)}\n"
        f"Prior caddie context: advised ~{plays_like_yd:.0f} yd, suggestion label {recommended_club}, hole {hole_number}.\n"
        f"Player said:\n{transcript}"
    )
    raw = _call_text(sys, usr, max_tokens=200).strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        brace = raw.find("{")
        if brace >= 0:
            tail = raw[brace:]
            end = tail.rfind("}") + 1
            if end > 0:
                return json.loads(tail[:end])
        return {"club_used_key": "", "outcome": transcript[:280], "estimated_carry_yards": None}


def voice_followup_answer(
    *,
    question: str,
    course_name: str | None,
    hole_number: int,
    par: int | None,
    plays_like_yds: float | None,
    lie_label: str,
    landing_hint: str,
    brief_advice_snippet: str | None,
) -> str:
    """Short spoken-style answer to an ad-hoc player question."""
    sys = (
        "You are a seasoned golf caddie. Reply with ONE conversational paragraph suitable for voice, under "
        "500 characters: clear, actionable, no bullet list, no role-play labels."
    )
    crs = course_name.strip() if course_name else ""
    ctx = (
        f"Course: {crs}. " if crs else ""
    ) + (
        f"Hole {hole_number}"
        + (f" par-{par}" if par is not None else "")
        + (
            f", ~{round(plays_like_yds)} yards (plays-like) to pin." if plays_like_yds is not None else "."
        )
        + f" Lie: {lie_label}. Aim / landing cue: {landing_hint}.\n"
    )
    hint = ""
    if brief_advice_snippet and brief_advice_snippet.strip():
        hint = f"Fresh written advice summary snippet (trust if relevant):\n{brief_advice_snippet.strip()[:900]}\n\n"
    usr = hint + ctx + f"Player question (voice):\n{question.strip()}"
    return _call_text(sys, usr, max_tokens=300)


_slug_key_re = re.compile(r"[^a-z0-9]")


def _norm_key(label: str) -> str:
    return _slug_key_re.sub("", (label or "").lower())


def best_bag_key_for_extraction(candidate: str, bag_keys: list[str]) -> str | None:
    if not candidate or not isinstance(candidate, str):
        return None
    c = candidate.strip()
    if not c:
        return None
    if c in bag_keys:
        return c
    n = _norm_key(c)
    for k in bag_keys:
        if _norm_key(k) == n:
            return k
    for k in bag_keys:
        if _norm_key(k) in n or n in _norm_key(k):
            return k
    return None


def refine_bag_carry(bag: dict, club_key: str, observed_carry: float | None, alpha: float = 0.35) -> tuple[dict, bool]:
    """EMA toward observed carry when present; clamp 55–290."""
    if observed_carry is None or not isinstance(observed_carry, (int, float)):
        return bag, False
    y = float(observed_carry)
    if not (40 <= y <= 320):
        return bag, False
    y = max(55, min(290, y))
    out = dict(bag)
    try:
        old = float(out.get(club_key) or 0)
    except (TypeError, ValueError):
        old = 0.0
    if old <= 0:
        out[club_key] = round(y)
        return out, True
    blended = (1 - alpha) * old + alpha * y
    out[club_key] = max(55, min(290, round(blended)))
    return out, True
