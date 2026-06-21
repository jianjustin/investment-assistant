from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from investment_assistant.runtime_paths import RUN_LOG_PATH


def append_run(record: dict[str, Any], path: Path = RUN_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
