"""Plan outcome simulation (plan-shadow-1, design §6.1). Pure; frozen at review time.

Independent of actual fills: the plan is replayed bar by bar from its validity
window. Stops exit at the open when the open gaps through them; the trailing
stop updates after each close and applies from the next session.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

SHADOW_VERSION = 'plan-shadow-1'


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
    splits = sorted(splits)
    rescale = _basis_factor(plan['signal_date'], splits)
    entry_low = plan['entry_low'] / rescale
    entry_high = plan['entry_high'] / rescale
    stop0 = plan['stop'] / rescale
    target1 = plan['target1'] / rescale
    atr = plan['atr'] / rescale

    def basis(bar: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        f = _basis_factor(bar['price_date'], splits)
        return (Decimal(str(bar['open'])) / f, Decimal(str(bar['high'])) / f,
                Decimal(str(bar['low'])) / f, Decimal(str(bar['close'])) / f)

    latest_day = bars[-1]['price_date'] if bars else None
    window = [b for b in bars if plan['valid_from'] <= b['price_date'] <= plan['valid_until']]

    fill_date, fill_price, fill_bar = None, None, None
    for bar in window:
        op, hi, lo, _ = basis(bar)
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
        op, hi, lo, cl = basis(bar)
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
    last_close = basis(bars[-1])[3]
    return {'status': 'open', 'fill_date': fill_date, 'fill_price': fill_price, 'legs': legs,
            'r': r_sum + open_fraction * float((last_close - fill_price) / risk),
            'return': float((closed_value + Decimal(str(open_fraction)) * last_close) / fill_price - 1),
            'spy_return': _spy_return(spy_bars, fill_date, None)}
