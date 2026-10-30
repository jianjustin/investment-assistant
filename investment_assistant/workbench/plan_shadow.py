"""Plan outcome simulation (plan-shadow-1, design §6.1; plan-shadow-2, v2.9 spec §5.6). Pure; frozen at review time.

Independent of actual fills: the plan is replayed bar by bar from its validity
window. Stops exit at the open when the open gaps through them; the trailing
stop updates after each close and applies from the next session.

`simulate` is `plan-shadow-1` untouched. `simulate_v2` (`plan-shadow-2`) changes three things: the entry follows
the open scenarios of `entry_rules` (a gap to or below the stop voids the plan, `next_open` looks at the first
valid day only), a time stop exits at the next open, and a void is a status of its own. `simulate_both` gives
the counterfactual pair for plans that carry execution fields.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from investment_assistant.workbench import entry_rules
from investment_assistant.workbench.plans import MAX_HOLD_DEFAULT

SHADOW_V1 = 'plan-shadow-1'
SHADOW_V2 = 'plan-shadow-2'
# The current shadow version (spec §2). The read views run `simulate_both` and label each outcome with the version
# that produced it (`service.shadow_outcomes`); `plan-shadow-1` stays for plans without execution fields.
SHADOW_VERSION = SHADOW_V2


def _basis_factor(day: date, splits: list[tuple[date, Decimal]]) -> Decimal:
    factor = Decimal(1)
    for split_date, split_factor in splits:
        if day < split_date:
            factor *= split_factor
    return factor


def _spy_return(spy_bars: list[dict[str, Any]], fill_day: date, last_day: date | None) -> float | None:
    index = {b['price_date']: b for b in spy_bars}
    if last_day is None:
        last_day = max(index) if index else None
    if last_day is None or fill_day not in index or last_day not in index:
        return None
    return float(index[last_day]['adj_close'] / index[fill_day]['adj_close'] - 1)


def simulate(plan: dict[str, Any], bars: list[dict[str, Any]], spy_bars: list[dict[str, Any]],
             *, splits: list[tuple[date, Decimal]]) -> dict[str, Any]:
    """Replay one plan over ``bars`` (oldest first, split-adjusted OHLC)."""
    # Bars arrive in the current split basis (storage is split-adjusted with revisions);
    # only the plan's frozen levels move to that basis.
    splits = sorted(splits)
    rescale = _basis_factor(plan['signal_date'], splits)
    entry_low = plan['entry_low'] / rescale
    entry_high = plan['entry_high'] / rescale
    stop0 = plan['stop'] / rescale
    target1 = plan['target1'] / rescale
    atr = plan['atr'] / rescale

    latest_day = bars[-1]['price_date'] if bars else None
    window = [b for b in bars if plan['valid_from'] <= b['price_date'] <= plan['valid_until']]

    fill_date, fill_price, fill_bar = None, None, None
    for bar in window:
        op, hi, lo = Decimal(str(bar['open'])), Decimal(str(bar['high'])), Decimal(str(bar['low']))
        if lo > entry_high or hi < entry_low:
            continue
        fill_price = op if entry_low <= op <= entry_high else (entry_high if op > entry_high else entry_low)
        fill_date, fill_bar = bar['price_date'], bar
        break
    if fill_bar is None:
        expired = latest_day is not None and latest_day >= plan['valid_until']
        return {'status': 'expired' if expired else 'pending', 'fill_date': None, 'fill_price': None,
                'legs': [], 'r': None, 'return': None, 'spy_return': None}

    stop = stop0
    t1_done = False
    highest_close = None
    legs: list[dict[str, Any]] = []
    last_day = fill_date
    for bar in (b for b in bars if b['price_date'] >= fill_date):
        op, hi, lo, cl = (Decimal(str(bar['open'])), Decimal(str(bar['high'])),
                          Decimal(str(bar['low'])), Decimal(str(bar['close'])))
        last_day = bar['price_date']
        highest_close = cl if highest_close is None else max(highest_close, cl)
        if lo <= stop:  # stop first when both stop and T1 touch on the same day
            price = op if op < stop else stop
            legs.append({'fraction': 0.5 if t1_done else 1.0, 'exit_date': bar['price_date'].isoformat(),
                         'exit_price': price, 'reason': 'trail' if t1_done else 'stop'})
            break
        if not t1_done and hi >= target1:
            legs.append({'fraction': 0.5, 'exit_date': bar['price_date'].isoformat(),
                         'exit_price': max(op, target1), 'reason': 'target1'})
            t1_done = True
        if t1_done:  # trailing stop updates after the close, effective next session
            stop = max(highest_close - plan['trail_atr_multiple'] * atr, fill_price)

    risk = fill_price - stop0
    closed_fraction = sum(leg['fraction'] for leg in legs)
    closed_value = sum(Decimal(str(leg['fraction'])) * leg['exit_price'] for leg in legs)
    r_sum = sum(leg['fraction'] * float((leg['exit_price'] - fill_price) / risk) for leg in legs)
    closed = closed_fraction >= 1.0
    if closed:
        return {'status': 'closed', 'fill_date': fill_date, 'fill_price': fill_price, 'legs': legs,
                'r': r_sum, 'return': float(closed_value / fill_price - 1),
                'spy_return': _spy_return(spy_bars, fill_date, last_day)}
    open_fraction = 1 - closed_fraction
    last_close = Decimal(str(bars[-1]['close']))
    return {'status': 'open', 'fill_date': fill_date, 'fill_price': fill_price, 'legs': legs,
            'r': r_sum + open_fraction * float((last_close - fill_price) / risk),
            'return': float((closed_value + Decimal(str(open_fraction)) * last_close) / fill_price - 1),
            'spy_return': _spy_return(spy_bars, fill_date, None)}


# ---------------------------------------------------------------- plan-shadow-2

def has_exec_fields(plan: dict[str, Any]) -> bool:
    """plan-2, agent-3 and v2.9 own plans carry both execution fields; older rows have neither (spec §8.2)."""
    return plan.get('entry_type') is not None and plan.get('max_hold_sessions') is not None


def simulate_v2(plan: dict[str, Any], bars: list[dict[str, Any]], spy_bars: list[dict[str, Any]],
                *, splits: list[tuple[date, Decimal]]) -> dict[str, Any]:
    """`plan-shadow-2`: replay one plan with the open scenarios and the time stop.

    Same inputs and result keys as `simulate`, plus `void_reason` / `void_date` and `time_stop_due`. A void
    (`status = 'voided'`, reason `gap_below_stop` / `gap_above_zone` / `gap_below_zone`) carries no R: the
    caller scores it 0R and counts it apart. The time stop (spec §5.6, R9): counting the fill day as day 1,
    when the close of day n >= max_hold_sessions and no close since the fill reached fill + 1R (R = fill price
    minus the initial stop) and T1 has not traded, the position leaves at the next day's open (`time_stop`);
    a stop touched on day n itself goes first. After T1 the time stop no longer applies.
    """
    splits = sorted(splits)
    rescale = _basis_factor(plan['signal_date'], splits)
    entry_low = plan['entry_low'] / rescale
    entry_high = plan['entry_high'] / rescale
    stop0 = plan['stop'] / rescale
    target1 = plan['target1'] / rescale
    atr = plan['atr'] / rescale
    max_hold = plan.get('max_hold_sessions') or MAX_HOLD_DEFAULT

    entry = entry_rules.simulate_entry(
        {'entry_low': entry_low, 'entry_high': entry_high, 'stop': stop0,
         'entry_type': plan.get('entry_type') or entry_rules.DEFAULT_ENTRY_TYPE,
         'valid_from': plan['valid_from'], 'valid_until': plan['valid_until']}, bars)
    base = {'fill_date': None, 'fill_price': None, 'legs': [], 'r': None, 'return': None, 'spy_return': None,
            'void_reason': None, 'void_date': None, 'time_stop_due': False}
    if entry['status'] != 'filled':
        return {**base, 'status': entry['status'], 'void_reason': entry['void_reason'],
                'void_date': entry['void_date']}
    fill_date, fill_price = entry['fill_date'], entry['fill_price']

    stop = stop0
    risk = fill_price - stop0
    t1_done = False
    reached_1r = False
    time_stop_due = False
    highest_close = None
    legs: list[dict[str, Any]] = []
    last_day = fill_date
    for index, bar in enumerate((b for b in bars if b['price_date'] >= fill_date), start=1):
        op, hi, lo, cl = (Decimal(str(bar['open'])), Decimal(str(bar['high'])),
                          Decimal(str(bar['low'])), Decimal(str(bar['close'])))
        last_day = bar['price_date']
        if time_stop_due:                        # decided at yesterday's close: leave at today's open
            legs.append({'fraction': 1.0, 'exit_date': bar['price_date'].isoformat(), 'exit_price': op,
                         'reason': 'time_stop'})
            time_stop_due = False
            break
        highest_close = cl if highest_close is None else max(highest_close, cl)
        if lo <= stop:  # stop first when both stop and T1 touch on the same day
            price = op if op < stop else stop
            legs.append({'fraction': 0.5 if t1_done else 1.0, 'exit_date': bar['price_date'].isoformat(),
                         'exit_price': price, 'reason': 'trail' if t1_done else 'stop'})
            break
        if not t1_done and hi >= target1:
            legs.append({'fraction': 0.5, 'exit_date': bar['price_date'].isoformat(),
                         'exit_price': max(op, target1), 'reason': 'target1'})
            t1_done = True
        if t1_done:  # trailing stop updates after the close, effective next session
            stop = max(highest_close - plan['trail_atr_multiple'] * atr, fill_price)
        elif not reached_1r and risk > 0 and cl >= fill_price + risk:
            reached_1r = True
        if not t1_done and not reached_1r and risk > 0 and index >= max_hold:
            time_stop_due = True

    risk = fill_price - stop0
    closed_fraction = sum(leg['fraction'] for leg in legs)
    closed_value = sum(Decimal(str(leg['fraction'])) * leg['exit_price'] for leg in legs)
    r_sum = sum(leg['fraction'] * float((leg['exit_price'] - fill_price) / risk) for leg in legs)
    if closed_fraction >= 1.0:
        return {**base, 'status': 'closed', 'fill_date': fill_date, 'fill_price': fill_price, 'legs': legs,
                'r': r_sum, 'return': float(closed_value / fill_price - 1),
                'spy_return': _spy_return(spy_bars, fill_date, last_day)}
    open_fraction = 1 - closed_fraction
    last_close = Decimal(str(bars[-1]['close']))
    return {**base, 'status': 'open', 'fill_date': fill_date, 'fill_price': fill_price, 'legs': legs,
            'r': r_sum + open_fraction * float((last_close - fill_price) / risk),
            'return': float((closed_value + Decimal(str(open_fraction)) * last_close) / fill_price - 1),
            'spy_return': _spy_return(spy_bars, fill_date, None), 'time_stop_due': time_stop_due}


def simulate_both(plan: dict[str, Any], bars: list[dict[str, Any]], spy_bars: list[dict[str, Any]],
                  *, splits: list[tuple[date, Decimal]]) -> dict[str, dict[str, Any]]:
    """`{'v2': plan-shadow-2, 'v1': plan-shadow-1}` for a plan with execution fields (the v1 column is the
    counterfactual 「无时间止损、旧入场规则」, D14); `{'v1': …}` alone for an older plan."""
    out = {'v1': simulate(plan, bars, spy_bars, splits=splits)}
    if has_exec_fields(plan):
        out = {'v2': simulate_v2(plan, bars, spy_bars, splits=splits), **out}
    return out
