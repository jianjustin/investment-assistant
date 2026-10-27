"""Transactions and use cases for the US workbench. SQL lives in repository.py."""
from __future__ import annotations

import os
import uuid
import time as _time_module
from contextlib import ExitStack, contextmanager, nullcontext
from decimal import Decimal
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from investment_assistant.data.calendar import is_trading_day
from investment_assistant.db import connect, list_watchlist_items
from investment_assistant.workbench import (account, bars, briefs, chart, collect, earnings, exits, ledger, monthly,
                                               plans, positions, repository, review, rules, synthesis)
from investment_assistant.workbench.agent import graph as agent_graph
from investment_assistant.workbench.agent import model as agent_model
from investment_assistant.workbench.agent import tools as agent_tools
from investment_assistant.workbench import macro as macro_module
from investment_assistant.workbench import pool as pool_module
from investment_assistant.workbench import regime as regime_module
from investment_assistant.workbench import screening
from investment_assistant.workbench import stages as stages_module
from investment_assistant.workbench import universe as universe_module
from investment_assistant.workbench import discipline as _discipline_module
from investment_assistant.workbench import plan_shadow as _plan_shadow_module
from investment_assistant.workbench import review_digest
from investment_assistant.workbench import tracks as _tracks_module

NY = ZoneInfo('America/New_York')
BENCHMARK = 'SPY'
ETF_TICKERS = pool_module.SECTOR_ETFS
BATCH_BUDGET_S = 1800
AGENT_DEADLINE_S = 1500     # no new agent unit starts after this many seconds since batch start (§8.1)
AGENT_MAX_ATTEMPTS = 3      # a failed unit runs at most this many times per batch re-run cycle
HISTORY_DAYS = 420          # calendar days fetched; covers MA200 plus look-backs
FILING_LOOKBACK_DAYS = 10
NEWS_LOOKBACK_DAYS = 7
OPEN_UNIT_DAYS = 14
SEC_EVIDENCE_DIR = Path(__file__).resolve().parents[2] / '.local/us-workbench/sec-evidence'


class Unavailable(RuntimeError):
    """Database or schema not ready (HTTP 503). Never shown as an empty result."""


@dataclass
class Deps:
    bar_fetcher: Callable | None = None
    news_fetcher: Callable | None = None
    filing_source: Any = None           # object with discover(tickers, start_iso, end_iso)
    earnings_fetcher: Callable | None = None
    macro_fetcher: Callable | None = None
    clock: Callable[[], float] | None = None
    agent_model: Any = None                 # scripted model in tests; built from settings when None
    agent_checkpointer: Callable[[], Any] | None = None
    agent_settings: Any = None              # AgentSettings; settings_from_env() when None
    universe: Any = None                    # screening universe; universe.load() when both are None
    universe_loader: Callable[[], Any] | None = None


def connection():
    url = os.environ.get('INVESTMENT_ASSISTANT_DATABASE_URL')
    if not url:
        raise Unavailable('数据库未配置')
    return connect(url)


@contextmanager
def _tx():
    import psycopg

    try:
        with connection() as conn:
            missing = repository.missing_tables(conn)
            if missing:
                raise Unavailable('工作台数据表未就绪（需执行迁移 016–020）：' + ', '.join(missing))
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
    except psycopg.OperationalError:
        raise Unavailable('数据库不可达') from None


def _book(conn, ticker: str) -> dict[str, Any]:
    return positions.build(repository.list_trades(conn, ticker), splits=repository.split_events(conn, ticker))


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=NY)


def _filing_events(conn, ticker: str, session: date, cutoff_at: datetime) -> tuple[list, list]:
    """(rule inputs, filings rows). SEC 8-K listings not in the filings table still count as new filings."""
    since = session - timedelta(days=FILING_LOOKBACK_DAYS)
    rows = repository.read_filings(conn, ticker, since=since, cutoff_at=cutoff_at)
    events = [{**r, 'id': f"filing:{r['id']}"} for r in rows]
    known = {r['accession_number'].replace('-', '') for r in rows}
    for item in repository.read_news(conn, ticker, cutoff_at=cutoff_at, since=_midnight(since)):
        if item['source'] != 'sec_8k' or any(acc in item['url'] for acc in known):
            continue
        seen = item['published_at'] or item['fetched_at']
        events.append({'id': f"news:{item['id']}", 'form': '8-K', 'items': None,
                       'filing_date': seen.astimezone(NY).date(), 'accepted_at': item['published_at']})
    return events, rows


def exposure(conn, session: date, *, cutoff_at: datetime, ticker: str) -> dict[str, Decimal]:
    """Market value of the ticker's open position and of all open positions, at each latest close."""
    from decimal import Decimal

    ticker_value = Decimal('0')
    total_value = Decimal('0')
    for held in sorted({t['ticker'] for t in repository.list_trades(conn) if t['voided_at'] is None}):
        pos = _book(conn, held)['position']
        if pos is None:
            continue
        latest = repository.read_bars(conn, held, session, cutoff_at=cutoff_at, limit=1)
        value = Decimal(str(pos['quantity'])) * Decimal(str(latest[-1]['close'])) if latest else Decimal('0')
        total_value += value
        if held == ticker.upper():
            ticker_value = value
    return {'ticker_value': ticker_value, 'total_value': total_value}


def _position_plan_state(conn, ticker: str, book: dict[str, Any], ticker_bars: list[dict[str, Any]],
                         session: date, *, now: datetime) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(plan, active_stop state) for a held ticker; both None when the position has no plan."""
    position = book['position']
    if position is None:
        return None, None
    trades = repository.list_trades(conn, ticker)
    plans_by_trade = repository.plan_for_buy_trades(conn, [lot['buy_trade_id'] for lot in book['open']])
    plan = exits.position_plan(book['open'], trades, plans_by_trade)
    if plan is None:
        return None, None
    opened = position['opened_at'].astimezone(NY).date()
    bars_since = [b for b in ticker_bars if b['price_date'] >= opened]
    state = exits.active_stop(plan, bars_since, avg_cost=position['avg_cost'],
                              splits=repository.split_events(conn, ticker)) if bars_since else {
        'stop': plan['stop'], 't1_reached': False, 't1_reached_on': None, 'mode': 'initial', 'target1': plan['target1']}
    return plan, state


def plan_context(conn, ticker: str, session: date, *, now: datetime,
                 screen_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """Market context frozen into a plan: tier and source at the signal date, regime, sector,
    earnings, and the screen pick that put the ticker in the pool."""
    entry = repository.pool_entry_at(conn, ticker, session, cutoff_at=now)
    tier = entry['tier'] if entry and entry['tier'] in ('core', 'extended') else 'unknown'
    regime_row = repository.regime_for(conn, session, cutoff_at=now)
    sector = None
    if entry and entry.get('sector_etf'):
        snap_sector = (regime_row or {}).get('sectors', {}).get(entry['sector_etf'])
        sector = ({'etf': entry['sector_etf'], 'rs20': snap_sector['rs20'], 'rs60': snap_sector['rs60'],
                   'state': snap_sector['state']} if snap_sector is not None
                  else {'etf': entry['sector_etf'], 'rs20': None, 'rs60': None, 'state': None})
    earnings = repository.latest_earnings(conn, ticker, cutoff_at=now)
    next_earnings = (earnings['earnings_date'] if earnings and earnings['status'] == 'known'
                     and earnings['earnings_date'] and earnings['earnings_date'] >= session else None)
    return {'context_version': plans.CONTEXT_VERSION, 'pool_tier': tier,
            'source': entry.get('source') if entry else None,
            'screen': screen_ref,
            'regime': ({'id': str(regime_row['id']), 'label': regime_row['label']}
                       if regime_row is not None else None),
            'sector': sector, 'next_earnings': next_earnings}


def _generate_rule_plan(conn, ticker: str, session: date, ticker_bars: list[dict[str, Any]], summary: dict[str, Any],
                        *, now: datetime) -> dict[str, Any] | None:
    """Build and store the rule plan for a fresh buy unit; record skip/conflict in the summary.

    Returns None when the plan was skipped, else ``{'status': inserted|existing|conflict, 'id': plan_id}``
    for the stage accounting (v2.4 §4); the summary is written exactly as before."""
    from investment_assistant.config import load_config

    entry = repository.pool_entry_at(conn, ticker, session, cutoff_at=now)
    screen_ref = (screening.screen_ref(conn, ticker, session)
                  if entry is not None and entry.get('source') == 'screen' else None)
    plan = plans.build_rule_plan(
        ticker=ticker, signal_date=session, bars=ticker_bars,
        earnings_row=repository.latest_earnings(conn, ticker, cutoff_at=now),
        snapshot=repository.snapshot_at(conn, session, cutoff_at=now),
        exposure=exposure(conn, session, cutoff_at=now, ticker=ticker),
        params=load_config().workbench,
        context=plan_context(conn, ticker, session, now=now, screen_ref=screen_ref))
    if 'skip' in plan:
        summary['plans'][ticker] = f"skip: {plan['skip']}"
        return None
    out = repository.store_plan(conn, plan)
    summary['plans'][ticker] = out['status']
    if out['status'] == 'conflict':
        summary['conflicts'].append({'ticker': ticker, 'rule_id': 'rule_plan', 'id': str(out['record']['id'])})
    return {'status': out['status'], 'id': out['record']['id']}


def _note_signals(acc: stages_module.StageAcc, ticker: str, noted: dict[str, Any]) -> None:
    """Fold one committed ticker's candidates, rule skips and unit action into the signals stage."""
    for rule_id, out in noted['candidates']:
        if out['status'] == 'conflict':
            acc.degrade('conflict', f'{ticker}:{rule_id}')
            continue
        acc.output()
        acc.ref('inserted' if out['status'] == 'inserted' else 'existing', out['id'])
    for reason in noted['skips']:
        acc.skip(reason, ticker)
    if 'action' in noted:
        units = acc.detail.setdefault('units', {})
        units[noted['action']] = units.get(noted['action'], 0) + 1


def _note_plan(acc: stages_module.StageAcc, ticker: str, planned: dict[str, Any] | None,
               summary_text: str) -> None:
    """Fold one rule-plan attempt into the plan stage: a skip keeps its reason, a stored plan its id."""
    if planned is None:
        acc.skip(summary_text.removeprefix('skip: '), ticker)
        return
    acc.output()
    acc.ref('inserted' if planned['status'] == 'inserted' else 'existing', planned['id'])
    if planned['status'] == 'conflict':
        acc.degrade('conflict', ticker)


def _sync_pool(conn, pool_: pool_module.Pool, session: date, now: datetime) -> list[dict[str, Any]]:
    """Append tier changes against the newest recorded state, effective this session."""
    changes = pool_module.tier_changes(pool_, repository.pool_latest(conn))
    repository.insert_pool_tiers(conn, changes, session=session, now=now)
    return changes


def _unit_is_extended(conn, ticker: str, signal_date: date, *, held: bool, now: datetime) -> bool:
    """Extended-pool unit: the signal-date tier is extended, the ticker is not held, and a screen
    pick with a valid rule plan counts as a main-list unit (spec §7.2)."""
    if held:
        return False
    entry = repository.pool_entry_at(conn, ticker, signal_date, cutoff_at=now)
    if entry is None or entry['tier'] != 'extended':
        return False
    if entry.get('source') == 'screen':
        plan = repository.rule_plan(conn, ticker, signal_date)
        if plan is not None and plan['status'] == 'ok':
            return False
    return True


def _breadth_tickers(manual: pool_module.Pool, universe_: Any) -> tuple[list[str], list[str]]:
    """Breadth sample and notes: the screening universe ∪ the manual pool, deduped.

    A missing universe falls back to the manual pool alone and flags it. """
    if universe_ is not None:
        merged = sorted({*manual.tickers, *universe_.tickers})
        return merged, []
    return sorted(manual.tickers), ['regime_universe_missing']


def run_batch(*, now: datetime, tickers: list[str] | None = None, pool: pool_module.Pool | None = None,
              deps: Deps | None = None, skip_non_trading: bool = False, run_id: str | None = None,
              breadth_tickers: list[str] | None = None,
              record_trigger: str | None = None,
              wall_now: Callable[[], datetime] | None = None,
              stages: stages_module.StageRecorder | None = None) -> dict[str, Any]:
    """Collect -> market context -> rules -> units -> briefs for the latest settled session. Idempotent per session.

    The batch runs over the tiered watch pool read from the watchlist (holdings
    join regardless of tier); explicit tickers build an all-core pool for tests
    and manual overrides.

    ``record_trigger`` set ('scheduled' / 'manual_batch') holds the per-family
    advisory locks for the collection stage and appends one data_fetch_runs row
    per recorded family afterwards; None keeps the batch exactly as before (v2.3 §6.2).
    ``wall_now`` (default real wall clock, I07) timestamps those rows' start and
    finish; ``now`` keeps its old meaning as trading session, data fetched_at and
    every computation cutoff.
    ``stages`` (v2.4 §6.2) is the task layer's stage recorder: accounting next to
    the existing code for collect / screen / regime, never changing the control
    flow; None keeps the batch exactly as before.
    """
    deps = deps or Deps()
    clock = deps.clock or _time_module.monotonic
    ny_date = now.astimezone(NY).date()
    if skip_non_trading and not is_trading_day(ny_date):
        if stages is not None:   # 非交易日：前 6 个阶段整段跳过，push 留给任务层（v2.4 §4）
            stages.skip_many(stages_module.STAGE_IDS[:-1], 'not_trading_day')
        return {'status': 'skipped', 'reason': 'not a trading day in New York', 'ny_date': ny_date.isoformat()}
    session = bars.latest_closed_session(now)
    started = clock()
    # The first transaction only reads the manual pool and holdings: the screen
    # stage runs between them and the merged pool's tier sync.
    with _tx() as conn:
        explicit = pool is not None or tickers is not None
        if pool is None:
            pool = (pool_module.Pool.all_core(tickers) if tickers is not None
                    else pool_module.from_watchlist(list_watchlist_items(conn)))
        watchlist = list(pool.tickers)
        # Holdings join the batch even off the pool: plan stops and earnings reminders need their data.
        held = [t for t in sorted({r['ticker'] for r in repository.list_trades(conn) if r['voided_at'] is None})
                if t not in watchlist]
    summary: dict[str, Any] = {
        'session': session.isoformat(), 'cutoff_at': now.isoformat(), 'tickers': {}, 'benchmark': {},
        'filings': {}, 'earnings': {}, 'plans': {}, 'conflicts': [], 'errors': [], 'briefs': {},
        'screen': None,
        'pool': {'core': len(pool.core), 'extended': len(pool.extended), 'holdings': len(held),
                 'screen': None, 'changes': []},
        'etfs': {}, 'macro': {}, 'regime': None,
        'sources': {'bars': [], 'news': [], 'earnings': [], 'sec': [], 'etf_bars': [], 'fred': [],
                    'regime': [], 'agent': []},
        'timings': {}}

    # v2.3 §6.2 / v2.4 §6.2: per-family outcome accounting, fed next to every collect
    # call. record_trigger holds the locks and writes data_fetch_runs; stages alone
    # still builds the tallies for the collect stage's counts — no locks, no rows;
    # with neither set the path stays exactly as before (no tallies at all).
    tallies = ({'bars': collect.Tally('bars', 'workbench'),
                'news': collect.Tally('news', 'workbench'),
                'sec_filings': collect.Tally('sec_filings', 'workbench'),
                'fred': collect.Tally('fred', 'workbench', macro_module.MACRO_SERIES)}
               if record_trigger is not None or stages is not None else None)
    if tallies is not None and not explicit:   # no screen stage -> no universe row
        tallies['universe'] = collect.Tally('universe', 'workbench', ('nasdaq100',))

    t_collect = clock()
    # I07: the rows' timestamps are real wall clock (injectable), not the batch's
    # cutoff ``now``; captured from the moment the collection stage starts.
    if tallies is not None:
        wall = wall_now or collect.wall_clock
        collect_started_at = wall()
    # v2.4 §4: collect 的窗口从 SPY 采集前开始，包住嵌在其中的 screen，止于 fetch 行落库。
    c_acc = stages.open('collect') if stages is not None else None
    c_started = clock() if c_acc is not None else 0.0
    # v2.3 §6.4: one session advisory lock per fetched family over the whole collection
    # stage, on a dedicated connection, acquired in a fixed order (a manual fetch holds
    # a single lock, so no deadlock); universe only reads a file and takes no lock.
    with ExitStack() as locks:
        if record_trigger is not None:
            locks.enter_context(collect.family_locks(['bars', 'news', 'sec_filings', 'fred']))
        # SPY and the industry ETFs collect bars only, before the screen stage: QQQ is its benchmark.
        for ticker in [BENCHMARK, *ETF_TICKERS]:
            try:
                out = collect.bars_one(ticker, session=session, now=now, deps=deps,
                                       lookback_days=HISTORY_DAYS)
                if tallies is not None:
                    tallies['bars'].ok(ticker)
                if ticker == BENCHMARK:
                    summary['benchmark'] = {'bars': out['counts'],
                                            'skipped_bars': [d.isoformat() for d in out['skipped']],
                                            'news': None, 'candidates': [], 'skips': [], 'error': None}
                else:
                    summary['etfs'][ticker] = f"inserted {out['counts']['inserted']}"
            except Unavailable:
                raise
            except Exception as exc:
                if tallies is not None:
                    tallies['bars'].fail(ticker, exc)
                if ticker == BENCHMARK:
                    summary['benchmark'] = {'bars': None, 'skipped_bars': [], 'news': None, 'candidates': [],
                                            'skips': [], 'error': f'bars: {exc}'}
                    summary['sources']['bars'].append(ticker)
                    summary['errors'].append(f'{ticker} bars: {exc}')
                else:
                    summary['etfs'][ticker] = f'error: {exc}'
                    summary['sources']['etf_bars'].append(ticker)
                    summary['errors'].append(f'{ticker} etf_bars: {exc}')

        # The screen stage: Nasdaq-100 candidates join the extended pool with source 'screen'.
        # Explicit tickers/pool stay a manual override and skip it entirely.
        stage = None
        manual_pool = pool
        if explicit:
            summary['screen'] = {'status': 'skipped', 'reason': 'explicit_pool'}
            if stages is not None:   # 显式池：整阶段跳过（v2.4 §4）
                stages.skip('screen', 'explicit_pool')
        else:
            s_acc = stages.open('screen') if stages is not None else None
            s_started = clock() if s_acc is not None else 0.0
            stage = screening.run_stage(session=session, now=now, manual=pool, held=held,
                                        deps=deps, run_id=run_id)
            if s_acc is not None:
                s_acc.duration_ms += (clock() - s_started) * 1000
                s_acc.input(len(stage['universe'].tickers) if stage['universe'] is not None else 0)
                s_acc.output(len(stage['summary']['selected']))
                if stage['summary']['screen_run_id'] is not None:
                    s_acc.set_ref('screen_run_id', stage['summary']['screen_run_id'])
                error = stage['summary']['error']
                if error is None:
                    stages.finish('screen')
                elif error.startswith('universe:') or error == 'benchmark_missing':
                    # 范围文件加载失败或 QQQ 缺当日数据、沿用成员：降级不是失败（§4）
                    s_acc.degrade('universe_load_failed' if error.startswith('universe:')
                                  else 'benchmark_missing', error)
                    stages.finish('screen')
                else:
                    stages.finish('screen', failed=error)
            summary['screen'] = stage['summary']
            summary['sources']['bars'].extend(stage['fetch_failures'])
            if tallies is not None:
                # Screen-stage fetches count once here: the loop below does not fetch them again.
                for fetched in stage['fetched']:
                    tallies['bars'].ok(fetched)
                for failed, reason in stage['fetch_reasons'].items():
                    tallies['bars'].fail(failed, reason)
                universe_tally = tallies['universe']
                if stage['universe'] is not None:
                    universe_tally.ok('nasdaq100')
                    universe_tally.detail.update(name=stage['universe'].name,
                                                 as_of=stage['universe'].as_of,
                                                 tickers=len(stage['universe'].tickers),
                                                 stale=universe_module.is_stale(stage['universe'], session))
                else:
                    universe_tally.fail('nasdaq100', stage['summary']['error'])
            if stage['status'] == 'error':
                summary['errors'].append(f"screen: {stage['summary']['error']}")
            pool = pool_module.with_screen(pool, stage['members'])
            with _tx() as conn:
                tier_changes = _sync_pool(conn, pool, session, now)
            # A held screen member is in the pool now; run it once, not again as an off-pool holding.
            held = [t for t in held if t not in pool.tickers]
            summary['pool'] = {**summary['pool'], 'extended': len(pool.extended), 'holdings': len(held),
                               'screen': len(stage['members']), 'changes': tier_changes}
        all_tickers = [*pool.tickers, *held]
        if not pool.core:
            summary['errors'].append('core_empty')

        e_ok = e_failed = 0                 # 财报日成败（collect 阶段 detail.earnings，v2.4 §4）
        for ticker in all_tickers:
            entry: dict[str, Any] = {'bars': None, 'skipped_bars': [], 'news': None, 'candidates': [], 'skips': [],
                                     'error': None}
            problems = []
            try:
                if ticker in (stage['fetched'] if stage is not None else ()):
                    entry['bars'] = 'collected_in_screen'   # news and earnings still collect below
                else:
                    out = collect.bars_one(ticker, session=session, now=now, deps=deps,
                                           lookback_days=HISTORY_DAYS)
                    if tallies is not None:
                        tallies['bars'].ok(ticker)
                    entry['bars'] = out['counts']
                    entry['skipped_bars'] = [d.isoformat() for d in out['skipped']]
            except Unavailable:
                raise
            except Exception as exc:
                if tallies is not None:
                    tallies['bars'].fail(ticker, exc)
                problems.append(f'bars: {exc}')
                summary['sources']['bars'].append(ticker)
            try:
                entry['news'] = collect.news_one(ticker, now=now, deps=deps)
                if tallies is not None:
                    tallies['news'].ok(ticker)
            except Unavailable:
                raise
            except Exception as exc:
                if tallies is not None:
                    tallies['news'].fail(ticker, exc)
                problems.append(f'news: {exc}')
                summary['sources']['news'].append(ticker)
            try:
                row = earnings.fetch_next(ticker, fetcher=deps.earnings_fetcher, today=ny_date)
                with _tx() as conn:
                    summary['earnings'][ticker] = repository.store_earnings(conn, ticker, row, now=now)['status']
                if c_acc is not None:
                    e_ok += 1
            except Unavailable:
                raise
            except Exception as exc:  # 采集失败不写库，也不冒充无财报
                summary['earnings'][ticker] = f'error: {exc}'
                summary['errors'].append(f'{ticker} earnings: {exc}')
                summary['sources']['earnings'].append(ticker)
                if c_acc is not None:
                    c_acc.fail(f'earnings:{ticker}', exc)
                    e_failed += 1
            if problems:
                entry['error'] = '; '.join(problems)
                summary['errors'].extend(f'{ticker} {p}' for p in problems)
            summary['tickers'][ticker] = entry

        # Freeze the denominator before the call: one SEC listing covers every
        # ticker (I04); a whole-call failure is the '*' sentinel, not an N+1th target.
        if tallies is not None:
            tallies['sec_filings'].set_targets(all_tickers)
        try:
            summary['filings'] = collect.sec_listing(all_tickers, session=session, now=now, deps=deps)
            if tallies is not None:
                for ticker in all_tickers:
                    tallies['sec_filings'].ok(ticker)
        except Unavailable:
            raise
        except Exception as exc:
            summary['filings'] = {'error': str(exc)}
            summary['errors'].append(f'SEC listings: {exc}')
            summary['sources']['sec'] = ['all']
            if tallies is not None:
                tallies['sec_filings'].fail('*', exc)

        # FRED: no key means not_configured, no request, no rows.
        api_key = os.environ.get('FRED_API_KEY')
        if tallies is not None and not api_key:
            tallies['fred'].skip('FRED_API_KEY 未配置')
        if c_acc is not None and not api_key:
            c_acc.degrade('fred_not_configured', 'FRED_API_KEY 未配置')
        for series_id in macro_module.MACRO_SERIES:
            try:
                summary['macro'][series_id] = collect.fred_series(series_id, session=session, now=now,
                                                                  deps=deps, api_key=api_key)
                if tallies is not None and api_key:
                    tallies['fred'].ok(series_id)
            except Unavailable:
                raise
            except Exception as exc:
                if tallies is not None:
                    tallies['fred'].fail(series_id, exc)
                summary['macro'][series_id] = f'error: {exc}'
                summary['sources']['fred'].append(series_id)
                summary['errors'].append(f'{series_id} fred: {exc}')
        summary['timings']['collect'] = round(clock() - t_collect, 1)

    if tallies is not None:
        collect_finished_at = wall()
        fetch_rows = [tally.row(trigger=record_trigger, run_id=run_id, session=session,
                                started_at=collect_started_at, finished_at=collect_finished_at)
                      for tally in tallies.values()]
        if record_trigger is not None:
            summary['data_status'], fetch_ids = collect.write_runs_with_ids(fetch_rows)
        else:
            fetch_ids = []           # 只记账不落 fetch 行（v2.4 §6.2）
        if c_acc is not None:
            # 计数与失败取自 v2.3 四个 Tally 的冻结行（universe 若有在其后，§4）。
            for row in fetch_rows[:4]:
                c_acc.input(row['target_count'])
                c_acc.output(row['ok_count'])
                for failure in row['failures']:
                    c_acc.fail(f"{row['family']}:{failure['target']}", failure['reason'])
            if fetch_ids:
                c_acc.set_ref('data_fetch_runs', fetch_ids[:4])
            c_acc.detail['earnings'] = {'targets': len(all_tickers), 'ok': e_ok, 'failed': e_failed}
            c_acc.duration_ms += (clock() - c_started) * 1000
            stages.finish('collect')

    # Market context sits between collection and rules; pool bars exclude off-pool holdings.
    t_regime = clock()
    r_acc = stages.open('regime') if stages is not None else None
    try:
        with _tx() as conn:
            if breadth_tickers is not None:
                breadth_sample = list(breadth_tickers)
            elif stage is not None:
                breadth_sample, breadth_notes = _breadth_tickers(manual_pool, stage['universe'])
                summary['errors'].extend(breadth_notes)
            else:
                breadth_sample = watchlist
            pool_bars = {t: b for t in breadth_sample
                         if (b := repository.read_bars(conn, t, session, cutoff_at=now, limit=300))}
            etf_read = {etf: repository.read_bars(conn, etf, session, cutoff_at=now) for etf in ETF_TICKERS}
            spy_read = repository.read_bars(conn, BENCHMARK, session, cutoff_at=now)
            macro_read = {s: repository.read_macro(conn, s, end_date=session, cutoff_at=now)
                          for s in macro_module.MACRO_SERIES}
            macro_status = {s: v if v == 'not_configured' else
                            ('error' if isinstance(v, str) and v.startswith('error:') else 'ok')
                            for s, v in summary['macro'].items()}
            snap = regime_module.snapshot(session=session, pool_bars=pool_bars, etf_bars=etf_read,
                                          spy_bars=spy_read, macro_rows=macro_read, macro_status=macro_status)
            out = repository.store_regime(conn, snap, now=now)
        summary['regime'] = {'status': out['status'], 'label': snap['label']}
        if out['status'] == 'conflict':
            summary['conflicts'].append({'ticker': None, 'rule_id': 'market_regime',
                                         'id': str(out['record']['id'])})
    except Unavailable:
        raise
    except Exception as exc:
        summary['regime'] = f'error: {exc}'
        summary['sources']['regime'] = ['all']
        summary['errors'].append(f'regime: {exc}')
        if stages is not None:   # 区制异常：failed（v2.4 §4）
            stages.finish('regime', failed=str(exc) or type(exc).__name__)
    else:
        if r_acc is not None:
            r_acc.input(len(breadth_sample))
            r_acc.output(1)      # 写入或已存的快照（§4）
            r_acc.set_ref('market_regime_id', out['record']['id'])
            if snap['label'] == 'insufficient':
                r_acc.degrade('label_insufficient', '')      # 广度样本不足
            for series_id, state in macro_status.items():
                if state != 'ok':
                    r_acc.degrade('macro_not_ok', f'{series_id}:{state}')
            if out['status'] == 'conflict':
                r_acc.degrade('conflict', '')
            r_acc.duration_ms += (clock() - t_regime) * 1000
            stages.finish('regime')
    summary['timings']['regime'] = round(clock() - t_regime, 1)

    t_rules = clock()
    sig_acc = stages.open('signals') if stages is not None else None
    plan_acc = stages.open('plan') if stages is not None else None
    for acc_ in (sig_acc, plan_acc):   # 空跑与重跑时两个列表也在（inserted 为 []，v2.4 §4）
        if acc_ is not None:
            acc_.outputs.update({'inserted': [], 'existing': []})
    for ticker in all_tickers:
        entry = summary['tickers'][ticker]
        if sig_acc is not None:
            sig_acc.input()
        phase = 'signals'          # 异常归到出错的那个阶段
        noted: dict[str, Any] = {}  # 本只的记账，事务提交后才并入阶段（回滚的写入不进证据）
        try:
            with _tx() as conn:
                ticker_bars = repository.read_bars(conn, ticker, session, cutoff_at=now)
                events, _ = _filing_events(conn, ticker, session, now)
                book = _book(conn, ticker)
                _, plan_state = _position_plan_state(conn, ticker, book, ticker_bars, session, now=now)
                with (sig_acc.timing() if sig_acc is not None else nullcontext()):
                    result = rules.evaluate(ticker, session, ticker_bars, events, book['position'],
                                            plan_state=plan_state)
                    stored_candidates = []
                    for cand in result['candidates']:
                        out = repository.store_candidate(conn, ticker, session, cand, run_id=run_id)
                        stored_candidates.append((cand.rule_id, out))
                        if out['status'] == 'conflict':
                            summary['conflicts'].append({'ticker': ticker, 'rule_id': cand.rule_id, 'id': str(out['id'])})
                entry['candidates'] = [c.rule_id for c in result['candidates']]
                entry['skips'] = sorted({f'{s.rule_id}:{s.reason}' for s in result['skips']})
                noted['candidates'] = stored_candidates
                noted['skips'] = entry['skips']
                group = repository.unit_candidates(conn, ticker, session)
                unit = synthesis.synthesize(ticker, session, group, holding=book['position'] is not None,
                                            now=now) \
                    if group and repository.decision_head(conn, ticker, session) is None else None
                if unit is not None:
                    noted['action'] = unit['proposed_action']
                if unit is not None and unit['proposed_action'] == 'buy' and 'conflict' not in unit['labels']:
                    phase = 'plan'
                    if plan_acc is not None:
                        plan_acc.input()
                    with (plan_acc.timing() if plan_acc is not None else nullcontext()):
                        noted['plan'] = _generate_rule_plan(conn, ticker, session, ticker_bars, summary, now=now)
                    noted['planned'] = True
                # Briefs come from the agent stage only (P4 §7.3): propose for
                # conflict-free buys, interpret for everything else on the main list.
        except Unavailable:
            raise
        except Exception as exc:
            entry['error'] = '; '.join(filter(None, [entry['error'], f'rules: {exc}']))
            summary['errors'].append(f'{ticker} rules: {exc}')
            if stages is not None:
                (plan_acc if phase == 'plan' else sig_acc).fail(ticker, exc)
        else:
            if stages is not None:
                _note_signals(sig_acc, ticker, noted)
                if noted.get('planned'):
                    _note_plan(plan_acc, ticker, noted['plan'], summary['plans'][ticker])
    if stages is not None:
        stages.finish('signals')
        stages.finish('plan')
    summary['timings']['rules'] = round(clock() - t_rules, 1)
    a_acc = stages.open('agent') if stages is not None else None
    unavailable = _agent_stage(session, now=now, deps=deps, summary=summary, started=started, clock=clock,
                               acc=a_acc)
    if stages is not None:
        if unavailable is not None:    # 不可用压过「空跑成功」：整阶段 skipped（v2.4 §4）
            stages.skip('agent', f'agent_unavailable: {unavailable}')
        else:
            stages.finish('agent')
    summary['timings']['total'] = round(clock() - started, 1)
    if summary['timings']['total'] > BATCH_BUDGET_S:
        summary['errors'].append(f"batch_over_budget: {summary['timings']['total']}")
    return summary


def _holdings(conn, session: date, *, now: datetime) -> list[dict[str, Any]]:
    out = []
    for ticker in sorted({t['ticker'] for t in repository.list_trades(conn) if t['voided_at'] is None}):
        book = _book(conn, ticker)
        position = book['position']
        if position is None:
            continue
        bars_ = repository.read_bars(conn, ticker, session, cutoff_at=now)
        plan, state = _position_plan_state(conn, ticker, book, bars_, session, now=now)
        last_close = bars_[-1]['close'] if bars_ else None
        earnings = repository.latest_earnings(conn, ticker, cutoff_at=now)
        next_earnings = (earnings['earnings_date'] if earnings and earnings['status'] == 'known'
                         and earnings['earnings_date'] and earnings['earnings_date'] >= session else None)
        out.append({
            'ticker': ticker, 'quantity': position['quantity'], 'avg_cost': position['avg_cost'],
            'plan_id': plan['id'] if plan else None,
            'stop': state['stop'] if state else None, 'mode': state['mode'] if state else None,
            't1_reached': state['t1_reached'] if state else False, 'target1': state['target1'] if state else None,
            'last_close': last_close,
            'to_stop_pct': float(last_close / float(state['stop']) - 1) if state and last_close else None,
            'to_target_pct': float(float(state['target1']) / last_close - 1) if state and last_close else None,
            'next_earnings': next_earnings.isoformat() if next_earnings else None,
        })
    return out


def _brief_view(brief: dict[str, Any] | None) -> dict[str, Any] | None:
    if brief is None or brief['status'] != 'error':
        return brief
    # A brief citing unknown sources is never shown; only its failure is.
    return {k: brief[k] for k in ('id', 'status', 'error', 'created_at', 'prompt_version')}


def today(*, now: datetime) -> dict[str, Any]:
    session = bars.latest_closed_session(now)
    with _tx() as conn:
        units = []
        extended_units = []
        for group in repository.open_candidate_groups(conn, since=session - timedelta(days=OPEN_UNIT_DAYS)):
            ticker, signal_date = group['ticker'], group['signal_date']
            book = _book(conn, ticker)
            held = book['position'] is not None
            unit = synthesis.synthesize(ticker, signal_date, group['candidates'], holding=held,
                                        now=now)
            since = signal_date - timedelta(days=NEWS_LOOKBACK_DAYS)
            entry = repository.pool_entry_at(conn, ticker, signal_date, cutoff_at=now)
            unit.update(
                source=entry.get('source') if entry else None,
                candidates=group['candidates'], position=book['position'],
                brief=_brief_view(repository.latest_brief(conn, ticker, signal_date)),
                plan=repository.rule_plan(conn, ticker, signal_date),
                filings=repository.read_filings(conn, ticker, since=since, cutoff_at=now),
                news=repository.read_news(conn, ticker, cutoff_at=now, since=_midnight(since), limit=20),
                agent=_agent_view(repository.latest_agent_run(conn, ticker, signal_date),
                                  repository.agent_plan(conn, ticker, signal_date)))
            # The tier as of the signal date decides the list, not today's tier.
            if _unit_is_extended(conn, ticker, signal_date, held=held, now=now):
                agent_run = repository.latest_agent_run(conn, ticker, signal_date)
                extended_units.append({'ticker': ticker, 'signal_date': signal_date,
                                       'proposed_action': unit['proposed_action'],
                                       'rule_ids': unit['rule_ids'], 'plan': unit['plan'],
                                       'agent_status': _agent_status_line(agent_run)})
            else:
                units.append(unit)
        holdings = _holdings(conn, session, now=now)
        market = repository.latest_regime(conn, on_or_before=session, cutoff_at=now)
        screen_report = screening.report(conn, session, now=now)
    return {'session': session, 'units': units, 'extended_units': extended_units,
            'holdings': holdings, 'market': market, 'screen': screen_report}


def run_backcheck(*, now: datetime, tickers: list[str] | None = None) -> dict[str, Any]:
    """Replay stored data through the current rules; reads only, never collects."""
    from investment_assistant.workbench import backcheck as backcheck_module
    from investment_assistant.workbench import plan_shadow as shadow_module

    with _tx() as conn:
        symbols = (pool_module.Pool.all_core(tickers).tickers if tickers is not None
                   else pool_module.from_watchlist(list_watchlist_items(conn)).tickers)
        spy_bars = repository.read_bars(conn, BENCHMARK, bars.latest_closed_session(now), cutoff_at=now, limit=2000)
        replays = []
        for ticker in symbols:
            ticker_bars = repository.read_bars(conn, ticker, bars.latest_closed_session(now), cutoff_at=now,
                                               limit=2000)
            first_day = ticker_bars[0]['price_date'] if ticker_bars else date(2026, 1, 1)
            replays.append(backcheck_module.replay(
                ticker, ticker_bars, repository.read_filings(conn, ticker, since=first_day, cutoff_at=now),
                spy_bars, splits=repository.split_events(conn, ticker)))
        stats = backcheck_module.summarize(replays)
        params = {'tickers': list(symbols), 'rule_version': rules.RULE_VERSION,
                  'plan_version': plans.PLAN_VERSION, 'shadow_version': shadow_module.SHADOW_VERSION,
                  'bars': 'stored current revisions'}
        return repository.insert_backcheck(conn, backcheck_module.CALC_VERSION, params, stats)


def list_backchecks(limit: int = 10) -> list[dict[str, Any]]:
    with _tx() as conn:
        out = repository.list_backchecks(conn, limit)
    return [{**row, 'id': str(row['id'])} for row in out]


def decide(payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    with _tx() as conn:
        return ledger.record_decision(conn, payload, now=now)


def add_trade(payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    with _tx() as conn:
        return ledger.record_trade(conn, payload, now=now)


def list_trades() -> list[dict[str, Any]]:
    with _tx() as conn:
        return list(reversed(repository.list_trades(conn)))


def void_trade(trade_id: str, reason: Any, *, now: datetime) -> dict[str, Any]:
    with _tx() as conn:
        return ledger.void_trade(conn, trade_id, reason, now=now)


def account_view() -> dict[str, Any]:
    from investment_assistant.config import load_config

    params = load_config().workbench
    with _tx() as conn:
        return {'snapshots': repository.list_snapshots(conn), 'flows': repository.list_flows(conn),
                'params': {'risk_pct': params.risk_pct, 'single_cap': params.single_cap,
                           'total_cap': params.total_cap, 'public_url': params.public_url,
                           'return_tiers': list(params.return_tiers)}}


def add_snapshot(payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    with _tx() as conn:
        return account.record_snapshot(conn, payload, now=now)


def add_flow(payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    with _tx() as conn:
        return account.record_flow(conn, payload, now=now)


def void_flow(flow_id: str, reason: Any, *, now: datetime) -> dict[str, Any]:
    with _tx() as conn:
        return account.void_flow(conn, flow_id, reason, now=now)


def _last_push_failed(conn, session: date) -> bool:
    last = repository.last_push(conn)
    return bool(last and last.get('session') == session.isoformat() and last.get('sent') is False
                and last.get('reason') not in (None, 'already_pushed'))


def push(*, now: datetime, force: bool, summary: dict[str, Any] | None = None, notify_cfg, client=None) -> dict[str, Any]:
    """Send the day's digest; scheduled runs skip when today already pushed successfully."""
    from investment_assistant.config import load_config
    from investment_assistant.notify import notifier, templates
    from investment_assistant.workbench import digest as digest_module

    session = bars.latest_closed_session(now)
    with _tx() as conn:
        if not force:
            last = repository.last_push(conn, session=session)
            if last and last.get('sent') is True:
                return {'session': session.isoformat(), 'sent': False, 'reason': 'already_pushed', 'messages': 0}
        view = today(now=now)
        payload = digest_module.build(
            session=session, units=view['units'], holdings=view.get('holdings', []), summary=summary or {},
            last_push_failed=_last_push_failed(conn, session),
            public_url=load_config().workbench.public_url,
            extended_plans=sum(1 for u in view.get('extended_units', []) if u.get('plan') is not None),
            market=view.get('market'), agent_summary=(summary or {}).get('agent'),
            screen=view.get('screen'))
    out = notifier.send_notifications('workbench', templates.workbench_digest(payload), notify_cfg, client=client)
    return {'session': session.isoformat(), **out}


def push_closed(*, now: datetime, notify_cfg, client=None) -> dict[str, Any]:
    """One line for a New York holiday instead of the digest."""
    from investment_assistant.notify import notifier, templates

    ny_date = now.astimezone(NY).date()
    out = notifier.send_notifications('workbench', templates.workbench_closed(ny_date), notify_cfg, client=client)
    return {'session': ny_date.isoformat(), **out}


def screen_view(*, now: datetime, session: date | None = None, full: bool = False) -> dict[str, Any]:
    """The screen report of one session (default the newest run, spec §9.2); None when no run exists.

    The newest run, not the latest closed session: between the New York close and the
    batch the closed session has no run yet, and the page should keep showing the last one."""
    with _tx() as conn:
        if session is None:
            run = repository.latest_screen_run(conn, session=None)
            if run is None:
                return {'report': None}
            session = run['session']
        return {'report': screening.report(conn, session, now=now, full=full)}


def replay_screen(*, now: datetime, sessions: int) -> dict[str, Any]:
    return {'reports': screening.replay(sessions=sessions, now=now)}


def instrument(ticker: str, *, now: datetime) -> dict[str, Any]:
    ticker = ticker.strip().upper()
    session = bars.latest_closed_session(now)
    with _tx() as conn:
        book = _book(conn, ticker)
        return {
            'ticker': ticker, 'session': session,
            'bars': repository.read_bars(conn, ticker, session, cutoff_at=now, limit=120),
            'chart': chart.build(repository.read_bars(
                conn, ticker, session, cutoff_at=now, limit=chart.READ_LIMIT)),
            'filings': repository.read_filings(conn, ticker, since=session - timedelta(days=180), cutoff_at=now),
            'news': repository.read_news(conn, ticker, cutoff_at=now, since=_midnight(session - timedelta(days=60))),
            'candidates': repository.read_candidates(conn, ticker, since=session - timedelta(days=120)),
            'decisions': repository.decision_heads(conn, ticker=ticker),
            'trades': repository.list_trades(conn, ticker),
            'position': book['position'], 'closed': book['closed'],
        }


def _decided_units(conn, heads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rule_ids = {c['id']: c['rule_id'] for c in repository.candidates_by_ids(
        conn, [cid for h in heads for cid in h['candidate_ids']])}
    return [{**h, 'rule_ids': [rule_ids[c] for c in h['candidate_ids'] if c in rule_ids]} for h in heads]


def _outcomes(conn, units, session: date, now: datetime) -> dict[Any, dict[str, Any]]:
    spy = repository.read_bars(conn, BENCHMARK, session, cutoff_at=now, limit=400)
    cache: dict[str, list] = {}
    out = {}
    for u in units:
        if u['ticker'] not in cache:
            cache[u['ticker']] = repository.read_bars(conn, u['ticker'], session, cutoff_at=now, limit=400)
        out[u['id']] = review.shadow_outcome(u, cache[u['ticker']], spy)
    return out


def shadow(*, now: datetime, since: date | None = None) -> dict[str, Any]:
    session = bars.latest_closed_session(now)
    since = since or session - timedelta(days=90)
    with _tx() as conn:
        units = _decided_units(conn, repository.decision_heads(conn, since=since))
        outcomes = _outcomes(conn, units, session, now)
    return {'session': session, 'since': since, 'calc_version': review.CALC_VERSION,
            'units': [{**u, 'outcome': outcomes[u['id']]} for u in units]}


def plan_shadow(*, now: datetime, since: date | None = None) -> dict[str, Any]:
    """Simulated outcomes for rule and own plans of the last 90 days; nothing frozen until a review."""
    session = bars.latest_closed_session(now)
    since = since or session - timedelta(days=90)
    with _tx() as conn:
        spy = repository.read_bars(conn, BENCHMARK, session, cutoff_at=now, limit=400)
        out = []
        for plan in repository.plans_since(conn, since):
            ticker_bars = repository.read_bars(conn, plan['ticker'], session, cutoff_at=now, limit=400)
            outcome = _plan_shadow_module.simulate(plan, ticker_bars, spy,
                                           splits=repository.split_events(conn, plan['ticker']))
            out.append({**plan, 'outcome': outcome})
    return {'session': session, 'since': since, 'calc_version': _plan_shadow_module.SHADOW_VERSION, 'plans': out}


def discipline(*, now: datetime, since: date | None = None) -> dict[str, Any]:
    """Execution discipline of recorded buys against their confirmed plans."""
    session = bars.latest_closed_session(now)
    since = since or session - timedelta(days=90)
    with _tx() as conn:
        # Buys and stop events share one window, or old buys see no stops and flag false early_takes.
        trades = [t for t in repository.list_trades(conn)
                  if t['voided_at'] is None and t['executed_at'].astimezone(NY).date() >= since]
        decisions_by_id: dict[Any, dict[str, Any]] = {}
        for t in trades:
            if t['decision_id'] and t['decision_id'] not in decisions_by_id:
                d = repository.decision_by_id(conn, t['decision_id'])
                if d is not None:
                    decisions_by_id[t['decision_id']] = d
        plans_by_id = {}
        for d in decisions_by_id.values():
            if d['plan_id'] and d['plan_id'] not in plans_by_id:
                p = repository.plan_by_id(conn, d['plan_id'])
                if p is not None:
                    plans_by_id[d['plan_id']] = p
        tickers = sorted({t['ticker'] for t in trades})
        bars_by_ticker = {tk: repository.read_bars(conn, tk, session, cutoff_at=now, limit=400) for tk in tickers}
        stop_events, segments = [], []
        for tk in tickers:
            stop_events += [c for c in repository.read_candidates(conn, tk, since=since)
                            if c['rule_id'] == 'plan_stop']
            segments += _book(conn, tk)['closed']
        out = _discipline_module.evaluate(trades=trades, decisions_by_id=decisions_by_id, plans_by_id=plans_by_id,
                                  bars_by_ticker=bars_by_ticker, stop_events=stop_events, segments=segments,
                                  session=session)
    return {'session': session, 'since': since, **out}


def trade_review(*, now: datetime) -> dict[str, Any]:
    session = bars.latest_closed_session(now)
    with _tx() as conn:
        spy = repository.read_bars(conn, BENCHMARK, session, cutoff_at=now, limit=400)
        closed, open_ = [], []
        for ticker in sorted({t['ticker'] for t in repository.list_trades(conn)}):
            book = _book(conn, ticker)
            ticker_bars = repository.read_bars(conn, ticker, session, cutoff_at=now, limit=400)
            closed += [{'ticker': ticker, **review.trade_segment_review(s, ticker_bars, spy)} for s in book['closed']]
            if book['position'] and ticker_bars:
                open_.append(review.open_position_review(ticker, book['position'], ticker_bars))
    return {'session': session, 'calc_version': review.CALC_VERSION, 'closed': closed, 'open': open_}


def _week_discipline(conn, session: date, now: datetime) -> dict[str, Any]:
    """Discipline over the same 90-day window the stop events use, in an existing transaction."""
    since = session - timedelta(days=90)
    trades = [t for t in repository.list_trades(conn)
              if t['voided_at'] is None and t['executed_at'].astimezone(NY).date() >= since]
    decisions_by_id = {}
    for t in trades:
        if t['decision_id'] and t['decision_id'] not in decisions_by_id:
            d = repository.decision_by_id(conn, t['decision_id'])
            if d is not None:
                decisions_by_id[t['decision_id']] = d
    plans_by_id = {}
    for d in decisions_by_id.values():
        if d['plan_id'] and d['plan_id'] not in plans_by_id:
            p = repository.plan_by_id(conn, d['plan_id'])
            if p is not None:
                plans_by_id[d['plan_id']] = p
    tickers = sorted({t['ticker'] for t in trades})
    stop_events, segments = [], []
    for tk in tickers:
        stop_events += [c for c in repository.read_candidates(conn, tk, since=since)
                        if c['rule_id'] == 'plan_stop']
        segments += _book(conn, tk)['closed']
    return _discipline_module.evaluate(trades=trades, decisions_by_id=decisions_by_id, plans_by_id=plans_by_id,
                               bars_by_ticker={tk: repository.read_bars(conn, tk, session, cutoff_at=now, limit=400)
                                               for tk in tickers},
                               stop_events=stop_events, segments=segments, session=session)


def _track_rows(conn, since: date, until: date, *, session: date, now: datetime) -> list[dict[str, Any]]:
    """§4.4: one row per unit in the window — rule, agent and actual side by side,
    every id traceable. Bars and books are cached per ticker within the transaction;
    ids and dates are stringified so the rows freeze into JSONB snapshots as-is."""
    rows: list[dict[str, Any]] = []
    spy = repository.read_bars(conn, BENCHMARK, session, cutoff_at=now, limit=400)
    bars_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for unit in repository.track_units(conn, since, until):
        ticker, signal_date = unit['ticker'], unit['signal_date']
        if ticker not in bars_by_ticker:
            bars_by_ticker[ticker] = repository.read_bars(conn, ticker, session, cutoff_at=now, limit=400)
        ticker_bars = bars_by_ticker[ticker]
        splits = repository.split_events(conn, ticker)
        rule = repository.rule_plan(conn, ticker, signal_date)
        agent_plan = repository.agent_plan(conn, ticker, signal_date)
        run = repository.latest_agent_run(conn, ticker, signal_date)
        rule_outcome = (_plan_shadow_module.simulate(rule, ticker_bars, spy, splits=splits)
                        if rule is not None and rule['status'] == 'ok' else None)
        agent_outcome = (_plan_shadow_module.simulate(agent_plan, ticker_bars, spy, splits=splits)
                         if agent_plan is not None and agent_plan['status'] == 'ok' else None)
        rule_track = _tracks_module.plan_track(rule, rule_outcome)
        agent_track = _tracks_module.agent_track(run, agent_plan, agent_outcome)
        decision = repository.decision_head(conn, ticker, signal_date)
        chosen = (repository.plan_by_id(conn, decision['plan_id'])
                  if decision is not None and decision.get('plan_id') else None)
        book = _book(conn, ticker)
        # A buy may link to any decision in the unit's chain: correcting a decision
        # after the fill must not drop the fill from the actual track.
        chain_ids = repository.unit_decision_ids(conn, ticker, signal_date) if decision is not None else set()
        buy_ids = ({t['id'] for t in repository.list_trades(conn, ticker)
                    if t.get('voided_at') is None and t['side'] == 'buy'
                    and t.get('decision_id') in chain_ids})
        actual = _tracks_module.actual_track(
            decision=decision, plan=chosen, buys=[{'id': tid} for tid in sorted(buy_ids, key=str)],
            segments=[s for s in book['closed'] if s['buy_trade_id'] in buy_ids],
            open_lots=[l for l in book['open'] if l['buy_trade_id'] in buy_ids],
            last_close=Decimal(str(ticker_bars[-1]['close'])) if ticker_bars else None,
            splits=splits, session=session,
            unit_valid_until=max((p['valid_until'] for p in (rule, agent_plan, chosen)
                                  if p is not None), default=None))
        def context_of(plan):
            return (plan.get('inputs') or {}).get('context') if plan else None
        pool = review.pool_of(context_of(rule) or context_of(agent_plan),
                              repository.pool_entry_at(conn, ticker, signal_date, cutoff_at=now))
        rows.append({
            'ticker': ticker, 'signal_date': signal_date.isoformat(), 'pool': pool,
            'rule': {**rule_track, 'plan_id': str(rule_track['plan_id']) if rule_track['plan_id'] else None},
            'agent': {**agent_track,
                      'run_id': str(agent_track['run_id']) if agent_track['run_id'] else None,
                      'plan_id': str(agent_track['plan_id']) if agent_track['plan_id'] else None},
            'actual': {**actual,
                       'decision_id': str(actual['decision_id']) if actual['decision_id'] else None,
                       'plan_id': str(actual['plan_id']) if actual['plan_id'] else None,
                       'buy_trade_ids': [str(tid) for tid in actual['buy_trade_ids']]},
        })
    return rows


def tracks(*, now: datetime, since: date | None = None, until: date | None = None) -> dict[str, Any]:
    """§4.5: the live three-track view, defaulting to the last 90 days of signal dates;
    not frozen — weekly and monthly snapshots carry their own copy."""
    session = bars.latest_closed_session(now)
    since = since if since is not None else session - timedelta(days=90)
    until = until if until is not None else session
    with _tx() as conn:
        rows = _track_rows(conn, since, until, session=session, now=now)
    return {'session': session.isoformat(), 'since': since.isoformat(), 'until': until.isoformat(),
            'calc_version': _tracks_module.TRACKS_VERSION, 'units': rows,
            'summary': _tracks_module.summarize(rows)}


def generate_weekly(week_start: date, *, notes: str = '', supersedes_id=None, now: datetime) -> dict[str, Any]:
    if week_start.isoweekday() != 1:
        raise ledger.LedgerError('week_start must be a Monday')
    week_end = week_start + timedelta(days=6)
    session = bars.latest_closed_session(now)
    with _tx() as conn:
        heads = [h for h in repository.decision_heads(conn, since=week_start) if h['signal_date'] <= week_end]
        units = _decided_units(conn, heads)
        outcomes = _outcomes(conn, units, session, now)
        undecided = sum(1 for g in repository.open_candidate_groups(conn, since=week_start)
                        if g['signal_date'] <= week_end)
        spy = repository.read_bars(conn, BENCHMARK, session, cutoff_at=now, limit=400)
        segments = []
        for ticker in sorted({t['ticker'] for t in repository.list_trades(conn)}):
            ticker_bars = repository.read_bars(conn, ticker, session, cutoff_at=now, limit=400)
            segments += [{'ticker': ticker, **review.trade_segment_review(s, ticker_bars, spy)}
                         for s in _book(conn, ticker)['closed']
                         if week_start <= s['closed_at'].astimezone(NY).date() <= week_end]
        spy_bars = repository.read_bars(conn, BENCHMARK, session, cutoff_at=now, limit=400)
        plan_outcomes = []
        for plan in repository.plans_since(conn, week_start):
            if plan['signal_date'] > week_end:
                continue
            ticker_bars = repository.read_bars(conn, plan['ticker'], session, cutoff_at=now, limit=400)
            # Pool of a plan: the frozen context first, else the tier recorded on its signal date.
            plan_outcomes.append({**plan, 'pool': review.pool_of(
                (plan.get('inputs') or {}).get('context'),
                repository.pool_entry_at(conn, plan['ticker'], plan['signal_date'], cutoff_at=now)),
                'rule_ids': [c['rule_id'] for c in repository.unit_candidates(conn, plan['ticker'], plan['signal_date'])
                             if c['action'] == 'buy'],
                'outcome': _plan_shadow_module.simulate(
                    plan, ticker_bars, spy_bars, splits=repository.split_events(conn, plan['ticker']))})
        triggers = []
        for group in repository.open_candidate_groups(conn, since=week_start):
            if group['signal_date'] > week_end:
                continue
            for cand in group['candidates']:
                if cand['action'] != 'buy':
                    continue
                triggers.append({'pool': review.pool_of(
                    None, repository.pool_entry_at(conn, group['ticker'], group['signal_date'], cutoff_at=now)),
                    'rule_id': cand['rule_id']})
        for head in [h for h in heads if h['signal_date'] <= week_end]:
            for cand in repository.unit_candidates(conn, head['ticker'], head['signal_date']):
                if cand['action'] != 'buy':
                    continue
                triggers.append({'pool': review.pool_of(
                    None, repository.pool_entry_at(conn, head['ticker'], head['signal_date'], cutoff_at=now)),
                    'rule_id': cand['rule_id']})
        track_rows = _track_rows(conn, week_start, week_end, session=session, now=now)
        stats = review.weekly_stats(week_start, units, outcomes, repository.list_trades(conn), segments=segments,
                                    undecided=undecided,
                                    entry_opens={k: v.get('entry_price') for k, v in outcomes.items()},
                                    plan_outcomes=plan_outcomes, by_pool=review.pool_summary(triggers, plan_outcomes),
                                    discipline=_week_discipline(conn, session, now),
                                    tracks={'units': track_rows, 'summary': _tracks_module.summarize(track_rows)})
        stats['generated_at'] = now.isoformat()
        return review.save_weekly(conn, week_start, stats, notes=notes, supersedes_id=supersedes_id)


def _prev_month(m: date) -> date:
    return (m - timedelta(days=1)).replace(day=1)


def _spy_return_between(conn, start_day: date, end_day: date, *, now: datetime) -> float | None:
    index = {b['price_date']: b['adj_close'] for b in
             repository.read_bars(conn, BENCHMARK, end_day, cutoff_at=now, limit=400)}
    if start_day not in index or end_day not in index:
        return None
    return float(index[end_day] / index[start_day] - 1)


def generate_monthly(month: date, *, notes: str = '', supersedes_id=None, now: datetime) -> dict[str, Any]:
    """Freeze one month's review; corrections supersede. Missing snapshots show, never fake zeros."""
    from investment_assistant.config import load_config

    if month.day != 1:
        raise ledger.LedgerError('month must be the first day of the month')
    month_end = month.replace(day=[31, 29 if month.year % 4 == 0 and (month.year % 100 != 0 or month.year % 400 == 0)
                                   else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month.month - 1])
    params = load_config().workbench
    with _tx() as conn:
        repository.lock(conn, f'monthly:{month}')
        head = repository.monthly_head(conn, month)
        if (head['id'] if head else None) != supersedes_id:
            raise ledger.Conflict('该月已有更新的月度复盘；请更正最新一条')
        snapshots, flows = repository.list_snapshots(conn), repository.list_flows(conn)

        months = [month]
        for _ in range(2):
            months.insert(0, _prev_month(months[0]))
        per_month, spy_ret = [], None
        for m in months:
            ret = monthly.month_return(m, snapshots, flows)
            if ret['status'] != 'ok':
                per_month.append({'month': m.isoformat(), 'return': None, 'spy_return': None})
                continue
            spy_r = _spy_return_between(conn, ret['start']['as_of'], ret['end']['as_of'], now=now)
            per_month.append({'month': m.isoformat(), 'return': ret['return'], 'spy_return': spy_r})
            if m == month:
                spy_ret = spy_r
        ret = monthly.month_return(month, snapshots, flows)

        trades = repository.list_trades(conn)
        trades_by_id = {t['id']: t for t in trades}
        tickers = sorted({t['ticker'] for t in trades})
        plans_by_trade = repository.plan_for_buy_trades(conn, list(trades_by_id))
        rs, segments_month, plan_outcomes = [], [], []   # rs: (closed_at, r), sorted below
        for ticker in tickers:
            book = _book(conn, ticker)
            splits = repository.split_events(conn, ticker)
            for seg in book['closed']:
                if not month <= seg['closed_at'].astimezone(NY).date() <= month_end:
                    continue
                segments_month.append({'ticker': ticker, **seg})
                plan = plans_by_trade.get(seg['buy_trade_id'])
                if plan is None:
                    continue
                buy_trade = trades_by_id.get(seg['buy_trade_id'])
                buy_day = buy_trade['executed_at'].astimezone(NY).date()
                stop = _discipline_module._at_basis(plan['stop'], plan['signal_date'], buy_day, splits)
                entry, exit_ = seg['entry_cost_per_share'], seg['exit_price']
                if entry != stop:
                    # P4 §5: sensitivity orders by close time, not ticker order
                    rs.append((seg['closed_at'], float((exit_ - entry) / (entry - stop))))
        spy_bars = repository.read_bars(conn, BENCHMARK, bars.latest_closed_session(now), cutoff_at=now, limit=400)
        for plan in repository.plans_since(conn, month):
            if plan['signal_date'] > month_end:
                continue
            ticker_bars = repository.read_bars(conn, plan['ticker'], bars.latest_closed_session(now),
                                               cutoff_at=now, limit=400)
            plan_outcomes.append({**plan, 'outcome': _plan_shadow_module.simulate(
                plan, ticker_bars, spy_bars, splits=repository.split_events(conn, plan['ticker']))})
        decisions_by_id = {}
        for t in trades:
            if t['decision_id'] and t['decision_id'] not in decisions_by_id:
                d = repository.decision_by_id(conn, t['decision_id'])
                if d is not None:
                    decisions_by_id[t['decision_id']] = d
        plans_by_id = {}
        for d in decisions_by_id.values():
            if d['plan_id'] and d['plan_id'] not in plans_by_id:
                p = repository.plan_by_id(conn, d['plan_id'])
                if p is not None:
                    plans_by_id[d['plan_id']] = p
        stop_events_month = []
        for ticker in tickers:
            stop_events_month += [c for c in repository.read_candidates(conn, ticker, since=month)
                                  if c['rule_id'] == 'plan_stop' and c['signal_date'] <= month_end]
        disc = _discipline_module.evaluate(
            trades=[t for t in trades if month <= t['executed_at'].astimezone(NY).date() <= month_end],
            decisions_by_id=decisions_by_id, plans_by_id=plans_by_id,
            bars_by_ticker={tk: repository.read_bars(conn, tk, bars.latest_closed_session(now), cutoff_at=now,
                                                     limit=400) for tk in tickers},
            stop_events=stop_events_month, segments=segments_month,
            session=bars.latest_closed_session(now))

        rs = [r for _, r in sorted(rs, key=lambda item: item[0])]
        track_rows = _track_rows(conn, month, month_end, session=bars.latest_closed_session(now), now=now)
        stats = {
            'calc_version': monthly.MONTHLY_VERSION, 'month': month.isoformat(), 'return': ret,
            'tier': monthly.tier(ret['return'], params.return_tiers) if ret['status'] == 'ok' else None,
            'spy': ({'return': spy_ret, 'excess': ret['return'] - spy_ret}
                    if ret['status'] == 'ok' and spy_ret is not None else None),
            'review_flag': monthly.review_flag(per_month),
            'review': monthly.review_detail(per_month),
            'sensitivity': {'approximate': True, 'count': len(rs), 'rows': monthly.sensitivity(rs)},
            'discipline': disc,
            'plans': review._plan_summary(plan_outcomes, month, month_end),
            'tracks': {'units': track_rows, 'summary': _tracks_module.summarize(track_rows)},
            'generated_at': now.isoformat(),
        }
        return repository.insert_monthly_review(conn, month, monthly.MONTHLY_VERSION, stats, notes, supersedes_id)


def list_monthly(limit: int = 12) -> list[dict[str, Any]]:
    with _tx() as conn:
        return repository.monthly_heads(conn, limit)


def list_weekly(limit: int = 20) -> list[dict[str, Any]]:
    with _tx() as conn:
        return review.list_weekly(conn, limit)


# ---------------------------------------------------------------- agent track (P3 §8)

def _read_only(fn):
    """Run fn(conn) inside a pass-through transaction; agent tool reads only."""
    with _tx() as conn:
        return fn(conn)


def _session_units(conn, session: date, *, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """This session's undecided units in three groups (P4 §7.3): main-list
    conflict-free buys (propose), other main-list units (interpret), extended
    conflict-free buys (propose); each alphabetical, every item carrying its
    candidates for the fallback brief."""
    main_buy: list[dict[str, Any]] = []
    main_other: list[dict[str, Any]] = []
    extended: list[dict[str, Any]] = []
    for group in repository.candidate_groups_since(conn, session):
        if group['signal_date'] != session:
            continue
        ticker = group['ticker']
        if repository.decision_head(conn, ticker, group['signal_date']) is not None:
            continue
        book = _book(conn, ticker)
        unit = synthesis.synthesize(ticker, group['signal_date'], group['candidates'],
                                    holding=book['position'] is not None,
                                    now=now)
        if unit is None:
            continue
        conflict_free_buy = unit['proposed_action'] == 'buy' and 'conflict' not in unit['labels']
        is_extended = _unit_is_extended(conn, ticker, group['signal_date'],
                                        held=book['position'] is not None, now=now)
        entry = repository.pool_entry_at(conn, ticker, group['signal_date'], cutoff_at=now)
        item = {'ticker': ticker, 'signal_date': group['signal_date'],
                'pool': 'extended' if is_extended else 'main',
                'pool_tier': entry['tier'] if entry else 'core',
                'proposed_action': unit['proposed_action'], 'labels': unit['labels'],
                'candidates': group['candidates']}
        if is_extended:
            if conflict_free_buy:
                extended.append(item)
        elif conflict_free_buy:
            main_buy.append(item)
        else:
            main_other.append(item)
    for bucket in (main_buy, main_other, extended):
        bucket.sort(key=lambda u: u['ticker'])
    return {'main_buy': main_buy, 'main_other': main_other, 'extended': extended}


def _agent_units(conn, session: date, *, now: datetime) -> list[dict[str, Any]]:
    """§8.1 1–2: this session's undecided, conflict-free buy units (ATR-skipped rule
    plans included); main-list units first, then extended, each alphabetical."""
    groups = _session_units(conn, session, now=now)
    return groups['main_buy'] + groups['extended']


def _interpret_units(conn, session: date, *, now: datetime) -> list[dict[str, Any]]:
    """§7.1: this session's undecided main-list units that are not conflict-free
    buys (sell, watch, conflicted); alphabetical. Extended units never interpret."""
    return _session_units(conn, session, now=now)['main_other']


def _agent_run_row(unit: dict, *, settings, attempt: int, now: datetime, status: str,
                   run_id: str | None = None, reason: str | None = None, detail: str | None = None,
                   output: dict | None = None,
                   counter: dict | None = None, plan_id=None, input_tokens: int = 0,
                   output_tokens: int = 0, mode: str = 'propose') -> dict:
    return {'id': run_id or str(uuid.uuid4()), 'ticker': unit['ticker'],
            'signal_date': unit['signal_date'], 'pool': unit['pool'], 'attempt': attempt,
            'mode': mode,
            'agent_version': (agent_graph.INTERPRET_VERSION if mode == 'interpret'
                              else agent_graph.AGENT_VERSION),
            'provider': settings.provider,
            'model': settings.model, 'cutoff_at': now, 'status': status, 'reason': reason, 'detail': detail,
            'output': output, 'counter': counter, 'plan_id': plan_id,
            'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'started_at': now, 'finished_at': now}


def _skip(unit: dict, reason: str, *, now: datetime, settings, attempt: int, mode: str = 'propose') -> dict:
    """A skipped unit still gets its agent_runs row: every candidate has an answer or
    a reason. A skipped main-list unit also gets its rule-only brief (§7.3)."""
    run_row = _agent_run_row(unit, settings=settings, attempt=attempt, now=now,
                             status='skipped', reason=reason, mode=mode)
    with _tx() as conn:
        record = repository.insert_agent_run(conn, run_row, [])
        if unit['pool'] == 'main':
            repository.store_brief(conn, briefs.for_run(run_row, [], unit=unit,
                                                        candidates=unit['candidates']))
        return record


def _checkpoint_missing(exc: BaseException) -> bool:
    """A missing checkpoint table (setup not run) is checkpoint_unavailable, not a model
    error (spec §3.4); psycopg raises UndefinedTable, possibly wrapped in the chain."""
    try:
        import psycopg.errors
        table_errors = (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn)
    except ImportError:   # pragma: no cover - psycopg is a hard dependency in practice
        return False
    current, seen = exc, set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, table_errors):
            return True
        current = current.__cause__ or current.__context__
    return False


def _run_agent_unit(unit: dict, *, now: datetime, deps: Deps, settings, attempt: int) -> dict:
    """One unit through the graph. Plan, run and calls share one transaction; a model
    or checkpoint failure lands as this unit's error row and never propagates."""
    from investment_assistant.config import load_config

    run_id = str(uuid.uuid4())
    ticker, signal_date = unit['ticker'], unit['signal_date']

    def row(status: str, **kwargs) -> dict:
        return _agent_run_row(unit, settings=settings, attempt=attempt, now=now, status=status,
                              run_id=run_id, **kwargs)

    def write(run_row: dict, calls: list[dict] | None = None) -> dict:
        with _tx() as conn:
            record = repository.insert_agent_run(conn, run_row, calls or [])
            if unit['pool'] == 'main':   # §7.1: main-list brief in the run's transaction
                repository.store_brief(conn, briefs.for_run(run_row, calls or [], unit=unit,
                                                            candidates=unit['candidates']))
            return record

    try:
        with _tx() as conn:
            bars = repository.read_bars(conn, ticker, signal_date, cutoff_at=now)
        last_close = Decimal(str(bars[-1]['close']))
        ctx = agent_tools.ToolContext(ticker=ticker, session=signal_date, cutoff_at=now, read=_read_only)
        with ExitStack() as stack:
            try:
                factory = deps.agent_checkpointer or (
                    lambda: agent_model.checkpointer(os.environ.get('INVESTMENT_ASSISTANT_DATABASE_URL', '')))
                checkpointer = stack.enter_context(factory())
            except Exception as exc:
                _, detail = agent_model.classify_error(exc, settings.api_key)
                return write(row('error', reason='checkpoint_unavailable', detail=detail))
            model_obj = deps.agent_model if deps.agent_model is not None else agent_model.chat_model(settings)
            try:
                result = agent_graph.run_unit(unit=unit, ctx=ctx, model=model_obj,
                                              checkpointer=checkpointer, run_id=run_id,
                                              last_close=last_close, now=lambda: now)
            except Unavailable:
                raise
            except Exception as exc:
                reason, detail = agent_model.classify_error(exc, settings.api_key)
                if _checkpoint_missing(exc):
                    reason = 'checkpoint_unavailable'
                return write(row('error', reason=reason, detail=detail))
        if result['status'] == 'ok':
            with _tx() as conn:   # §3.3: plan, run, calls in one transaction
                levels = {key: Decimal(item['value']) for key, item in result['output']['levels'].items()}
                plan = plans.build_agent_plan(
                    levels=levels, agent_run_id=run_id, model=settings.model, ticker=ticker,
                    signal_date=signal_date, bars=bars,
                    earnings_row=repository.latest_earnings(conn, ticker, cutoff_at=now),
                    snapshot=repository.snapshot_at(conn, signal_date, cutoff_at=now),
                    exposure=exposure(conn, signal_date, cutoff_at=now, ticker=ticker),
                    params=load_config().workbench,
                    context=plan_context(conn, ticker, signal_date, now=now))
                stored = repository.store_plan(conn, plan)
                run_row = row('ok', plan_id=stored['record']['id'], output=result['output'],
                              counter=result['counter'], input_tokens=result['input_tokens'],
                              output_tokens=result['output_tokens'])
                record = repository.insert_agent_run(conn, run_row, result['calls'])   # plan → run → calls
                if unit['pool'] == 'main':                                             # → brief, one transaction
                    repository.store_brief(conn, briefs.for_run(run_row, result['calls'], unit=unit,
                                                                candidates=unit['candidates']))
                return record
        return write(row(result['status'], reason=result['reason'], output=result['output'],
                         counter=result['counter'], input_tokens=result['input_tokens'],
                         output_tokens=result['output_tokens']), result['calls'])
    except Unavailable:
        raise
    except Exception as exc:   # the unexpected: this unit only, never the batch
        reason, detail = agent_model.classify_error(exc, settings.api_key)
        return write(row('error', reason=reason, detail=detail))


def _run_interpret_unit(unit: dict, *, now: datetime, deps: Deps, settings, attempt: int) -> dict:
    """One unit through the interpret graph (§7.2); error classification mirrors
    _run_agent_unit. The run (mode='interpret', no plan) and its brief share
    one transaction; model exceptions become this unit's error row."""
    run_id = str(uuid.uuid4())
    ticker, signal_date = unit['ticker'], unit['signal_date']

    def row(status: str, **kwargs) -> dict:
        return _agent_run_row(unit, settings=settings, attempt=attempt, now=now, status=status,
                              run_id=run_id, mode='interpret', **kwargs)

    def write(run_row: dict, calls: list[dict] | None = None) -> dict:
        with _tx() as conn:
            record = repository.insert_agent_run(conn, run_row, calls or [])
            repository.store_brief(conn, briefs.for_run(run_row, calls or [], unit=unit,
                                                        candidates=unit['candidates']))
            return record

    try:
        ctx = agent_tools.ToolContext(ticker=ticker, session=signal_date, cutoff_at=now, read=_read_only)
        with ExitStack() as stack:
            try:
                factory = deps.agent_checkpointer or (
                    lambda: agent_model.checkpointer(os.environ.get('INVESTMENT_ASSISTANT_DATABASE_URL', '')))
                checkpointer = stack.enter_context(factory())
            except Exception as exc:
                _, detail = agent_model.classify_error(exc, settings.api_key)
                return write(row('error', reason='checkpoint_unavailable', detail=detail))
            model_obj = deps.agent_model if deps.agent_model is not None else agent_model.chat_model(settings)
            try:
                result = agent_graph.run_interpret(unit=unit, ctx=ctx, model=model_obj,
                                                   checkpointer=checkpointer, run_id=run_id,
                                                   now=lambda: now)
            except Unavailable:
                raise
            except Exception as exc:
                reason, detail = agent_model.classify_error(exc, settings.api_key)
                if _checkpoint_missing(exc):
                    reason = 'checkpoint_unavailable'
                return write(row('error', reason=reason, detail=detail))
        return write(row(result['status'], reason=result['reason'], output=result['output'],
                         input_tokens=result['input_tokens'], output_tokens=result['output_tokens']),
                     result['calls'])
    except Unavailable:
        raise
    except Exception as exc:   # the unexpected: this unit only, never the batch
        reason, detail = agent_model.classify_error(exc, settings.api_key)
        return write(row('error', reason=reason, detail=detail))


def _agent_stage(session: date, *, now: datetime, deps: Deps, summary: dict[str, Any],
                 started: float, clock: Callable[[], float],
                 acc: stages_module.StageAcc | None = None) -> str | None:
    """The agent track after all rule plans (§8.1): skip rules, then one unit at a time.

    ``acc`` (v2.4 §4) collects the stage accounting next to ``record`` and the skip branches. Returns the
    unavailable reason (disabled / not_configured) or None, so the caller can close an unavailable stage
    as skipped rather than as an empty success."""
    t_agent = clock()
    settings = deps.agent_settings if deps.agent_settings is not None else agent_model.settings_from_env()
    if settings.config_error:
        summary['errors'].append(f'agent_config: {settings.config_error}')
    unavailable = agent_model.unavailable_reason(settings)
    ny_date = now.astimezone(NY).date()
    runs: dict[str, str] = {}
    briefs: dict[str, str] = {}
    tokens = {'input': 0, 'output': 0}
    quota_exhausted = False

    def record(unit: dict, run: dict) -> None:
        nonlocal quota_exhausted
        if run.get('mode', 'propose') == 'propose':    # 7.3: runs only records propose
            runs[unit['ticker']] = run['status'] if run['status'] in ('ok', 'pass') else (
                f"{run['status']}: {run['reason']}")
        if unit['pool'] == 'main':
            # 7.3: agent.briefs is the run view; the top-level briefs key carries the brief row's status
            briefs[unit['ticker']] = run['status'] if run['status'] in ('ok', 'pass') else (
                f"{run['status']}: {run['reason']}")
            summary['briefs'][unit['ticker']] = brief_status(run)
        tokens['input'] += run['input_tokens'] or 0
        tokens['output'] += run['output_tokens'] or 0
        if acc is not None:
            acc.ref('agent_run_ids', run['id'])
            if run['status'] in ('ok', 'pass'):
                acc.output()
            if run['status'] == 'ok' and run.get('mode', 'propose') == 'propose' and run.get('plan_id') is not None:
                acc.ref('plan_ids', run['plan_id'])      # 只收本次 ok 运行新增的 Agent 计划
            elif run['status'] == 'skipped':
                acc.skip(run['reason'], unit['ticker'])
            elif run['status'] == 'error':
                acc.fail(unit['ticker'], run['reason'])
        if run['status'] == 'error':
            summary['sources']['agent'].append(unit['ticker'])
            if run['reason'] == 'quota_exhausted':
                quota_exhausted = True

    def brief_status(run: dict) -> str:
        mode, status = run.get('mode', 'propose'), run['status']
        if mode == 'propose' and status in ('ok', 'pass'):
            return 'ok'
        if mode == 'interpret' and status == 'ok':
            return 'ok'
        if mode == 'interpret' and status == 'rejected':
            return 'error'
        return 'fallback'

    def run_one(unit: dict, mode: str, runner: Callable) -> None:
        """The three shared gates (§7.3: deadline, provider, quota, token budget);
        completion and attempts are counted per mode."""
        try:
            with _tx() as conn:
                prior = repository.agent_runs_for(conn, unit['ticker'], unit['signal_date'], mode=mode)
            done = ('ok', 'pass') if mode == 'propose' else ('ok',)
            if any(r['status'] in done for r in prior):
                if acc is not None:
                    acc.skip('already_completed', unit['ticker'])
                return
            if any(r['status'] == 'skipped' and r['reason'] == 'max_attempts' for r in prior):
                if acc is not None:
                    acc.skip('max_attempts', unit['ticker'])
                return
            attempt = len(prior) + 1
            if clock() - started >= AGENT_DEADLINE_S:
                run = _skip(unit, 'stage_budget', now=now, settings=settings, attempt=attempt, mode=mode)
            elif unavailable is not None:
                run = _skip(unit, unavailable, now=now, settings=settings, attempt=attempt, mode=mode)
            elif quota_exhausted:
                run = _skip(unit, 'quota_exhausted', now=now, settings=settings, attempt=attempt, mode=mode)
            elif len(prior) >= AGENT_MAX_ATTEMPTS:
                run = _skip(unit, 'max_attempts', now=now, settings=settings, attempt=attempt, mode=mode)
            elif settings.daily_tokens is not None:
                with _tx() as conn:
                    used = repository.agent_tokens_on(conn, ny_date)
                if used >= settings.daily_tokens:
                    run = _skip(unit, 'token_budget', now=now, settings=settings, attempt=attempt, mode=mode)
                else:
                    run = runner(unit, attempt)
            else:
                run = runner(unit, attempt)
            record(unit, run)
        except Unavailable:
            raise
        except Exception as exc:   # §2: an agent failure never drags the rule track
            summary['errors'].append(f"{unit['ticker']} agent: {exc}")
            if acc is not None:
                acc.fail(unit['ticker'], exc)

    with _tx() as conn:
        groups = _session_units(conn, session, now=now)
    if acc is not None:
        acc.input(sum(len(units) for units in groups.values()))

    def propose(unit: dict, attempt: int) -> dict:
        return _run_agent_unit(unit, now=now, deps=deps, settings=settings, attempt=attempt)

    def interpret(unit: dict, attempt: int) -> dict:
        return _run_interpret_unit(unit, now=now, deps=deps, settings=settings, attempt=attempt)

    for unit in groups['main_buy']:          # §7.3: main propose, main interpret, extended propose
        run_one(unit, 'propose', propose)
    for unit in groups['main_other']:
        run_one(unit, 'interpret', interpret)
    for unit in groups['extended']:
        run_one(unit, 'propose', propose)

    summary['agent'] = {'runs': runs, 'briefs': briefs, 'tokens': tokens,
                       'quota_exhausted': quota_exhausted}
    summary['timings']['agent'] = round(clock() - t_agent, 1)
    if acc is not None:
        acc.detail['tokens'] = dict(tokens)
        acc.duration_ms += (clock() - t_agent) * 1000
    return unavailable


class AgentConflict(RuntimeError):
    """The unit already has an ok/pass agent run."""


def run_agent(ticker: str, signal_date: date, *, now: datetime, deps: Deps | None = None) -> dict[str, Any]:
    """Manual single-unit run (§10.3): not a conflict-free buy unit -> ValueError,
    already ok/pass -> AgentConflict; otherwise one run at the given cutoff."""
    deps = deps or Deps()
    settings = deps.agent_settings if deps.agent_settings is not None else agent_model.settings_from_env()
    with _tx() as conn:
        group = repository.unit_candidates(conn, ticker, signal_date)
        if not group:
            raise ValueError(f'{ticker} {signal_date} 没有候选，不是决策单元')
        book = _book(conn, ticker)
        unit = synthesis.synthesize(ticker, signal_date, group, holding=book['position'] is not None,
                                    now=now)
        if unit is None or unit['proposed_action'] != 'buy' or 'conflict' in unit['labels']:
            raise ValueError(f'{ticker} {signal_date} 不是无冲突的买入单元')
        prior = repository.agent_runs_for(conn, ticker, signal_date)
        if any(r['status'] in ('ok', 'pass') for r in prior):
            raise AgentConflict(f'{ticker} {signal_date} 已有 Agent 建议')
        extended = _unit_is_extended(conn, ticker, signal_date, held=book['position'] is not None, now=now)
        entry = repository.pool_entry_at(conn, ticker, signal_date, cutoff_at=now)
        agent_unit = {'ticker': unit['ticker'], 'signal_date': signal_date,
                      'pool': 'extended' if extended else 'main',
                      'pool_tier': entry['tier'] if entry else 'core',
                      'proposed_action': unit['proposed_action'], 'labels': unit['labels'],
                      'candidates': group}
    unavailable = agent_model.unavailable_reason(settings)
    if unavailable is not None:
        return _skip(agent_unit, unavailable, now=now, settings=settings, attempt=len(prior) + 1)
    return _run_agent_unit(agent_unit, now=now, deps=deps, settings=settings, attempt=len(prior) + 1)


def _agent_view(run: dict[str, Any] | None, plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """The unit's latest agent run (§10.1): full suggestion on ok/pass, status and reason only otherwise."""
    if run is None:
        return None
    if run['status'] in ('ok', 'pass'):
        return {'id': str(run['id']), 'status': run['status'], 'model': run['model'],
                'agent_version': run['agent_version'], 'output': run['output'], 'counter': run['counter'],
                'plan': plan, 'input_tokens': run['input_tokens'], 'output_tokens': run['output_tokens'],
                'created_at': run['created_at']}
    return {'id': str(run['id']), 'status': run['status'], 'reason': run['reason'],
            'created_at': run['created_at']}


def _agent_status_line(run: dict[str, Any] | None) -> str | None:
    if run is None:
        return None
    return run['status'] if run['status'] in ('ok', 'pass') else f"{run['status']}: {run['reason']}"


def agent_runs(*, now: datetime, since: date | None = None) -> dict[str, Any]:
    """Run rows without result payloads, plus coverage: every buy unit in range has a run or is missing."""
    session = bars.latest_closed_session(now)
    with _tx() as conn:
        start = since if since is not None else session - timedelta(days=14)
        runs = repository.list_agent_runs(conn, start)
        total = covered = 0
        missing: list[dict[str, Any]] = []
        for group in repository.candidate_groups_since(conn, start):
            ticker, signal_date = group['ticker'], group['signal_date']
            book = _book(conn, ticker)
            unit = synthesis.synthesize(ticker, signal_date, group['candidates'],
                                        holding=book['position'] is not None,
                                        now=now)
            if unit is None or unit['proposed_action'] != 'buy' or 'conflict' in unit['labels']:
                continue
            total += 1
            if repository.latest_agent_run(conn, ticker, signal_date) is not None:
                covered += 1
            else:
                missing.append({'ticker': ticker, 'signal_date': signal_date})
    return {'since': start, 'runs': runs, 'coverage': {'units': total, 'covered': covered, 'missing': missing}}


def agent_run_detail(run_id: str) -> dict[str, Any]:
    """One run with every tool call, arguments, results and hashes (§10.3 traceability)."""
    with _tx() as conn:
        run = repository.agent_run_by_id(conn, run_id)
        if run is None:
            raise LookupError(f'运行 {run_id} 不存在')
        return {**run, 'id': str(run['id']), 'tool_calls': repository.agent_tool_calls(conn, run['id'])}


# --- review pushes (P4 §6.1, §6.3) ---

def _redact_reason(reason: str, notify_cfg) -> str:
    """Webhook URLs never survive into stored push reasons."""
    from investment_assistant.workbench.macro import redact

    for secret in (getattr(notify_cfg, 'webhooks', None) or {}).values():
        if secret:
            reason = redact(reason, str(secret))
    return reason


def _record_push(kind, period, *, review_id, trigger_source, result, notify_cfg, conn=None) -> dict[str, Any]:
    row = {'kind': kind, 'period': period, 'review_id': review_id, 'trigger_source': trigger_source,
           'sent': bool(result.get('sent')), 'messages': result.get('messages') or 0,
           'reason': _redact_reason(result['reason'], notify_cfg) if result.get('reason') else None}
    with _tx() as conn2:
        repository.insert_review_push(conn2, row)
    return {'kind': kind, 'period': period, 'review_id': review_id, 'sent': row['sent'],
            'messages': row['messages'], 'reason': row['reason']}


def push_review(kind: str, period: date, *, now: datetime, notify_cfg, trigger_source: str = 'manual',
                client=None) -> dict[str, Any]:
    """Push one period's latest frozen snapshot and record the attempt (§6.3).
    Manual pushes resend regardless of a previous success."""
    from investment_assistant.config import load_config
    from investment_assistant.notify import notifier, templates

    if kind not in ('weekly', 'monthly'):
        raise ledger.LedgerError('kind 必须是 weekly 或 monthly')
    if kind == 'weekly' and period.weekday() != 0:
        raise ledger.LedgerError('period 必须是周一')
    if kind == 'monthly' and period.day != 1:
        raise ledger.LedgerError('period 必须是当月 1 日')
    public_url = load_config().workbench.public_url
    with _tx() as conn:
        head = (repository.weekly_head(conn, period) if kind == 'weekly'
                else repository.monthly_head(conn, period))
    if head is None:
        raise ledger.NotFound(f'{period} 没有该周期的复盘快照')
    payload = (review_digest.weekly(head, public_url=public_url) if kind == 'weekly'
               else review_digest.monthly(head, public_url=public_url))
    messages = (templates.workbench_weekly if kind == 'weekly' else templates.workbench_monthly)(payload)
    result = notifier.send_notifications('workbench_review', messages, notify_cfg, client=client)
    return _record_push(kind, period, review_id=head['id'], trigger_source=trigger_source,
                        result=result, notify_cfg=notify_cfg)


def _tick_weekly(*, now: datetime, notify_cfg, trigger_source: str, client) -> dict[str, Any]:
    """§6.1 weekly: reuse a snapshot frozen after the week's final close, else
    generate one (superseding whatever is there), then push."""
    week = review_digest.due_week(now)
    week_end = week + timedelta(days=6)
    with _tx() as conn:
        if repository.review_push_sent(conn, 'weekly', week):
            return {'period': week, 'action': 'already_sent'}
        head = repository.weekly_head(conn, week)
    final = review_digest.last_session(week, week_end)
    fresh = head is not None and final is not None and bars.latest_closed_session(head['created_at']) >= final
    if fresh:
        action = 'reused'
    else:
        head = generate_weekly(week, notes='自动生成', supersedes_id=head['id'] if head else None, now=now)
        action = 'generated'
    push = push_review('weekly', week, now=now, notify_cfg=notify_cfg, trigger_source=trigger_source,
                       client=client)
    return {'period': week, 'action': action, 'push': push}


def _tick_monthly(*, now: datetime, notify_cfg, trigger_source: str, client) -> dict[str, Any]:
    """§6.1 monthly: with the month-end snapshot, reuse-or-generate then push; without it,
    remind once from the first Saturday of the next month on — unless the month predates
    the workbench (no decision or account snapshot on or before its last day)."""
    from investment_assistant.notify import notifier, templates
    from investment_assistant.config import load_config

    month = review_digest.due_month(now)
    month_end = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    with _tx() as conn:
        if repository.review_push_sent(conn, 'monthly', month):
            return {'period': month, 'action': 'already_sent'}
        reminded_before = repository.review_push_sent(conn, 'monthly_reminder', month)
        snapshots, flows = repository.list_snapshots(conn), repository.list_flows(conn)
        head = repository.monthly_head(conn, month)
        account_recorded = repository.latest_account_record_at(conn)
        started_on = repository.workbench_started_on(conn)
    if monthly.month_end_snapshot(snapshots, month) is None:
        if started_on is None or started_on > month_end:
            return {'period': month, 'action': 'before_start'}
        if reminded_before:
            return {'period': month, 'action': 'waiting'}
        if not review_digest.reminder_due(month, now):
            return {'period': month, 'action': 'waiting'}
        payload = review_digest.reminder(month, public_url=load_config().workbench.public_url)
        messages = templates.workbench_review_reminder(payload)
        result = notifier.send_notifications('workbench_review', messages, notify_cfg, client=client)
        push = _record_push('monthly_reminder', month, review_id=None, trigger_source=trigger_source,
                            result=result, notify_cfg=notify_cfg)
        return {'period': month, 'action': 'reminded', 'push': push}
    final = review_digest.last_session(month, month_end)
    fresh = (head is not None and final is not None
             and bars.latest_closed_session(head['created_at']) >= final
             and (account_recorded is None or head['created_at'] > account_recorded))
    if fresh:
        action = 'reused'
    else:
        head = generate_monthly(month, notes='自动生成', supersedes_id=head['id'] if head else None, now=now)
        action = 'generated'
    push = push_review('monthly', month, now=now, notify_cfg=notify_cfg, trigger_source=trigger_source,
                       client=client)
    return {'period': month, 'action': action, 'push': push}


def review_tick(*, now: datetime, notify_cfg, trigger_source: str, client=None) -> dict[str, Any]:
    """The workbench_review task body (§6.1): weekly and monthly each in their own
    transaction; one failing never blocks the other, and errors land in the report."""
    out: dict[str, Any] = {'weekly': None, 'monthly': None, 'errors': []}
    for name, part in (('weekly', _tick_weekly), ('monthly', _tick_monthly)):
        try:
            out[name] = part(now=now, notify_cfg=notify_cfg, trigger_source=trigger_source, client=client)
        except Unavailable:
            raise
        except Exception as exc:
            out[name] = {'action': 'error', 'error': str(exc)}
            out['errors'].append(f'review {name}: {exc}')
    return out


def list_review_pushes(limit: int = 20) -> list[dict[str, Any]]:
    with _tx() as conn:
        rows = repository.list_review_pushes(conn, limit)
    return [{**row, 'id': str(row['id']), 'review_id': str(row['review_id']) if row['review_id'] else None,
             'period': row['period'].isoformat(), 'created_at': row['created_at'].isoformat()}
            for row in rows]
