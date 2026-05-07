"""Shared Open-Meteo HTTP: retries for 429/503 (Render shared IPs hit rate limits)."""

from __future__ import annotations

import random
import time
from typing import Any

import requests

_USER_AGENT = "golf-caddy-backend/1.0"


_MAX_BACKOFF_S = 8.0

def fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 15.0,
    max_attempts: int = 3,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    GET JSON from Open-Meteo with retries on rate limit / transient errors.
    Returns (json_dict_or_none, error_message_or_none).
    """
    last_err: str | None = None
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}

    for attempt in range(max_attempts):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code in (429, 503):
                ra = r.headers.get("Retry-After")
                try:
                    wait_s = float(ra) if ra is not None else min(_MAX_BACKOFF_S, (2**attempt) + random.uniform(0, 0.35))
                except ValueError:
                    wait_s = min(_MAX_BACKOFF_S, (2**attempt) + random.uniform(0, 0.35))
                time.sleep(min(_MAX_BACKOFF_S, max(0.5, wait_s)))
                last_err = f"{r.status_code} {r.reason}"
                continue
            r.raise_for_status()
            out = r.json()
            return (out if isinstance(out, dict) else None, None)
        except (requests.RequestException, ValueError) as e:
            last_err = str(e)
            if attempt < max_attempts - 1:
                time.sleep(min(_MAX_BACKOFF_S, (2**attempt) + random.uniform(0, 0.25)))

    return (None, last_err)
