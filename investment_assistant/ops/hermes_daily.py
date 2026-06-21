from __future__ import annotations

import argparse
import json

from investment_assistant.config import load_config
from investment_assistant.hermes.daily import run_daily


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Hermes investment assistant daily task")
    parser.add_argument("--config", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-brief", action="store_true")
    args = parser.parse_args()
    result = run_daily(load_config(args.config), dry_run=args.dry_run, skip_brief=args.skip_brief)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
