"""The screen stage of the daily batch: collect universe bars, run screen-1, persist and pick.

Owns its transactions, like every other stage of ``run_batch``. On failure
(unreadable universe, missing benchmark) the members stay with the locked and
retention-window tickers, no new picks, and an error row lands in screen_runs.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import bars as bars_module
from investment_assistant.workbench import earnings as earnings_module
from investment_assistant.workbench import pool as pool_module
from investment_assistant.workbench import repository, screen
from investment_assistant.workbench import universe as universe_module

NY = ZoneInfo('America/New_York')
OVER_BUDGET_S = 600
COLLECT_LOOKBACK_DAYS = 400


def _load_universe(deps: Any):
    if deps.universe is not None:
        return deps.universe
    if deps.universe_loader is not None:
        return deps.universe_loader()
    return universe_module.load()


def _collect(conn_factory, *, session: date, now: datetime, targets: list[str],
             deps: Any) -> tuple[set[str], list[str]]:
    """Collect daily bars and earnings for range tickers outside the manual pool.

    Bar failures are skips, never filters: they surface in the batch-level
    summary['sources']['bars'] and never count as illiquid or no-setup. Earnings
    failures leave the date unknown, which screen-1 only notes."""
    fetched: set[str] = set()
    failures: list[str] = []
    for ticker in targets:
        try:
            frame = bars_module.fetch_history(ticker, session - timedelta(days=COLLECT_LOOKBACK_DAYS),
                                              session, fetcher=deps.bar_fetcher)
            rows, _ = bars_module.normalize_history(frame)
            with conn_factory() as conn:
                repository.store_bars(conn, ticker, rows, now=now)
            fetched.add(ticker)
        except Exception:
            failures.append(ticker)
            continue
        try:
            row = earnings_module.fetch_next(ticker, fetcher=deps.earnings_fetcher,
                                             today=now.astimezone(NY).date())
            with conn_factory() as conn:
                repository.store_earnings(conn, ticker, row, now=now)
        except Exception:
            pass  # the next earnings date stays unknown; screen-1 notes it, never excludes
    return fetched, failures


def _carryover_members(conn, *, session: date, now: datetime,
                       manual: pool_module.Pool) -> tuple[str, ...]:
    """Members for a failed run: the locked and retention-window tickers, nothing new."""
    recent = repository.screen_selected_since(
        conn, add_trading_days(session, -(screen.RETENTION_SESSIONS - 1)),
        add_trading_days(session, -1))
    locked = repository.locked_screen_tickers(conn, session, cutoff_at=now)
    out = screen.members(selected_today=[], recent=recent, locked=locked,
                         manual=set(manual.tickers), cap=screen.MAX_MEMBERS)
    return out['members']


def _stamp(summary: dict[str, Any], clock) -> None:
    summary['timing'] = round(clock() - summary.pop('_started'), 1)
    if summary['timing'] > OVER_BUDGET_S and 'screen_over_budget' not in summary['flags']:
        summary['flags'].append('screen_over_budget')


def _persist(conn_factory, *, session: date, now: datetime, run_id: str | None,
             universe_: universe_module.Universe | None, status: str,
             summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    try:
        with conn_factory() as conn:
            record = repository.insert_screen_run(
                conn,
                {'session': session, 'calc_version': screen.SCREEN_VERSION,
                 'universe_name': universe_.name if universe_ else 'unknown',
                 'universe_as_of': universe_.as_of if universe_ else session,
                 'cutoff_at': now, 'status': status, 'summary': summary, 'run_id': run_id},
                results)
        summary['screen_run_id'] = record['id']
    except Exception:
        pass  # a failed bookkeeping write must not take the batch down with it


def run_stage(*, session: date, now: datetime, manual: pool_module.Pool, held: list[str], deps: Any,
              run_id: str | None) -> dict[str, Any]:
    """Run screen-1 for the session. Returns members, fetched tickers, the universe and summary['screen']."""
    from investment_assistant.workbench import service as service_module

    conn_factory = service_module.connection
    clock = deps.clock or time.monotonic
    summary: dict[str, Any] = {'_started': clock(), 'status': 'success', 'run_id': run_id,
                               'screen_run_id': None, 'selected': [], 'members': [],
                               'counts': {}, 'skips': {}, 'evicted': [], 'removed': [],
                               'flags': [], 'error': None, 'timing': 0.0}
    universe_: universe_module.Universe | None = None
    fetched: set[str] = set()

    def fail(error: str) -> dict[str, Any]:
        summary['status'] = 'error'
        summary['error'] = error
        _stamp(summary, clock)
        try:
            with conn_factory() as conn:
                members = _carryover_members(conn, session=session, now=now, manual=manual)
        except Exception:
            members = ()
        summary['members'] = list(members)
        _persist(conn_factory, session=session, now=now, run_id=run_id, universe_=universe_,
                 status='error', summary=summary, results=[])
        return {'status': 'error', 'members': members, 'fetched': fetched, 'universe': None,
                'fetch_failures': [], 'summary': summary}

    try:
        universe_ = _load_universe(deps)
        if universe_module.is_stale(universe_, session):
            summary['flags'].append('universe_stale')
        targets = [t for t in universe_.tickers
                   if t not in manual.tickers and t != screen.BENCHMARK]
        fetched, fetch_failures = _collect(conn_factory, session=session, now=now, targets=targets,
                                          deps=deps)
        with conn_factory() as conn:
            bars_by_ticker = {t: repository.read_bars(conn, t, session, cutoff_at=now, limit=300)
                              for t in targets}
            earnings_by_ticker = {t: repository.latest_earnings(conn, t, cutoff_at=now) for t in targets}
            benchmark_bars = repository.read_bars(conn, screen.BENCHMARK, session,
                                                  cutoff_at=now, limit=300)
            recent = repository.screen_selected_since(
                conn, add_trading_days(session, -(screen.RETENTION_SESSIONS - 1)),
                add_trading_days(session, -1))
            locked = repository.locked_screen_tickers(conn, session, cutoff_at=now)
            previous = {t for t, row in repository.pool_latest(conn).items()
                        if row.get('source') == 'screen' and row['tier'] != 'removed'}
        out = screen.evaluate(session=session, bars_by_ticker=bars_by_ticker,
                              benchmark_bars=benchmark_bars, earnings_by_ticker=earnings_by_ticker)
        summary['counts'] = out['counts']
        summary['skips'].update(out['skips'])
        summary['selected'] = [r['ticker'] for r in sorted(
            (r for r in out['results'] if r['selected']), key=lambda r: r['rank'])]
        picked = screen.members(selected_today=summary['selected'], recent=recent, locked=locked,
                                manual=set(manual.tickers),
                                cap=min(screen.MAX_MEMBERS,
                                        pool_module.MAX_POOL - len(manual.tickers)))
        members = picked['members']
        summary['members'] = list(members)
        summary['evicted'] = picked['evicted']
        summary['flags'].extend(picked['flags'])
        summary['removed'] = sorted(previous - set(members))
        _stamp(summary, clock)
        _persist(conn_factory, session=session, now=now, run_id=run_id, universe_=universe_,
                 status='success', summary=summary, results=out['results'])
        return {'status': 'success', 'members': members, 'fetched': fetched,
                'universe': universe_, 'fetch_failures': fetch_failures, 'summary': summary}
    except universe_module.UniverseError as exc:
        return fail(f'universe: {exc}')
    except screen.BenchmarkMissing:
        return fail('benchmark_missing')


def screen_ref(conn, ticker: str, session: date, *, cutoff_at: datetime | None = None) -> dict[str, Any] | None:
    """The ticker's newest screen pick at or before the session, for plan_context.

    cutoff_at defaults to None so the batch's own rule-plan stage can read the run
    the screen stage wrote in the same pass (spec §7.3)."""
    return repository.latest_screen_pick(conn, ticker, session, cutoff_at=cutoff_at)
