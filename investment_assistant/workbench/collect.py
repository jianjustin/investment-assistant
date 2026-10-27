"""Per-ticker collectors shared by the batch and the screen stage.

Each function owns exactly one fetch -> normalize -> store step and its own
transaction (``service._tx``), so every caller keeps its try/except and its
summary writes where they are. Exceptions always propagate unchanged.

The rest of this module is the fetch-run bookkeeping the batch and the manual
fetch feed (v2.3 §6): the per-family Tally, the append-only write, and the
per-family advisory locks.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
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

def wall_clock() -> datetime:
    """Real wall time for data_fetch_runs timestamps; injected in tests (I07)."""
    return datetime.now(UTC)


class Tally:
    """Per-target outcome accounting for one family's fetch; ``row`` freezes it into
    a data_fetch_runs row. The last write per target wins; failure reasons are
    sanitised on the way in (redacted, truncated).

    ``'*'`` is the whole-call failure sentinel, never a target: it does not enter
    ``targets`` or the denominator. The denominator is the real target set —
    frozen upfront with ``set_targets`` (what the call was about to collect) or
    built per target by ``ok``/``fail``. A call failure with zero targets is
    ``failed``, never a 0==0 ``success``."""

    def __init__(self, family: str, job: str, targets: Iterable[str] = ()):
        self.family = family
        self.job = job
        self.targets: list[str] = []
        self.outcomes: dict[str, str | None] = {}   # target -> failure reason; None means ok
        self.detail: dict[str, Any] = {}
        self._skipped: str | None = None
        self._call_failure: str | None = None
        self.set_targets(targets)

    def set_targets(self, targets: Iterable[str]) -> None:
        """Freeze the call's real target set (the denominator) before collecting."""
        for target in targets:
            self.add_target(target)

    def add_target(self, target: str) -> None:
        if target != '*' and target not in self.targets:
            self.targets.append(target)

    def ok(self, target: str) -> None:
        self.add_target(target)
        self.outcomes[target] = None

    def fail(self, target: str, reason: str) -> None:
        if target == '*':
            self._call_failure = families.sanitize_reason(reason)
            return
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
        detail = dict(self.detail)
        if self._call_failure is not None:
            failures.append({'target': '*', 'reason': self._call_failure})
            # I05: a family-scoped '*' failure applies to this call's own targets only.
            detail['failed_targets'] = sorted(self.targets)
        status = ('skipped' if self._skipped else
                  'failed' if self._call_failure is not None and ok_count == 0 else
                  families.classify(len(self.targets), ok_count))
        return {'family': self.family, 'job': self.job, 'trigger': trigger, 'run_id': run_id,
                'scope': scope, 'ticker': ticker, 'session': session,
                'status': status,
                'target_count': len(self.targets), 'ok_count': ok_count,
                'failures': failures, 'detail': detail,
                'started_at': started_at, 'finished_at': finished_at}


def write_runs_with_ids(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[int]]:
    """Append every row in one transaction; also return the inserted ids.

    The first element is exactly ``write_runs``' return value, the second the
    inserted rows' ids in order (``[]`` when nothing was written). A failure
    (including migration 024 not run) is reported, never raised (design §6.2)."""
    from investment_assistant.workbench import service as service_module

    try:
        with service_module._tx() as conn:
            ids = [repository.insert_fetch_run(conn, row)['id'] for row in rows]
        return {'written': len(rows), 'error': None}, ids
    except Exception as exc:
        return {'written': 0, 'error': families.sanitize_reason(exc)}, []


def write_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Append every row in one transaction; see ``write_runs_with_ids``."""
    return write_runs_with_ids(rows)[0]


def _lock_key(family_id: str) -> str:
    return f'data_family:{family_id}'


def try_family_lock(conn, family_id: str) -> bool:
    """Take the family's session lock without waiting; the caller owns connection and unlock."""
    return bool(conn.execute('SELECT pg_try_advisory_lock(hashtext(%s))',
                             (_lock_key(family_id),)).fetchone()[0])


def unlock_family(conn, family_id: str) -> bool:
    """Release the family's session lock; False when this session did not hold it."""
    return bool(conn.execute('SELECT pg_advisory_unlock(hashtext(%s))',
                             (_lock_key(family_id),)).fetchone()[0])


def discard_connection(conn) -> None:
    """Physically close a pooled connection; the pool replaces it and every
    session-level advisory lock on it dies with the session (I01)."""
    try:
        conn.close()
    except Exception:
        pass


def _session_ready(conn) -> bool:
    """True when a statement can run on this session: idle, or rolled back out of
    an aborted transaction (session advisory locks survive the rollback)."""
    from psycopg.pq import TransactionStatus

    try:
        if conn.info.transaction_status == TransactionStatus.IDLE:
            return True
        conn.rollback()
        return conn.info.transaction_status == TransactionStatus.IDLE
    except Exception:
        return False


def release_family(conn, family_id: str) -> None:
    """Release one family lock without ever raising. When the session cannot be
    proved clean (aborted beyond rollback, unlock refused) the connection is
    physically discarded instead of returned to the pool: a session still holding
    an advisory lock must never go back (I01)."""
    try:
        if _session_ready(conn) and unlock_family(conn, family_id):
            return
    except Exception:
        pass
    discard_connection(conn)


@contextmanager
def family_locks(family_ids: Sequence[str]):
    """Hold every family's session lock on one dedicated connection, taken and released
    in the given order (design §6.4). Session-level, so the locks survive the commit and
    die with the connection; a blocked acquire waits instead of failing.

    Cleanup is protected from the first acquire on: every lock taken is tracked,
    releasing one never stops the next, an aborted transaction is rolled back
    first, and a session that cannot be proved clean is physically closed so its
    locks die with it — never returned to the pool still holding one (I01)."""
    from investment_assistant.workbench import service as service_module

    with service_module.connection() as conn:
        acquired: list[str] = []
        clean = True
        try:
            for family_id in family_ids:
                try:
                    conn.execute('SELECT pg_advisory_lock(hashtext(%s))', (_lock_key(family_id),))
                except Exception:
                    clean = False   # earlier locks may be held and the session may be aborted
                    raise
                acquired.append(family_id)
            try:
                yield conn
            finally:
                for family_id in reversed(acquired):
                    release_family(conn, family_id)   # never raises; discards when unsure
        finally:
            if not clean:
                discard_connection(conn)
