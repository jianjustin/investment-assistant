from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import date, timedelta
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.db import connect, upsert_market_signal
from investment_assistant.market.service import compute_market_signal, compute_market_signal_for_date
from investment_assistant.services.tickers import run_ticker_trend_scan
from investment_assistant.tasks._harness import run_task


def _core(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    if start_date is None:
        return _core_today(config)
    return _core_backfill(config, start_date, end_date or start_date)


def _core_today(config: AssistantConfig) -> dict[str, Any]:
    signal = compute_market_signal(config.market)
    _persist_signal(signal)
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


def _core_backfill(config: AssistantConfig, start: date, end: date) -> dict[str, Any]:
    days: list[dict[str, Any]] = []
    tickers_scanned = 0
    target = start
    while target <= end:
        if target.isoweekday() >= 6:  # 跳过周末
            target += timedelta(days=1)
            continue
        run_id = f"backfill-metrics-{target.isoformat()}-{uuid.uuid4().hex[:8]}"
        try:
            signal = compute_market_signal_for_date(config.market, target, run_id=run_id)
            _persist_signal(signal)
            scan = run_ticker_trend_scan({"mode": "metrics", "date": target.isoformat()})
            tickers_scanned += scan.get("count", 0)
            days.append({"date": target.isoformat(), "market_status": signal.market_status})
        except Exception as exc:  # 单日失败不中断整个范围
            days.append({"date": target.isoformat(), "error": str(exc)})
        target += timedelta(days=1)
    return {
        "requested": {"from": start.isoformat(), "to": end.isoformat()},
        "days": days,
        "tickers_scanned": tickers_scanned,
        "errors": [d for d in days if d.get("error")],
    }


def _persist_signal(signal) -> None:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if database_url:
        with connect(database_url) as conn:
            upsert_market_signal(conn, signal)


def run(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    target_start = start_date or date.today()
    target_end = end_date or target_start
    return run_task(
        "metrics",
        lambda: _core(config, start_date=start_date, end_date=end_date),
        config=config,
        target_start_date=target_start,
        target_end_date=target_end,
        trigger_source=trigger_source,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily 08:00 metrics task")
    parser.add_argument("--config", default=None)
    parser.add_argument("--date", default=None, help="回补指定单日（YYYY-MM-DD）")
    parser.add_argument("--from", dest="from_date", default=None, help="回补范围起始日（YYYY-MM-DD）")
    parser.add_argument("--to", dest="to_date", default=None, help="回补范围结束日（YYYY-MM-DD）")
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
