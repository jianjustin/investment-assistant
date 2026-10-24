"""Assemble the daily push payload (design §7.2). Pure data, no rendering.

Input is what service already read: today()'s units (with plan) and holdings,
plus the batch summary. Nothing here talks to a channel or the database.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from investment_assistant.data.calendar import add_trading_days

EVIDENCE_TEXT = '证据：未验证'  # Phase 0 Gate HOLD


def build(*, session: date, units: list[dict[str, Any]], holdings: list[dict[str, Any]], summary: dict[str, Any],
          last_push_failed: bool, public_url: str, extended_plans: int = 0,
          market: dict[str, Any] | None = None) -> dict[str, Any]:
    """{'session', 'overview', 'plans', 'holdings', 'pending', 'errors', 'errors_by_source'} for the day's push."""
    plans = []
    expiring = []
    tomorrow = add_trading_days(session, 1)
    for u in units:
        plan = u.get('plan')
        if plan is None:
            continue
        sizing = plan.get('sizing') or {}
        output = (u.get('brief') or {}).get('output') or {}
        snapshot_as_of = sizing.get('snapshot_as_of')
        context = (plan.get('inputs') or {}).get('context') or {}
        sector = context.get('sector') or None
        plans.append({
            'ticker': u['ticker'], 'action': u['proposed_action'], 'rule_ids': u.get('rule_ids', []),
            'kind': plan['kind'], 'plan_version': plan.get('plan_version'), 'status': plan['status'],
            'entry_low': plan['entry_low'], 'entry_high': plan['entry_high'],
            'stop': plan['stop'], 'target1': plan['target1'],
            'shares': sizing.get('shares'), 'risk_amount': sizing.get('risk_amount'),
            'sizing_status': sizing.get('status'),
            'snapshot_as_of': snapshot_as_of.isoformat() if snapshot_as_of else None,
            'valid_from': plan['valid_from'], 'valid_until': plan['valid_until'],
            'warnings': plan.get('warnings') or [], 'invalid_reasons': plan.get('invalid_reasons') or [],
            'regime_label': (context.get('regime') or {}).get('label'),
            'next_earnings': context.get('next_earnings').isoformat()
            if isinstance(context.get('next_earnings'), date) else context.get('next_earnings'),
            'sector': sector,
            'evidence': EVIDENCE_TEXT,
            'brief_summary': output.get('summary'),
            'contra': ' | '.join(item.get('text', '') for item in (output.get('contra') or [])
                                 if isinstance(item, dict)),
            'url': f'{public_url.rstrip("/")}/today',
        })
        if plan['valid_until'] <= tomorrow:
            expiring.append({'ticker': u['ticker'], 'valid_until': plan['valid_until']})

    def alerts(ticker: str) -> list[str]:
        candidates = (summary.get('tickers') or {}).get(ticker, {}).get('candidates') or []
        return [c for c in ('plan_stop', 'plan_target') if c in candidates]

    holdings_out = []
    for h in holdings:
        earnings_eve = h.get('next_earnings') is not None and h['next_earnings'] == tomorrow.isoformat()
        holdings_out.append({**h, 'earnings_eve': earnings_eve, 'plan_alerts': alerts(h['ticker'])})

    errors = list(summary.get('errors') or [])
    errors += [f"{ticker} earnings: {status.split('error: ', 1)[1]}"
               for ticker, status in (summary.get('earnings') or {}).items()
               if isinstance(status, str) and status.startswith('error:')]

    errors_by_source = {source: list(items) for source, items in (summary.get('sources') or {}).items() if items}
    budget = [e for e in errors if e.startswith('batch_over_budget')]
    if budget:
        errors_by_source['budget'] = budget

    return {
        'session': session.isoformat(),
        'overview': {'session': session.isoformat(), 'new_plans': len(plans), 'holdings': len(holdings_out),
                     'pending': len(units), 'errors': len(errors), 'last_push_failed': last_push_failed,
                     'extended_plans': extended_plans,
                     'core_empty': 'core_empty' in (summary.get('errors') or []),
                     'market': market},
        'plans': plans,
        'holdings': holdings_out,
        'pending': {'undecided': [u['ticker'] for u in units], 'expiring': expiring},
        'errors': errors,
        'errors_by_source': errors_by_source,
    }
