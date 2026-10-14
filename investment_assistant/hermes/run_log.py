from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _default_log_path() -> Path:
    base = Path(os.environ.get("INVESTMENT_ASSISTANT_RUNTIME_BASE", "/opt/hermes-investment-assistant"))
    return base / "logs" / "investment-assistant-runs.jsonl"


def append_run(record: dict[str, Any], path: Path | None = None) -> None:
    target = path or _default_log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
