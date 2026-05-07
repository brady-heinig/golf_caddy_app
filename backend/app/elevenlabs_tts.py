from __future__ import annotations

import os
from typing import Any

import requests

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def _clamp_speed(v: float) -> float:
    return max(0.5, min(2.0, float(v)))


def _effective_speech_speed(explicit: float | None) -> float | None:
    if explicit is not None:
        return _clamp_speed(explicit)
    raw = os.environ.get("ELEVENLABS_SPEECH_SPEED")
    if raw is None or not str(raw).strip():
        return None
    try:
        return _clamp_speed(float(str(raw).strip()))
    except ValueError:
        return None


def synthesize_speech_mp3(
    text: str,
    *,
    api_key: str,
    voice_id: str,
    model_id: str | None = None,
    speech_speed: float | None = None,
    timeout_s: int = 120,
) -> bytes:
    """Call ElevenLabs text-to-speech; returns raw MP3 bytes."""
    mid = model_id or os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    url = ELEVENLABS_TTS_URL.format(voice_id=voice_id)
    payload: dict[str, Any] = {
        "text": text,
        "model_id": mid.strip(),
    }
    spd = _effective_speech_speed(speech_speed)
    if spd is not None:
        payload["voice_settings"] = {"speed": spd}

    r = requests.post(
        url,
        headers={
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout_s,
    )
    if not r.ok:
        try:
            err = r.json()
            msg = err.get("detail", {}).get("message") if isinstance(err.get("detail"), dict) else err.get("detail")
            if not msg and isinstance(err.get("detail"), list) and err["detail"]:
                msg = err["detail"][0].get("msg")
        except Exception:
            msg = None
        raise RuntimeError(msg or r.text or f"ElevenLabs HTTP {r.status_code}")

    return r.content
