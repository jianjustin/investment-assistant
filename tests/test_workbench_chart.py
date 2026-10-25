"""Chart payload for the instrument view: split-adjusted bars with simple moving averages."""
from datetime import date, timedelta

from investment_assistant.workbench.chart import KEEP, READ_LIMIT, WINDOWS, build


def _bars(n, *, start=date(2026, 1, 1)):
    return [{'price_date': start + timedelta(days=i), 'open': i + 1.0, 'high': i + 1.0,
             'low': i + 1.0, 'close': float(i + 1), 'volume': 1000 + i} for i in range(n)]


def test_constants():
    assert (READ_LIMIT, KEEP, WINDOWS) == (450, 250, (20, 50, 200))


def test_ma_values_are_simple_close_averages():
    out = build(_bars(300))
    last = out['bars'][-1]
    assert last['ma20'] == sum(range(281, 301)) / 20
    assert last['ma50'] == sum(range(251, 301)) / 50
    assert last['ma200'] == sum(range(101, 301)) / 200


def test_keeps_last_250_but_uses_full_history_for_ma():
    out = build(_bars(450))
    assert len(out['bars']) == KEEP
    # The first returned bar is input #201; its ma200 needs the 200 bars dropped from the payload.
    assert out['bars'][0]['price_date'] == date(2026, 1, 1) + timedelta(days=200)
    assert out['bars'][0]['ma200'] is not None
    assert out['bars'][-1]['price_date'] == date(2026, 1, 1) + timedelta(days=449)
    assert out['adjustment'] == 'split_only'


def test_chart_short_history_keeps_nulls():
    out = build(_bars(120))
    assert len(out['bars']) == 120
    assert all(bar['ma200'] is None for bar in out['bars'])
    assert all(bar['ma50'] is None for bar in out['bars'][:49])
    assert out['bars'][49]['ma50'] is not None
    candle_keys = {'price_date', 'open', 'high', 'low', 'close', 'volume', 'ma20', 'ma50', 'ma200'}
    assert candle_keys <= set(out['bars'][0])


def test_empty_bars():
    assert build([]) == {'bars': [], 'adjustment': 'split_only'}
