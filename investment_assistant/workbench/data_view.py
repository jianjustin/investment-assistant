"""Use cases behind the Data menu (design 2026-10-26 §7): the manual single-family fetch.

start_fetch is the route's entry: validate, refuse when migration 024 has not run,
probe the family's advisory lock (409 when held) and submit the background job.
run_fetch is that job: hold the lock (universe only reads a file and takes none),
run the shared collectors over the family's targets, and append exactly one
data_fetch_runs row — no rules, plans, candidates, pool changes, pushes or
job_reports. The read half of the menu lives here too, in later tasks.
"""
from __future__ import annotations

import os
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Any, Callable

from investment_assistant.data import identity
from investment_assistant.tasks import runner
from investment_assistant.workbench import bars as bars_module
from investment_assistant.workbench import collect, families, repository, service
from investment_assistant.workbench import macro as macro_module
from investment_assistant.workbench import universe as universe_module


class FetchBusy(RuntimeError):
    """The family is being collected right now (the route maps this to 409)."""


def _now() -> datetime:
    return datetime.now(UTC)


def validate_fetch(family_id: str, ticker: str | None) -> tuple[str, str | None]:
    """(family_id, normalized ticker) or the route's error: unknown family LookupError;
    derived family / ticker on a non-per-ticker family / invalid ticker ValueError."""
    family = families.get(family_id)
    if family.kind == 'derived':
        raise ValueError('派生族，请拉取日线')
    if ticker is not None and not family.per_ticker:
        raise ValueError('该族不支持单只拉取')
    if ticker is not None:
        ticker = ticker.strip().upper()
        try:
            identity.stock_id(ticker)
        except ValueError:
            raise ValueError(f'非法 ticker：{ticker}') from None
    return family_id, ticker


def start_fetch(family_id: str, ticker: str | None, *, now_fn: Callable[[], datetime] | None = None,
                deps: service.Deps | None = None) -> dict[str, Any]:
    """Submit one family fetch in the background and return {'run_id', 'status': 'pending'}.

    The lock is only probed here, then released: the background task takes it for
    real, so a batch starting in between ends as {'status': 'busy'} instead of two
    writers racing on the data tables (§6.4)."""
    family_id, ticker = validate_fetch(family_id, ticker)
    now_fn = now_fn or _now
    with service.connection() as conn:
        if not repository.fetch_runs_ready(conn):
            raise service.Unavailable('需执行迁移 024')
        if family_id != 'universe':   # universe reads a file only; no lock to probe
            if not collect.try_family_lock(conn, family_id):
                raise FetchBusy('该族正在采集')
            collect.unlock_family(conn, family_id)

    def job(run_id: str) -> dict[str, Any]:
        return run_fetch(family_id, ticker, run_id=run_id, now=now_fn(), deps=deps)

    run_id = runner.submit(f'data:{family_id}', job, with_run_id=True)
    return {'run_id': run_id, 'status': 'pending'}


def run_fetch(family_id: str, ticker: str | None, *, run_id: str | None, now: datetime,
              deps: service.Deps | None = None) -> dict[str, Any]:
    """The background body: hold the family lock, collect, append one manual_family row.

    Validated again so direct callers cannot bypass start_fetch's checks. The lock
    is held over the whole collection on a dedicated connection; without it the
    fetch reports busy and writes nothing. Per-target failures land in the row,
    never abort the family."""
    family_id, ticker = validate_fetch(family_id, ticker)
    deps = deps or service.Deps()
    session = bars_module.latest_closed_session(now)
    with ExitStack() as stack:
        if family_id != 'universe':
            lock_conn = stack.enter_context(service.connection())
            if not collect.try_family_lock(lock_conn, family_id):
                return {'status': 'busy'}
            stack.callback(collect.unlock_family, lock_conn, family_id)
        else:
            lock_conn = None
        tally = _collect_family(family_id, ticker, session=session, now=now, deps=deps,
                                conn=lock_conn)
    row = tally.row(trigger='manual_family', run_id=run_id, session=session, started_at=now,
                    finished_at=now, scope='ticker' if ticker is not None else 'family',
                    ticker=ticker)
    return {'status': row['status'], 'row': row, 'data_status': collect.write_runs([row])}


def _collect_family(family_id: str, ticker: str | None, *, session, now: datetime,
                    deps: service.Deps, conn) -> collect.Tally:
    """One family's shared collectors into its Tally; targets = ticker or families.targets."""
    if family_id == 'fred':
        return _collect_fred(session=session, now=now, deps=deps)
    if family_id == 'universe':
        return _reload_universe(session=session, deps=deps)
    targets = [ticker] if ticker is not None else list(families.targets(conn, family_id)[0])
    if family_id == 'sec_filings':
        tally = collect.Tally('sec_filings', 'workbench', targets)
        try:
            collect.sec_listing(targets, session=session, now=now, deps=deps)
            for target in targets:
                tally.ok(target)
        except service.Unavailable:
            raise
        except Exception as exc:   # one listing call covers every target (§6.2 convention)
            tally.fail('*', exc)
        return tally
    tally = collect.Tally(family_id, 'workbench')
    for target in targets:
        try:
            if family_id == 'bars':
                collect.bars_one(target, session=session, now=now, deps=deps,
                                 lookback_days=service.HISTORY_DAYS)
            else:
                collect.news_one(target, now=now, deps=deps)
            tally.ok(target)
        except service.Unavailable:
            raise
        except Exception as exc:   # single-ticker failure recorded, never retried
            tally.fail(target, exc)
    return tally


def _collect_fred(*, session, now: datetime, deps: service.Deps) -> collect.Tally:
    api_key = os.environ.get('FRED_API_KEY')
    tally = collect.Tally('fred', 'workbench', macro_module.MACRO_SERIES)
    if not api_key:
        tally.skip('FRED_API_KEY 未配置')
        return tally
    for series_id in macro_module.MACRO_SERIES:
        try:
            collect.fred_series(series_id, session=session, now=now, deps=deps, api_key=api_key)
            tally.ok(series_id)
        except service.Unavailable:
            raise
        except Exception as exc:
            tally.fail(series_id, exc)
    return tally


def _reload_universe(*, session, deps: service.Deps) -> collect.Tally:
    """Reload and validate the range file (universe.load checks it); no network."""
    tally = collect.Tally('universe', 'workbench', ('nasdaq100',))
    try:
        loaded = collect.load_universe(deps)
    except service.Unavailable:
        raise
    except Exception as exc:
        tally.fail('nasdaq100', exc)
        return tally
    tally.ok('nasdaq100')
    tally.detail.update(name=loaded.name, as_of=loaded.as_of, tickers=len(loaded.tickers),
                        stale=universe_module.is_stale(loaded, session))
    return tally
