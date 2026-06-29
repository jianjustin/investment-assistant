from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)
_RETRYABLE = {429, 500, 502, 503, 504}


def _backoff(attempt: int, base: float) -> float:
    return min(base * (2 ** attempt), 30.0)


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    last: dict[str, Any] = {"ok": False, "error": "unknown", "status_code": None}
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last = {"ok": False, "error": f"network: {exc}", "status_code": None}
            logger.warning("http get network error (attempt %s): %s", attempt + 1, exc)
            if attempt < max_retries:
                time.sleep(_backoff(attempt, backoff_seconds))
                continue
            return None, last
        if resp.status_code == 200:
            try:
                return resp.json(), {"ok": True, "error": None, "status_code": 200}
            except ValueError as exc:
                return None, {"ok": False, "error": f"bad json: {exc}", "status_code": 200}
        last = {"ok": False, "error": f"http {resp.status_code}: {resp.text[:300]}", "status_code": resp.status_code}
        logger.warning("http get error (attempt %s): %s", attempt + 1, last["error"])
        if resp.status_code in _RETRYABLE and attempt < max_retries:
            time.sleep(_backoff(attempt, backoff_seconds))
            continue
        return None, last
    return None, last
