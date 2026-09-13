"""
Talking to GeM: one polite, cached, survivable HTTP request.

Rules, because this calls a government portal:
  * Cached with a time-to-live. The same query twice in an hour hits the
    cache, not GeM.
  * A delay between requests, and a real User-Agent.
  * A short timeout, and every failure raises GemUnavailable so callers
    can fall back to the local snapshot rather than erroring.
  * Off unless switched on, so a demo never depends on venue wifi.
"""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.config import (
    GEM_CACHE_DIR,
    GEM_CACHE_TTL_HOURS,
    GEM_LIVE_ENABLED,
    GEM_REQUEST_DELAY_SECONDS,
    GEM_SEARCH_URL,
    GEM_TIMEOUT_SECONDS,
    GEM_USER_AGENT,
)

_last_request_at = 0.0


class GemUnavailable(Exception):
    """GeM could not be reached. Callers fall back to the local snapshot."""


def _cache_path(query: str) -> Path:
    digest = hashlib.sha256(query.lower().strip().encode("utf-8")).hexdigest()[:16]
    return GEM_CACHE_DIR / f"{digest}.json"


def read_cache(query: str) -> Optional[dict]:
    path = _cache_path(query)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(payload["fetched_at"])
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        return None

    age_hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
    if age_hours > GEM_CACHE_TTL_HOURS:
        return None

    payload["from_cache"] = True
    return payload


def write_cache(query: str, payload: dict) -> None:
    GEM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(query).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def fetch_html(query: str) -> str:
    """One polite request. Raises GemUnavailable on any failure."""
    global _last_request_at

    if not GEM_LIVE_ENABLED:
        raise GemUnavailable(
            "live GeM lookup is off. Set GEM_LIVE_ENABLED=true in backend/.env"
        )

    try:
        import requests
    except ImportError as exc:
        raise GemUnavailable("requests is not installed") from exc

    wait = GEM_REQUEST_DELAY_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)

    try:
        response = requests.get(
            GEM_SEARCH_URL,
            params={"q": query},
            headers={"User-Agent": GEM_USER_AGENT,
                     "Accept": "text/html,application/xhtml+xml"},
            timeout=GEM_TIMEOUT_SECONDS,
        )
        _last_request_at = time.monotonic()
        response.raise_for_status()
    except Exception as exc:
        raise GemUnavailable(f"could not reach GeM: {exc}") from exc

    return response.text


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
