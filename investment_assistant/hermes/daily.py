from __future__ import annotations

import os
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from investment_assistant.config import AssistantConfig

MarketStep = Callable[[AssistantConfig, str], Any]
FilingStep = Callable[[list[str], Any], dict[str, Any]]
BriefStep = Callable[[dict[str, Any]], dict[str, Any]]


def run_daily(
    config: AssistantConfig,
    *,
    market_step: MarketStep | None = None,
    filing_step: FilingStep | None = None,
    brief_step: BriefStep | None = None,
    dry_run: bool = False,
    skip_brief: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or f"hermes-daily-{uuid.uuid4().hex[:12]}"
    market_runner = market_step or (_dry_run_market_step if dry_run else _persist_market_step)
    filing_runner = filing_step or (_dry_run_filings_step if dry_run else _download_filings_step)
    brief_runner = brief_step or _daily_brief_step

    market = market_runner(config, run_id)
    filings = filing_runner(config.watchlist, config.filings)
    context = {"run_id": run_id, "market": _to_plain(market), "filings": filings, "dry_run": dry_run}
    brief = {"skipped": True}
    if not skip_brief:
        brief = brief_runner(context)
    return {"run_id": run_id, "status": "success", "market": context["market"], "filings": filings, "brief": brief}


def _dry_run_market_step(config: AssistantConfig, run_id: str):
    from investment_assistant.market.service import compute_market_signal

    return compute_market_signal(config.market, run_id=run_id)


def _persist_market_step(config: AssistantConfig, run_id: str):
    from investment_assistant.db import connect, upsert_market_signal
    from investment_assistant.market.service import compute_market_signal

    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    signal = compute_market_signal(config.market, run_id=run_id)
    with connect(database_url) as conn:
        upsert_market_signal(conn, signal)
    return signal


def _dry_run_filings_step(watchlist: list[str], filings_config):
    return {"skipped": True, "watchlist": list(watchlist), "output_dir": str(filings_config.output_dir)}


def _download_filings_step(watchlist: list[str], filings_config):
    from investment_assistant.filings.service import download_configured_filings

    return download_configured_filings(watchlist, filings_config)


def _daily_brief_step(context: dict[str, Any]) -> dict[str, Any]:
    from investment_assistant.hermes.assistant import daily_brief

    return daily_brief(context=context)


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        result = asdict(value)
        if "signal_date" in result:
            result["signal_date"] = str(result["signal_date"])
        return result
    return value
