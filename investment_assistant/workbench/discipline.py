"""Execution discipline against confirmed plans (design §6.2). Pure.

Flags: chase (buy above entry_high, judged at fill), early_take (sold before T1
and T1 arrived within 20 sessions, matured after those 20 sessions), held_loser
(no sell through the session after a plan_stop), unplanned (no decision or no
plan). Actual R prices risk at the plan stop, FIFO-matched.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from investment_assistant.data.calendar import add_trading_days

EARLY_TAKE_SESSIONS = 20
NY = ZoneInfo('America/New_York')


def _session(ts) -> date:
    return ts.astimezone(NY).date()


def _splits_of(bars: list[dict[str, Any]]) -> list[tuple[date, Decimal]]:
    return [(b['price_date'], Decimal(str(b['split_factor']))) for b in bars if b['split_factor'] != 1]


def _at_basis(level: Decimal, signal_date: date, day: date, splits: list[tuple[date, Decimal]]) -> Decimal:
    """Express a plan-time level in ``day``'s split basis (for trade-date comparisons)."""
    factor = Decimal(1)
    for split_date, split_factor in splits:
        if signal_date < split_date <= day:
            factor *= split_factor
    return level / factor


def _current_basis(level: Decimal, signal_date: date, splits: list[tuple[date, Decimal]]) -> Decimal:
    """Bars are stored in the current split basis, so bar comparisons use this basis."""
    return _at_basis(level, signal_date, date.max, splits)


def _t1_touched_while_held(bars: list[dict[str, Any]], target1: Decimal, signal_date: date, since: date,
                           through: date, splits: list[tuple[date, Decimal]]) -> bool:
    """Whether T1 traded between the buy and the sell; highs from before the buy never count."""
    target = _current_basis(target1, signal_date, splits)
    return any(since <= b['price_date'] <= through and Decimal(str(b['high'])) >= target for b in bars)


def evaluate(*, trades: list[dict[str, Any]], decisions_by_id: dict, plans_by_id: dict,
             bars_by_ticker: dict[str, list[dict[str, Any]]], stop_events: list[dict[str, Any]],
             segments: list[dict[str, Any]], session: date) -> dict[str, Any]:
    stop_days: dict[str, list[date]] = {}
    for candidate in stop_events:
        if candidate['rule_id'] == 'plan_stop':
            stop_days.setdefault(candidate['ticker'], []).append(candidate['signal_date'])
    segments_by_buy: dict[Any, list[dict[str, Any]]] = {}
    for seg in segments:
        segments_by_buy.setdefault(seg['buy_trade_id'], []).append(seg)
    sell_days_by_ticker = {t: sorted(_session(x['executed_at']) for x in trades
                                     if x['ticker'] == t and x['side'] == 'sell' and x['voided_at'] is None)
                           for t in {x['ticker'] for x in trades}}

    out_trades, counts, immature_counts = [], {'chase': 0, 'early_take': 0, 'held_loser': 0, 'unplanned': 0}, \
        {'early_take': 0, 'held_loser': 0}
    planned_buys = planned_flagged = 0

    for t in (x for x in trades if x['side'] == 'buy' and x['voided_at'] is None):
        ticker, flags, immature = t['ticker'], [], []
        bars = bars_by_ticker.get(ticker, [])
        splits = _splits_of(bars)
        decision = decisions_by_id.get(t['decision_id']) if t['decision_id'] else None
        p = plans_by_id.get(decision['plan_id']) if decision and decision['plan_id'] else None
        track = p['kind'] if p else None
        buy_day = _session(t['executed_at'])
        price = Decimal(str(t['price']))
        r: float | None = None

        if p is None:
            flags.append('unplanned')
        else:
            planned_buys += 1
            if price > _at_basis(p['entry_high'], p['signal_date'], buy_day, splits):
                flags.append('chase')
            # Actual R over this lot's closed segments, risk priced at the plan stop.
            total_qty = Decimal(0)
            weighted = Decimal(0)
            stop_at_buy = _at_basis(p['stop'], p['signal_date'], buy_day, splits)
            for seg in segments_by_buy.get(t['id'], []):
                entry, exit_ = seg['entry_cost_per_share'], seg['exit_price']
                if entry - stop_at_buy == 0:
                    continue
                weighted += seg['quantity'] * (exit_ - entry) / (entry - stop_at_buy)
                total_qty += seg['quantity']
            r = float(weighted / total_qty) if total_qty else None
            # Early take: sold before T1, not executing a plan_stop, and T1 arrived within 20 sessions.
            for seg in segments_by_buy.get(t['id'], []):
                sell_day = _session(seg['closed_at'])
                if _t1_touched_while_held(bars, p['target1'], p['signal_date'], buy_day, sell_day, splits):
                    continue
                if any(d <= sell_day <= add_trading_days(d, 1) for d in stop_days.get(ticker, [])):
                    continue  # the sell followed a plan_stop within a session: executing the stop is the plan
                window_end = add_trading_days(sell_day, EARLY_TAKE_SESSIONS)
                if session < window_end:
                    immature.append('early_take')
                    continue
                window = [b for b in bars if sell_day < b['price_date'] <= window_end]
                if any(Decimal(str(b['high'])) >= _current_basis(p['target1'], p['signal_date'], splits)
                       for b in window):
                    flags.append('early_take')
            # Held loser: a plan_stop fired on an open lot and no sell followed through the next session.
            sells = sell_days_by_ticker.get(ticker, [])
            for stop_day in sorted(stop_days.get(ticker, [])):
                if stop_day < buy_day:
                    continue
                segs = segments_by_buy.get(t['id'], [])
                if segs and all(_session(s['closed_at']) < stop_day for s in segs):
                    continue  # this lot was already gone
                deadline = add_trading_days(stop_day, 1)
                if session < deadline:
                    immature.append('held_loser')
                    continue
                if not any(stop_day <= s <= deadline for s in sells):
                    flags.append('held_loser')

        for flag in dict.fromkeys(flags):
            counts[flag] += 1
        for flag in dict.fromkeys(immature):
            immature_counts[flag] += 1
        if p is not None and flags:
            planned_flagged += 1
        out_trades.append({'trade_id': str(t['id']), 'ticker': ticker, 'track': track, 'flags': flags,
                           'immature': list(dict.fromkeys(immature)), 'r': r})

    return {'trades': out_trades, 'counts': counts, 'immature': immature_counts, 'planned_buys': planned_buys,
            'compliance_rate': (planned_buys - planned_flagged) / planned_buys if planned_buys else None}
