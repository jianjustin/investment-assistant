from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
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


def _record_fetch_run(result: dict[str, Any], *, config: AssistantConfig,
                      trigger_source: str, started_at: datetime) -> dict[str, Any]:
    """Append this run's one sec_filings row to data_fetch_runs (v2.3 §6.3).

    Targets are this task's own config.watchlist, not the batch's pool. A write
    failure is only reported (the return value), never changes the task result."""
    from investment_assistant.workbench import collect

    summary = result.get("summary") or {}
    tally = collect.Tally("sec_filings", "filings", targets=config.watchlist)
    errors = summary.get("errors")
    if isinstance(errors, dict):
        for ticker, reason in errors.items():
            tally.fail(ticker, reason)
        for ticker in config.watchlist:
            if ticker not in errors:
                tally.ok(ticker)
    elif isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                tally.fail(item.get("ticker", "*"), item.get("error", item))
            else:
                tally.fail("*", item)
        for ticker in config.watchlist:
            if ticker not in tally.outcomes:
                tally.ok(ticker)
    elif summary.get("error"):
        tally.fail("*", summary["error"])  # 整次失败：没有任何目标成功
    else:
        for ticker in config.watchlist:
            tally.ok(ticker)
    tally.detail = {"targets_source": "config.watchlist",
                    "mode": "monitor" if config.sec_monitor.enabled else "downloader"}
    return collect.write_runs([tally.row(
        trigger="scheduled" if trigger_source == "scheduled" else "manual_batch",
        run_id=result.get("run_id"), session=None,
        started_at=started_at, finished_at=datetime.now(UTC))])


def run(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    if config.sec_monitor.enabled:
        from investment_assistant.filings.monitor import run_monitor

        result = run_monitor(config, start_date=start_date, end_date=end_date, trigger_source=trigger_source)
    else:
        target_start = start_date or (date.today() - timedelta(days=1))  # 自然目标日 T-1
        target_end = end_date or target_start
        result = run_task(
            "filings",
            lambda: _core(config, start_date=start_date, end_date=end_date),
            config=config,
            target_start_date=target_start,
            target_end_date=target_end,
            trigger_source=trigger_source,
        )
    data_status = _record_fetch_run(result, config=config,
                                    trigger_source=trigger_source, started_at=started_at)
    return _local_research_after_success({**result, "data_status": data_status}, config)


def _local_research_after_success(result, config):
    """After original reporting/notifications, derive only indexed local files."""
    summary = result.get("summary", {})
    tickers = list(dict.fromkeys(m.get("ticker") for m in summary.get("filings", []) if m.get("ticker")))
    if not tickers:
        return result
    try:
        from investment_assistant.us_research.service import refresh_local_filings
        research = refresh_local_filings(tickers, config=config)
    except Exception:
        research = {"errors": [{"error": "美股本地原文研究刷新失败；原SEC结果保留"}], "notifications": "disabled"}
    return {**result, "research": research}


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
