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

CALC_VERSION = 'review-2'
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


def _plan_summary(plan_outcomes: list[dict[str, Any]], week_start: date, week_end: date) -> dict[str, Any]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for entry in plan_outcomes:
        if not week_start <= entry['signal_date'] <= week_end:
            continue
        by_kind.setdefault(entry['kind'], []).append(entry['outcome'])
    out = {}
    for kind, outcomes in by_kind.items():
        rs = [o['r'] for o in outcomes if o.get('r') is not None]
        out[kind] = {'count': len(outcomes), 'expired': sum(1 for o in outcomes if o['status'] == 'expired'),
                     'r_mean': statistics.fmean(rs) if rs else None,
                     'r_median': statistics.median(rs) if rs else None}
    return out


def weekly_stats(week_start: date, units: list[dict[str, Any]], outcomes: dict[Any, dict[str, Any]],
                 trades: list[dict[str, Any]], *, segments: list[dict[str, Any]], undecided: int,
                 entry_opens: dict[Any, float], plan_outcomes: list[dict[str, Any]] | None = None,
                 discipline: dict[str, Any] | None = None) -> dict[str, Any]:
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
        'discipline': discipline or {},
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
