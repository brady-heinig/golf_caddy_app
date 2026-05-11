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


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _one_spoken_sentence(raw: str, *, max_chars: int = 260) -> str:
    """Force a single crisp sentence for voice TTS."""
    t = (raw or "").strip()
    if not t:
        return t
    t = re.sub(r"^[\s\"'*`]+|[\s\"'*`]+$", "", t)
    parts = _SENTENCE_SPLIT.split(t, maxsplit=1)
    one = parts[0].strip()
    # Drop common hedges so the reply leads with the actual answer.
    one = re.sub(
        r"^(?:great question|good question|sure|okay|yeah|yes)\s*[,.:-]?\s*",
        "",
        one,
        flags=re.IGNORECASE,
    ).strip()
    if len(one) > max_chars:
        one = one[: max_chars - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return one


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
    """One direct sentence answering the player's follow-up question (voice)."""
    sys = (
        "You answer a golfer who just asked ONE follow-up question after getting on-course advice.\n"
        "Rules:\n"
        "- Reply with exactly ONE sentence. No lists, no second sentence, no 'firstly/also'.\n"
        "- Answer their question DIRECTLY as the MAIN point of that sentence — not a preamble, not a tangent.\n"
        "- Use the situation context ONLY if needed to answer; do not recap advice they did not ask about.\n"
        "- Conversational tone, spoken aloud; max ~240 characters preferred.\n"
        "- Never start with 'As a caddie' or 'I'd suggest' fluff unless the answer needs it."
    )
    crs = course_name.strip() if course_name else ""
    segs = [f"Hole {hole_number}"]
    if par is not None:
        segs.append(f"par {par}")
    if plays_like_yds is not None:
        segs.append(f"~{round(plays_like_yds)} yd plays-like to pin")
    hole_line = ", ".join(segs) + "."
    ctx = (
        "(Background — use only what's needed to answer their question; do not recap unrelated topics.)\n"
        + (f"Course: {crs}. " if crs else "")
        + hole_line
        + "\n"
        + f"Lie: {lie_label}. Aim: {landing_hint}.\n"
    )
    hint = ""
    if brief_advice_snippet and brief_advice_snippet.strip():
        hint = f"Earlier advice excerpt (ONLY if directly relevant):\n{brief_advice_snippet.strip()[:500]}\n\n"
    usr = hint + ctx + f"Their question:\n{question.strip()}"
    raw = _call_text(sys, usr, max_tokens=150)
    return _one_spoken_sentence(raw)


def format_voice_hole_situation(
    *,
    course_name: str | None,
    hole_number: int,
    par: int | None,
    plays_like_yds: float | None,
    lie_label: str,
    landing_hint: str,
) -> str:
    """Single block of on-course facts for voice Q&A models."""
    crs = course_name.strip() if course_name else ""
    head = f"Course: {crs}. " if crs else ""
    segs = [f"Hole {hole_number}"]
    if par is not None:
        segs.append(f"par {par}")
    if plays_like_yds is not None:
        segs.append(f"~{round(plays_like_yds)} yd plays-like to pin")
    hole_line = ", ".join(segs) + "."
    return (
        head
        + hole_line
        + f"\nLie: {lie_label}.\nAim / target: {landing_hint}.\n"
    )


def voice_thread_reply(
    *,
    grounding_context: str,
    transcript: list[tuple[str, str]],
) -> str:
    """Next caddie reply in a multi-turn voice conversation; uses full transcript as memory."""
    lines: list[str] = []
    for role, content in transcript:
        r = "Player" if role == "user" else "Caddie"
        lines.append(f"{r}: {content.strip()}")
    convo = "\n".join(lines)
    sys = (
        "You are the player's on-course golf caddie in a **continuing voice conversation**.\n"
        "You receive VOICE_ASK_CONTEXT: a **trimmed** fact block built from the same map/metrics/bag pipeline as the "
        "main caddie, but only sections relevant to the player's **latest question** (plus a short CORE summary). "
        "If they ask for 'everything' / full detail, the context may include full STRUCTURED_SHOT_INTEL JSON.\n"
        "Rules:\n"
        "- Treat the provided sections as **ground truth** for yardages, wind, trouble, and club-vs-distance; "
        "do not contradict them unless the player corrects you with new facts.\n"
        "- Respond with **exactly one sentence** unless the player explicitly asked for two distinct things; "
        "if two, use at most two short clauses in one breath (still one sentence).\n"
        "- Your reply must **directly address their last message** and stay consistent with **everything the player "
        "said earlier** in the thread (clubs, choices, worries, numbers they gave).\n"
        "- Do not reset the topic unless they changed it; use prior user lines as binding context.\n"
        "- No bullets, no recap of the whole thread, no 'as we discussed' padding.\n"
        "- Stay within on-course advice; if unclear, ask one clarifying thing in that single sentence.\n"
        "\nVOICE_ASK_CONTEXT:\n"
        f"{grounding_context.strip()}\n"
    )
    usr = (
        "CONVERSATION (chronological, oldest first):\n"
        f"{convo}\n\n"
        "Write the Caddie's **next** spoken reply only (plain text, no label)."
    )
    raw = _call_text(sys, usr, max_tokens=200)
    return _one_spoken_sentence(raw, max_chars=300)


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
