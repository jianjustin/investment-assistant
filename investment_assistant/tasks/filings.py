from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.filings.service import download_configured_filings
from investment_assistant.tasks._harness import run_task


def _core(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    result = download_configured_filings(
        config.watchlist, config.filings, start_date=start_date, end_date=end_date
    )
    return {
        "downloaded_count": result.get("downloaded_count", 0),
        "filings": [
            {"ticker": m.get("ticker"), "form": m.get("form"),
             "filing_date": m.get("filing_date"), "path": m.get("path")}
            for m in result.get("filings", [])
        ],
        "errors": result.get("errors", {}),
    }


def run(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    target_start = start_date or (date.today() - timedelta(days=1))  # 自然目标日 T-1
    target_end = end_date or target_start
    return run_task(
        "filings",
        lambda: _core(config, start_date=start_date, end_date=end_date),
        config=config,
        target_start_date=target_start,
        target_end_date=target_end,
        trigger_source=trigger_source,
    )


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description="Daily 09:00 filings task")
    parser.add_argument("--config", default=None)
    parser.add_argument("--date", default=None, help="拉取指定单日（YYYY-MM-DD），默认 T-1")
    parser.add_argument("--from", dest="from_date", default=None, help="范围起始日（YYYY-MM-DD）")
    parser.add_argument("--to", dest="to_date", default=None, help="范围结束日（YYYY-MM-DD）")
    args = parser.parse_args()
    if args.date:
        start = end = date.fromisoformat(args.date)
    else:
        start = date.fromisoformat(args.from_date) if args.from_date else None
        end = date.fromisoformat(args.to_date) if args.to_date else None
    print(json.dumps(
        run(load_config(args.config), start_date=start, end_date=end, trigger_source="manual"),
        ensure_ascii=False, indent=2, default=str,
    ))


if __name__ == "__main__":
    main()
