from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.data.calendar import is_trading_day
from investment_assistant.tasks._harness import run_task


def _core(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    from investment_assistant.services.strategies import run_strategy_score_scan

    if start_date is None:
        result = run_strategy_score_scan({"mode": "nightly"})
        return {**result, "errors": result.get("failures", [])}

    days: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    actual_dates: set[str] = set()
    scored_dates: set[str] = set()
    end = end_date or start_date
    if end < start_date:
        raise ValueError("end_date must be on or after start_date")
    target = start_date
    while target <= end:
        if not is_trading_day(target):
            skipped.append({"date": target.isoformat(), "reason": "non_trading_day"})
            target += timedelta(days=1)
            continue
        try:
            result = run_strategy_score_scan({"mode": "backfill", "date": target.isoformat()})
            failures = [{**failure, "date": target.isoformat(), "stage": "strategy_score"}
                        for failure in result.get("failures", [])]
            errors.extend(failures)
            skipped.extend(result.get("skipped", []))
            actual_dates.update(result.get("actual_dates", []))
            scored_dates.update(result.get("scored_dates", []))
            days.append({
                "date": target.isoformat(),
                "count": result.get("count", 0),
                "computed_count": result.get("computed_count", result.get("count", 0)),
                "inserted_count": result.get("inserted_count", 0),
                "skipped_count": result.get("skipped_count", 0),
                "actual_dates": result.get("actual_dates", []),
                "market_contexts": result.get("market_contexts", {}),
                "failures": len(failures),
                "failure_details": failures,
            })
        except Exception as exc:  # 单日失败不中断整个范围
            failure = {"date": target.isoformat(), "error": str(exc)}
            days.append(failure)
            errors.append(failure)
        target += timedelta(days=1)
    return {
        "requested": {"from": start_date.isoformat(), "to": end.isoformat()},
        "days": days,
        "skipped": skipped,
        "total": sum(d.get("count", 0) for d in days),
        "computed_count": sum(d.get("computed_count", 0) for d in days),
        "inserted_count": sum(d.get("inserted_count", 0) for d in days),
        "skipped_count": sum(d.get("skipped_count", 0) for d in days),
        "actual_dates": sorted(actual_dates),
        "scored_dates": sorted(scored_dates),
        "errors": errors,
        "note": "宏观环境按每个评分日的历史输入重建；缺失输入拒绝评分，非归档数据版本回放",
    }


def run(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    # An undated run selects persisted snapshots, possibly from several older
    # sessions. Only the returned selection can determine its report range.
    target_start = start_date
    target_end = end_date or target_start
    return run_task(
        "scores",
        lambda: _core(config, start_date=start_date, end_date=end_date),
        config=config,
        target_start_date=target_start,
        target_end_date=target_end,
        trigger_source=trigger_source,
        target_dates_from_summary=start_date is None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Nightly strategy score task")
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
