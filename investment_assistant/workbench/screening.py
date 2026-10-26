"""The screen stage of the daily batch: collect universe bars, run screen-1, persist and pick.

Owns its transactions, like every other stage of ``run_batch``. On failure
(unreadable universe, missing benchmark) the members stay with the locked and
retention-window tickers, no new picks, and an error row lands in screen_runs.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import collect
from investment_assistant.workbench import earnings as earnings_module
from investment_assistant.workbench import pool as pool_module
from investment_assistant.workbench import repository, screen
from investment_assistant.workbench import universe as universe_module

NY = ZoneInfo('America/New_York')
OVER_BUDGET_S = 600
COLLECT_LOOKBACK_DAYS = 400


def _collect(conn_factory, *, session: date, now: datetime, targets: list[str],
             deps: Any) -> tuple[set[str], list[str], dict[str, str]]:
    """Collect daily bars and earnings for range tickers outside the manual pool.

    Bar failures are skips, never filters: they surface in the batch-level
    summary['sources']['bars'] and never count as illiquid or no-setup. Earnings
    failures leave the date unknown, which screen-1 only notes."""
    fetched: set[str] = set()
    failures: list[str] = []
    reasons: dict[str, str] = {}
    for ticker in targets:
        try:
            collect.bars_one(ticker, session=session, now=now, deps=deps,
                             lookback_days=COLLECT_LOOKBACK_DAYS)
            fetched.add(ticker)
        except Exception as exc:
            failures.append(ticker)
            reasons[ticker] = str(exc)
            continue
        try:
            row = earnings_module.fetch_next(ticker, fetcher=deps.earnings_fetcher,
                                             today=now.astimezone(NY).date())
            with conn_factory() as conn:
                repository.store_earnings(conn, ticker, row, now=now)
        except Exception:
            pass  # the next earnings date stays unknown; screen-1 notes it, never excludes
    return fetched, failures, reasons


def _pick_members(conn, *, session: date, now: datetime, manual: pool_module.Pool,
                  selected_today: list[str]) -> tuple[tuple[str, ...], list[str], list[str]]:
    """Members by spec §6.2 plus the hard pool cap: `100 - manual` outranks even locked
    picks, so a full manual pool can never make with_screen raise and kill the batch.

    A lock (valid plan or open position) only keeps tickers that came from the screen;
    off-pool holdings and plans of never-screened tickers do not become screen members."""
    recent = repository.screen_selected_since(
        conn, add_trading_days(session, -(screen.RETENTION_SESSIONS - 1)),
        add_trading_days(session, -1))
    screened = repository.screen_lockable_tickers(conn) | set(recent) | set(selected_today)
    locked = repository.locked_screen_tickers(conn, session, cutoff_at=now) & screened
    hard_cap = pool_module.MAX_POOL - len(manual.tickers)
    picked = screen.members(selected_today=selected_today, recent=recent, locked=locked,
                            manual=set(manual.tickers), cap=min(screen.MAX_MEMBERS, hard_cap))
    members, evicted, flags = picked['members'], list(picked['evicted']), list(picked['flags'])
    if len(members) > hard_cap > 0:   # locked picks beyond the pool cap: cap wins, flag it
        flags.append('screen_locked_over_pool_cap')
        evicted = list(members[hard_cap:]) + evicted
        members = members[:hard_cap]
    return members, evicted, flags


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
        """Carry the locked and retention-window members, nothing new. A loaded universe
        still goes back for the regime breadth: only an unreadable one falls back."""
        summary['status'] = 'error'
        summary['error'] = error
        _stamp(summary, clock)
        try:
            with conn_factory() as conn:
                members, _, member_flags = _pick_members(
                    conn, session=session, now=now, manual=manual, selected_today=[])
                summary['flags'].extend(member_flags)
        except Exception:
            members = ()
        summary['members'] = list(members)
        _persist(conn_factory, session=session, now=now, run_id=run_id, universe_=universe_,
                 status='error', summary=summary, results=[])
        return {'status': 'error', 'members': members, 'fetched': fetched, 'universe': universe_,
                'fetch_failures': [], 'fetch_reasons': {}, 'summary': summary}

    try:
        universe_ = collect.load_universe(deps)
        if universe_module.is_stale(universe_, session):
            summary['flags'].append('universe_stale')
        targets = [t for t in universe_.tickers
                   if t not in manual.tickers and t != screen.BENCHMARK]
        fetched, fetch_failures, fetch_reasons = _collect(conn_factory, session=session, now=now,
                                                          targets=targets, deps=deps)
        with conn_factory() as conn:
            bars_by_ticker = {t: repository.read_bars(conn, t, session, cutoff_at=now, limit=300)
                              for t in targets}
            earnings_by_ticker = {t: repository.latest_earnings(conn, t, cutoff_at=now) for t in targets}
            benchmark_bars = repository.read_bars(conn, screen.BENCHMARK, session,
                                                  cutoff_at=now, limit=300)
            previous = {t for t, row in repository.pool_latest(conn).items()
                        if row.get('source') == 'screen' and row['tier'] != 'removed'}
        out = screen.evaluate(session=session, bars_by_ticker=bars_by_ticker,
                              benchmark_bars=benchmark_bars, earnings_by_ticker=earnings_by_ticker)
        summary['counts'] = out['counts']
        summary['skips'].update(out['skips'])
        summary['selected'] = [r['ticker'] for r in sorted(
            (r for r in out['results'] if r['selected']), key=lambda r: r['rank'])]
        with conn_factory() as conn:
            members, evicted, member_flags = _pick_members(
                conn, session=session, now=now, manual=manual, selected_today=summary['selected'])
        summary['members'] = list(members)
        summary['evicted'] = evicted
        summary['flags'].extend(member_flags)
        summary['removed'] = sorted(previous - set(members))
        _stamp(summary, clock)
        _persist(conn_factory, session=session, now=now, run_id=run_id, universe_=universe_,
                 status='success', summary=summary, results=out['results'])
        return {'status': 'success', 'members': members, 'fetched': fetched,
                'universe': universe_, 'fetch_failures': fetch_failures,
                'fetch_reasons': fetch_reasons, 'summary': summary}
    except universe_module.UniverseError as exc:
        return fail(f'universe: {exc}')
    except screen.BenchmarkMissing:
        return fail('benchmark_missing')


def screen_ref(conn, ticker: str, session: date, *, cutoff_at: datetime | None = None) -> dict[str, Any] | None:
    """The ticker's newest screen pick at or before the session, for plan_context.

    cutoff_at defaults to None so the batch's own rule-plan stage can read the run
    the screen stage wrote in the same pass (spec §7.3)."""
    return repository.latest_screen_pick(conn, ticker, session, cutoff_at=cutoff_at)


def _plan_view(plan: dict[str, Any]) -> dict[str, Any]:
    sizing = plan.get('sizing') or {}
    return {'entry_low': plan['entry_low'], 'entry_high': plan['entry_high'],
            'stop': plan['stop'], 'target1': plan['target1'],
            'shares': sizing.get('shares'), 'sizing_status': sizing.get('status')}


def report(conn, session: date, *, now: datetime, full: bool = False) -> dict[str, Any] | None:
    """The screen report of the newest run for one session; None when there is no run."""
    from investment_assistant.workbench import synthesis

    run = repository.latest_screen_run(conn, session=session)
    if run is None:
        return None
    stored = repository.screen_results(conn, run['id'])
    summary = run['summary'] or {}
    flags = summary.get('flags') or []
    triggers: list[dict[str, Any]] = []
    setups: list[dict[str, Any]] = []
    for row in stored:
        if row['group'] == 'trigger':
            plan = repository.rule_plan(conn, row['ticker'], session)
            review, plan_out, reasons = 'watch', None, []
            if plan is not None:
                plan_out = _plan_view(plan)
                reasons = plan.get('invalid_reasons') or []
                review = 'plan' if plan['status'] == 'ok' else 'invalid'
            else:
                group = repository.unit_candidates(conn, row['ticker'], session)
                unit = synthesis.synthesize(row['ticker'], session, group, holding=False,
                                            now=now) if group else None
                if unit is not None and ('conflict' in unit['labels'] or 'avoid' in unit['labels']):
                    review = 'conflict'
            triggers.append({'ticker': row['ticker'], 'rule_ids': row['trigger_rules'],
                             'rs': row['rs'], 'review': review, 'plan': plan_out,
                             'invalid_reasons': reasons})
        elif row['group'] == 'setup':
            setups.append({'ticker': row['ticker'], 'rs': row['rs'], 'atr_pct': row['atr_pct'],
                           'rank': row['rank']})
    manual = sum(1 for row in repository.pool_latest(conn).values()
                 if row.get('source', 'watchlist') == 'watchlist' and row['tier'] != 'removed')
    out: dict[str, Any] = {
        'session': session.isoformat(), 'calc_version': run['calc_version'],
        'status': run['status'], 'error': summary.get('error'),
        'universe': {'name': run['universe_name'],
                     'as_of': run['universe_as_of'].isoformat()
                     if hasattr(run['universe_as_of'], 'isoformat') else run['universe_as_of'],
                     'stale': 'universe_stale' in flags},
        'counts': summary.get('counts') or {},
        'selected': summary.get('selected') or [],
        'members': len(summary.get('members') or []),
        'cap': min(screen.MAX_MEMBERS, pool_module.MAX_POOL - manual),
        'evicted': summary.get('evicted') or [], 'removed': summary.get('removed') or [],
        'flags': flags, 'triggers': triggers,
        'setups': setups if full else setups[:10],
        'setups_more': 0 if full else max(0, len(setups) - 10),
    }
    if full:
        out['results'] = stored
    return out


def replay(*, sessions: int, now: datetime) -> list[dict[str, Any]]:
    """Read-only replay of the last N closed sessions through screen-1.

    Only bars at or before each day are read; nothing is written, nothing pushed.
    Earnings dates are the currently known ones, not point-in-time."""
    if not 1 <= sessions <= 20:
        raise ValueError(f'sessions must be 1..20, got {sessions}')
    from investment_assistant.db import list_watchlist_items
    from investment_assistant.workbench import bars as bars_module
    from investment_assistant.workbench import service as service_module

    note = '财报日用当前已知值，非当时时点值'
    with service_module.connection() as conn:
        latest = bars_module.latest_closed_session(now)
        days = [add_trading_days(latest, -i) for i in range(sessions)]   # newest first
        universe_ = universe_module.load()
        manual = pool_module.from_watchlist(list_watchlist_items(conn))
        targets = [t for t in universe_.tickers
                   if t not in manual.tickers and t != screen.BENCHMARK]
        reports = []
        for day in days:
            bars_by_ticker = {t: repository.read_bars(conn, t, day, cutoff_at=now, limit=300)
                              for t in targets}
            earnings_by_ticker = {t: repository.latest_earnings(conn, t, cutoff_at=now) for t in targets}
            benchmark_bars = repository.read_bars(conn, screen.BENCHMARK, day, cutoff_at=now, limit=300)
            base = {'session': day.isoformat(), 'note': note}
            try:
                out = screen.evaluate(session=day, bars_by_ticker=bars_by_ticker,
                                      benchmark_bars=benchmark_bars,
                                      earnings_by_ticker=earnings_by_ticker)
            except screen.BenchmarkMissing as exc:
                reports.append({**base, 'error': 'benchmark_missing', 'detail': str(exc),
                                'counts': {}, 'selected': [], 'triggers': [], 'setups': []})
                continue
            reports.append({**base, 'counts': out['counts'],
                            'selected': [r['ticker'] for r in sorted(
                                (r for r in out['results'] if r['selected']),
                                key=lambda r: r['rank'])],
                            'triggers': [{'ticker': r['ticker'], 'rule_ids': r['trigger_rules'],
                                          'rs': r['rs']} for r in out['results'] if r['group'] == 'trigger'],
                            'setups': [{'ticker': r['ticker'], 'rs': r['rs'], 'atr_pct': r['atr_pct'],
                                        'rank': r['rank']} for r in out['results'] if r['group'] == 'setup']})
        return reports
