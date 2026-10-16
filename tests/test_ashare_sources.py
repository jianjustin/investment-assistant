from datetime import date
from unittest.mock import Mock

import pytest

from investment_assistant.ashare.sources import PublicSources, SourceError, number
from investment_assistant.ashare.cards import Scenario, scenario_values
from investment_assistant.ashare.repository import content_hash


def test_source_business_failure_is_not_no_records(tmp_path):
    source = PublicSources(archive=tmp_path)
    source.get = lambda *a, **k: ({'success': False, 'code': 9501, 'message': 'broken report'}, {'source_url': 'https://example.com'})
    with pytest.raises(SourceError):
        source.report('RPT_LICO_FN_CPD', '688008.SH')


def test_partial_pagination_and_ignored_symbol_filter_fail(tmp_path):
    source = PublicSources(archive=tmp_path)
    source.get = lambda *a, **k: ({'success': True, 'result': {'pages': 2, 'data': [], 'count': 200}}, {})
    with pytest.raises(SourceError, match='中途缺失'):
        source.report('RPT', '688008.SH')
    source.get = lambda *a, **k: ({'success': True, 'result': {'pages': 1, 'data': [{'SECUCODE': '600519.SH'}]}}, {})
    with pytest.raises(SourceError, match='证券过滤'):
        source.report('RPT', '688008.SH')


def test_unknown_numeric_does_not_become_zero():
    for x in [None, '', '-', 'bad', float('inf'), float('nan')]:
        assert number(x) is None
    assert number(0) == 0


def test_snapshot_hash_ignores_fetch_window_but_preserves_financial_revision():
    a = {'payload': {'value': 5, 'origins': [{'source_url': 'https://example.com?a=1'}]}, 'data_date': '2026-01-01'}
    b = {'payload': {'value': 5, 'origins': [{'source_url': 'https://example.com?a=2'}]}, 'data_date': '2026-01-01'}
    assert content_hash(a) == content_hash(b)
    b['payload']['value'] = 4
    assert content_hash(a) != content_hash(b)


def test_negative_profit_does_not_produce_regular_pe_value():
    body = {'scenarios': [{'profit_cny': -100, 'pe': 20, 'shares': 10}]}
    assert scenario_values(body)[0]['implied_value_per_share'] is None
    with pytest.raises(ValueError):
        Scenario(label='bad', method='analyst_assumption', period='FY2026', share_basis='total', pe=-1)


def test_task_never_sends_notifications_and_obeys_cn_holidays(monkeypatch):
    from investment_assistant.tasks import ashares
    from investment_assistant.config import AssistantConfig
    called = {}
    monkeypatch.setattr(ashares, 'run_task', lambda task, fn, **kw: called.update(kw) or fn())
    monkeypatch.setattr(ashares, 'today_cn', lambda: date(2026, 10, 1))
    monkeypatch.setattr(ashares.service, 'sync', Mock(side_effect=AssertionError('holiday must skip')))
    assert '休市' in ashares.run(AssistantConfig())['skipped']
    assert called['notify'] is False


def test_legacy_us_scan_rejects_explicit_a_shares():
    from investment_assistant.services.tickers import run_ticker_trend_scan
    with pytest.raises(ValueError, match='A股'):
        run_ticker_trend_scan({'tickers': ['688008.SH']})


def test_optional_financial_source_failure_preserves_other_fields(tmp_path):
    source = PublicSources(archive=tmp_path)

    def report(name, symbol, **kwargs):
        if name != 'RPT_LICO_FN_CPD':
            raise SourceError('HTTP 429: limited')
        return [{'REPORTDATE': '2026-06-30', 'TOTAL_OPERATE_INCOME': 250,
                 'PARENT_NETPROFIT': 40, 'NOTICE_DATE': '2026-08-28'}], [{'source_url': 'https://example.com'}]

    source.report = report
    row = source.financials('CN:stock:688008.SH', date(2025, 1, 1), date(2026, 10, 15))[0]['payload']
    assert row['revenue'] == 250
    assert row['inventory'] is None and row['shares'] is None
    assert len(row['component_errors']) == 4


def test_announcement_clock_jitter_does_not_create_versions():
    a = {'payload': {'title': 'report', 'display_time': '2026-09-24 10:00:00.101'}}
    b = {'payload': {'title': 'report', 'display_time': '2026-09-24 10:00:00.999'}}
    assert content_hash(a) == content_hash(b)
    b['payload']['title'] = 'revised report'
    assert content_hash(a) != content_hash(b)


def test_explicit_a_share_does_not_enter_us_macro_rules(monkeypatch):
    from investment_assistant.services import hermes, market
    monkeypatch.setattr(market, 'market_signal_rows', lambda _: [])
    with pytest.raises(ValueError, match='SPY/VIX'):
        hermes.hermes_macro_analysis({'watchlist': ['688008.SH']})
    with pytest.raises(ValueError, match='SPY/VIX'):
        hermes.run_hermes_macro_llm_analysis({'watchlist': ['688008.SH']})
