from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.data.calendar import is_trading_day
from investment_assistant.db import connect, upsert_market_signal
from investment_assistant.market.service import compute_market_signal_for_date
from investment_assistant.services.tickers import run_ticker_trend_scan
from investment_assistant.tasks._harness import run_task
from investment_assistant.tickers.trend import latest_completed_signal_date, validate_signal_date


_COUNT_KEYS = (
    "market_computed_count", "market_inserted_count", "market_skipped_count",
    "ticker_computed_count", "ticker_inserted_count", "ticker_inserted_success_count", "ticker_skipped_count",
)


def _core(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    target_date: date | None = None,
) -> dict[str, Any]:
    if start_date is None:
        return _core_today(config, target_date=target_date)
    return _core_backfill(config, start_date, end_date or start_date)


def _core_today(
    config: AssistantConfig, *, target_date: date | None = None, run_id: str | None = None,
) -> dict[str, Any]:
    target = target_date or latest_completed_signal_date()
    validate_signal_date(target)
    signal = compute_market_signal_for_date(config.market, target, run_id=run_id)
    _validate_market_bar_dates(signal, target)
    persistence = _persist_signal(signal)
    scan = run_ticker_trend_scan({"mode": "metrics", "date": target.isoformat()})
    errors = [{**failure, "date": target.isoformat(), "stage": "ticker_scan"}
              for failure in scan.get("failures", [])]
    if persistence.get("error"):
        errors.append({"date": target.isoformat(), "stage": "market_persistence", "error": persistence["error"]})
    attempted = scan.get("count", len(scan.get("rows", [])))
    return {
        "market_status": signal.market_status,
        "vix": signal.vix_close,
        "signal_date": str(signal.signal_date),
        "actual_dates": [target.isoformat()],
        "market_computed_count": 1,
        "market_inserted_count": persistence["inserted_count"],
        "market_skipped_count": persistence["skipped_count"],
        "tickers_scanned": attempted,
        "ticker_computed_count": scan.get("computed_count", attempted - len(scan.get("failures", []))),
        "ticker_inserted_count": scan.get("inserted_count", 0),
        "ticker_inserted_success_count": scan.get("inserted_success_count", 0),
        "ticker_skipped_count": scan.get("skipped_count", 0),
        "tickers": [
            {"ticker": r.get("ticker"), "trend_state": r.get("trend_state")}
            for r in scan.get("rows", [])
        ],
        "skipped": persistence["skipped"] + scan.get("skipped", []),
        "errors": errors,
    }


def _core_backfill(config: AssistantConfig, start: date, end: date) -> dict[str, Any]:
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    days: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    actual_dates: set[str] = set()
    totals = dict.fromkeys((*_COUNT_KEYS, "tickers_scanned"), 0)
    target = start
    while target <= end:
        if not is_trading_day(target):
            skipped.append({"date": target.isoformat(), "reason": "non_trading_day"})
            target += timedelta(days=1)
            continue
        run_id = f"backfill-metrics-{target.isoformat()}-{uuid.uuid4().hex[:8]}"
        try:
            result = _core_today(config, target_date=target, run_id=run_id)
            for key in totals:
                totals[key] += result[key]
            errors.extend(result["errors"])
            skipped.extend(result["skipped"])
            actual_dates.update(result["actual_dates"])
            days.append({"date": target.isoformat(), "market_status": result["market_status"],
                         **{key: result[key] for key in totals}, "failures": result["errors"]})
        except Exception as exc:  # 单日失败不中断整个范围
            failure = {"date": target.isoformat(), "error": str(exc)}
            days.append(failure)
            errors.append(failure)
        target += timedelta(days=1)
    return {
        "requested": {"from": start.isoformat(), "to": end.isoformat()},
        "actual_dates": sorted(actual_dates),
        "days": days,
        "skipped": skipped,
        **totals,
        "errors": errors,
    }


def _validate_market_bar_dates(signal, target: date) -> None:
    if str(signal.signal_date) != target.isoformat():
        raise ValueError(f"Market signal date does not match {target}")
    details = getattr(signal, "details", None) or {}
    for key in ("spy_latest_index", "vix_latest_index"):
        try:
            actual = datetime.fromisoformat(str(details.get(key))).date()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unknown market bar date: {key} for {target}") from exc
        if actual != target:
            raise ValueError(f"Market bar date mismatch: {key}={actual}, target={target}")


def _persist_signal(signal) -> dict[str, Any]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return {"inserted_count": 0, "skipped_count": 0, "skipped": [],
                "error": "Market signal not persisted: database is not configured"}
    with connect(database_url) as conn:
        inserted = upsert_market_signal(conn, signal, preserve_existing=True)
    skipped = [] if inserted else [{"date": str(signal.signal_date), "stage": "market_signal",
                                    "reason": "existing_record_preserved"}]
    return {"inserted_count": int(inserted), "skipped_count": len(skipped), "skipped": skipped}


def run(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    # Resolve once: crossing the close-delay boundary must not change the input
    # date after the report's target range has already been chosen.
    target_start = start_date or latest_completed_signal_date()
    target_end = end_date or target_start
    return run_task(
        "metrics",
        lambda: _core(config, start_date=start_date, end_date=end_date, target_date=target_start),
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
