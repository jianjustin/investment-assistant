"""Next earnings date from the yfinance calendar.

A failed fetch raises so the caller records it in the run report; a missing or
all-past answer is 'unknown', never a fabricated date.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

CalendarFetcher = Callable[[str], dict]


def _yfinance_fetcher(ticker: str) -> dict:
    import yfinance as yf

    return yf.Ticker(ticker).calendar


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, 'date') and callable(value.date):  # pandas.Timestamp
        try:
            return value.date()
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def fetch_next(ticker: str, *, fetcher: CalendarFetcher | None = None, today: date) -> dict:
    """Earliest earnings date on or after today; unknown when absent or all past."""
    calendar = (fetcher or _yfinance_fetcher)(ticker.upper())
    raw = calendar.get('Earnings Date') if isinstance(calendar, dict) else None
    if raw is None:
        raw = []
    elif not isinstance(raw, list):
        raw = [raw]
    upcoming = sorted(d for value in raw if (d := _as_date(value)) is not None and d >= today)
    if not upcoming:
        return {'status': 'unknown', 'earnings_date': None}
    return {'status': 'known', 'earnings_date': upcoming[0]}
