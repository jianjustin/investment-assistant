"""Per-ticker collectors shared by the batch and the screen stage.

Each function owns exactly one fetch -> normalize -> store step and its own
transaction (``service._tx``), so every caller keeps its try/except and its
summary writes where they are. Exceptions always propagate unchanged.

The rest of this module is the fetch-run bookkeeping the batch and the manual
fetch feed (v2.3 §6): the per-family Tally, the append-only write, and the
per-family advisory locks.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

from investment_assistant.workbench import bars as bars_module
from investment_assistant.workbench import families
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


# ------------------------------------------------------------- fetch-run bookkeeping

class Tally:
    """Per-target outcome accounting for one family's fetch; ``row`` freezes it into
    a data_fetch_runs row. The last write per target wins; failure reasons are
    sanitised on the way in (redacted, truncated)."""

    def __init__(self, family: str, job: str, targets: Iterable[str] = ()):
        self.family = family
        self.job = job
        self.targets: list[str] = list(targets)
        self.outcomes: dict[str, str | None] = {}   # target -> failure reason; None means ok
        self.detail: dict[str, Any] = {}
        self._skipped: str | None = None

    def add_target(self, target: str) -> None:
        if target not in self.targets:
            self.targets.append(target)

    def ok(self, target: str) -> None:
        self.add_target(target)
        self.outcomes[target] = None

    def fail(self, target: str, reason: str) -> None:
        self.add_target(target)
        self.outcomes[target] = families.sanitize_reason(reason)

    def skip(self, reason: str) -> None:
        self._skipped = families.sanitize_reason(reason)
        self.detail['reason'] = self._skipped

    def row(self, *, trigger: str, run_id: str | None, session: date, started_at: datetime,
            finished_at: datetime, scope: str = 'family', ticker: str | None = None) -> dict[str, Any]:
        ok_count = sum(1 for target in self.targets
                       if target in self.outcomes and self.outcomes[target] is None)
        failures = sorted(({'target': target, 'reason': reason}
                           for target, reason in self.outcomes.items() if reason is not None),
                          key=lambda failure: failure['target'])
        return {'family': self.family, 'job': self.job, 'trigger': trigger, 'run_id': run_id,
                'scope': scope, 'ticker': ticker, 'session': session,
                'status': families.classify(len(self.targets), ok_count, skipped_reason=self._skipped),
                'target_count': len(self.targets), 'ok_count': ok_count,
                'failures': failures, 'detail': self.detail,
                'started_at': started_at, 'finished_at': finished_at}


def write_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Append every row in one transaction. A failure (including migration 024 not
    run) is reported, never raised: ``{'written': n, 'error': None}`` or
    ``{'written': 0, 'error': '...'}`` (design §6.2)."""
    from investment_assistant.workbench import service as service_module

    try:
        with service_module._tx() as conn:
            for row in rows:
                repository.insert_fetch_run(conn, row)
        return {'written': len(rows), 'error': None}
    except Exception as exc:
        return {'written': 0, 'error': families.sanitize_reason(exc)}


def _lock_key(family_id: str) -> str:
    return f'data_family:{family_id}'


def try_family_lock(conn, family_id: str) -> bool:
    """Take the family's session lock without waiting; the caller owns connection and unlock."""
    return bool(conn.execute('SELECT pg_try_advisory_lock(hashtext(%s))',
                             (_lock_key(family_id),)).fetchone()[0])


def unlock_family(conn, family_id: str) -> None:
    conn.execute('SELECT pg_advisory_unlock(hashtext(%s))', (_lock_key(family_id),))


@contextmanager
def family_locks(family_ids: Sequence[str]):
    """Hold every family's session lock on one dedicated connection, taken and released
    in the given order (design §6.4). Session-level, so the locks survive the commit and
    die with the connection; a blocked acquire waits instead of failing."""
    from investment_assistant.workbench import service as service_module

    with service_module.connection() as conn:
        for family_id in family_ids:
            conn.execute('SELECT pg_advisory_lock(hashtext(%s))', (_lock_key(family_id),))
        try:
            yield conn
        finally:
            for family_id in family_ids:
                conn.execute('SELECT pg_advisory_unlock(hashtext(%s))', (_lock_key(family_id),))
