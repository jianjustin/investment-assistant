from __future__ import annotations

import json
from typing import Any

from investment_assistant.hermes.run_log import append_run


def run() -> dict[str, Any]:
    from investment_assistant.services.strategies import run_strategy_score_scan
    result = run_strategy_score_scan({"mode": "nightly"})
    append_run({"type": "nightly_scores", **result})
    return result


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
