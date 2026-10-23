"""Discipline flags against confirmed plans (spec §6.2)."""
from datetime import date, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import discipline

NY = ZoneInfo('America/New_York')
D0, D1, D2, D3, D4 = (date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23),
                      date(2026, 10, 26))


def at(day, hour=15):
    return datetime(day.year, day.month, day.day, hour, tzinfo=NY)


def bar(day, o=100, h=101, l=99, c=100):
    return {'id': 1, 'price_date': day, 'open': float(o), 'high': float(h), 'low': float(l), 'close': float(c),
            'adj_close': float(c), 'volume': 1, 'split_factor': 1.0}


def trade(id_, ticker='NVDA', side='buy', price=100, executed=None, decision_id='d1', quantity=10):
    return {'id': id_, 'ticker': ticker, 'side': side, 'quantity': quantity, 'price': str(price),
            'executed_at': executed or at(D1), 'decision_id': decision_id, 'voided_at': None}


def decision(id_='d1', plan_id='p1'):
    return {'id': id_, 'plan_id': plan_id}


def plan(id_='p1', kind='rule'):
    return {'id': id_, 'kind': kind, 'ticker': 'NVDA', 'signal_date': D0, 'entry_low': D('98'),
            'entry_high': D('102'), 'stop': D('94'), 'target1': D('112')}


def segment(buy='b1', sell='s1', *, cost=100, exit_=105, opened=D1, closed=D2, quantity=10):
    return {'buy_trade_id': buy, 'sell_trade_id': sell, 'quantity': quantity,
            'entry_cost_per_share': D(cost), 'exit_price': D(exit_), 'opened_at': at(opened),
            'closed_at': at(closed)}


def evaluate(trades, *, decisions=None, plans=None, bars=None, stop_events=(), segments=(), session=D4):
    return discipline.evaluate(
        trades=trades,
        decisions_by_id=decisions if decisions is not None else {'d1': decision()},
        plans_by_id=plans if plans is not None else {'p1': plan()},
        bars_by_ticker={'NVDA': bars if bars is not None else [bar(D1), bar(D2), bar(D3), bar(D4)]},
        stop_events=list(stop_events), segments=list(segments), session=session)


def test_chase_above_entry_high():
    out = evaluate([trade('b1', price=103)])
    assert out['trades'][0]['flags'] == ['chase']
    assert out['counts'] == {'chase': 1, 'early_take': 0, 'held_loser': 0, 'unplanned': 0}
    assert out['compliance_rate'] == 0.0


def test_unplanned_without_decision():
    out = evaluate([trade('b1', decision_id=None)])
    assert out['trades'][0]['flags'] == ['unplanned']
    assert out['planned_buys'] == 0 and out['compliance_rate'] is None


def test_unplanned_decision_without_plan():
    out = evaluate([trade('b1')], decisions={'d1': decision(plan_id=None)})
    assert out['trades'][0]['flags'] == ['unplanned']


def test_early_take_matures_after_20_sessions():
    sell_day = D2
    later_t1 = add_trading_days(sell_day, 21)
    bars = [bar(D1), bar(sell_day), bar(add_trading_days(sell_day, 1))]
    bars += [bar(add_trading_days(sell_day, 5), h=113)]          # T1 到达（卖出后 20 个交易日内）
    bars += [bar(later_t1)]
    trades = [trade('b1', price=100, executed=at(D1)), trade('s1', side='sell', price=105, executed=at(sell_day))]

    immature = evaluate(trades, bars=bars, segments=[segment(closed=sell_day)],
                        session=add_trading_days(sell_day, 19))
    assert 'early_take' in immature['trades'][0]['immature']
    assert immature['counts']['early_take'] == 0

    mature = evaluate(trades, bars=bars, segments=[segment(closed=sell_day)],
                      session=add_trading_days(sell_day, 20))
    assert 'early_take' in mature['trades'][0]['flags']


def test_sell_after_plan_stop_not_early_take():
    bars = [bar(D1), bar(D2), bar(D3), bar(D4, h=113)]
    trades = [trade('b1', price=100, executed=at(D1)), trade('s1', side='sell', price=95, executed=at(D2))]
    out = evaluate(trades, bars=bars, segments=[segment(exit_=95, closed=D2)], session=D4,
                   stop_events=[{'ticker': 'NVDA', 'signal_date': D2, 'rule_id': 'plan_stop'}])
    assert out['trades'][0]['flags'] == []


def test_held_loser_when_no_sell_next_session():
    out = evaluate([trade('b1', price=100)], session=D3,
                   stop_events=[{'ticker': 'NVDA', 'signal_date': D2, 'rule_id': 'plan_stop'}])
    assert 'held_loser' in out['trades'][0]['flags']
    assert out['counts']['held_loser'] == 1


def test_early_take_after_stop_window_still_flags():
    # 止损日后第 3 个交易日才卖出：超出「当日/次日」豁免窗口，T1 随后到位仍算过早止盈
    sell_day = add_trading_days(D2, 3)
    bars = [bar(D1), bar(D2), bar(sell_day), bar(add_trading_days(sell_day, 2), h=113)]
    trades = [trade('b1', price=100, executed=at(D1)), trade('s1', side='sell', price=105, executed=at(sell_day))]
    out = evaluate(trades, bars=bars, segments=[segment(closed=sell_day)],
                   session=add_trading_days(sell_day, 20),
                   stop_events=[{'ticker': 'NVDA', 'signal_date': D2, 'rule_id': 'plan_stop'}])
    assert 'early_take' in out['trades'][0]['flags']


def test_held_loser_cleared_by_next_day_sell():
    trades = [trade('b1', price=100, executed=at(D1)), trade('s1', side='sell', price=95, executed=at(D3))]
    out = evaluate(trades, session=D4,
                   stop_events=[{'ticker': 'NVDA', 'signal_date': D2, 'rule_id': 'plan_stop'}])
    assert out['trades'][0]['flags'] == []


def test_compliance_rate():
    trades = [trade('b1', price=100, executed=at(D1)), trade('b2', price=103, executed=at(D1)),
              trade('b3', decision_id=None)]
    out = evaluate(trades)
    assert out['planned_buys'] == 2
    assert out['counts'] == {'chase': 1, 'early_take': 0, 'held_loser': 0, 'unplanned': 1}
    assert out['compliance_rate'] == 0.5


def test_actual_r_uses_plan_stop():
    trades = [trade('b1', price=100, executed=at(D1)), trade('s1', side='sell', price=106, executed=at(D2))]
    out = evaluate(trades, segments=[segment(exit_=106, closed=D2)])
    assert out['trades'][0]['r'] == pytest.approx(1.0)  # (106-100)/(100-94)，不是成本回撤口径


def test_track_from_plan_kind():
    out = evaluate([trade('b1')], plans={'p1': plan(kind='own')})
    assert out['trades'][0]['track'] == 'own'


def test_early_take_ignores_highs_before_the_buy():
    # 买入前很久曾高于 T1，不能算作「卖出时已触及 T1」
    sell_day = D2
    bars = [bar(add_trading_days(D1, -30), h=150), bar(D1), bar(sell_day)]
    bars += [bar(add_trading_days(sell_day, 5), h=113)]          # 卖出后 20 个交易日内 T1 到达
    trades = [trade('b1', price=100, executed=at(D1)), trade('s1', side='sell', price=105, executed=at(sell_day))]
    out = evaluate(trades, bars=bars, segments=[segment(closed=sell_day)], session=add_trading_days(sell_day, 20))
    assert 'early_take' in out['trades'][0]['flags']
