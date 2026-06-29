from __future__ import annotations

import argparse
import json
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig) -> dict[str, Any]:
    from investment_assistant.services.strategies import run_strategy_score_scan

    return run_strategy_score_scan({"mode": "nightly"})


def run(config: AssistantConfig) -> dict[str, Any]:
    return run_task("scores", lambda: _core(config), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nightly strategy score task")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    print(json.dumps(run(load_config(args.config)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
