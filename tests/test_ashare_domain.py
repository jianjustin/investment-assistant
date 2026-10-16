from datetime import UTC, date, datetime

import pytest

from investment_assistant.ashare.domain import (
    comparison, financial_periods, last_closed_session, performance, security_id,
    stock_id, trading_day, us_only,
)
from investment_assistant.ashare.service import adjusted_bars, checked_valuation, describe_status


@pytest.mark.parametrize('value', ['688008', '000300.SH', '931865.SH', '688008.SZ', '510300.SH', 'INDEX.000001.SH'])
def test_stock_identity_rejects_ambiguous_or_nonstock_codes(value):
    with pytest.raises(ValueError):
        stock_id(value)


def test_explicit_index_stock_identity_and_us_isolation():
    assert stock_id('688008.sh') == 'CN:stock:688008.SH'
    assert stock_id('000001.SZ') != security_id('CN:index:000300.SH')
    assert us_only(['MU', '688008.SH', 'NVDA', 'CRDO']) == ['MU', 'NVDA', 'CRDO']


@pytest.mark.parametrize('day,expected', [('2026-02-23', False), ('2026-02-24', True),
    ('2026-10-07', False), ('2026-10-08', True), ('2026-10-10', False), ('2025-10-11', False)])
def test_china_calendar_no_makeup_weekends(day, expected):
    assert trading_day(date.fromisoformat(day)) is expected


def test_unknown_year_is_not_guessed_and_intraday_is_excluded():
    with pytest.raises(ValueError):
        trading_day(date(2027, 1, 4))
    assert last_closed_session(datetime(2026, 10, 16, 4, tzinfo=UTC)) == date(2026, 10, 15)


def row(period, revenue, id=1):
    return {'period_end': period, 'revenue': revenue, 'parent_profit': revenue / 2,
            'deducted_profit': revenue / 3, 'operating_cashflow': revenue / 4,
            'gross_profit': revenue * .6, 'inventory': 17, 'shares': 100, 'id': id}


def test_ytd_difference_keeps_balance_and_recalculates_margin():
    result = financial_periods([row('2026-03-31', 100, 1), row('2026-06-30', 250, 2)])
    assert result[0]['quarter']['revenue'] == 150
    assert result[0]['quarter']['gross_margin_pct'] == 60
    assert result[0]['inventory'] == 17
    assert result[0]['shares'] == 100
    assert result[0]['quarter_inputs'] == [2, 1]


def test_missing_prior_is_null_not_zero_and_cross_year_is_not_subtracted():
    result = financial_periods([row('2025-12-31', 400), row('2026-06-30', 250)])
    assert result[0]['quarter']['revenue'] is None
    assert result[0]['ttm']['revenue'] is None
    first = financial_periods([row('2025-12-31', 400), row('2026-03-31', 90)])
    assert first[0]['quarter']['revenue'] == 90


def test_ttm_is_four_consecutive_quarters_not_annualised_latest():
    data = [row('2025-03-31', 50), row('2025-06-30', 120), row('2025-09-30', 210),
            row('2025-12-31', 350), row('2026-03-31', 100), row('2026-06-30', 220)]
    assert financial_periods(data)[0]['ttm']['revenue'] == 450  # 350 - 120 + 220


def test_adjustment_uses_hfq_multiplier_and_no_factor_no_price():
    bars = [{'date': '2026-01-01', 'open': 10, 'close': 10, 'high': 10, 'low': 10, 'volume': 100},
            {'date': '2026-01-02', 'open': 5, 'close': 5, 'high': 5, 'low': 5, 'volume': 200}]
    f = [{'id': 3, 'factors': [{'date': '2026-01-01', 'factor': 1}, {'date': '2026-01-02', 'factor': 2}]}]
    qfq = adjusted_bars(bars, f, '2026-01-02', basis='qfq')
    assert [x['close'] for x in qfq] == [5, 5]
    assert qfq[0]['volume'] == 100
    assert adjusted_bars(bars, [], '2026-01-02', basis='qfq')[0]['close'] is None
    late = [{'id': 3, 'factors': [{'date': '2026-01-02', 'factor': 2}]}]
    assert adjusted_bars(bars, late, '2026-01-02', basis='qfq')[0]['close'] is None


def test_returns_drawdown_and_common_dates():
    bars = [{'date': f'2026-01-0{i}', 'close': n} for i, n in enumerate([100, 120, 90, 110], start=1)]
    p = performance(bars)
    assert p['return_pct'] == pytest.approx(10)
    assert p['max_drawdown_pct'] == -25
    c = comparison(bars, [{'date': '2026-01-02', 'close': 100}, {'date': '2026-01-04', 'close': 105}])
    assert c['start'] == '2026-01-02'
    assert c['relative_return_pp'] == pytest.approx((110 / 120 - 1) * 100 - 5)
    assert c['excluded_stock_sessions'] == 2


def test_failed_empty_stale_and_uncollected_are_distinct():
    now = datetime(2026, 10, 16, 8, tzinfo=UTC)
    state = {'dataset': 'announcements', 'status': 'failed', 'succeeded_at': now,
             'error': 'HTTP 429', 'attempted_at': now}
    rows = [{'data_date': '2026-09-30', 'first_seen_at': now}]
    assert describe_status(state, rows, 'announcements', now=now)['retained_old_values']
    assert describe_status(state, rows, 'announcements', now=now)['status'] == 'failed'
    assert describe_status(None, [], 'announcements')['status'] == 'never_collected'
    assert describe_status({**state, 'status': 'empty'}, [], 'announcements', now=now)['status'] == 'empty'
    assert describe_status({**state, 'status': 'ready', 'succeeded_at': datetime(2026,1,1,tzinfo=UTC)}, rows,
                           'announcements', now=now)['status'] == 'stale'


def test_nonpositive_ttm_suppresses_vendor_pe_without_using_future_report():
    valuation = {'date': '2026-10-15', 'pe_ttm': 30}
    loss = {'period_end': '2026-06-30', 'first_disclosed_date': '2026-08-28', 'ttm': {'parent_profit': -5}}
    assert checked_valuation(valuation, [loss])['pe_ttm'] is None
    assert checked_valuation(valuation, [loss])['source_pe_ttm'] == 30
    assert checked_valuation({**valuation, 'date': '2026-07-01'}, [loss])['pe_ttm'] == 30
