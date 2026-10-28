"""Shadow outcomes, trade reviews and weekly snapshots (design §7).

Descriptive only: counts, means, medians and raw values. No significance tests,
no claim that a rule works. Prices: entry at the next session's open adjusted by
that day's adj_close/close factor, exits at adj_close, so dividends and splits
inside a window do not distort returns.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from investment_assistant.data.calendar import add_trading_days, trading_days_between
from investment_assistant.workbench import ledger, repository

CALC_VERSION = 'review-6'          # v2.5 D17: plans.agent = first versions, plans.agent_latest = heads
SHADOW_MIN_SAMPLE = 5              # v2.5 §9.1: agent_summary gives no mean / median below this
WINDOWS = (5, 10, 20)
NY = ZoneInfo('America/New_York')


def _by_date(bars: list[dict[str, Any]]) -> dict[date, dict[str, Any]]:
    return {b['price_date']: b for b in bars}


def _adj_open(bar: dict[str, Any]) -> float:
    return bar['open'] * bar['adj_close'] / bar['close']


def _session(ts: datetime) -> date:
    return ts.astimezone(NY).date()


def _window_return(index, entry_day: date, sessions: int) -> tuple[date, float] | None:
    exit_day = add_trading_days(entry_day, sessions - 1)
    entry, exit_ = index.get(entry_day), index.get(exit_day)
    if entry is None or exit_ is None:
        return None
    return exit_day, exit_['adj_close'] / _adj_open(entry) - 1


def shadow_outcome(unit: dict[str, Any], bars: list[dict[str, Any]], spy_bars: list[dict[str, Any]]) -> dict[str, Any]:
    """What following the unit's proposed action from the next open would have done."""
    stock, spy = _by_date(bars), _by_date(spy_bars)
    entry_day = add_trading_days(unit['signal_date'], 1)
    if entry_day not in stock:
        return {'status': 'pending_entry', 'windows': {}}
    action = unit['proposed_action']
    windows: dict[str, Any] = {}
    for n in WINDOWS:
        own, bench = _window_return(stock, entry_day, n), _window_return(spy, entry_day, n)
        if own is None or bench is None:
            windows[str(n)] = {'status': 'immature'}
            continue
        exit_day, ret = own
        if action == 'watch':
            windows[str(n)] = {'status': 'mature', 'exit_date': exit_day.isoformat(), 'move': ret}
            continue
        sign = 1 if action == 'buy' else -1  # sell: the move avoided
        windows[str(n)] = {'status': 'mature', 'exit_date': exit_day.isoformat(), 'return': sign * ret,
                           'spy_return': sign * bench[1], 'excess': sign * (ret - bench[1])}
    return {'status': 'entered', 'entry_date': entry_day, 'entry_price': stock[entry_day]['open'],
            'direction': action, 'windows': windows}


def trade_segment_review(segment: dict[str, Any], bars: list[dict[str, Any]], spy_bars: list[dict[str, Any]]) -> dict[str, Any]:
    opened, closed = _session(segment['opened_at']), _session(segment['closed_at'])
    sessions = trading_days_between(opened, closed)
    stock, spy = _by_date(bars), _by_date(spy_bars)
    cost = segment['quantity'] * segment['entry_cost_per_share']
    out = {'buy_trade_id': str(segment['buy_trade_id']), 'sell_trade_id': str(segment['sell_trade_id']),
           'opened': opened.isoformat(), 'closed': closed.isoformat(), 'holding_sessions': len(sessions),
           'quantity': str(segment['quantity']), 'realized_pnl': float(segment['realized_pnl']),
           'return': float(segment['realized_pnl'] / cost) if cost else None,
           'spy_return': None, 'max_favorable': None, 'max_adverse': None}
    if opened in spy and closed in spy:
        out['spy_return'] = spy[closed]['adj_close'] / _adj_open(spy[opened]) - 1
    if opened in stock and all(d in stock for d in sessions):
        base = _adj_open(stock[opened])
        path = [stock[d]['adj_close'] / base - 1 for d in sessions]
        out['max_favorable'], out['max_adverse'] = max(0.0, *path), min(0.0, *path)
    return out


def open_position_review(ticker: str, position: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    last = bars[-1]
    cost = Decimal(position['avg_cost'])
    return {'ticker': ticker, 'quantity': str(position['quantity']), 'avg_cost': float(cost),
            'last_close': last['close'], 'as_of': last['price_date'].isoformat(),
            'unrealized_pnl': float(position['quantity'] * (Decimal(str(last['close'])) - cost)),
            'unrealized_return': last['close'] / float(cost) - 1}


def _summary(values: list[float], count: int) -> dict[str, Any]:
    return {'count': count, 'mature': len(values),
            'mean': statistics.fmean(values) if values else None,
            'median': statistics.median(values) if values else None,
            'values': [round(v, 6) for v in values]}


def _grouped(groups: dict[str, list[dict[str, Any]]], outcomes) -> dict[str, Any]:
    result = {}
    for key, units in groups.items():
        result[key] = {}
        for n in WINDOWS:
            values = [w['excess'] for u in units
                      if (w := outcomes.get(u['id'], {}).get('windows', {}).get(str(n), {})).get('excess') is not None]
            result[key][str(n)] = _summary(values, len(units))
    return result


def is_first_version(entry: dict[str, Any]) -> bool:
    """v2.5 §9.1 / D17: an agent plan is its chain's first version (agent-1 plans have no chain
    and count as their own first version)."""
    chain = entry.get('chain')
    return chain is None or chain.get('version_no') in (0, None)


def is_latest_version(entry: dict[str, Any]) -> bool:
    """The chain's head when the view was built (agent-1 plans are their own latest version)."""
    chain = entry.get('chain')
    return chain is None or bool(chain.get('is_head'))


def _plan_summary(plan_outcomes: list[dict[str, Any]], week_start: date, week_end: date) -> dict[str, Any]:
    """Per plan kind: count, expired, R mean and median. v2.5 D17 (review-6 / monthly-3): ``agent``
    counts each chain's first version only, ``agent_latest`` each chain's head at generation time."""
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for entry in plan_outcomes:
        if not week_start <= entry['signal_date'] <= week_end:
            continue
        if entry['kind'] != 'agent':
            by_kind.setdefault(entry['kind'], []).append(entry['outcome'])
            continue
        if is_first_version(entry):
            by_kind.setdefault('agent', []).append(entry['outcome'])
        if is_latest_version(entry):
            by_kind.setdefault('agent_latest', []).append(entry['outcome'])
    out = {}
    for kind, outcomes in by_kind.items():
        rs = [o['r'] for o in outcomes if o.get('r') is not None]
        out[kind] = {'count': len(outcomes), 'expired': sum(1 for o in outcomes if o['status'] == 'expired'),
                     'r_mean': statistics.fmean(rs) if rs else None,
                     'r_median': statistics.median(rs) if rs else None}
    return out


def shadow_agent_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """v2.5 §9.1 ``agent_summary`` of the plan-shadow view: ``first`` (each chain's first version) and
    ``latest`` (each chain's current head) over the agent rows; ``determined`` = rows with an R; mean
    and median only from ``SHADOW_MIN_SAMPLE`` determined rows on."""
    def block(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        rs = [o['r'] for o in outcomes if o.get('r') is not None]
        enough = len(rs) >= SHADOW_MIN_SAMPLE
        return {'count': len(outcomes), 'determined': len(rs),
                'expired': sum(1 for o in outcomes if o.get('status') == 'expired'),
                'r_mean': statistics.fmean(rs) if enough else None,
                'r_median': statistics.median(rs) if enough else None}

    agent = [row for row in rows if row.get('kind') == 'agent']
    return {'first': block([row['outcome'] for row in agent if is_first_version(row)]),
            'latest': block([row['outcome'] for row in agent if is_latest_version(row)])}


def pool_of(context: dict | None, entry: dict | None) -> str:
    """Pool of a plan: the frozen context wins, else the tier recorded at the signal date.

    'screen' comes first (a screened pick stays screen even after entering the main
    list); then only 'extended' lands in the extended pool — unknown and legacy
    (P1) plans count as core. Old contexts and entries without a source keep the
    two-way split.
    """
    context = context or {}
    if context.get('source') == 'screen':
        return 'screen'
    entry = entry or {}
    if not context and entry.get('source') == 'screen':
        return 'screen'
    tier = context.get('pool_tier') or entry.get('tier')
    return 'extended' if tier == 'extended' else 'core'


def pool_summary(triggers: list[dict], plan_outcomes: list[dict]) -> dict:
    """Per pool and buy rule: trigger count, plan count, expired, filled and R stats.

    A plan counts once for each of its buy rules; `filled` covers open and closed outcomes.
    Only rule plans count (spec §9): an own plan on the same unit would double it.
    """
    rows: dict[tuple, dict] = {}

    def row(pool: str, rule_id: str) -> dict:
        return rows.setdefault((pool, rule_id), {'triggers': 0, 'plans': 0, 'expired': 0, 'filled': 0, 'r': []})

    for trigger in triggers:
        row(trigger['pool'], trigger['rule_id'])['triggers'] += 1
    for plan in plan_outcomes:
        if plan.get('kind', 'rule') != 'rule':
            continue
        outcome = plan.get('outcome') or {}
        for rule_id in plan.get('rule_ids') or []:
            r = row(plan['pool'], rule_id)
            r['plans'] += 1
            if outcome.get('status') == 'expired':
                r['expired'] += 1
            if outcome.get('status') in ('open', 'closed'):
                r['filled'] += 1
            if outcome.get('r') is not None:
                r['r'].append(outcome['r'])
    out: dict[str, dict] = {}
    for (pool, rule_id), r in rows.items():
        out.setdefault(pool, {})[rule_id] = {
            'triggers': r['triggers'], 'plans': r['plans'], 'expired': r['expired'], 'filled': r['filled'],
            'r_mean': statistics.fmean(r['r']) if r['r'] else None,
            'r_median': statistics.median(r['r']) if r['r'] else None}
    return out


def weekly_stats(week_start: date, units: list[dict[str, Any]], outcomes: dict[Any, dict[str, Any]],
                 trades: list[dict[str, Any]], *, segments: list[dict[str, Any]], undecided: int,
                 entry_opens: dict[Any, float], plan_outcomes: list[dict[str, Any]] | None = None,
                 discipline: dict[str, Any] | None = None, by_pool: dict | None = None,
                 tracks: dict[str, Any] | None = None) -> dict[str, Any]:
    """Snapshot for units whose signal_date falls in the week; values are excess returns vs SPY."""
    week_end = week_start + timedelta(days=6)
    by_rule: dict[str, list] = {}
    by_decision: dict[str, list] = {}
    for u in units:
        for rule_id in dict.fromkeys(u['rule_ids']):
            by_rule.setdefault(rule_id, []).append(u)
        by_decision.setdefault(u['decision'], []).append(u)

    unit_ids = {u['id']: u for u in units}
    live = [t for t in trades if t.get('voided_at') is None]
    execution = []
    for t in live:
        u = unit_ids.get(t.get('decision_id'))
        if u is None:
            continue
        entry = entry_opens.get(u['id']) or outcomes.get(u['id'], {}).get('entry_price')
        execution.append({'trade_id': str(t['id']), 'decision_id': str(u['id']), 'ticker': t['ticker'],
                          'slippage': float(t['price']) / entry - 1 if entry else None,
                          'delay_hours': (t['executed_at'] - u['decided_at']).total_seconds() / 3600})
    unsignaled = [str(t['id']) for t in live
                  if t.get('decision_id') is None and week_start <= _session(t['executed_at']) <= week_end]
    return {
        'calc_version': CALC_VERSION,
        'week': {'start': week_start.isoformat(), 'end': week_end.isoformat()},
        'units': {'decided': len(units), 'undecided': undecided},
        'by_rule': _grouped(by_rule, outcomes),
        'by_decision': _grouped(by_decision, outcomes),
        'execution': execution,
        'unsignaled_trades': unsignaled,
        'closed_trades': segments,
        'plans': _plan_summary(plan_outcomes or [], week_start, week_start + timedelta(days=6)),
        'by_pool': by_pool or {},
        'discipline': discipline or {},
        'tracks': tracks,
        'note': '描述性统计，样本小且重叠，不代表规则有效。',
    }


def save_weekly(conn, week_start: date, stats: dict[str, Any], *, notes: str, supersedes_id) -> dict[str, Any]:
    """Freeze a snapshot. A week's later snapshot must supersede the current head."""
    if week_start.isoweekday() != 1:
        raise ledger.LedgerError('week_start must be a Monday')
    repository.lock(conn, f'weekly:{week_start}')
    head = repository.weekly_head(conn, week_start)
    if (head['id'] if head else None) != supersedes_id:
        raise ledger.Conflict('this week already has a newer review; supersede the latest one')
    return repository.insert_weekly_review(conn, week_start, CALC_VERSION, stats, notes or '', supersedes_id)


def list_weekly(conn, limit: int = 20) -> list[dict[str, Any]]:
    return repository.weekly_heads(conn, limit)
