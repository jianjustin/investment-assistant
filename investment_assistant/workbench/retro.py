"""Review cards (v2.7 spec §4, ``retro-1``): end events, reference plan, frozen facts, decision text and card
status. Pure functions over rows the caller has already read: no database, no clock, and no ``service``,
``agent`` or ``repository`` import. The host freezes the numbers here; the Agent only narrates them.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from investment_assistant.data.calendar import add_trading_days
# private helpers on purpose: reuse discipline's own split-basis / T1 judgement, as tracks.py does
from investment_assistant.workbench.discipline import _current_basis, _splits_of, _t1_touched_while_held
from investment_assistant.workbench.tracks import TRACK_STATUS_TEXT

RETRO_VERSION = 'retro-1'
RETRO_LOOKBACK_SESSIONS = 5        # D6: only end events within the last 5 sessions are detected
RETRO_MAX_DRAFTS = 5               # drafts started per batch run (§4.4)
RETRO_MAX_ATTEMPTS = 3             # rejected / error drafts before a card counts as failed
LESSONS_MAX = 3

NY = ZoneInfo('America/New_York')

END_KINDS = ('position_closed', 'stop', 'target', 'expired', 'invalidated')
END_PRIORITY = ('invalidated', 'stop', 'target', 'expired')       # same-day order of the no-position ends
END_TEXT = {'position_closed': '平仓', 'stop': '止损', 'target': '到 T1', 'expired': '过期未成交',
            'invalidated': '作废'}
EXIT_BASIS_TEXT = {'stop': '按止损', 'target': '到 T1 后', 'other': '自行卖出'}
DECISION_TEXT = {
    'accept_rule': '采纳（照规则计划）',
    'accept_agent': '采纳（照 Agent 第 {n} 版）',
    'accept_agent_legacy': '采纳（照 Agent agent-1）',
    'accept_own': '自改价位',
    'reject': '否决',
    'downgrade': '降为观察',
    'none': '未决定（计划外成交）',
    'accept': '采纳',                                              # accepted, but the executed plan is unknown
}
FACT_KEYS = ('subject', 'plans', 'bars_after', 'shadow', 'tracks', 'decision', 'trades', 'discipline', 'reviews',
             'knowledge')
CARD_STATUSES = ('reviewed', 'to_review', 'draft_failed', 'drafting')
CARD_STATUS_TEXT = {'reviewed': '已审定', 'to_review': '待审定', 'draft_failed': '起草失败（可手动审定或重新起草）',
                    'drafting': '起草中'}

FLAG_ORDER = ('chase', 'early_take', 'held_loser', 'unplanned')
FLAG_TEXT = {'chase': '追高', 'early_take': '过早止盈', 'held_loser': '死扛亏损', 'unplanned': '计划外'}
PENDING_TEXT = {'early_take': '待定（卖出后 20 个交易日才能判定）', 'held_loser': '待定（止损次日之后判定）'}

_SHADOW_END_KIND = {'stop': 'stop', 'trail': 'stop', 'target1': 'target'}   # plan_shadow leg reasons


# ---- small helpers ------------------------------------------------------------------------------------

def _day(value: Any) -> date | None:
    """A date from a date, a datetime (its own date) or an ISO string; None stays None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _ny_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(NY).date()
    return _day(value)


def _jsonable(value: Any) -> Any:
    """Plain JSON types (Decimal as a normalised string, dates and ids as strings), recursively."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return str(value)


def _id(value: Any) -> str | None:
    return None if value is None else str(value)


# ---- reference plan, keys, exit basis -----------------------------------------------------------------

def reference_plan(*, decision: dict[str, Any] | None, plans: list[dict[str, Any]], has_buys: bool,
                   buys: list[dict[str, Any]] | tuple = (),
                   chain: list[dict[str, Any]] | tuple = ()) -> dict[str, Any] | None:
    """D3. With a position: the plan the decision executed (``signal_decisions.plan_id`` only, never a fallback).
    A buy can sit on any decision of the unit and only an accept carries a ``plan_id``, so the executed plan is
    (1) the plan of the decision the live ``buys`` are attached to (the latest buy whose decision has a plan_id
    that is among ``plans``), else (2) the most recent decision of the ``chain`` (rows ``{id, plan_id}`` oldest
    first; the head ``decision`` when no chain is given) that carries one. Without a position: that plan, else
    the Agent version the user saw when deciding, else the rule plan ``plan-1``, else the ``agent-1`` plan."""
    def find(plan_id: Any) -> dict[str, Any] | None:
        if plan_id is None:
            return None
        return next((p for p in plans if str(p['id']) == str(plan_id)), None)

    if has_buys:
        plan_of = {str(d['id']): d.get('plan_id') for d in chain}
        for buy in sorted(buys, key=lambda b: (b['executed_at'], str(b['id'])), reverse=True):
            found = find(plan_of.get(str(buy.get('decision_id'))))
            if found is not None:
                return found
        for row in reversed(list(chain) or ([decision] if decision else [])):
            found = find(row.get('plan_id'))
            if found is not None:
                return found
        return None
    executed = find(decision.get('plan_id')) if decision else None
    if executed is not None:
        return executed
    seen = find(decision.get('agent_plan_id')) if decision else None
    if seen is not None:
        return seen
    rule = next((p for p in plans if p.get('kind') == 'rule' and p.get('plan_version') == 'plan-1'), None)
    if rule is not None:
        return rule
    return next((p for p in plans if p.get('kind') == 'agent' and p.get('plan_version') == 'agent-1'), None)


def event_key(*, subject: str, ticker: str, signal_date: date | None, closing_sell_id: Any = None,
              buy_trade_id: Any = None) -> str:
    """D4: ``trade:<buy id>`` for an unplanned buy, ``unit:<T>:<date>:closed:<sell id>`` for a closed unit,
    ``unit:<T>:<date>:ended`` for a unit that ended without a position."""
    if subject == 'trade':
        return f'trade:{buy_trade_id}'
    base = f'unit:{ticker.upper()}:{signal_date.isoformat()}'
    return f'{base}:closed:{closing_sell_id}' if closing_sell_id is not None else f'{base}:ended'


def _followed_signal(day: date, signal_days: list[date]) -> bool:
    """The sell fell on a plan_stop / plan_target signal day or the session after (the discipline rule)."""
    return any(d <= day <= add_trading_days(d, 1) for d in signal_days)


def exit_basis(*, closing_sell: dict[str, Any], stop_days: list[date], target_days: list[date],
               t1_touched_while_held: bool) -> str:
    """How the last lot was sold, described only: ``stop`` when it followed a plan_stop signal within a
    session, else ``target`` when T1 traded while held or it followed a plan_target signal, else ``other``.
    ``closing_sell`` is a sell trade (``executed_at``) or a closed segment (``closed_at``)."""
    sell_day = _ny_day(closing_sell.get('executed_at') or closing_sell.get('closed_at'))
    if _followed_signal(sell_day, stop_days):
        return 'stop'
    if t1_touched_while_held or _followed_signal(sell_day, target_days):
        return 'target'
    return 'other'


# ---- end event ----------------------------------------------------------------------------------------

def _last_segment(segments, open_lots):
    """The segment that flattened the position, or None while a lot is still held / nothing was sold."""
    if open_lots or not segments:
        return None
    return max(segments, key=lambda seg: (seg['closed_at'], str(seg['sell_trade_id'])))


def close_session(*, segments: list[dict[str, Any]], open_lots: list[dict[str, Any]]) -> date | None:
    """The New York day the last lot was sold (the end session of a closed position), or None while open."""
    last = _last_segment(segments, open_lots)
    return None if last is None else _ny_day(last['closed_at'])


def _closed_event(*, subject, ref_plan, buys, segments, open_lots, stop_days, target_days, bars):
    last = _last_segment(segments, open_lots)
    if last is None:
        return None                                   # a lot is still held, or nothing has been sold yet
    end_session = _ny_day(last['closed_at'])
    detail: dict[str, Any] = {'closing_sell_id': str(last['sell_trade_id'])}
    if subject.get('kind') == 'unit':
        if ref_plan is None:
            return None
        first_buy = min(_ny_day(b['executed_at']) for b in buys)
        touched = _t1_touched_while_held(bars, Decimal(str(ref_plan['target1'])), _day(ref_plan['signal_date']),
                                         first_buy, end_session, _splits_of(bars))
        basis = exit_basis(closing_sell=last, stop_days=stop_days, target_days=target_days,
                           t1_touched_while_held=touched)
        detail['plan_id'] = str(ref_plan['id'])
        key = event_key(subject='unit', ticker=subject['ticker'], signal_date=_day(subject['signal_date']),
                        closing_sell_id=detail['closing_sell_id'])
    else:
        basis = 'other'                               # an unplanned trade has no stop or target to follow
        key = event_key(subject='trade', ticker=subject['ticker'], signal_date=None,
                        buy_trade_id=subject['buy_trade_id'])
    detail['exit_basis'] = basis
    return {'end_kind': 'position_closed', 'end_session': end_session, 'event_key': key, 'detail': detail}


def _ended_event(*, subject, ref_plan, shadow, invalidating_review, decided_session, session):
    if ref_plan is None:
        return None
    plan_id = str(ref_plan['id'])
    found: list[tuple[date, int, str, dict[str, Any]]] = []

    def add(kind: str, day: date | None, detail: dict[str, Any]) -> None:
        if day is not None and day <= session:
            found.append((day, END_PRIORITY.index(kind), kind, detail))

    if invalidating_review is not None:
        add('invalidated', _day(invalidating_review['session']),
            {'review_id': invalidating_review['id'], 'reason': invalidating_review.get('reason')})
    if ref_plan.get('status') == 'invalid':
        add('invalidated', _day(decided_session), {'invalid_reasons': list(ref_plan.get('invalid_reasons') or [])})
    if shadow:
        legs = shadow.get('legs') or []
        if legs:
            kind = _SHADOW_END_KIND.get(legs[0].get('reason'))
            if kind is not None:
                fill = shadow.get('fill_date')
                add(kind, _day(legs[0]['exit_date']),
                    {'plan_id': plan_id, 'fill_date': _day(fill).isoformat() if fill else None})
        elif shadow.get('status') == 'expired':
            add('expired', _day(ref_plan['valid_until']), {'plan_id': plan_id})
    if not found:
        return None
    day, _, kind, detail = min(found, key=lambda item: (item[0], item[1]))
    return {'end_kind': kind, 'end_session': day, 'detail': detail,
            'event_key': event_key(subject='unit', ticker=subject['ticker'], signal_date=_day(subject['signal_date']))}


def window_start(session: date) -> date:
    """First session of the detection window for ``session`` S (D6): 5 sessions counting S itself, so S minus 4."""
    return add_trading_days(session, -(RETRO_LOOKBACK_SESSIONS - 1))


def end_event(*, subject: dict[str, Any], ref_plan: dict[str, Any] | None, buys: list[dict[str, Any]],
              segments: list[dict[str, Any]], open_lots: list[dict[str, Any]], shadow: dict[str, Any] | None,
              invalidating_review: dict[str, Any] | None, decided_session: date | None, stop_days: list[date],
              target_days: list[date], bars: list[dict[str, Any]], session: date,
              window_start: date) -> dict[str, Any] | None:
    """§4.1 on rows already read: ``{end_kind, end_session, event_key, detail}`` or None.

    A position ends a card only by closing (D2): with buys, invalidation and expiry never count. Without
    buys the earliest of review invalidation, rule invalidation, the shadow's first stop / target leg and
    expiry wins, ties by ``END_PRIORITY``. Only the earliest end counts, and it is reported only while it
    lies in ``[window_start, session]`` (callers pass ``window_start(session)``, or an earlier day for ``--since``), so an old end is never replaced by a later one."""
    if buys:
        event = _closed_event(subject=subject, ref_plan=ref_plan, buys=buys, segments=segments,
                              open_lots=open_lots, stop_days=stop_days, target_days=target_days, bars=bars)
    elif subject.get('kind') == 'unit':
        event = _ended_event(subject=subject, ref_plan=ref_plan, shadow=shadow,
                             invalidating_review=invalidating_review, decided_session=decided_session,
                             session=session)
    else:
        event = None
    if event is None or not window_start <= event['end_session'] <= session:
        return None
    return event


# ---- decision text and discipline ---------------------------------------------------------------------

def decision_text(decision: dict[str, Any] | None, plan: dict[str, Any] | None, *,
                  agent_version_no: int | None) -> str:
    """§4.3: the user's latest decision in words; ``plan`` is the plan it executed."""
    if decision is None:
        return DECISION_TEXT['none']
    if decision.get('decision') == 'reject':
        return DECISION_TEXT['reject']
    if decision.get('decision') == 'downgrade':
        return DECISION_TEXT['downgrade']
    kind = plan.get('kind') if plan else None
    if kind == 'rule':
        return DECISION_TEXT['accept_rule']
    if kind == 'own':
        return DECISION_TEXT['accept_own']
    if kind == 'agent':
        if agent_version_no is None:
            return DECISION_TEXT['accept_agent_legacy']
        return DECISION_TEXT['accept_agent'].format(n=agent_version_no)
    return DECISION_TEXT['accept']


def discipline_summary(evaluated: dict[str, Any], buy_ids: set, *, as_of: date) -> dict[str, Any]:
    """The card's buys out of a ``discipline.evaluate`` result: per buy ``{trade_id, flags, immature}`` and the
    totals ``{chase, early_take, held_loser, unplanned, pending}`` (``pending`` = judgements not yet mature)."""
    wanted = {str(b) for b in buy_ids}
    trades = [{'trade_id': str(t['trade_id']), 'flags': list(t['flags']), 'immature': list(t['immature'])}
              for t in evaluated['trades'] if str(t['trade_id']) in wanted]
    totals = {flag: sum(flag in t['flags'] for t in trades) for flag in FLAG_ORDER}
    totals['pending'] = sum(len(t['immature']) for t in trades)
    return {'trades': trades, 'totals': totals, 'as_of': as_of.isoformat()}



# ---- frozen facts -------------------------------------------------------------------------------------

def end_text(end_kind: str, basis: str | None) -> str:
    text = END_TEXT[end_kind]
    if end_kind == 'position_closed' and basis in EXIT_BASIS_TEXT:
        return f'{text}（{EXIT_BASIS_TEXT[basis]}）'
    return text


def _plan_fact(plan: dict[str, Any], roles: dict[str, list[str]]) -> dict[str, Any]:
    return {'key': f"plan:{plan['id']}", 'kind': plan.get('kind'), 'version_no': plan.get('version_no'),
            'origin': plan.get('origin'),
            'levels': {name: plan.get(name) for name in ('entry_low', 'entry_high', 'stop', 'target1')},
            'valid_from': plan.get('valid_from'), 'valid_until': plan.get('valid_until'),
            'cutoff_at': plan.get('cutoff_at'), 'status': plan.get('status'),
            'invalid_reasons': list(plan.get('invalid_reasons') or []),
            'roles': list(roles.get(str(plan['id'])) or roles.get(plan['id']) or [])}


def _touches(plan: dict[str, Any], bars: list[dict[str, Any]], splits: list[tuple[date, Decimal]],
             end_day: date) -> dict[str, Any]:
    """First entry-zone, stop and T1 touch dates in the plan's own rescaled levels (the basis
    ``plan_shadow.simulate`` uses). Stop and T1 are looked for from the entry day on, as the replay does."""
    signal = _day(plan['signal_date'])

    def level(name: str) -> Decimal:
        return _current_basis(Decimal(str(plan[name])), signal, splits)

    entry_low, entry_high, stop, target1 = level('entry_low'), level('entry_high'), level('stop'), level('target1')
    first, last = _day(plan['valid_from']), min(_day(plan['valid_until']), end_day)
    entry_day = next((b['price_date'] for b in bars if first <= b['price_date'] <= last
                      and not (Decimal(str(b['low'])) > entry_high or Decimal(str(b['high'])) < entry_low)), None)
    stop_day = t1_day = None
    if entry_day is not None:
        held = [b for b in bars if entry_day <= b['price_date'] <= end_day]
        stop_day = next((b['price_date'] for b in held if Decimal(str(b['low'])) <= stop), None)
        t1_day = next((b['price_date'] for b in held if Decimal(str(b['high'])) >= target1), None)
    return {'key': f"plan:{plan['id']}", 'entry_touched': entry_day, 'stop_touched_on': stop_day,
            't1_touched_on': t1_day}


def _bars_after(plans, bars, splits, trades, end_day) -> dict[str, Any]:
    starts = [_day(p['valid_from']) for p in plans]
    if not starts:
        starts = [_ny_day(t['executed_at']) for t in trades if t.get('voided_at') is None]
    start = min(starts) if starts else None
    ordered = sorted(bars, key=lambda b: b['price_date'])
    window = [b for b in ordered if start is not None and start <= b['price_date'] <= end_day]
    summary: dict[str, Any] = {'first_day': None, 'last_day': None, 'sessions': len(window), 'high': None,
                               'high_date': None, 'low': None, 'low_date': None, 'close_end': None}
    if window:
        top, bottom = max(window, key=lambda b: b['high']), min(window, key=lambda b: b['low'])
        summary.update(first_day=window[0]['price_date'], last_day=window[-1]['price_date'], high=top['high'],
                       high_date=top['price_date'], low=bottom['low'], low_date=bottom['price_date'],
                       close_end=window[-1]['close'])
    # per-plan touch dates are searched from the entry-touch day on, on the same split-adjusted basis as
    # plan_shadow.simulate (see _touches)
    summary['per_plan'] = [_touches(p, ordered, sorted(splits), end_day) for p in plans]
    return summary


def _track(part: dict[str, Any], *extra: str) -> dict[str, Any]:
    status = part.get('status')
    out = {'status': status, 'status_text': TRACK_STATUS_TEXT.get(status, status), 'r': part.get('r'),
           'plan_id': _id(part.get('plan_id'))}
    out.update({name: part.get(name) for name in extra})
    return out


def build_facts(*, subject: dict[str, Any], end: dict[str, Any], plans: list[dict[str, Any]],
                roles: dict[str, list[str]], bars: list[dict[str, Any]], splits: list[tuple[date, Decimal]],
                shadow_by_plan: dict[str, Any], track_row: dict[str, Any] | None, decision: dict[str, Any] | None,
                decision_text: str, trades: list[dict[str, Any]], segments: list[dict[str, Any]],
                actual_r: float | None, discipline: dict[str, Any], reviews: dict[str, Any] | None,
                knowledge: list[dict[str, Any]]) -> dict[str, Any]:
    """§4.2: the ten frozen facts, in ``FACT_KEYS`` order, as plain JSON types. Computed once at detection
    time and never recomputed. ``plans`` rows may carry ``version_no`` / ``origin`` / ``cutoff_at`` from the
    Agent chain; ``roles`` and ``shadow_by_plan`` are keyed by plan id."""
    end_day = _day(end['end_session'])
    basis = (end.get('detail') or {}).get('exit_basis')
    live = sorted((t for t in trades if t.get('voided_at') is None),
                  key=lambda t: (t['executed_at'], str(t['id'])))
    plan_by_id = {str(p['id']): p for p in plans}

    subject_fact = {'kind': subject['kind'], 'ticker': subject['ticker'], 'signal_date': subject.get('signal_date'),
                    'pool': subject.get('pool'), 'end_kind': end['end_kind'],
                    'end_text': end_text(end['end_kind'], basis), 'end_session': end_day, 'exit_basis': basis}
    if subject['kind'] == 'trade':
        subject_fact['buy_trade_id'] = _id(subject.get('buy_trade_id'))

    shadow_fact: dict[str, Any] = {}
    for plan in plans:
        outcome = shadow_by_plan.get(str(plan['id']))
        shadow_fact[f"plan:{plan['id']}"] = None if outcome is None else {
            name: outcome.get(name) for name in ('status', 'fill_date', 'fill_price', 'legs', 'r')}

    if track_row is None:
        tracks_fact = {'actual': _track({'status': 'no_plan'}, 'plan_kind')}
    else:
        tracks_fact = {'rule': _track(track_row['rule']),
                       'agent': _track(track_row['agent'], 'version_no', 'version_basis'),
                       'actual': _track(track_row['actual'], 'plan_kind')}

    decision_fact = {name: None for name in ('decision', 'final_action', 'plan_kind', 'plan_id', 'agent_plan_id',
                                             'agent_version_no', 'reason', 'decided_at')}
    if decision is not None:
        executed = plan_by_id.get(str(decision.get('plan_id'))) if decision.get('plan_id') else None
        seen = plan_by_id.get(str(decision.get('agent_plan_id'))) if decision.get('agent_plan_id') else None
        versioned = seen or (executed if executed and executed.get('kind') == 'agent' else None)
        decision_fact.update(
            decision=decision.get('decision'), final_action=decision.get('final_action'),
            plan_kind=executed.get('kind') if executed else None, plan_id=_id(decision.get('plan_id')),
            agent_plan_id=_id(decision.get('agent_plan_id')),
            agent_version_no=(decision.get('agent_version_no') if decision.get('agent_version_no') is not None
                              else (versioned.get('version_no') if versioned else None)),
            reason=decision.get('reason'), decided_at=decision.get('decided_at'))
    decision_fact['text'] = decision_text

    trades_fact = {
        'trades': [{'id': str(t['id']), 'side': t['side'], 'quantity': t['quantity'], 'price': t['price'],
                    'fee': t.get('fee'), 'executed_at': t['executed_at']} for t in live],
        'segments': [{name: seg.get(name) for name in ('buy_trade_id', 'sell_trade_id', 'quantity',
                                                         'entry_cost_per_share', 'exit_price', 'opened_at',
                                                         'closed_at', 'realized_pnl')} for seg in segments],
        'actual_r': actual_r}

    facts = {
        'subject': subject_fact,
        'plans': [_plan_fact(p, roles) for p in plans],
        'bars_after': _bars_after(plans, bars, splits, trades, end_day),
        'shadow': shadow_fact,
        'tracks': tracks_fact,
        'decision': decision_fact,
        'trades': trades_fact,
        'discipline': discipline,
        'reviews': reviews,
        'knowledge': knowledge,
    }
    return _jsonable({key: facts[key] for key in FACT_KEYS})


# ---- the evidence block for the draft prompt (spec §4.4, inputs 1-7) -----------------------------------

KIND_TEXT = {'rule': '规则计划', 'own': '自定计划', 'agent': 'Agent'}
ROLE_TEXT = {'reference': '参考', 'executed': '执行', 'seen_at_decision': '决定时看到', 'first': '首版',
             'head': '最新版'}
BASIS_TEXT = {'decision': '决定时看到的版本', 'first': '首版'}


def _r(value: Any) -> str:
    return '无' if value is None else f'{value:+.2f}R'


def _plan_line(plan: dict[str, Any]) -> str:
    kind = KIND_TEXT.get(plan['kind'], str(plan['kind']))
    if plan['kind'] == 'agent':
        kind = f"Agent 第 {plan['version_no']} 版" if plan.get('version_no') is not None else 'Agent agent-1'
        if plan.get('origin'):
            kind += f"（{plan['origin']}）"
    levels = plan['levels']
    parts = [plan['key'], kind, '角色：' + ('、'.join(ROLE_TEXT.get(r, r) for r in plan['roles']) or '无'),
             f"入场 {levels['entry_low']}–{levels['entry_high']}，止损 {levels['stop']}，T1 {levels['target1']}",
             f"有效 {plan['valid_from']} 至 {plan['valid_until']}"]
    if plan.get('cutoff_at'):
        parts.append(f"截止 {plan['cutoff_at']}")
    parts.append(f"状态 {plan['status']}" + (f"（{'、'.join(plan['invalid_reasons'])}）" if plan['invalid_reasons'] else ''))
    return ' | '.join(parts)


def _subject_text(facts: dict[str, Any]) -> str:
    s = facts['subject']
    if s['kind'] == 'trade':
        who = f"计划外成交 {s['ticker']}（买入成交 {s.get('buy_trade_id')}）"
    else:
        who = f"单元 {s['ticker']}（信号日 {s['signal_date']}，池 {s.get('pool') or '未知'}）"
    return f"[fact:subject] 对象：{who}。结束：{s['end_text']}，结束日 {s['end_session']}。"


def _bars_text(facts: dict[str, Any]) -> str:
    b = facts['bars_after']
    if not b['sessions']:
        head = '[fact:bars_after] 没有可用的日线。'
    else:
        head = (f"[fact:bars_after] {b['first_day']} 至 {b['last_day']}，共 {b['sessions']} 个交易日："
                f"最高 {b['high']}（{b['high_date']}），最低 {b['low']}（{b['low_date']}），结束日收盘 {b['close_end']}。")
    lines = [f"{row['key']} 首次触及：入场区 {row['entry_touched'] or '无'}，止损 {row['stop_touched_on'] or '无'}，"
             f"T1 {row['t1_touched_on'] or '无'}" for row in b['per_plan']]
    return '\n'.join([head, *lines])


def _shadow_tracks_text(facts: dict[str, Any]) -> str:
    lines = ['[fact:shadow] 影子模拟（plan-shadow-1，按各计划当时的价位逐日回放）：']
    for key, outcome in facts['shadow'].items():
        if outcome is None:
            lines.append(f'{key} | 未模拟（计划作废或没有结果）')
            continue
        legs = '；'.join(f"{leg['reason']} {leg['exit_date']} @ {leg['exit_price']}" for leg in outcome['legs'])
        fill = f"成交 {outcome['fill_date']} @ {outcome['fill_price']}" if outcome['fill_date'] else '未成交'
        lines.append(f"{key} | {TRACK_STATUS_TEXT.get(outcome['status'], outcome['status'])} | {fill} | "
                     f"离场：{legs or '无'} | R {_r(outcome['r'])}")
    t = facts['tracks']
    parts = []
    if 'rule' in t:
        parts.append(f"规则 {t['rule']['status_text']} R {_r(t['rule']['r'])}")
    if 'agent' in t:
        a = t['agent']
        version = f"第 {a['version_no']} 版，" if a.get('version_no') is not None else ''
        parts.append(f"Agent（{version}{BASIS_TEXT.get(a.get('version_basis'), '无版本')}）{a['status_text']} "
                     f"R {_r(a['r'])}")
    parts.append(f"实际 {t['actual']['status_text']} R {_r(t['actual']['r'])}")
    lines.append('[fact:tracks] 三条轨道（tracks-1，R 都按各自计划的止损算）：' + '；'.join(parts))
    return '\n'.join(lines)


def _decision_trades_text(facts: dict[str, Any]) -> str:
    d, t = facts['decision'], facts['trades']
    line = f"[fact:decision] 你的决定：{d['text']}"
    if d['decision'] is not None:
        line += f"（{d['decision']} → {d['final_action']}，{d['decided_at']}）。理由：{d['reason']}"
    else:
        line += '。'
    sides = {'buy': '买', 'sell': '卖'}
    deals = '、'.join(f"{sides.get(x['side'], x['side'])} {x['quantity']} @ {x['price']}（{x['executed_at']}）"
                      for x in t['trades']) or '无'
    return f"{line}\n[fact:trades] 成交：{deals}；平仓段 {len(t['segments'])} 段；实际 R {_r(t['actual_r'])}。"


def _discipline_text(facts: dict[str, Any]) -> str:
    d = facts['discipline']
    if not d['trades']:
        return '[fact:discipline] 未成交，纪律四项不适用。'
    totals = d['totals']
    summary = ' · '.join(f'{FLAG_TEXT[flag]} {totals[flag]}' for flag in FLAG_ORDER) + f" · 待定 {totals['pending']}"
    lines = [f"[fact:discipline] 纪律四项（截至 {d['as_of']}）：{summary}。"]
    for t in d['trades']:
        flags = '、'.join(FLAG_TEXT[f] for f in t['flags']) or '无标记'
        pending = '；'.join(f'{FLAG_TEXT[f]}{PENDING_TEXT.get(f, "待定")}' for f in t['immature'])
        lines.append(f"买入 {t['trade_id']}：{flags}" + (f'；{pending}' if pending else ''))
    return '\n'.join(lines)


def _reviews_knowledge_text(facts: dict[str, Any]) -> str:
    r = facts['reviews']
    if r is None:
        first = '[fact:reviews] 这个单元没有 Agent 复查链。'
    else:
        o = r['outcomes']
        first = (f"[fact:reviews] 链的复查共 {r['count']} 次（维持 {o.get('maintain', 0)}，修订 {o.get('revise', 0)}，"
                 f"作废 {o.get('invalidate', 0)}，跳过 {o.get('skipped', 0)}，出错 {o.get('error', 0)}）。")
        if r.get('invalidated'):
            inv = r['invalidated']
            first += f" 作废：{inv.get('session')}，{inv.get('reason')}（{inv.get('decided_by')}）。"
    items = '；'.join(f"{k['ref']}《{k['title_at_version']}》（{'、'.join(k['fields'])}）" for k in facts['knowledge'])
    return f"{first}\n[fact:knowledge] 计划当时引用过的我的知识：{items or '无'}。"


def facts_text(facts: dict[str, Any]) -> str:
    """The evidence block of the draft prompt: seven sections (spec §4.4 inputs 1-7) separated by a blank
    line, each opening with its ``[fact:<key>]`` tag so the narrative can cite them."""
    plans = '\n'.join(_plan_line(p) for p in facts['plans']) or '（没有相关计划）'
    sections = [
        _subject_text(facts),
        f'[fact:plans] 各份计划当时的价位、有效期、截止时间与角色：\n{plans}',
        _bars_text(facts),
        _shadow_tracks_text(facts),
        _decision_trades_text(facts),
        _discipline_text(facts),
        _reviews_knowledge_text(facts),
    ]
    return '\n\n'.join(sections)


# ---- card status --------------------------------------------------------------------------------------

def card_status(*, drafts: list[dict[str, Any]], verdict: dict[str, Any] | None) -> str:
    """§4.6, derived from the records and never stored."""
    if verdict is not None:
        return 'reviewed'
    if any(d['status'] == 'ok' for d in drafts):
        return 'to_review'
    if sum(d['status'] in ('rejected', 'error') for d in drafts) >= RETRO_MAX_ATTEMPTS:
        return 'draft_failed'
    return 'drafting'
