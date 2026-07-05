from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.research.event_sources import collect_events
from investment_assistant.research.event_study import run_event_study
from investment_assistant.tasks._harness import run_task

DEFAULT_KINDS = ["rs_strong", "ma_reclaim", "score_high"]


def _core(
    config: AssistantConfig,
    *,
    asof: date | None = None,
    since: date | None = None,
    kinds: list[str] | None = None,
) -> dict[str, Any]:
    target_kinds = kinds or DEFAULT_KINDS
    horizons = tuple(getattr(config.backtest, "horizons", [5, 10, 20]))
    results: dict[str, Any] = {}
    skipped_total = 0
    for kind in target_kinds:
        events = collect_events(kind, asof=asof, since=since, config=config)
        result = run_event_study(events, horizons=horizons)
        results[kind] = result.to_dict()
        skipped_total += len(result.params.get("skipped", []))
    return {
        "results": results,
        "params": {
            "kinds": target_kinds,
            "asof": asof.isoformat() if asof else None,
            "since": since.isoformat() if since else None,
            "horizons": list(horizons),
        },
        "skipped_total": skipped_total,
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
        "event_study",
        lambda: _core(config, asof=end_date, since=start_date),
        config=config,
        target_start_date=target_start,
        target_end_date=target_end,
        trigger_source=trigger_source,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Event study task (scheduled or manual replay)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--kind", action="append", dest="kinds", default=None,
                        help="事件类型，可多次传入；缺省跑全部")
    parser.add_argument("--asof", default=None, help="历史 as-of 日期 YYYY-MM-DD（回放用）")
    parser.add_argument("--since", default=None, help="事件下界日期 YYYY-MM-DD")
    parser.add_argument("--no-record", action="store_true", help="仅打印，不落 job_reports")
    args = parser.parse_args()
    config = load_config(args.config)
    asof = date.fromisoformat(args.asof) if args.asof else None
    since = date.fromisoformat(args.since) if args.since else None

    if args.no_record:
        summary = _core(config, asof=asof, since=since, kinds=args.kinds)
        out = {"task": "event_study", "status": "manual", "summary": summary}
    else:
        target_start = since or date.today()
        target_end = asof or target_start
        out = run_task(
            "event_study",
            lambda: _core(config, asof=asof, since=since, kinds=args.kinds),
            config=config,
            target_start_date=target_start,
            target_end_date=target_end,
            trigger_source="manual",
        )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
