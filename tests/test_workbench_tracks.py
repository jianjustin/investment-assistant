"""Three-track comparison pure functions (P4 design §4): statuses, R, summary."""
import uuid
from datetime import date, timedelta
from decimal import Decimal as D

from investment_assistant.workbench import tracks

S = date(2026, 10, 22)
PLAN = {'id': uuid.uuid4(), 'kind': 'rule', 'stop': D('95'), 'signal_date': S,
        'valid_from': S + timedelta(days=1), 'valid_until': S + timedelta(days=3)}


def _decision(action='buy', plan_id='p1'):
    return {'id': uuid.uuid4(), 'final_action': action, 'plan_id': plan_id}


def _run(status='ok', reason=None, plan_id=None):
    return {'id': uuid.uuid4(), 'status': status, 'reason': reason, 'plan_id': plan_id}


def _buy(tid='b1'):
    return {'id': tid, 'side': 'buy', 'quantity': D(10), 'price': D('100'), 'executed_at': S + timedelta(days=1)}


def _seg(tid='b1', qty=D(10), cost=D('100'), exit_=D('110')):
    return {'buy_trade_id': tid, 'quantity': qty, 'entry_cost_per_share': cost, 'exit_price': exit_,
            'opened_at': S + timedelta(days=1), 'closed_at': S + timedelta(days=3)}


def _lot(tid='b1', qty=D(10), cost=D('100')):
    return {'buy_trade_id': tid, 'quantity': qty, 'cost_per_share': cost, 'opened_at': S + timedelta(days=1)}


def _outcome(status, r=None):
    return {'status': status, 'r': r}


# --- rule track ---

def test_rule_missing_without_plan():
    assert tracks.plan_track(None, None) == {'plan_id': None, 'status': 'missing', 'r': None}
    assert tracks.plan_track(None, _outcome('closed', 1.0)) == {'plan_id': None, 'status': 'missing', 'r': None}


def test_rule_invalid_plan_is_zero():
    out = tracks.plan_track({**PLAN, 'status': 'invalid'}, _outcome('pending'))
    assert out == {'plan_id': PLAN['id'], 'status': 'not_executable', 'r': 0.0}


def test_rule_pending_has_no_r():
    out = tracks.plan_track(PLAN, _outcome('pending', None))
    assert out == {'plan_id': PLAN['id'], 'status': 'pending', 'r': None}


def test_rule_expired_is_zero():
    out = tracks.plan_track(PLAN, _outcome('expired', None))
    assert out == {'plan_id': PLAN['id'], 'status': 'expired', 'r': 0.0}


def test_rule_open_and_closed_take_simulated_r():
    assert tracks.plan_track(PLAN, _outcome('open', 0.5)) == {'plan_id': PLAN['id'], 'status': 'open', 'r': 0.5}
    assert tracks.plan_track(PLAN, _outcome('closed', 1.5)) == {'plan_id': PLAN['id'], 'status': 'closed', 'r': 1.5}


# --- agent track ---

def test_agent_pass_is_zero():
    out = tracks.agent_track(_run('pass'), None, None)
    assert out['status'] == 'pass' and out['r'] == 0.0
    assert out['plan_id'] is None


def test_agent_rejected_is_missing_with_reason():
    out = tracks.agent_track(_run('rejected', 'invalid_citation'), None, None)
    assert out == {'run_id': out['run_id'], 'run_status': 'rejected', 'run_reason': 'invalid_citation',
                   'plan_id': None, 'status': 'missing', 'r': None}


def test_agent_ok_uses_agent_plan_outcome():
    plan = {**PLAN, 'kind': 'agent'}
    out = tracks.agent_track(_run('ok', plan_id=plan['id']), plan, _outcome('closed', 2.0))
    assert out == {'run_id': out['run_id'], 'run_status': 'ok', 'run_reason': None,
                   'plan_id': plan['id'], 'status': 'closed', 'r': 2.0}


# --- actual track ---

def test_ignored_unit_is_not_executed_zero():
    out = tracks.actual_track(decision=_decision('ignore'), plan=PLAN, buys=[], segments=[], open_lots=[],
                              last_close=None, splits=[], session=S + timedelta(days=5),
                              unit_valid_until=PLAN['valid_until'])
    assert out['status'] == 'not_executed' and out['r'] == 0.0 and out['open'] is False


def test_buy_decision_without_fill_pending_until_validity_ends():
    until = PLAN['valid_until']
    pending = tracks.actual_track(decision=_decision('buy'), plan=PLAN, buys=[], segments=[], open_lots=[],
                                  last_close=None, splits=[], session=until - timedelta(days=1),
                                  unit_valid_until=until)
    assert pending['status'] == 'pending' and pending['r'] is None
    expired = tracks.actual_track(decision=_decision('buy'), plan=PLAN, buys=[], segments=[], open_lots=[],
                                  last_close=None, splits=[], session=until + timedelta(days=1),
                                  unit_valid_until=until)
    assert expired['status'] == 'not_executed' and expired['r'] == 0.0


def test_undecided_unit_pending_then_not_executed():
    until = PLAN['valid_until']
    pending = tracks.actual_track(decision=None, plan=PLAN, buys=[], segments=[], open_lots=[],
                                  last_close=None, splits=[], session=until - timedelta(days=1),
                                  unit_valid_until=until)
    assert pending['status'] == 'pending' and pending['final_action'] is None
    gone = tracks.actual_track(decision=None, plan=PLAN, buys=[], segments=[], open_lots=[],
                               last_close=None, splits=[], session=until + timedelta(days=1),
                               unit_valid_until=until)
    assert gone['status'] == 'not_executed' and gone['r'] == 0.0


def test_closed_r_priced_at_chosen_plan_stop():
    out = tracks.actual_track(decision=_decision('buy'), plan={**PLAN, 'kind': 'agent'}, buys=[_buy()],
                              segments=[_seg()], open_lots=[], last_close=None, splits=[],
                              session=S + timedelta(days=5), unit_valid_until=PLAN['valid_until'])
    assert out['plan_kind'] == 'agent' and out['r'] == 2.0     # (110-100)/(100-95)
    assert out['status'] == 'closed' and out['open'] is False
    assert out['buy_trade_ids'] == ['b1']


def test_partial_close_weights_open_lot():
    out = tracks.actual_track(decision=_decision('buy'), plan=PLAN,
                              buys=[_buy()],
                              segments=[_seg(qty=D(50), exit_=D('110'))],
                              open_lots=[_lot(qty=D(50), cost=D('100'))],
                              last_close=D('105'), splits=[], session=S + timedelta(days=5),
                              unit_valid_until=PLAN['valid_until'])
    assert out['r'] == 1.5      # (50x2R + 50x1R) / 100
    assert out['status'] == 'open' and out['open'] is True


def test_split_between_buy_and_now():
    splits = [(S + timedelta(days=2), D(2))]
    out = tracks.actual_track(decision=_decision('buy'), plan=PLAN, buys=[_buy()], segments=[],
                              open_lots=[_lot(qty=D(20), cost=D('50'))], last_close=D('52.5'),
                              splits=splits, session=S + timedelta(days=5),
                              unit_valid_until=PLAN['valid_until'])
    assert out['r'] == 1.0      # (52.5-50)/(50-47.5)：拆股后浮动 R 不变


def test_trade_without_plan_is_no_plan():
    out = tracks.actual_track(decision=_decision('buy', plan_id=None), plan=None, buys=[_buy()],
                              segments=[_seg()], open_lots=[], last_close=None, splits=[],
                              session=S + timedelta(days=5), unit_valid_until=PLAN['valid_until'])
    assert out['status'] == 'no_plan' and out['r'] is None and out['plan_kind'] is None


# --- summarize ---

def _row(pool='core', rule=None, agent=None, actual=None):
    return {'ticker': 'X', 'signal_date': S, 'pool': pool,
            'rule': rule or {'plan_id': None, 'status': 'missing', 'r': None},
            'agent': agent or {'run_id': None, 'run_status': None, 'run_reason': None,
                               'plan_id': None, 'status': 'missing', 'r': None},
            'actual': actual or {'decision_id': None, 'final_action': None, 'plan_id': None,
                                 'plan_kind': None, 'buy_trade_ids': [], 'status': 'missing',
                                 'r': None, 'open': False}}


def test_summarize_excludes_none_from_mean():
    rows = [_row(rule={'plan_id': 'a', 'status': 'pending', 'r': None}),
            _row(rule={'plan_id': 'b', 'status': 'closed', 'r': 2.0})]
    stats = tracks.summarize(rows)['all']['rule']
    assert stats['units'] == 2 and stats['determined'] == 1 and stats['pending'] == 1
    assert stats['mean'] == 2.0 and stats['median'] == 2.0 and stats['sum'] == 2.0 and stats['wins'] == 1


def test_summarize_by_pool_and_plan_kind():
    rows = [_row(pool='core',
                 actual={'decision_id': 'd', 'final_action': 'buy', 'plan_id': 'p', 'plan_kind': 'agent',
                         'buy_trade_ids': ['b'], 'status': 'closed', 'r': 1.0, 'open': False}),
            _row(pool='extended',
                 actual={'decision_id': None, 'final_action': 'ignore', 'plan_id': None, 'plan_kind': None,
                         'buy_trade_ids': [], 'status': 'not_executed', 'r': 0.0, 'open': False})]
    out = tracks.summarize(rows)
    assert out['all']['actual']['units'] == 2 and out['core']['actual']['units'] == 1
    assert out['all']['actual']['by_plan_kind'] == {'agent': 1, None: 1}
    assert out['extended']['actual']['by_status'] == {'not_executed': 1}


def test_status_text_covers_every_status():
    assert set(tracks.TRACK_STATUS_TEXT) == {'missing', 'not_executable', 'pending', 'expired',
                                             'open', 'closed', 'pass', 'not_executed', 'no_plan'}
    assert tracks.TRACKS_VERSION == 'tracks-1'
