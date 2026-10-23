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
          last_push_failed: bool, public_url: str) -> dict[str, Any]:
    """{'session', 'overview', 'plans', 'holdings', 'pending', 'errors'} for the day's push."""
    plans = []
    expiring = []
    tomorrow = add_trading_days(session, 1)
    for u in units:
        plan = u.get('plan')
        if plan is None:
            continue
        sizing = plan.get('sizing') or {}
        plans.append({
            'ticker': u['ticker'], 'action': u['proposed_action'], 'rule_ids': u.get('rule_ids', []),
            'kind': plan['kind'], 'plan_version': plan.get('plan_version'), 'status': plan['status'],
            'entry_low': plan['entry_low'], 'entry_high': plan['entry_high'],
            'stop': plan['stop'], 'target1': plan['target1'],
            'shares': sizing.get('shares'), 'risk_amount': sizing.get('risk_amount'),
            'sizing_status': sizing.get('status'), 'snapshot_as_of': sizing.get('snapshot_as_of'),
            'valid_from': plan['valid_from'], 'valid_until': plan['valid_until'],
            'warnings': plan.get('warnings') or [], 'invalid_reasons': plan.get('invalid_reasons') or [],
            'evidence': EVIDENCE_TEXT,
            'brief_summary': (u.get('brief') or {}).get('output', {}).get('summary'),
            'url': f'{public_url.rstrip("/")}/today',
        })
        if plan['valid_until'] <= tomorrow:
            expiring.append({'ticker': u['ticker'], 'valid_until': plan['valid_until']})

    holdings_out = []
    for h in holdings:
        earnings_eve = h.get('next_earnings') is not None and h['next_earnings'] == tomorrow.isoformat()
        holdings_out.append({**h, 'earnings_eve': earnings_eve})

    errors = list(summary.get('errors') or [])
    errors += [f"{ticker} earnings: {status.split('error: ', 1)[1]}"
               for ticker, status in (summary.get('earnings') or {}).items()
               if isinstance(status, str) and status.startswith('error:')]

    return {
        'session': session.isoformat(),
        'overview': {'session': session.isoformat(), 'new_plans': len(plans), 'holdings': len(holdings_out),
                     'pending': len(units), 'errors': len(errors), 'last_push_failed': last_push_failed},
        'plans': plans,
        'holdings': holdings_out,
        'pending': {'undecided': [u['ticker'] for u in units], 'expiring': expiring},
        'errors': errors,
    }
