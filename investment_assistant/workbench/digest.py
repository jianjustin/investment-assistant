"""Assemble the daily push payload (design §7.2). Pure data, no rendering.

Input is what service already read: today()'s units (with plan) and holdings,
plus the batch summary. Nothing here talks to a channel or the database.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from investment_assistant.data.calendar import add_trading_days

EVIDENCE_TEXT = '证据：未验证'  # Phase 0 Gate HOLD
AGENT_BRIEF_VERSIONS = ('agent-1', 'agent-2')


def _agent_field(agent: dict[str, Any] | None) -> dict[str, Any] | None:
    """One unit's agent line data: levels, shares and status from the agent plan, the
    proposal's summary and the counter's first risk (P3 §10.2); v2.5 §10.3 adds the chain's
    version number, the first per-thesis counter and whether the unit is an agent-1 one."""
    if agent is None:
        return None
    plan = agent.get('plan') or {}
    sizing = plan.get('sizing') or {}
    counter = agent.get('counter') or {}
    risks = counter.get('risks') or []
    first_risk = risks[0].get('text') if risks and isinstance(risks[0], dict) else None
    counters = counter.get('counter') or []
    legacy = bool(agent.get('legacy')) or agent.get('agent_version') == 'agent-1'
    if legacy:
        first_counter = first_risk                       # agent-1 has no per-thesis counters
    else:
        first_counter = counters[0].get('text') if counters and isinstance(counters[0], dict) else None
    chain = agent.get('chain') or {}
    latest = chain.get('latest_review') or {}
    return {
        'status': agent.get('status'), 'model': agent.get('model'), 'reason': agent.get('reason'),
        'summary': (agent.get('output') or {}).get('summary'),
        'first_risk': first_risk,
        'entry_low': plan.get('entry_low'), 'entry_high': plan.get('entry_high'),
        'stop': plan.get('stop'), 'target1': plan.get('target1'),
        'shares': sizing.get('shares'), 'sizing_status': sizing.get('status'),
        'plan_status': plan.get('status'), 'invalid_reasons': plan.get('invalid_reasons') or [],
        'version_no': chain.get('version_no'), 'first_counter': first_counter, 'legacy': legacy,
        'chain_state': chain.get('state'),
        'invalidated_reason': latest.get('reason') if chain.get('state') == 'invalidated' else None,
    }


def build(*, session: date, units: list[dict[str, Any]], holdings: list[dict[str, Any]], summary: dict[str, Any],
          last_push_failed: bool, public_url: str, extended_plans: int = 0,
          market: dict[str, Any] | None = None, agent_summary: dict[str, Any] | None = None,
          screen: dict[str, Any] | None = None, plan_updates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """{'session', 'overview', 'plans', 'plan_updates', 'holdings', 'pending', 'errors', 'errors_by_source'}
    for the day's push. `plan_updates` are the review rows of the D25 window, each with its chain's
    `pool`, `from_version` / `to_version`, `changes` (texts), the new version's `levels` and `valid_until`."""
    plans = []
    expiring = []
    tomorrow = add_trading_days(session, 1)
    for u in units:
        agent_field = _agent_field(u.get('agent'))
        plan = u.get('plan')
        if plan is None:
            # Rule plan skipped (e.g. ATR) but the agent plan is ok: the unit still
            # gets one entry, its rule-level fields empty (P3 §10.2).
            if agent_field is None or agent_field['status'] != 'ok':
                continue
            plan = ((u.get('agent') or {}).get('plan'))
        sizing = plan.get('sizing') or {}
        # P4 §7.5: an agent brief (agent-1, or agent-2's summary + first counter) already
        # sits in the agent line; it is not repeated after the plan. Other briefs still attach.
        brief = u.get('brief') or {}
        brief_hidden = brief.get('prompt_version') in AGENT_BRIEF_VERSIONS
        output = {} if brief_hidden else (brief.get('output') or {})
        snapshot_as_of = sizing.get('snapshot_as_of')
        context = (plan.get('inputs') or {}).get('context') or {}
        sector = context.get('sector') or None
        rule_plan = u.get('plan')
        plans.append({
            'ticker': u['ticker'], 'source': u.get('source'),
            'action': u['proposed_action'], 'rule_ids': u.get('rule_ids', []),
            'kind': plan['kind'], 'plan_version': plan.get('plan_version'), 'status': plan['status'],
            'entry_low': rule_plan['entry_low'] if rule_plan else None,
            'entry_high': rule_plan['entry_high'] if rule_plan else None,
            'stop': rule_plan['stop'] if rule_plan else None,
            'target1': rule_plan['target1'] if rule_plan else None,
            'shares': sizing.get('shares') if rule_plan else None,
            'risk_amount': sizing.get('risk_amount') if rule_plan else None,
            'sizing_status': sizing.get('status') if rule_plan else None,
            'snapshot_as_of': snapshot_as_of.isoformat() if snapshot_as_of else None,
            'valid_from': plan['valid_from'], 'valid_until': plan['valid_until'],
            'warnings': plan.get('warnings') or [], 'invalid_reasons': plan.get('invalid_reasons') or [],
            'regime_label': (context.get('regime') or {}).get('label'),
            'next_earnings': context.get('next_earnings').isoformat()
            if isinstance(context.get('next_earnings'), date) else context.get('next_earnings'),
            'sector': sector,
            'evidence': EVIDENCE_TEXT,
            'brief_summary': output.get('summary'),
            'contra': None if brief_hidden else ' | '.join(item.get('text', '') for item in (output.get('contra') or [])
                                 if isinstance(item, dict)),
            'url': f'{public_url.rstrip("/")}/today',
            'agent': agent_field,
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

    updates = select_plan_updates(plan_updates or [])

    return {
        'session': session.isoformat(),
        'overview': {'session': session.isoformat(), 'new_plans': len(plans), 'holdings': len(holdings_out),
                     'pending': len(units), 'errors': len(errors), 'last_push_failed': last_push_failed,
                     'extended_plans': extended_plans,
                     'core_empty': 'core_empty' in (summary.get('errors') or []),
                     'market': market,
                     'agent': _agent_counts(units, session),
                     'agent_quota_exhausted': bool((agent_summary or {}).get('quota_exhausted')),
                     'plan_updates': {kind: sum(1 for u in updates if u['kind'] == kind)
                                      for kind in ('revise', 'invalidate')}},
        'plans': plans,
        'plan_updates': updates,
        'holdings': holdings_out,
        'pending': {'undecided': [u['ticker'] for u in units], 'expiring': expiring},
        'errors': errors,
        'errors_by_source': errors_by_source,
        'screen': screen,
    }


def select_plan_updates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The window's reviews worth a push (v2.5 §10.3): invalidations, and revisions that produced a new
    version. Maintains, failed revisions, skips and errors stay out; so does an extended-pool chain still
    in its entry period (shadow-tracked only). A holding chain is always pushed."""
    out = []
    for row in rows:
        outcome = row.get('outcome')
        if outcome == 'revise' and row.get('new_plan_id') is None:
            continue
        if outcome not in ('revise', 'invalidate'):
            continue
        if row.get('mode') != 'holding' and row.get('pool') == 'extended':
            continue
        out.append({'ticker': row['ticker'], 'kind': outcome, 'from_version': row.get('from_version'),
                    'to_version': row.get('to_version') if outcome == 'revise' else None,
                    'changes': list(row.get('changes') or []) if outcome == 'revise' else [],
                    'levels': row.get('levels') if outcome == 'revise' else None,
                    'valid_until': row.get('valid_until') if outcome == 'revise' else None,
                    'decided_by': row.get('decided_by'), 'reason': row.get('reason')})
    return out


def _agent_counts(units: list[dict[str, Any]], session: date) -> dict[str, int]:
    """Main-list units the agent stage covers (this session's conflict-free buys, §8.1) by
    outcome; anything but ok/pass counts as not given."""
    counts = {'ok': 0, 'pass': 0, 'missing': 0}
    for u in units:
        if (u['signal_date'] != session or u.get('proposed_action') != 'buy'
                or 'conflict' in (u.get('labels') or [])):
            continue
        status = (u.get('agent') or {}).get('status')
        if status in counts:
            counts[status] += 1
        else:
            counts['missing'] += 1
    return counts
