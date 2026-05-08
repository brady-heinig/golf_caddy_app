from __future__ import annotations

import re

import anthropic

# Maximum characters for the spoken summary paragraph (TTS / UI).
SUMMARY_MAX_CHARACTERS = 600

# Lines shown to the player under “Briefing details” (same order as model output).
DISPLAY_ORDER = [
    "CURRENT_SHOT",
    "AIM",
    "TROUBLE",
    "FAIRWAY",
    "GO_FOR_IT",
    "IDEAL_DISTANCE_NOTE",
    "CLUB",
    "NEXT_SHOT",
]

_LINE_HINTS: dict[str, str] = {
    "CURRENT_SHOT": (
        "Brief stroke label using lie_and_situation.shot_type, par, and distance_to_pin_yds "
        "(e.g. tee shot par 4 ~410 yd)."
    ),
    "AIM": (
        "Start line and curve using shot_shape_from_settings.shape where relevant; "
        "reference bunker/trouble sides from JSON; align with fairway landing."
    ),
    "TROUBLE": (
        "From bunkers_near_tee_shot_corridor and major_trouble_near_corridor — what to avoid; "
        "if none material, say clear."
    ),
    "FAIRWAY": (
        "STRUCTURED_SHOT_INTEL.fairway_at_landing — width, inside polygon or not, roomy vs tight."
    ),
    "GO_FOR_IT": (
        "yes or no plus a short clause from club_recommendation.go_for_it_explanation. "
        "Must be **no** when positional_play_to_landing is true — pin yardage may fit driver but routing/trees mean "
        "playing to the fairway with irons or fairway woods, not at the green."
    ),
    "IDEAL_DISTANCE_NOTE": (
        "club_recommendation.ideal_second_shot_distance_yds and suggested_layup_carry_yds when present; "
        "otherwise n/a. One short phrase."
    ),
    "CLUB": (
        "Final club + shot type for THIS swing using club_distance_basis_yds (see club_recommendation): "
        "when club_distance_basis is adjusted_carry_to_intended_landing, fit carry to white/fairway target — "
        "never driver-at-pin based only on plays-like to pin."
    ),
    "NEXT_SHOT": "One short clause condensed from next_shot_if_plan_works.summary.",
}

CADDIE_BRIEFING_SYSTEM = (
    "You are an experienced on-course golf caddie. In the user message, STRUCTURED_SHOT_INTEL JSON is ground truth "
    "from mapping/software; trust it over guesses.\n"
    "Reply with EXACTLY eight lines and nothing else: no markdown code fences, no preamble, no trailing commentary. "
    "Each line starts with the exact label and a colon as shown, in the prescribed order. "
    "Keep each line to one sentence when possible."
)

CADDIE_SUMMARY_SYSTEM = (
    "You are an experienced golf caddie speaking directly to the player. You receive STRUCTURED_SHOT_INTEL "
    "plus labeled briefing lines produced earlier.\n"
    "Write ONE fluent paragraph meant for text-to-speech: conversational English, no bullet list, "
    "do not echo the section labels as headings.\n"
    f"STRICT LENGTH: the text after SUMMARY: must be at most {SUMMARY_MAX_CHARACTERS} characters "
    "(count spaces and punctuation). Stay under this limit — be concise.\n"
    "The paragraph must naturally cover all of the following (weave them, don’t number them):\n"
    "- How far from the hole you are (yardage / plays-like feel).\n"
    "- Whether it’s reasonable to go straight at the pin from here.\n"
    "- How far to hit this shot (carry intent / shot type).\n"
    "- Where to aim.\n"
    "- What an ideal outcome leaves for the next shot.\n"
    "- What to look to avoid.\n"
    "- A brief word of encouragement.\n"
    "If space is tight, prioritize: yardage, club/carry intent, aim, next-shot leave, then hazards and encouragement.\n"
    "If STRUCTURED_SHOT_INTEL.club_recommendation.positional_play_to_landing is true, say clearly this stroke is a "
    "fairway/layup target (often blocked direct line), not driver-at-pin.\n"
    "Start your reply with exactly SUMMARY: followed by the paragraph (you may continue on the same line "
    "and wrap naturally)."
)

_SUMMARY_HEAD_FIX = re.compile(r"(?is)^\*{0,2}\s*SUMMARY\s*:\s*\*{0,2}\s*")


def _clamp_summary_body(text: str, max_chars: int = SUMMARY_MAX_CHARACTERS) -> str:
    """Enforce max length for TTS; break at last space when possible. Includes ellipsis if truncated."""
    t = text.strip()
    if len(t) <= max_chars:
        return t
    ellipsis = "…"
    budget = max_chars - len(ellipsis)
    if budget < 12:
        return t[:max_chars]
    truncated = t[:budget]
    sp = truncated.rfind(" ")
    if sp >= budget // 2:
        truncated = truncated[:sp]
    base = truncated.rstrip(".,;:- ")
    return base + ellipsis


def _normalize_summary(raw: str) -> str:
    t = raw.replace("\r\n", "\n").strip()
    if _SUMMARY_HEAD_FIX.match(t):
        body = _SUMMARY_HEAD_FIX.sub("", t, count=1).strip()
        return f"SUMMARY: {body}"
    return f"SUMMARY: {t}"


def summary_plain_text(raw_model_output: str) -> str:
    """Strip SUMMARY: prefix for API `summary` field and TTS; enforce SUMMARY_MAX_CHARACTERS."""
    normalized = _normalize_summary(raw_model_output)
    body = _SUMMARY_HEAD_FIX.sub("", normalized, count=1).strip()
    return _clamp_summary_body(body)


def _message_assistant_text(msg: object) -> str:
    parts: list[str] = []
    for block in msg.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


def _call_text(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
) -> str:
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _message_assistant_text(msg)


def _strip_md_fence(s: str) -> str:
    t = s.strip()
    if not t.startswith("```"):
        return t
    t = re.sub(r"^```\w*\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _build_briefing_user_message(ctx: str, user_line: str) -> str:
    order_block = "\n".join(
        f"{i + 1}. {label}: {_LINE_HINTS[label]}" for i, label in enumerate(DISPLAY_ORDER)
    )
    labels_line = ", ".join(f"{lb}:" for lb in DISPLAY_ORDER)
    return (
        f"COURSE CONTEXT\n{ctx}\n\n"
        f"PLAYER QUESTION\n{user_line}\n\n"
        "OUTPUT\n"
        f"Write exactly eight lines in this order. Each line must begin with one of these labels exactly: {labels_line}\n\n"
        f"{order_block}"
    )


def run_caddie_advice_chain(
    *,
    ctx: str,
    user_line: str,
    client: anthropic.Anthropic,
    model: str,
) -> tuple[str, str]:
    """Two LLM calls: (1) eight labeled briefing lines, (2) spoken summary paragraph. Returns (briefing, summary_plain)."""
    briefing_user = _build_briefing_user_message(ctx, user_line)
    briefing_raw = _call_text(
        client,
        model,
        CADDIE_BRIEFING_SYSTEM,
        briefing_user,
        max_tokens=900,
    )
    briefing = _strip_md_fence(briefing_raw)

    summary_user = (
        f"COURSE CONTEXT\n{ctx}\n\n"
        f"PLAYER QUESTION\n{user_line}\n\n"
        f"CADDIE SECTIONS (treat as locked-in briefing)\n{briefing}\n\n"
        "Write the SUMMARY paragraph as specified in your system instructions.\n"
        f"HARD LIMIT REMINDER: paragraph after SUMMARY: ≤ {SUMMARY_MAX_CHARACTERS} characters."
    )
    summary_raw = _call_text(client, model, CADDIE_SUMMARY_SYSTEM, summary_user, max_tokens=280)
    summary_plain = summary_plain_text(summary_raw)

    return briefing, summary_plain
