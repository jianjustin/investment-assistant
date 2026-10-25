"""Three-track comparison per decision unit (P4 design §4): rule plan, agent
plan and the actually executed result, all in R of each track's own stop.
Pure functions; the row assembly and SQL live in repository/service.

「没算出来」（pending、missing）与「0R」（没交易）分开：均值与中位数只
用 r 不为空的结果，not_executable / expired / not_executed 记 0。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from statistics import median
from typing import Any

from investment_assistant.workbench.discipline import _at_basis, _current_basis

TRACKS_VERSION = 'tracks-1'

TRACK_STATUS_TEXT = {
    'missing': '缺失',
    'not_executable': '计划作废',
    'pending': '待定',
    'expired': '到期未成交',
    'open': '未平仓',
    'closed': '已平仓',
    'pass': '不建议',
    'not_executed': '未执行',
    'no_plan': '无计划成交',
}


def plan_track(plan: dict[str, Any] | None, outcome: dict[str, Any] | None) -> dict[str, Any]:
    """§4.2's rule table applied to one plan and its simulated outcome."""
    if plan is None:
        return {'plan_id': None, 'status': 'missing', 'r': None}
    if plan.get('status') == 'invalid':
        return {'plan_id': plan['id'], 'status': 'not_executable', 'r': 0.0}
    if outcome is None:
        return {'plan_id': plan['id'], 'status': 'missing', 'r': None}
    status = outcome['status']
    r = 0.0 if status == 'expired' else outcome.get('r')
    return {'plan_id': plan['id'], 'status': status, 'r': r}


def agent_track(run: dict[str, Any] | None, plan: dict[str, Any] | None,
                outcome: dict[str, Any] | None) -> dict[str, Any]:
    """The unit's latest propose run: pass scores 0, ok follows its agent plan,
    everything else is missing with the run status and reason kept."""
    if run is None:
        return {'run_id': None, 'run_status': None, 'run_reason': None,
                'plan_id': None, 'status': 'missing', 'r': None}
    base = {'run_id': run['id'], 'run_status': run['status'], 'run_reason': run.get('reason')}
    if run['status'] == 'pass':
        return {**base, 'plan_id': None, 'status': 'pass', 'r': 0.0}
    if run['status'] == 'ok':
        track = plan_track(plan, outcome)
        return {**base, 'plan_id': track['plan_id'], 'status': track['status'], 'r': track['r']}
    return {**base, 'plan_id': None, 'status': 'missing', 'r': None}


def _day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def actual_track(*, decision: dict[str, Any] | None, plan: dict[str, Any] | None, buys: list[dict[str, Any]],
                 segments: list[dict[str, Any]], open_lots: list[dict[str, Any]],
                 last_close: Decimal | None, splits: list[tuple[date, Decimal]],
                 session: date, unit_valid_until: date | None) -> dict[str, Any]:
    """§4.2's actual table: what you did with this unit, in R of the chosen
    plan's stop. Closed legs price the risk at the buy-date basis (the same
    formula as the discipline metrics); open lots convert stop and cost to the
    current basis and use the latest close."""
    out = {'decision_id': decision['id'] if decision else None,
           'final_action': decision['final_action'] if decision else None,
           'plan_id': decision['plan_id'] if decision else None,
           'plan_kind': plan['kind'] if plan else None,
           'buy_trade_ids': [b['id'] for b in buys],
           'status': None, 'r': None, 'open': False}
    if decision is not None and decision['final_action'] != 'buy':
        return {**out, 'status': 'not_executed', 'r': 0.0}
    if not buys:
        valid_until = unit_valid_until
        if decision is not None and plan is not None and plan['valid_until'] < session:
            return {**out, 'status': 'not_executed', 'r': 0.0}
        if valid_until is None or valid_until < session:
            return {**out, 'status': 'not_executed', 'r': 0.0}
        return {**out, 'status': 'pending', 'r': None}
    if plan is None or decision is None or decision.get('plan_id') is None:
        return {**out, 'plan_kind': plan['kind'] if plan else None,
                'status': 'no_plan', 'r': None}
    total_qty = Decimal(0)
    weighted = Decimal(0)
    for seg in segments:
        buy_day = _day(seg['opened_at'])
        stop_at_buy = _at_basis(plan['stop'], plan['signal_date'], buy_day, splits)
        entry, exit_ = seg['entry_cost_per_share'], seg['exit_price']
        if entry - stop_at_buy == 0:
            continue
        weighted += seg['quantity'] * (exit_ - entry) / (entry - stop_at_buy)
        total_qty += seg['quantity']
    open_qty = sum((lot['quantity'] for lot in open_lots), Decimal(0))
    if open_qty and last_close is not None:
        stop_now = _current_basis(plan['stop'], plan['signal_date'], splits)
        for lot in open_lots:
            if lot['cost_per_share'] - stop_now == 0:
                continue
            weighted += lot['quantity'] * (last_close - lot['cost_per_share']) / (lot['cost_per_share'] - stop_now)
            total_qty += lot['quantity']
    if total_qty == 0:
        return {**out, 'status': 'pending', 'r': None}
    r = float(weighted / total_qty)
    status = 'open' if open_qty else 'closed'
    return {**out, 'status': status, 'r': r, 'open': status == 'open'}


def _stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    rs = [result['r'] for result in results if result['r'] is not None]
    by_status: dict[str, int] = {}
    for result in results:
        by_status[result['status']] = by_status.get(result['status'], 0) + 1
    return {'units': len(results), 'determined': len(rs),
            'pending': sum(1 for result in results if result['status'] == 'pending'),
            'missing': sum(1 for result in results if result['status'] in ('missing', 'no_plan')),
            'mean': sum(rs) / len(rs) if rs else None,
            'median': median(rs) if rs else None,
            'sum': sum(rs) if rs else None,
            'wins': sum(1 for r in rs if r > 0),
            'by_status': by_status}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """§4.3: counts and descriptive stats per pool and track; no significance tests."""
    out: dict[str, Any] = {}
    for pool in ('all', 'core', 'extended'):
        group = rows if pool == 'all' else [row for row in rows if row['pool'] == pool]
        block = {track: _stats([row[track] for row in group]) for track in ('rule', 'agent', 'actual')}
        kinds: dict[str, int] = {}          # plan_kind as a string key: None (no plan) sorts in JSON
        for row in group:
            kind = row['actual'].get('plan_kind') or 'none'
            kinds[kind] = kinds.get(kind, 0) + 1
        block['actual']['by_plan_kind'] = kinds
        out[pool] = block
    return out
