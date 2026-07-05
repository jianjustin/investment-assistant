from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.tasks._harness import run_task


def _core(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    from investment_assistant.services.strategies import run_strategy_score_scan

    if start_date is None:
        return run_strategy_score_scan({"mode": "nightly"})

    days: list[dict[str, Any]] = []
    end = end_date or start_date
    target = start_date
    while target <= end:
        if target.isoweekday() >= 6:  # 跳过周末
            target += timedelta(days=1)
            continue
        try:
            result = run_strategy_score_scan({"mode": "backfill", "date": target.isoformat()})
            days.append({
                "date": target.isoformat(),
                "count": result.get("count", 0),
                "failures": len(result.get("failures", [])),
            })
        except Exception as exc:  # 单日失败不中断整个范围
            days.append({"date": target.isoformat(), "error": str(exc)})
        target += timedelta(days=1)
    return {
        "requested": {"from": start_date.isoformat(), "to": end.isoformat()},
        "days": days,
        "total": sum(d.get("count", 0) for d in days),
        "note": "宏观环境取当前状态（历史宏观未回放）",
    }


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
        "scores",
        lambda: _core(config, start_date=start_date, end_date=end_date),
        config=config,
        target_start_date=target_start,
        target_end_date=target_end,
        trigger_source=trigger_source,
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
