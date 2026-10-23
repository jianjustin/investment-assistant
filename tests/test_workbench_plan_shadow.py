"""plan-shadow-1 simulation: entry, stop, T1 and trailing per spec §6.1 (hand-computed)."""
from datetime import date
from decimal import Decimal as D

import pytest

from investment_assistant.workbench import plan_shadow

D0, D1, D2, D3, D4 = date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 26)


def plan(**overrides):
    p = {'id': 'p1', 'ticker': 'NVDA', 'signal_date': D0, 'kind': 'rule', 'entry_low': D('98'),
         'entry_high': D('102'), 'stop': D('94'), 'target1': D('112'), 'atr': D('2'),
         'trail_atr_multiple': D('3'), 'valid_from': D1, 'valid_until': D3}
    p.update(overrides)
    return p


def bar(day, o, h, l, c):
    return {'id': 1, 'price_date': day, 'open': float(o), 'high': float(h), 'low': float(l), 'close': float(c),
            'adj_close': float(c), 'volume': 1, 'split_factor': 1.0}


def spy(*days):
    return [bar(d, 500, 501, 499, 500) for d in days]


def sim(plan_dict, bars, splits=()):
    return plan_shadow.simulate(plan_dict, bars, spy(*(b['price_date'] for b in bars)), splits=list(splits))


def test_fill_at_open_inside_zone():
    out = sim(plan(), [bar(D1, 100, 103, 99, 101), bar(D2, 101, 104, 100, 102)])
    assert out['status'] == 'open'
    assert out['fill_date'] == D1 and out['fill_price'] == D('100')
    assert out['legs'] == []
    assert out['r'] == pytest.approx((102 - 100) / (100 - 94))
    assert out['spy_return'] == 0.0


def test_fill_at_entry_high_when_gap_up_then_dip():
    out = sim(plan(), [bar(D1, 110, 111, 101, 105)])
    assert out['fill_price'] == D('102') and out['fill_date'] == D1


def test_fill_at_entry_low_when_gap_down_then_rise():
    out = sim(plan(), [bar(D1, 90, 101, 89, 99)])
    assert out['fill_price'] == D('98') and out['fill_date'] == D1


def test_expired_without_touch():
    out = sim(plan(), [bar(D1, 90, 95, 88, 92), bar(D2, 91, 96, 89, 93), bar(D3, 92, 97, 90, 94), bar(D4, 92, 97, 90, 93)])
    assert out['status'] == 'expired' and out['legs'] == []
    assert out['r'] is None and out['fill_date'] is None


def test_stop_same_day_as_fill():
    out = sim(plan(), [bar(D1, 100, 103, 93.5, 95)])
    assert out['status'] == 'closed'
    assert out['legs'] == [{'fraction': 1.0, 'exit_date': D1.isoformat(), 'exit_price': D('94'), 'reason': 'stop'}]
    assert out['r'] == pytest.approx(-1.0)


def test_gap_below_stop_exits_at_open():
    out = sim(plan(), [bar(D1, 100, 103, 99, 101), bar(D2, 92, 93, 90, 91)])
    assert out['legs'][0]['exit_price'] == D('92') and out['legs'][0]['reason'] == 'stop'
    assert out['r'] == pytest.approx(-8 / 6)


def test_t1_half_then_trail():
    bars = [bar(D1, 100, 103, 99, 101), bar(D2, 105, 113, 104, 111), bar(D3, 106, 108, 104, 105)]
    out = sim(plan(), bars)
    assert out['status'] == 'closed'
    assert out['legs'] == [{'fraction': 0.5, 'exit_date': D2.isoformat(), 'exit_price': D('112'), 'reason': 'target1'},
                           {'fraction': 0.5, 'exit_date': D3.isoformat(), 'exit_price': D('105'), 'reason': 'trail'}]
    assert out['r'] == pytest.approx(((112 - 100) / 6 + (105 - 100) / 6) / 2)
    assert out['return'] == pytest.approx((0.5 * 112 + 0.5 * 105) / 100 - 1)


def test_stop_and_t1_same_day_stop_first():
    out = sim(plan(), [bar(D1, 100, 103, 99, 101), bar(D2, 101, 113, 93, 99)])
    assert out['legs'] == [{'fraction': 1.0, 'exit_date': D2.isoformat(), 'exit_price': D('94'), 'reason': 'stop'}]
    assert out['r'] == pytest.approx(-1.0)


def test_trail_floor_is_fill_price():
    bars = [bar(D1, 100, 103, 99, 101), bar(D2, 105, 112.5, 104, 105), bar(D3, 101, 103, 99.5, 100)]
    out = sim(plan(), bars)
    assert out['legs'][1]['exit_price'] == D('100') and out['legs'][1]['reason'] == 'trail'
    assert out['r'] == pytest.approx(((112 - 100) / 6 + 0) / 2)


def test_split_inside_window():
    # 存储口径：拆股后重抓取会把历史 bar 修订为当前基准；只有计划价位需要换算
    bars = [bar(D1, 50, 51.5, 49.5, 50), bar(D2, 50.5, 57, 49.5, 56), bar(D3, 52, 52.5, 51, 51.2)]
    out = sim(plan(), bars, splits=[(D2, D(2))])
    assert out['fill_price'] == D('50') and out['fill_date'] == D1
    # trail = 56 − 3 ×（ATR 2 ÷ 2）= 53，D3 开盘 52 跳空低于止损，按开盘出场
    assert out['legs'] == [{'fraction': 0.5, 'exit_date': D2.isoformat(), 'exit_price': D('56'), 'reason': 'target1'},
                           {'fraction': 0.5, 'exit_date': D3.isoformat(), 'exit_price': D('52'), 'reason': 'trail'}]
    assert out['r'] == pytest.approx(((56 - 50) / 3 + (52 - 50) / 3) / 2)


def test_open_reports_floating_r():
    bars = [bar(D1, 100, 103, 99, 101), bar(D2, 105, 113, 104, 111), bar(D3, 118, 121, 117, 120)]
    out = sim(plan(), bars)
    assert out['status'] == 'open'
    assert out['legs'][0]['reason'] == 'target1'
    assert out['r'] == pytest.approx(((112 - 100) / 6 + (120 - 100) / 6) / 2)
    assert out['return'] == pytest.approx((0.5 * 112 + 0.5 * 120) / 100 - 1)


def test_pending_before_valid_from():
    out = sim(plan(), [bar(D0, 100, 101, 99, 100)])
    assert out['status'] == 'pending' and out['fill_date'] is None and out['r'] is None
