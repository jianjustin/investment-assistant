"""Transactions and use cases for the US workbench. SQL lives in repository.py."""
from __future__ import annotations

import os
from contextlib import contextmanager
from decimal import Decimal
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from investment_assistant.data.calendar import is_trading_day
from investment_assistant.db import connect
from investment_assistant.workbench import (account, bars, briefs, discipline, earnings, exits, ledger, news,
                                               plans, positions, repository, review, rules, synthesis)
from investment_assistant.workbench import plan_shadow as _plan_shadow_module

NY = ZoneInfo('America/New_York')
BENCHMARK = 'SPY'
MAX_TICKERS = 10
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
    brief_client: Callable | None = None
    earnings_fetcher: Callable | None = None


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
                raise Unavailable('工作台数据表未就绪（需执行迁移 016）：' + ', '.join(missing))
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


def _validate_tickers(tickers: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(t.strip().upper() for t in tickers if t and t.strip()))
    if not cleaned:
        raise ValueError('股票池为空')
    if len(cleaned) > MAX_TICKERS:
        raise ValueError(f'股票池 {len(cleaned)} 只，超过上限 {MAX_TICKERS}；请先缩减观察名单')
    return cleaned


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


def _generate_rule_plan(conn, ticker: str, session: date, ticker_bars: list[dict[str, Any]], summary: dict[str, Any],
                        *, now: datetime) -> None:
    """Build and store the rule plan for a fresh buy unit; record skip/conflict in the summary."""
    from investment_assistant.config import load_config

    plan = plans.build_rule_plan(
        ticker=ticker, signal_date=session, bars=ticker_bars,
        earnings_row=repository.latest_earnings(conn, ticker, cutoff_at=now),
        snapshot=repository.snapshot_at(conn, session, cutoff_at=now),
        exposure=exposure(conn, session, cutoff_at=now, ticker=ticker),
        params=load_config().workbench)
    if 'skip' in plan:
        summary['plans'][ticker] = f"skip: {plan['skip']}"
        return
    out = repository.store_plan(conn, plan)
    summary['plans'][ticker] = out['status']
    if out['status'] == 'conflict':
        summary['conflicts'].append({'ticker': ticker, 'rule_id': 'rule_plan', 'id': str(out['record']['id'])})


def run_batch(*, tickers: list[str], now: datetime, deps: Deps | None = None, skip_non_trading: bool = False,
              run_id: str | None = None) -> dict[str, Any]:
    """Collect -> rules -> units -> briefs for the latest settled session. Idempotent per session."""
    deps = deps or Deps()
    watchlist = _validate_tickers(tickers)
    ny_date = now.astimezone(NY).date()
    if skip_non_trading and not is_trading_day(ny_date):
        return {'status': 'skipped', 'reason': 'not a trading day in New York', 'ny_date': ny_date.isoformat()}
    session = bars.latest_closed_session(now)
    # Holdings join the batch even off the watchlist: plan stops and earnings reminders need their data.
    # The size cap only ever applies to the watchlist.
    with _tx() as conn:
        held = [t for t in sorted({r['ticker'] for r in repository.list_trades(conn) if r['voided_at'] is None})
                if t not in watchlist]
    tickers = [*watchlist, *held]
    summary: dict[str, Any] = {'session': session.isoformat(), 'cutoff_at': now.isoformat(), 'tickers': {},
                               'benchmark': {}, 'filings': {}, 'earnings': {}, 'plans': {},
                               'conflicts': [], 'errors': [], 'briefs': {}}

    for ticker in [BENCHMARK, *tickers]:
        entry: dict[str, Any] = {'bars': None, 'skipped_bars': [], 'news': None, 'candidates': [], 'skips': [],
                                 'error': None}
        problems = []
        try:
            frame = bars.fetch_history(ticker, session - timedelta(days=HISTORY_DAYS), session, fetcher=deps.bar_fetcher)
            rows, skipped = bars.normalize_history(frame)
            with _tx() as conn:
                entry['bars'] = repository.store_bars(conn, ticker, rows, now=now)
            entry['skipped_bars'] = [d.isoformat() for d in skipped]
        except Unavailable:
            raise
        except Exception as exc:
            problems.append(f'bars: {exc}')
        if ticker != BENCHMARK:
            try:
                raw = news.fetch_yfinance(ticker, fetcher=deps.news_fetcher)
                items, bad = news.normalize_yfinance(raw, ticker=ticker)
                with _tx() as conn:
                    entry['news'] = {**repository.store_news(conn, [(i, [ticker]) for i in items], now=now),
                                     'fetched': len(raw), 'skipped': bad}
            except Unavailable:
                raise
            except Exception as exc:
                problems.append(f'news: {exc}')
        try:
            row = earnings.fetch_next(ticker, fetcher=deps.earnings_fetcher, today=ny_date)
            with _tx() as conn:
                summary['earnings'][ticker] = repository.store_earnings(conn, ticker, row, now=now)['status']
        except Unavailable:
            raise
        except Exception as exc:  # 采集失败不写库，也不冒充无财报
            summary['earnings'][ticker] = f'error: {exc}'
            summary['errors'].append(f'{ticker} earnings: {exc}')
        if problems:
            entry['error'] = '; '.join(problems)
            summary['errors'].extend(f'{ticker} {p}' for p in problems)
        if ticker == BENCHMARK:
            summary['benchmark'] = entry
        else:
            summary['tickers'][ticker] = entry

    try:
        source = deps.filing_source
        if source is None:
            from investment_assistant.filings.monitor_source import EdgarSource
            source = EdgarSource(SEC_EVIDENCE_DIR)
        metas = source.discover(tickers, (session - timedelta(days=FILING_LOOKBACK_DAYS)).isoformat(), session.isoformat())
        with _tx() as conn:
            summary['filings'] = {**repository.store_news(conn, news.filing_news(metas), now=now),
                                  'acceptance_filled': repository.fill_filing_acceptance(conn, metas)}
    except Unavailable:
        raise
    except Exception as exc:
        summary['filings'] = {'error': str(exc)}
        summary['errors'].append(f'SEC listings: {exc}')

    for ticker in tickers:
        entry = summary['tickers'][ticker]
        try:
            with _tx() as conn:
                ticker_bars = repository.read_bars(conn, ticker, session, cutoff_at=now)
                events, filing_rows = _filing_events(conn, ticker, session, now)
                book = _book(conn, ticker)
                _, plan_state = _position_plan_state(conn, ticker, book, ticker_bars, session, now=now)
                result = rules.evaluate(ticker, session, ticker_bars, events, book['position'], plan_state=plan_state)
                inserted = 0
                for cand in result['candidates']:
                    out = repository.store_candidate(conn, ticker, session, cand, run_id=run_id)
                    inserted += out['status'] == 'inserted'
                    if out['status'] == 'conflict':
                        summary['conflicts'].append({'ticker': ticker, 'rule_id': cand.rule_id, 'id': str(out['id'])})
                entry['candidates'] = [c.rule_id for c in result['candidates']]
                entry['skips'] = sorted({f'{s.rule_id}:{s.reason}' for s in result['skips']})
                group = repository.unit_candidates(conn, ticker, session)
                unit = synthesis.synthesize(ticker, session, group, holding=book['position'] is not None,
                                            market_status=repository.market_status(conn, session), now=now) \
                    if group and repository.decision_head(conn, ticker, session) is None else None
                if unit is not None and unit['proposed_action'] == 'buy' and 'conflict' not in unit['labels']:
                    _generate_rule_plan(conn, ticker, session, ticker_bars, summary, now=now)
                needs_brief = group and repository.decision_head(conn, ticker, session) is None and (
                    inserted or repository.latest_brief(conn, ticker, session) is None)
                if needs_brief:
                    recent = repository.read_news(conn, ticker, cutoff_at=now,
                                                  since=_midnight(session - timedelta(days=NEWS_LOOKBACK_DAYS)))
                    brief = briefs.generate(unit, group, filing_rows, recent, cutoff_at=now, client=deps.brief_client)
                    repository.store_brief(conn, brief)
                    summary['briefs'][ticker] = brief['status']
        except Unavailable:
            raise
        except Exception as exc:
            entry['error'] = '; '.join(filter(None, [entry['error'], f'rules: {exc}']))
            summary['errors'].append(f'{ticker} rules: {exc}')
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
        for group in repository.open_candidate_groups(conn, since=session - timedelta(days=OPEN_UNIT_DAYS)):
            ticker, signal_date = group['ticker'], group['signal_date']
            book = _book(conn, ticker)
            unit = synthesis.synthesize(ticker, signal_date, group['candidates'], holding=book['position'] is not None,
                                        market_status=repository.market_status(conn, signal_date), now=now)
            since = signal_date - timedelta(days=NEWS_LOOKBACK_DAYS)
            unit.update(
                candidates=group['candidates'], position=book['position'],
                brief=_brief_view(repository.latest_brief(conn, ticker, signal_date)),
                plan=repository.rule_plan(conn, ticker, signal_date),
                filings=repository.read_filings(conn, ticker, since=since, cutoff_at=now),
                news=repository.read_news(conn, ticker, cutoff_at=now, since=_midnight(since), limit=20))
            units.append(unit)
        holdings = _holdings(conn, session, now=now)
    return {'session': session, 'units': units, 'holdings': holdings}


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


def instrument(ticker: str, *, now: datetime) -> dict[str, Any]:
    ticker = ticker.strip().upper()
    session = bars.latest_closed_session(now)
    with _tx() as conn:
        book = _book(conn, ticker)
        return {
            'ticker': ticker, 'session': session,
            'bars': repository.read_bars(conn, ticker, session, cutoff_at=now, limit=120),
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


def discipline_view(*, now: datetime, since: date | None = None) -> dict[str, Any]:
    """Execution discipline of recorded buys against their confirmed plans."""
    session = bars.latest_closed_session(now)
    since = since or session - timedelta(days=90)
    with _tx() as conn:
        trades = repository.list_trades(conn)
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
        out = discipline.evaluate(trades=trades, decisions_by_id=decisions_by_id, plans_by_id=plans_by_id,
                                  bars_by_ticker=bars_by_ticker, stop_events=stop_events, segments=segments,
                                  session=session)
    return {'session': session, 'since': since, **out}


# discipline() is the interface name; keep both for the route.
discipline = discipline_view


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
        stats = review.weekly_stats(week_start, units, outcomes, repository.list_trades(conn), segments=segments,
                                    undecided=undecided,
                                    entry_opens={k: v.get('entry_price') for k, v in outcomes.items()})
        stats['generated_at'] = now.isoformat()
        return review.save_weekly(conn, week_start, stats, notes=notes, supersedes_id=supersedes_id)


def list_weekly(limit: int = 20) -> list[dict[str, Any]]:
    with _tx() as conn:
        return review.list_weekly(conn, limit)
