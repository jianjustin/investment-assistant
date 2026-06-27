from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEEP_RESEARCH_MODEL = "deepseek-reasoner"


def deepseek_configured() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def request_json_completion(
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
    max_tokens: int = 4096,
    max_retries: int = 2,
    temperature: float = 0.2,
) -> dict[str, Any] | None:
    """Call DeepSeek's OpenAI-compatible Chat Completions endpoint for JSON output.

    Optional enhancement boundary: callers must fall back to deterministic
    analysis when no key is configured or the request fails. Returns the parsed
    JSON object, or None on failure. Failures are logged (status + reason) so an
    operator can tell "no key" from "bad key" from "API down" — see
    ``last_error()`` for the most recent structured failure.
    """
    result, _ = request_json_completion_verbose(
        system_prompt=system_prompt,
        user_payload=user_payload,
        model=model,
        timeout=timeout,
        max_tokens=max_tokens,
        max_retries=max_retries,
        temperature=temperature,
    )
    return result


def request_json_completion_verbose(
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
    max_tokens: int = 4096,
    max_retries: int = 2,
    temperature: float = 0.2,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Like ``request_json_completion`` but also returns a structured status.

    The status dict has ``ok`` plus, on failure, ``error`` and ``status_code``.
    Callers (e.g. the dashboard) can surface *why* the LLM was skipped.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None, {"ok": False, "error": "DEEPSEEK_API_KEY not configured", "status_code": None}

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    last_status: dict[str, Any] = {"ok": False, "error": "unknown", "status_code": None}
    for attempt in range(max_retries + 1):
        request = Request(f"{DEEPSEEK_BASE_URL}/chat/completions", data=data, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            return json.loads(content), {"ok": True, "error": None, "status_code": 200}
        except HTTPError as exc:  # 4xx/5xx
            detail = _read_error_body(exc)
            last_status = {"ok": False, "error": f"http {exc.code}: {detail}", "status_code": exc.code}
            logger.warning("deepseek http error (attempt %s): %s", attempt + 1, last_status["error"])
            if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(_backoff(attempt))
                continue
            return None, last_status
        except (URLError, TimeoutError) as exc:
            last_status = {"ok": False, "error": f"network: {exc}", "status_code": None}
            logger.warning("deepseek network error (attempt %s): %s", attempt + 1, exc)
            if attempt < max_retries:
                time.sleep(_backoff(attempt))
                continue
            return None, last_status
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            last_status = {"ok": False, "error": f"bad response: {exc}", "status_code": None}
            logger.warning("deepseek parse error: %s", exc)
            return None, last_status
    return None, last_status


def _backoff(attempt: int) -> float:
    return min(2.0 ** attempt, 8.0)


def _read_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8")[:300]
    except Exception:  # noqa: BLE001
        return exc.reason or ""
