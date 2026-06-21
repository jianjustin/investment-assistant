from __future__ import annotations

from typing import Any

from investment_assistant.runtime_paths import DEFAULT_DRAFT_DIR


def daily_brief(*, context: dict[str, Any]) -> dict[str, Any]:
    DEFAULT_DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    path = DEFAULT_DRAFT_DIR / "daily-brief-placeholder.md"
    body = (
        "# 每日投资简报占位\n\n"
        "Hermes daily job has collected market signal and filing metadata.\n"
    )
    path.write_text(body, encoding="utf-8")
    return {"output_file": str(path), "context_keys": sorted(context.keys())}
