from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.research.event_sources import (
    EVENT_DEFINITIONS, UNAVAILABLE_KINDS, EventSourceError, collect_events,
)
from investment_assistant.research.event_study import regime_fn_for_config, resolve_asof, run_event_study
from investment_assistant.tasks._harness import run_task

DEFAULT_KINDS = list(EVENT_DEFINITIONS)


def _core(
    config: AssistantConfig,
    *,
    asof: date | None = None,
    since: date | None = None,
    kinds: list[str] | None = None,
) -> dict[str, Any]:
    target_kinds = kinds or DEFAULT_KINDS
    horizons = tuple(config.backtest.horizons)
    cutoff = resolve_asof(asof)
    results: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    source_quality: dict[str, Any] = {}
    skipped_total = 0
    regime_fn = regime_fn_for_config(config.market)
    for kind in target_kinds:
        try:
            events = collect_events(kind, asof=cutoff, since=since, config=config)
        except EventSourceError as exc:
            errors[kind] = exc.to_dict()
            source_quality[kind] = exc.source_quality
            continue
        result = run_event_study(events, horizons=horizons, asof=cutoff, regime_fn=regime_fn)
        results[kind] = result.to_dict()
        results[kind]["kind"] = kind
        results[kind]["params"]["event_definition"] = dict(EVENT_DEFINITIONS.get(kind, {}))
        results[kind]["params"]["market_regime"] = asdict(config.market)
        quality = result.params.get("source_quality")
        if quality is not None:
            source_quality[kind] = quality
            if quality["status"] in ("partial", "excluded"):
                errors[kind] = {"code": f"source_quality_{quality['status']}",
                                "source": quality["source"], "excluded_count": quality["excluded_count"]}
        skipped_total += len(result.params.get("skipped", []))
    return {
        "results": results,
        "errors": errors,
        "degraded": bool(errors),
        "source_quality": source_quality,
        "unavailable": dict(UNAVAILABLE_KINDS),
        "params": {
            "kinds": target_kinds,
            "asof": cutoff.isoformat(),
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
    asof: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    # `end_date` remains the scheduler/replay alias; ambiguous pairs are rejected.
    if asof is not None and end_date is not None and asof != end_date:
        raise ValueError("asof and end_date must agree when both are supplied")
    cutoff = resolve_asof(asof if asof is not None else end_date)
    target_start = start_date or cutoff
    return run_task(
        "event_study",
        lambda: _core(config, asof=cutoff, since=start_date),
        config=config,
        target_start_date=target_start,
        target_end_date=cutoff,
        trigger_source=trigger_source,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Event study task (scheduled or manual replay)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--kind", action="append", dest="kinds", default=None,
                        help="事件类型，可多次传入；缺省仅跑可用定义")
    parser.add_argument("--asof", default=None,
                        help="事件及收益可用截止日 YYYY-MM-DD；至多为纽约当前日期前一个交易日")
    parser.add_argument("--since", default=None, help="事件下界日期 YYYY-MM-DD")
    parser.add_argument("--no-record", action="store_true", help="仅打印，不落 job_reports")
    args = parser.parse_args()
    config = load_config(args.config)
    asof = resolve_asof(date.fromisoformat(args.asof) if args.asof else None)
    since = date.fromisoformat(args.since) if args.since else None

    if args.no_record:
        summary = _core(config, asof=asof, since=since, kinds=args.kinds)
        out = {"task": "event_study", "status": "error" if summary.get("errors") else "manual", "summary": summary}
    else:
        target_start = since or asof
        target_end = asof
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
