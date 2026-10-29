"""Review-card end events, reference plan, frozen facts and card status (v2.7 spec §4). Pure, offline."""
import ast
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import discipline, plan_shadow, retro

NY = ZoneInfo('America/New_York')
D0, D1, D2, D3, D4, D5, S = (date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23),
                             date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28))


def at(day, hour=15):
    return datetime(day.year, day.month, day.day, hour, tzinfo=NY)


def plan(id_='p1', kind='rule', plan_version='plan-1', status='ok', valid_from=D1, valid_until=D5, **extra):
    return {'id': id_, 'kind': kind, 'plan_version': plan_version, 'ticker': 'NVDA', 'signal_date': D0,
            'entry_low': D('98'), 'entry_high': D('102'), 'stop': D('94'), 'target1': D('112'),
            'valid_from': valid_from, 'valid_until': valid_until, 'status': status, 'invalid_reasons': [],
            **extra}


def buy(id_='b1', day=D1):
    return {'id': id_, 'side': 'buy', 'quantity': D('10'), 'price': D('100'), 'fee': D('0'),
            'executed_at': at(day), 'ticker': 'NVDA', 'decision_id': 'd1', 'voided_at': None}


def segment(buy_id='b1', sell_id='s1', *, closed=D4, opened=D1):
    return {'buy_trade_id': buy_id, 'sell_trade_id': sell_id, 'quantity': D('10'),
            'entry_cost_per_share': D('100'), 'exit_price': D('105'), 'opened_at': at(opened),
            'closed_at': at(closed), 'realized_pnl': D('50')}


def bar(day, o=100, h=101, l=99, c=100, split=1.0):
    return {'price_date': day, 'open': float(o), 'high': float(h), 'low': float(l), 'close': float(c),
            'adj_close': float(c), 'volume': 1, 'split_factor': split}


UNIT = {'kind': 'unit', 'ticker': 'NVDA', 'signal_date': D0}
WINDOW_START = retro.window_start(S)


def end(**overrides):
    args = dict(subject=UNIT, ref_plan=plan(), buys=[], segments=[], open_lots=[], shadow=None,
                invalidating_review=None, decided_session=D1, stop_days=[], target_days=[],
                bars=[bar(D1), bar(D2), bar(D3), bar(D4)], session=S, window_start=WINDOW_START)
    args.update(overrides)
    return retro.end_event(**args)


def leg(day, reason, price=94):
    return {'fraction': 1.0, 'exit_date': day.isoformat(), 'exit_price': D(price), 'reason': reason}


def sim(status='closed', legs=(), fill=D1):
    return {'status': status, 'fill_date': fill if status in ('closed', 'open') else None,
            'fill_price': D('100') if status in ('closed', 'open') else None, 'legs': list(legs), 'r': -1.0}


REVIEW = {'id': 7, 'session': D3, 'reason': '财报临近，计划失效'}

END_CASES = [
    ('closed-unit', dict(buys=[buy()], segments=[segment()]), 'position_closed', D4,
     {'exit_basis': 'other', 'closing_sell_id': 's1'}),
    ('invalidated-by-review', dict(invalidating_review=REVIEW), 'invalidated', D3,
     {'review_id': 7, 'reason': '财报临近，计划失效'}),
    ('invalidated-by-rule', dict(ref_plan=plan(status='invalid', invalid_reasons=['no_room']), decided_session=D2),
     'invalidated', D2, {'invalid_reasons': ['no_room']}),
    ('stop', dict(shadow=sim(legs=[leg(D3, 'stop')])), 'stop', D3, {'plan_id': 'p1', 'fill_date': '2026-10-21'}),
    ('trailing-stop', dict(shadow=sim(legs=[leg(D2, 'trail')])), 'stop', D2, {'plan_id': 'p1'}),
    ('target', dict(shadow=sim(status='open', legs=[leg(D3, 'target1', 112)])), 'target', D3,
     {'plan_id': 'p1', 'fill_date': '2026-10-21'}),
    ('expired', dict(shadow=sim(status='expired')), 'expired', D5, {'plan_id': 'p1'}),
    ('trade-closed', dict(subject={'kind': 'trade', 'ticker': 'NVDA', 'signal_date': None, 'buy_trade_id': 'b9'},
                          ref_plan=None, buys=[buy('b9')], segments=[segment('b9', 's9')]),
     'position_closed', D4, {'exit_basis': 'other', 'closing_sell_id': 's9'}),
]


@pytest.mark.parametrize('name,kwargs,kind,end_session,detail', END_CASES, ids=[c[0] for c in END_CASES])
def test_end_event_table(name, kwargs, kind, end_session, detail):
    event = end(**kwargs)
    assert event is not None
    assert event['end_kind'] == kind and kind in retro.END_KINDS
    assert event['end_session'] == end_session
    for key, value in detail.items():
        assert event['detail'][key] == value, key
    assert set(event) == {'end_kind', 'end_session', 'event_key', 'detail'}


def test_end_event_keys_follow_the_kind():
    assert end(buys=[buy()], segments=[segment()])['event_key'] == 'unit:NVDA:2026-10-20:closed:s1'
    assert end(invalidating_review=REVIEW)['event_key'] == 'unit:NVDA:2026-10-20:ended'
    assert end(shadow=sim(status='expired'))['event_key'] == 'unit:NVDA:2026-10-20:ended'
    trade = end(subject={'kind': 'trade', 'ticker': 'NVDA', 'signal_date': None, 'buy_trade_id': 'b9'},
                ref_plan=None, buys=[buy('b9')], segments=[segment('b9', 's9')])
    assert trade['event_key'] == 'trade:b9'


def test_unfinished_units_have_no_event():
    assert end() is None                                             # nothing happened
    assert end(shadow=sim(status='pending')) is None
    assert end(shadow=sim(status='open')) is None                    # filled, no leg yet
    assert end(ref_plan=plan(status='invalid'), decided_session=None) is None


@pytest.mark.parametrize('other', [
    dict(shadow=sim(legs=[leg(D3, 'stop')])),
    dict(shadow=sim(status='open', legs=[leg(D3, 'target1', 112)])),
    dict(shadow=sim(status='expired'), ref_plan=plan(valid_until=D3)),
], ids=['stop', 'target', 'expired'])
def test_same_day_priority(other):
    assert end(**other)['end_kind'] in ('stop', 'target', 'expired')
    event = end(invalidating_review=REVIEW, **other)                 # same day as the review (D3)
    assert event['end_kind'] == 'invalidated' and event['end_session'] == D3
    assert event['detail']['review_id'] == 7
    assert retro.END_PRIORITY == ('invalidated', 'stop', 'target', 'expired')


def test_earliest_wins():
    early_stop = end(shadow=sim(legs=[leg(D2, 'stop')]), invalidating_review=REVIEW)      # stop D2 < review D3
    assert (early_stop['end_kind'], early_stop['end_session']) == ('stop', D2)
    early_review = end(shadow=sim(legs=[leg(D4, 'stop')]), invalidating_review=REVIEW)    # review D3 < stop D4
    assert (early_review['end_kind'], early_review['end_session']) == ('invalidated', D3)
    # the earliest end is the unit's end even when it lies before the window: no later event replaces it
    assert end(shadow=sim(legs=[leg(D0, 'stop')]), invalidating_review={**REVIEW, 'session': S}) is None


def test_holding_unit_ends_only_on_close():
    open_lot = {'buy_trade_id': 'b1', 'quantity': D('10'), 'cost_per_share': D('100'), 'opened_at': at(D1)}
    held = dict(buys=[buy()], open_lots=[open_lot], invalidating_review=REVIEW,
                shadow=sim(status='expired'), ref_plan=plan(status='invalid'))
    assert end(**held) is None                                       # invalidation / expiry never end a held unit
    assert end(**held, segments=[segment()]) is None                 # part closed, part still open
    assert end(buys=[buy()], segments=[segment()], open_lots=[], invalidating_review=REVIEW)['end_kind'] \
        == 'position_closed'
    assert end(buys=[buy()], segments=[], open_lots=[]) is None      # no fill history yet


def test_closing_sell_is_the_last_segment():
    segments = [segment('b1', 's1', closed=D3), segment('b1', 's2', closed=D4)]
    event = end(buys=[buy()], segments=segments)
    assert (event['end_session'], event['detail']['closing_sell_id']) == (D4, 's2')
    assert event['event_key'].endswith(':closed:s2')


def test_window_bounds():
    # D6: 5 sessions including S (28, 27, 26, 23, 22), so the first day is S minus 4 sessions
    assert WINDOW_START == D2 == add_trading_days(S, -(retro.RETRO_LOOKBACK_SESSIONS - 1))
    assert end(buys=[buy()], segments=[segment(closed=D2)]) is not None                 # exactly at the start
    assert end(buys=[buy()], segments=[segment(closed=D1)]) is None                     # one session before
    assert end(buys=[buy()], segments=[segment(closed=S)]) is not None                  # S itself
    assert end(buys=[buy()], segments=[segment(closed=S + timedelta(days=1))]) is None  # never after S
    assert end(shadow=sim(legs=[leg(D0, 'stop')])) is None
    assert end(shadow=sim(status='expired'), ref_plan=plan(valid_until=S + timedelta(days=2))) is None
    # --since moves the start
    assert end(buys=[buy()], segments=[segment(closed=D1)], window_start=D1) is not None


def test_exit_basis_in_closed_event():
    stop_sell = end(buys=[buy()], segments=[segment(closed=D3)], stop_days=[D2])
    assert stop_sell['detail']['exit_basis'] == 'stop'
    target_sell = end(buys=[buy()], segments=[segment(closed=D3)], target_days=[D3])
    assert target_sell['detail']['exit_basis'] == 'target'
    touched = end(buys=[buy()], segments=[segment(closed=D3)], bars=[bar(D1), bar(D2, h=113), bar(D3)])
    assert touched['detail']['exit_basis'] == 'target'                                  # high >= T1 while held
    before_buy = end(buys=[buy(day=D2)], segments=[segment(closed=D3, opened=D2)], bars=[bar(D1, h=120), bar(D2), bar(D3)])
    assert before_buy['detail']['exit_basis'] == 'other'                                # highs before the buy never count
    trade = end(subject={'kind': 'trade', 'ticker': 'NVDA', 'signal_date': None, 'buy_trade_id': 'b1'},
                ref_plan=None, buys=[buy()], segments=[segment(closed=D3)], stop_days=[D2], bars=[bar(D2, h=130)])
    assert trade['detail']['exit_basis'] == 'other'                                     # unplanned trades are always other


def test_reference_plan_fallback():
    rule, own = plan('p-rule'), plan('p-own', kind='own', plan_version='plan-1')
    a2 = plan('p-a2', kind='agent', plan_version='agent-2')
    a1 = plan('p-a1', kind='agent', plan_version='agent-1')
    plans = [rule, own, a2, a1]
    ref = retro.reference_plan
    # holding: only the plan the decision executed
    assert ref(decision={'plan_id': 'p-own', 'agent_plan_id': 'p-a2'}, plans=plans, has_buys=True)['id'] == 'p-own'
    assert ref(decision={'plan_id': None, 'agent_plan_id': 'p-a2'}, plans=plans, has_buys=True) is None
    assert ref(decision=None, plans=plans, has_buys=True) is None
    # no position: executed plan -> the Agent version seen -> rule plan -> agent-1
    assert ref(decision={'plan_id': 'p-own', 'agent_plan_id': 'p-a2'}, plans=plans, has_buys=False)['id'] == 'p-own'
    assert ref(decision={'plan_id': None, 'agent_plan_id': 'p-a2'}, plans=plans, has_buys=False)['id'] == 'p-a2'
    assert ref(decision={'plan_id': None, 'agent_plan_id': None}, plans=plans, has_buys=False)['id'] == 'p-rule'
    assert ref(decision={'plan_id': None, 'agent_plan_id': None}, plans=[own, a2, a1], has_buys=False)['id'] == 'p-a1'
    assert ref(decision={'plan_id': 'gone', 'agent_plan_id': 'gone-too'}, plans=plans, has_buys=False)['id'] == 'p-rule'
    assert ref(decision={'plan_id': None, 'agent_plan_id': None}, plans=[own, a2], has_buys=False) is None
    assert ref(decision=None, plans=[rule], has_buys=False)['id'] == 'p-rule'


def test_reference_plan_for_a_held_unit_follows_the_buys_decision():
    """Spec D3 as ruled in the final review: with live buys the plan is the one the buys' decision executed (the
    latest buy whose decision has a plan_id), else the latest chain decision that carries a plan_id; never a fallback."""
    rule, own = plan('p-rule'), plan('p-own', kind='own')
    plans = [rule, own, plan('p-a1', kind='agent', plan_version='agent-1')]
    chain = [{'id': 'd1', 'plan_id': 'p-rule'}, {'id': 'd2', 'plan_id': None}, {'id': 'd3', 'plan_id': 'p-own'},
             {'id': 'd4', 'plan_id': None}]
    head = chain[-1]                                                    # a later reject / downgrade has no plan_id
    on = lambda id_, decision_id, day: {**buy(id_, day), 'decision_id': decision_id}      # noqa: E731
    ref = retro.reference_plan
    # (1) accept + buy, later a reject: the buy's decision wins over the head
    assert ref(decision=head, plans=plans, has_buys=True, buys=[on('b1', 'd1', D1)], chain=chain)['id'] == 'p-rule'
    # several buys: the latest buy whose decision has a plan_id (a later buy on a plan-less decision is skipped)
    buys = [on('b1', 'd1', D1), on('b2', 'd3', D2), on('b3', 'd4', D3)]
    assert ref(decision=head, plans=plans, has_buys=True, buys=buys, chain=chain)['id'] == 'p-own'
    # (2) the buys sit on plan-less decisions: the most recent chain decision that carries a plan_id
    assert ref(decision=head, plans=plans, has_buys=True, buys=[on('b1', 'd2', D1)], chain=chain)['id'] == 'p-own'
    # a plan_id that is not among the unit's plans is passed over, not invented
    assert ref(decision=head, plans=[rule], has_buys=True, buys=[on('b1', 'd3', D1)], chain=chain)['id'] == 'p-rule'
    # nothing on the whole chain: no card, and the no-position fallbacks (rule plan, agent-1) do not apply
    bare = [{'id': 'd1', 'plan_id': None}]
    assert ref(decision=bare[0], plans=plans, has_buys=True, buys=[on('b1', 'd1', D1)], chain=bare) is None
    assert ref(decision=None, plans=plans, has_buys=True, buys=[buy()], chain=[]) is None


def test_no_plan_returns_none():
    assert retro.reference_plan(decision={'plan_id': None, 'agent_plan_id': None}, plans=[], has_buys=False) is None
    assert end(ref_plan=None, invalidating_review=REVIEW) is None
    assert end(ref_plan=None, buys=[buy()], segments=[segment()]) is None


def test_event_key_forms():
    assert retro.event_key(subject='unit', ticker='NVDA', signal_date=D0) == 'unit:NVDA:2026-10-20:ended'
    assert retro.event_key(subject='unit', ticker='NVDA', signal_date=D0, closing_sell_id='s1') \
        == 'unit:NVDA:2026-10-20:closed:s1'
    assert retro.event_key(subject='trade', ticker='NVDA', signal_date=None, buy_trade_id='b1') == 'trade:b1'


def test_exit_basis_three():
    sell = {'executed_at': at(D3)}
    kw = dict(closing_sell=sell, stop_days=[], target_days=[], t1_touched_while_held=False)
    assert retro.exit_basis(**kw) == 'other'
    assert retro.exit_basis(**{**kw, 'stop_days': [D2]}) == 'stop'                      # the day after the stop signal
    assert retro.exit_basis(**{**kw, 'stop_days': [D3]}) == 'stop'                      # the same day
    assert retro.exit_basis(**{**kw, 'stop_days': [D1]}) == 'other'                     # two sessions later: not the stop
    assert retro.exit_basis(**{**kw, 't1_touched_while_held': True}) == 'target'
    assert retro.exit_basis(**{**kw, 'target_days': [D2]}) == 'target'
    assert retro.exit_basis(**{**kw, 'stop_days': [D3], 't1_touched_while_held': True}) == 'stop'
    assert retro.EXIT_BASIS_TEXT == {'stop': '按止损', 'target': '到 T1 后', 'other': '自行卖出'}
    assert retro.exit_basis(**{**kw, 'closing_sell': {'closed_at': at(D3)}, 'stop_days': [D3]}) == 'stop'


def test_decision_text_six():
    decide = retro.decision_text
    accept = {'decision': 'accept', 'final_action': 'buy'}
    assert decide(accept, plan(kind='rule'), agent_version_no=None) == '采纳（照规则计划）'
    assert decide(accept, plan('a', kind='agent', plan_version='agent-2'), agent_version_no=2) == '采纳（照 Agent 第 2 版）'
    assert decide(accept, plan('a', kind='agent', plan_version='agent-2'), agent_version_no=0) == '采纳（照 Agent 第 0 版）'
    assert decide(accept, plan('a', kind='agent', plan_version='agent-1'), agent_version_no=None) \
        == '采纳（照 Agent agent-1）'
    assert decide(accept, plan(kind='own'), agent_version_no=None) == '自改价位'
    assert decide({'decision': 'reject', 'final_action': 'ignore'}, None, agent_version_no=None) == '否决'
    assert decide({'decision': 'downgrade', 'final_action': 'watch'}, None, agent_version_no=None) == '降为观察'
    assert decide(None, None, agent_version_no=None) == '未决定（计划外成交）'
    assert retro.DECISION_TEXT['reject'] == '否决' and retro.DECISION_TEXT['none'] == '未决定（计划外成交）'


def test_constants():
    assert retro.RETRO_VERSION == 'retro-1'
    assert retro.END_KINDS == ('position_closed', 'stop', 'target', 'expired', 'invalidated')
    assert retro.END_TEXT == {'position_closed': '平仓', 'stop': '止损', 'target': '到 T1', 'expired': '过期未成交',
                              'invalidated': '作废'}
    assert (retro.RETRO_LOOKBACK_SESSIONS, retro.RETRO_MAX_DRAFTS, retro.RETRO_MAX_ATTEMPTS, retro.LESSONS_MAX) \
        == (5, 5, 3, 3)
    assert retro.CARD_STATUSES == ('reviewed', 'to_review', 'draft_failed', 'drafting')
    assert retro.FACT_KEYS == ('subject', 'plans', 'bars_after', 'shadow', 'tracks', 'decision', 'trades',
                               'discipline', 'reviews', 'knowledge')
    assert retro.CARD_STATUS_TEXT == {'reviewed': '已审定', 'to_review': '待审定',
                                      'draft_failed': '起草失败（可手动审定或重新起草）', 'drafting': '起草中'}


def test_retro_module_stays_pure():
    tree = ast.parse(open(retro.__file__, encoding='utf-8').read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names += [f'{node.module}.{alias.name}' for alias in node.names]
    parts = {part for name in names for part in name.split('.')}
    assert not parts & {'service', 'agent', 'repository'}, names


# ---- frozen facts ------------------------------------------------------------------------------

TRACK_ROW = {
    'ticker': 'NVDA', 'signal_date': '2026-10-20', 'pool': 'core',
    'rule': {'plan_id': 'p1', 'status': 'closed', 'r': -1.0},
    'agent': {'run_id': 'r1', 'run_status': 'ok', 'run_reason': None, 'plan_id': 'p2', 'status': 'closed',
              'r': 0.5, 'version_no': 2, 'version_basis': 'decision'},
    'actual': {'decision_id': 'd1', 'final_action': 'buy', 'plan_id': 'p1', 'plan_kind': 'rule',
               'buy_trade_ids': ['b1'], 'status': 'closed', 'r': 0.8, 'open': False},
}


def make_facts(*, subject=None, decision='default', **overrides):
    p1 = plan('p1', valid_until=D5)
    p2 = plan('p2', kind='agent', plan_version='agent-2', version_no=2, origin='review', cutoff_at=at(D2))
    kwargs = dict(
        subject=subject or {**UNIT, 'pool': 'core'},
        end={'end_kind': 'position_closed', 'end_session': D4, 'event_key': 'unit:NVDA:2026-10-20:closed:s1',
             'detail': {'exit_basis': 'stop', 'closing_sell_id': 's1'}},
        plans=[p1, p2], roles={'p1': ['executed', 'reference'], 'p2': ['seen_at_decision', 'head']},
        bars=[bar(D1, 100, 103, 99, 101), bar(D2, 101, 104, 97, 98), bar(D3, 98, 99, 93, 94), bar(D4, 94, 95, 90, 91)],
        splits=[], shadow_by_plan={'p1': sim(legs=[leg(D3, 'stop')]), 'p2': None},
        track_row=TRACK_ROW,
        decision={'decision': 'accept', 'final_action': 'buy', 'plan_id': 'p1', 'agent_plan_id': 'p2',
                  'reason': '照规则', 'decided_at': at(D1)} if decision == 'default' else decision,
        decision_text='采纳（照规则计划）',
        trades=[{**buy(), 'fee': D('1')}, {'id': 's1', 'side': 'sell', 'quantity': D('10'), 'price': D('95'),
                                           'fee': D('1'), 'executed_at': at(D4), 'voided_at': None}],
        segments=[segment(closed=D4)], actual_r=0.8,
        discipline={'trades': [{'trade_id': 'b1', 'flags': ['chase'], 'immature': ['early_take']}],
                    'totals': {'chase': 1, 'early_take': 0, 'held_loser': 0, 'unplanned': 0, 'pending': 1},
                    'as_of': '2026-10-28'},
        reviews={'count': 2, 'outcomes': {'maintain': 1, 'revise': 1, 'invalidate': 0, 'skipped': 0, 'error': 0},
                 'invalidated': None},
        knowledge=[{'ref': 'know:3@2', 'title_at_version': '财报前不追', 'fields': ['thesis']}])
    kwargs.update(overrides)
    return retro.build_facts(**kwargs)


def test_build_facts_keys():
    facts = make_facts()
    assert tuple(facts) == retro.FACT_KEYS
    json.dumps(facts)                                                  # freezes into JSONB as-is
    assert facts['subject'] == {
        'kind': 'unit', 'ticker': 'NVDA', 'signal_date': '2026-10-20', 'pool': 'core',
        'end_kind': 'position_closed', 'end_text': '平仓（按止损）', 'end_session': '2026-10-26',
        'exit_basis': 'stop'}
    assert [p['key'] for p in facts['plans']] == ['plan:p1', 'plan:p2']
    first = facts['plans'][0]
    assert first['levels'] == {'entry_low': '98', 'entry_high': '102', 'stop': '94', 'target1': '112'}
    assert (first['kind'], first['valid_from'], first['valid_until'], first['roles']) \
        == ('rule', '2026-10-21', '2026-10-27', ['executed', 'reference'])
    second = facts['plans'][1]
    assert (second['version_no'], second['origin'], second['cutoff_at'][:10]) == (2, 'review', '2026-10-22')
    assert facts['shadow']['plan:p1']['status'] == 'closed' and facts['shadow']['plan:p1']['legs'][0]['reason'] == 'stop'
    assert facts['shadow']['plan:p2'] is None
    assert facts['decision']['text'] == '采纳（照规则计划）'
    assert (facts['decision']['plan_kind'], facts['decision']['agent_version_no']) == ('rule', 2)
    assert facts['decision']['decided_at'].startswith('2026-10-21')
    assert [t['side'] for t in facts['trades']['trades']] == ['buy', 'sell']
    assert facts['trades']['actual_r'] == 0.8 and facts['trades']['segments'][0]['sell_trade_id'] == 's1'
    assert facts['discipline']['totals']['pending'] == 1
    assert facts['knowledge'][0]['ref'] == 'know:3@2'


def test_build_facts_tracks_and_trade_subject():
    facts = make_facts()
    tracks = facts['tracks']
    assert tracks['rule'] == {'status': 'closed', 'status_text': '已平仓', 'r': -1.0, 'plan_id': 'p1'}
    assert tracks['agent'] == {'status': 'closed', 'status_text': '已平仓', 'r': 0.5, 'plan_id': 'p2',
                               'version_no': 2, 'version_basis': 'decision'}
    assert tracks['actual'] == {'status': 'closed', 'status_text': '已平仓', 'r': 0.8, 'plan_id': 'p1',
                                'plan_kind': 'rule'}
    trade = make_facts(
        subject={'kind': 'trade', 'ticker': 'NVDA', 'signal_date': None, 'pool': None, 'buy_trade_id': 'b1'},
        plans=[], roles={}, shadow_by_plan={}, track_row=None, decision=None, decision_text='未决定（计划外成交）',
        reviews=None, knowledge=[],
        end={'end_kind': 'position_closed', 'end_session': D4, 'event_key': 'trade:b1',
             'detail': {'exit_basis': 'other', 'closing_sell_id': 's1'}})
    assert tuple(trade) == retro.FACT_KEYS
    assert list(trade['tracks']) == ['actual'] and trade['tracks']['actual']['status'] == 'no_plan'
    assert trade['tracks']['actual']['status_text'] == '无计划成交'
    assert trade['subject']['buy_trade_id'] == 'b1' and trade['subject']['signal_date'] is None
    assert trade['decision']['text'] == '未决定（计划外成交）' and trade['decision']['decision'] is None
    assert trade['plans'] == [] and trade['reviews'] is None


def test_bars_after_summary():
    facts = make_facts()
    after = facts['bars_after']
    assert (after['first_day'], after['last_day'], after['sessions']) == ('2026-10-21', '2026-10-26', 4)
    assert (after['high'], after['high_date'], after['low'], after['low_date'], after['close_end']) \
        == (104.0, '2026-10-22', 90.0, '2026-10-26', 91.0)
    by_plan = {row['key']: row for row in after['per_plan']}
    assert by_plan['plan:p1'] == {'key': 'plan:p1', 'entry_touched': '2026-10-21', 'stop_touched_on': '2026-10-23',
                                  't1_touched_on': None}
    empty = make_facts(bars=[])['bars_after']
    assert empty['sessions'] == 0 and empty['first_day'] is None and empty['high'] is None


SPLIT_DAY = date(2026, 10, 23)
SPLITS = [(SPLIT_DAY, D('2'))]


def _split_bars(low_day=None, low=None, high_day=None, high=None):
    """Bars in the current (post-split) basis: the 100-ish plan prices read as 50-ish."""
    days = [D1, D2, D3, D4, D5, S]
    bars = []
    for day in days:
        o, h, l, c = 50, 51, 49, 50
        if day == low_day:
            l = low
        if day == high_day:
            h = high
        bars.append(bar(day, o, h, l, c, split=2.0 if day == SPLIT_DAY else 1.0))
    return bars


@pytest.mark.parametrize('case', ['stop', 'target'])
def test_bars_after_touch_dates_split_basis(case):
    """A split inside the window: the touch dates use the same rescaled levels as plan_shadow.simulate."""
    p = plan('p1', valid_from=D1, valid_until=S)
    if case == 'stop':
        bars = _split_bars(low_day=D4, low=46.9)           # stop 94 / 2 = 47 -> touched on 10-26
    else:
        bars = _split_bars(high_day=D5, high=56.5)         # T1 112 / 2 = 56 -> touched on 10-27
    outcome = plan_shadow.simulate({**p, 'atr': D('2'), 'trail_atr_multiple': D('2')}, bars, [], splits=SPLITS)
    first_leg = outcome['legs'][0]
    assert first_leg['reason'] == ('stop' if case == 'stop' else 'target1')
    facts = make_facts(plans=[p], roles={'p1': ['reference']}, bars=bars, splits=SPLITS,
                       shadow_by_plan={'p1': outcome}, track_row=None, decision=None,
                       end={'end_kind': 'expired', 'end_session': S, 'event_key': 'unit:NVDA:2026-10-20:ended',
                            'detail': {}})
    row = facts['bars_after']['per_plan'][0]
    touched = row['stop_touched_on'] if case == 'stop' else row['t1_touched_on']
    assert touched == first_leg['exit_date']
    assert row['entry_touched'] == '2026-10-21'
    other = row['t1_touched_on'] if case == 'stop' else row['stop_touched_on']
    assert other is None                                  # the unrescaled levels (94 / 112) would read wrongly here


def test_discipline_summary_pending():
    evaluated = {'trades': [
        {'trade_id': 'b1', 'ticker': 'NVDA', 'track': 'rule', 'flags': ['chase'], 'immature': ['early_take'], 'r': 1.0},
        {'trade_id': 'b2', 'ticker': 'NVDA', 'track': 'rule', 'flags': [], 'immature': ['early_take', 'held_loser'],
         'r': None},
        {'trade_id': 'b3', 'ticker': 'NVDA', 'track': None, 'flags': ['unplanned'], 'immature': [], 'r': None},
        {'trade_id': 'other', 'ticker': 'AMD', 'track': 'rule', 'flags': ['held_loser'], 'immature': [], 'r': None},
    ], 'counts': {}, 'immature': {}, 'planned_buys': 2, 'compliance_rate': None}
    summary = retro.discipline_summary(evaluated, {'b1', 'b2', 'b3'}, as_of=S)
    assert summary['as_of'] == '2026-10-28'
    assert [t['trade_id'] for t in summary['trades']] == ['b1', 'b2', 'b3']
    assert summary['trades'][0] == {'trade_id': 'b1', 'flags': ['chase'], 'immature': ['early_take']}
    assert summary['totals'] == {'chase': 1, 'early_take': 0, 'held_loser': 0, 'unplanned': 1, 'pending': 3}
    empty = retro.discipline_summary(evaluated, set(), as_of=S)
    assert empty['trades'] == [] and empty['totals']['pending'] == 0


def test_discipline_summary_matches_evaluate():
    trade = {'id': 'b1', 'ticker': 'NVDA', 'side': 'buy', 'quantity': 10, 'price': '103', 'executed_at': at(D1),
             'decision_id': 'd1', 'voided_at': None}
    evaluated = discipline.evaluate(
        trades=[trade], decisions_by_id={'d1': {'id': 'd1', 'plan_id': 'p1'}}, plans_by_id={'p1': plan()},
        bars_by_ticker={'NVDA': [bar(D1), bar(D2)]}, stop_events=[], segments=[], session=D2)
    summary = retro.discipline_summary(evaluated, {'b1'}, as_of=D2)
    assert summary['totals']['chase'] == 1
    assert summary['trades'][0]['flags'] == evaluated['trades'][0]['flags']


def test_facts_text_sections():
    text = retro.facts_text(make_facts())
    sections = text.split('\n\n')
    assert len(sections) == 7
    assert all(section.startswith('[fact:') for section in sections)
    tags = re.findall(r'^\[fact:([a-z_]+)\]', text, re.M)
    assert tuple(tags) == retro.FACT_KEYS
    assert sections[0].startswith('[fact:subject]') and '平仓（按止损）' in sections[0] and '2026-10-26' in sections[0]
    assert 'plan:p1' in sections[1] and '98' in sections[1] and '94' in sections[1] and '112' in sections[1]
    assert '2026-10-23' in sections[2]                                  # the first time the stop was touched
    assert '已平仓' in sections[3] and '-1.00' in sections[3]
    assert '采纳（照规则计划）' in sections[4] and '照规则' in sections[4]
    assert 'chase' in sections[5] or '追高' in sections[5]
    assert 'know:3@2' in sections[6]
    # frozen facts survive a JSON round trip
    assert retro.facts_text(json.loads(json.dumps(make_facts()))) == text


def test_card_status_four():
    ok = {'status': 'ok'}
    bad = {'status': 'rejected'}
    err = {'status': 'error'}
    skipped = {'status': 'skipped'}
    assert retro.card_status(drafts=[bad, ok], verdict={'id': 1}) == 'reviewed'
    assert retro.card_status(drafts=[], verdict={'id': 1}) == 'reviewed'
    assert retro.card_status(drafts=[ok], verdict=None) == 'to_review'
    assert retro.card_status(drafts=[bad, err, bad], verdict=None) == 'draft_failed'
    assert retro.card_status(drafts=[bad, err], verdict=None) == 'drafting'
    assert retro.card_status(drafts=[bad, err, skipped, skipped], verdict=None) == 'drafting'   # skips are not tries
    assert retro.card_status(drafts=[], verdict=None) == 'drafting'
    assert retro.card_status(drafts=[bad, bad, bad, ok], verdict=None) == 'to_review'
