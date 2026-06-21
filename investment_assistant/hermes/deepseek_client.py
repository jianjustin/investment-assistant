from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import Request, urlopen

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def deepseek_configured() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def request_json_completion(*, system_prompt: str, user_payload: dict[str, Any], model: str = "deepseek-v4-pro", timeout: int = 45) -> dict[str, Any] | None:
    """Call DeepSeek's OpenAI-compatible Chat Completions endpoint for JSON output.

    This is an optional enhancement boundary. Callers must be prepared to fall
    back to deterministic analysis when no key is configured or the request
    fails. It is intentionally not used automatically in dashboard refreshes.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "stream": False,
    }
    request = Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:  # noqa: BLE001
        return None
