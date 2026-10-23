"""Monthly return math, tiers, review flag and risk sensitivity (design §8.2). Pure.

Returns are broker-equity based, net of deposits and withdrawals; a month
without a usable snapshot at either end reports missing_snapshot, never zero.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

MONTHLY_VERSION = 'monthly-1'
SENSITIVITY_PCTS = (0.005, 0.01, 0.015, 0.02)


def _month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def _usable(snapshots: list[dict[str, Any]], through: date) -> dict[str, Any] | None:
    superseded = {s['supersedes_id'] for s in snapshots if s['supersedes_id']}
    live = [s for s in snapshots if s['id'] not in superseded and s['as_of'] <= through]
    return max(live, key=lambda s: (s['as_of'], s['recorded_at']), default=None)


def month_return(month: date, snapshots: list[dict[str, Any]], flows: list[dict[str, Any]]) -> dict[str, Any]:
    """(end − start − net deposits and withdrawals) / start over one calendar month."""
    start = _usable(snapshots, month - timedelta(days=1))
    end = _usable(snapshots, _month_end(month))
    if start is None or end is None:
        return {'status': 'missing_snapshot', 'start': start, 'end': end, 'net_flow': None, 'return': None}
    net = sum((f['amount'] for f in flows if f['voided_at'] is None
               and start['as_of'] < f['flow_date'] <= end['as_of']), Decimal(0))
    return {'status': 'ok', 'start': start, 'end': end, 'net_flow': float(net),
            'return': float((end['equity'] - start['equity'] - net) / start['equity'])}


def tier(r: float, tiers: tuple[float, float, float]) -> str:
    if r > tiers[0]:
        return 'excellent_plus'
    if r >= tiers[1]:
        return 'excellent'
    if r >= tiers[2]:
        return 'viable'
    return 'attention'


def review_flag(last_three: list[dict[str, Any]]) -> str:
    """'review' needs a negative compound return that also trails SPY over the same months."""
    if len(last_three) < 3 or any(m.get('return') is None or m.get('spy_return') is None for m in last_three):
        return 'insufficient'
    compound = 1.0
    spy_compound = 1.0
    for m in last_three:
        compound *= 1 + m['return']
        spy_compound *= 1 + m['spy_return']
    compound, spy_compound = compound - 1, spy_compound - 1
    return 'review' if compound < 0 and compound < spy_compound else 'ok'


def sensitivity(rs: list[float], pcts: tuple[float, ...] = SENSITIVITY_PCTS) -> list[dict[str, Any]]:
    """Approximate: return ≈ ΣR × risk_pct, drawdown = the deepest cumulative-R decline × risk_pct."""
    cumulative = peak = max_dd = 0.0
    for r in rs:
        cumulative += r
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return [{'risk_pct': pct, 'return': sum(rs) * pct, 'max_drawdown': max_dd * pct} for pct in pcts]
