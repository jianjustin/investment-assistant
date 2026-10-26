"""Per-ticker collectors shared by the batch and the screen stage.

Each function owns exactly one fetch -> normalize -> store step and its own
transaction (``service._tx``), so every caller keeps its try/except and its
summary writes where they are. Exceptions always propagate unchanged.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from investment_assistant.workbench import bars as bars_module
from investment_assistant.workbench import macro as macro_module
from investment_assistant.workbench import news as news_module
from investment_assistant.workbench import repository
from investment_assistant.workbench import universe as universe_module


def bars_one(ticker: str, *, session: date, now: datetime, deps: Any, lookback_days: int) -> dict:
    """One ticker's daily bars, stored in their own transaction.

    Returns ``{'counts': store_bars result, 'skipped': list[date]}``."""
    from investment_assistant.workbench import service as service_module

    frame = bars_module.fetch_history(ticker, session - timedelta(days=lookback_days), session,
                                      fetcher=deps.bar_fetcher)
    rows, skipped = bars_module.normalize_history(frame)
    with service_module._tx() as conn:
        counts = repository.store_bars(conn, ticker, rows, now=now)
    return {'counts': counts, 'skipped': skipped}


def news_one(ticker: str, *, now: datetime, deps: Any) -> dict:
    """One ticker's yfinance news, stored in its own transaction."""
    from investment_assistant.workbench import service as service_module

    raw = news_module.fetch_yfinance(ticker, fetcher=deps.news_fetcher)
    items, bad = news_module.normalize_yfinance(raw, ticker=ticker)
    with service_module._tx() as conn:
        return {**repository.store_news(conn, [(i, [ticker]) for i in items], now=now),
                'fetched': len(raw), 'skipped': bad}


def sec_listing(tickers: list[str], *, session: date, now: datetime, deps: Any) -> dict:
    """SEC 8-K listings over the filing lookback, stored as news plus acceptance fill."""
    from investment_assistant.workbench import service as service_module

    source = deps.filing_source
    if source is None:
        from investment_assistant.filings.monitor_source import EdgarSource
        source = EdgarSource(service_module.SEC_EVIDENCE_DIR)
    metas = source.discover(tickers,
                            (session - timedelta(days=service_module.FILING_LOOKBACK_DAYS)).isoformat(),
                            session.isoformat())
    with service_module._tx() as conn:
        return {**repository.store_news(conn, news_module.filing_news(metas), now=now),
                'acceptance_filled': repository.fill_filing_acceptance(conn, metas)}


def fred_series(series_id: str, *, session: date, now: datetime, deps: Any,
                api_key: str | None) -> dict | str:
    """One FRED series: ``'not_configured'`` without a key (no request, no rows),
    otherwise the stored observations."""
    from investment_assistant.workbench import service as service_module

    if not api_key:
        return 'not_configured'
    rows = macro_module.fetch_series(
        series_id, start=session - timedelta(days=macro_module.MACRO_LOOKBACK_DAYS), end=session,
        api_key=api_key, fetcher=deps.macro_fetcher)
    with service_module._tx() as conn:
        return repository.store_macro(conn, series_id, rows, now=now)


def load_universe(deps: Any):
    if deps.universe is not None:
        return deps.universe
    if deps.universe_loader is not None:
        return deps.universe_loader()
    return universe_module.load()
