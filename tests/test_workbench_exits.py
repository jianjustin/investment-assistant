"""Position plan derivation and the active stop (design §5.1, §5.2)."""
from datetime import date, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from investment_assistant.workbench import exits

NY = ZoneInfo('America/New_York')
T0, T1, T2 = date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)


def plan(**overrides):
    p = {'id': 'p1', 'ticker': 'NVDA', 'signal_date': date(2026, 10, 19), 'kind': 'rule',
         'stop': D('94'), 'target1': D('112'), 'atr': D('3'), 'trail_atr_multiple': D('3')}
    p.update(overrides)
    return p


def bar(day, *, open_=100, high=101, low=99, close=100):
    return {'id': 1, 'price_date': day, 'open': float(open_), 'high': float(high), 'low': float(low),
            'close': float(close), 'adj_close': float(close), 'volume': 100, 'split_factor': 1.0}


def test_initial_stop_before_t1():
    bars = [bar(T0, close=100), bar(T1, close=105, high=106), bar(T2, close=106, high=110)]
    assert exits.active_stop(plan(), bars, avg_cost=D('100'), splits=[]) == \
        {'stop': D('94'), 't1_reached': False, 't1_reached_on': None, 'mode': 'initial', 'target1': D('112')}


def test_trailing_after_t1():
    bars = [bar(T0, close=100, high=100), bar(T1, close=120, high=121), bar(T2, close=118, high=119)]
    state = exits.active_stop(plan(), bars, avg_cost=D('100'), splits=[])
    assert state['t1_reached'] is True and state['t1_reached_on'] == T1
    assert state['mode'] == 'trailing'
    assert state['stop'] == D('111')  # 最高收盘 120 − 3 ATR × 3
    assert state['target1'] == D('112')


def test_trailing_floor_is_cost():
    bars = [bar(T0, close=100, high=100), bar(T1, close=110, high=113), bar(T2, close=108, high=109)]
    state = exits.active_stop(plan(), bars, avg_cost=D('105'), splits=[])
    assert state['mode'] == 'trailing'
    assert state['stop'] == D('105')  # 110 − 9 低于成本，取成本


def test_split_rescales_levels():
    bars = [bar(T0, close=100, high=105), bar(T1, close=60, high=55), bar(T2, close=55, high=54)]
    state = exits.active_stop(plan(), bars, avg_cost=D('52'), splits=[(T1, D(2))])
    assert state['mode'] == 'initial'
    assert state['stop'] == D('47') and state['target1'] == D('56')
    # 触及 T1 后的移动止损同样按拆股换算：最高收盘（换算后 60）− 1.5 × 3
    hit = [bar(T0, close=100, high=105), bar(T1, close=60, high=57), bar(T2, close=55, high=55)]
    state2 = exits.active_stop(plan(), hit, avg_cost=D('50'), splits=[(T1, D(2))])
    assert state2['mode'] == 'trailing' and state2['stop'] == D('55.5')


def test_position_plan_picks_latest_planned_buy():
    trades = [{'id': 'b1', 'executed_at': datetime(2026, 10, 15, 15, tzinfo=NY)},
              {'id': 'b2', 'executed_at': datetime(2026, 10, 20, 15, tzinfo=NY)}]
    lots = [{'buy_trade_id': 'b1'}, {'buy_trade_id': 'b2'}]
    assert exits.position_plan(lots, trades, {'b1': {'id': 'p1'}})['id'] == 'p1'
    assert exits.position_plan(lots, trades, {'b1': {'id': 'p1'}, 'b2': {'id': 'p2'}})['id'] == 'p2'
    assert exits.position_plan(lots, trades, {}) is None


def test_rebuy_after_flat_uses_no_old_plan():
    # 清仓后重新买入：旧批次的计划不属于当前持仓，且新买入无计划
    trades = [{'id': 'b1', 'executed_at': datetime(2026, 10, 1, 15, tzinfo=NY)},
              {'id': 'b3', 'executed_at': datetime(2026, 10, 20, 15, tzinfo=NY)}]
    lots = [{'buy_trade_id': 'b3'}]
    assert exits.position_plan(lots, trades, {'b1': {'id': 'p1'}}) is None
