from __future__ import annotations

import argparse
import json
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.hermes.run_log import append_run


def run(config: AssistantConfig, *, dry_run: bool = False) -> dict[str, Any]:
    from investment_assistant.hermes.daily import run_daily
    try:
        result = run_daily(config, dry_run=dry_run)
    except (ImportError, Exception) as exc:
        result = {"run_id": "daily-error", "status": "error", "error": str(exc)}
    append_run({"type": "hermes_daily", **result})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes daily scheduled task")
    parser.add_argument("--config", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(load_config(args.config), dry_run=args.dry_run), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
