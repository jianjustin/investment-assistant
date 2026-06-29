from __future__ import annotations

import argparse
import json
import os
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.db import connect, upsert_market_signal
from investment_assistant.market.service import compute_market_signal
from investment_assistant.services.tickers import run_ticker_trend_scan
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig) -> dict[str, Any]:
    signal = compute_market_signal(config.market)
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if database_url:
        with connect(database_url) as conn:
            upsert_market_signal(conn, signal)
    scan = run_ticker_trend_scan({"mode": "metrics"})
    return {
        "market_status": signal.market_status,
        "vix": signal.vix_close,
        "signal_date": str(signal.signal_date),
        "tickers": [
            {"ticker": r.get("ticker"), "trend_state": r.get("trend_state")}
            for r in scan.get("rows", [])
        ],
        "errors": scan.get("failures", []),
    }


def run(config: AssistantConfig) -> dict[str, Any]:
    return run_task("metrics", lambda: _core(config), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily 08:00 metrics task")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    print(json.dumps(run(load_config(args.config)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
