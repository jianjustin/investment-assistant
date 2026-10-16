import hashlib
import json
import logging
from pathlib import Path

import pytest
import requests

from test_us_research_domain import module


class Response:
    def __init__(self, payload, status=200):
        self.content = json.dumps(payload).encode()
        self.status_code = status
        self.headers = {}


class Session:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def sec_payload(cik=1):
    return {'cik': cik, 'entityName': 'Example', 'facts': {'us-gaap': {'Revenues': {'units': {'USD': [
        {'val': 20, 'start': '2024-01-01', 'end': '2024-03-31', 'form': '10-Q',
         'accn': '0000000001-24-000001', 'filed': '2024-05-01'}]}}}}}


def test_sec_identity_and_exact_bytes_snapshot(monkeypatch, tmp_path):
    sources = module('sources')
    monkeypatch.setenv('SEC_USER_AGENT', 'local-test contact@example.invalid')
    session = Session([Response({'0': {'ticker': 'MU', 'cik_str': 1}}), Response(sec_payload())])
    result = sources.USSources(session=session, cache_dir=tmp_path, backoff_seconds=0).companyfacts('MU')
    assert result['identity'] == {'ticker': 'MU', 'security_id': 'US:stock:MU', 'cik': '0000000001', 'name': 'Example'}
    assert result['observations'][0]['value'] == 20
    assert result['source_hash'] == hashlib.sha256(result['raw_snapshot']).hexdigest()
    assert isinstance(result['raw_snapshot'], bytes)
    assert result['observations'][0]['source_hash'] == result['source_hash']
    assert result['coverage']['kind'] == 'historical_backfill_current_version'
    assert (tmp_path / 'company_tickers.json').exists()
    assert session.requests[1][1]['headers']['User-Agent'] == 'local-test contact@example.invalid'


def test_sec_cik_mismatch_is_not_a_valid_empty_company(monkeypatch):
    sources = module('sources')
    monkeypatch.setenv('SEC_USER_AGENT', 'contact@example.invalid')
    session = Session([Response({'0': {'ticker': 'MU', 'cik_str': 1}}), Response(sec_payload(2))])
    with pytest.raises(sources.SourceError, match='identity'):
        sources.USSources(session=session, backoff_seconds=0).companyfacts('MU')


def test_source_transport_retries_without_leaking_exception_or_response(monkeypatch, caplog):
    sources = module('sources')
    monkeypatch.setenv('SEC_USER_AGENT', 'contact@example.invalid')
    secret = 'password-from-proxy@example.com'
    session = Session([requests.ConnectionError(secret), Response({'secret': secret}, 503),
                       Response({'0': {'ticker': 'MU', 'cik_str': 1}}), Response(sec_payload())])
    with caplog.at_level(logging.WARNING):
        result = sources.USSources(session=session, backoff_seconds=0).companyfacts('MU')
    assert result['observations'][0]['value'] == 20
    assert secret not in caplog.text
    fail = Session([requests.ConnectionError(secret)] * 4)
    with pytest.raises(sources.SourceError) as exc:
        sources.USSources(session=fail, backoff_seconds=0).companyfacts('MU')
    assert secret not in str(exc.value) + caplog.text


def yahoo(symbol='MU'):
    return {'chart': {'error': None, 'result': [{'meta': {'symbol': symbol, 'currency': 'USD',
        'exchangeTimezoneName': 'America/New_York', 'regularMarketTime': 1735833600,
        'regularMarketPrice': 11, 'sharesOutstanding': 5, 'marketCap': 55},
        'timestamp': [1735747200, 1735833600], 'indicators': {'quote': [{'open': [9, 10],
        'high': [11, 12], 'low': [8, 9], 'close': [10, 11], 'volume': [100, 200]}],
        'adjclose': [{'adjclose': [5, 5.5]}]}}]}}


def test_market_keeps_raw_adjusted_and_quote_basis_separate():
    sources = module('sources')
    session = Session([Response(yahoo(t)) for t in ['MU', 'SPY', 'QQQ']])
    result = sources.USSources(session=session, backoff_seconds=0).market('MU')
    assert result['bars'][0]['close'] == 10
    assert result['bars'][0]['adjusted_close'] == 5
    assert result['quote']['currency'] == 'USD'
    assert result['quote']['market_cap_verified'] is False
    assert result['quote']['share_class_basis'] == 'unverified'
    assert set(result['benchmarks']) == {'SPY', 'QQQ'}
    assert len(result['raw_snapshots']) == 3
    assert result['bars'][0]['source_hash']


def test_market_identity_mismatch_rejected():
    sources = module('sources')
    with pytest.raises(sources.SourceError, match='identity'):
        sources.USSources(session=Session([Response(yahoo('BAD'))]), backoff_seconds=0).market('MU')


def test_benchmark_failure_keeps_stock_bars_and_explicit_limitation():
    sources = module('sources')
    session = Session([Response(yahoo()), Response({}, 404), Response(yahoo('QQQ'))])
    result = sources.USSources(session=session, backoff_seconds=0).market('MU')
    assert len(result['bars']) == 2
    assert result['benchmarks']['SPY'] == []
    assert any('SPY' in x for x in result['limitations'])


def test_source_metadata_preserves_request_parameters():
    sources = module('sources')
    session = Session([Response(yahoo(t)) for t in ['MU', 'SPY', 'QQQ']])
    result = sources.USSources(session=session, backoff_seconds=0).market('MU')
    assert result['raw_snapshots'][0]['request_params']['includeAdjustedClose'] == 'true'


def test_malformed_chart_is_sanitized_source_error():
    sources = module('sources')
    with pytest.raises(sources.SourceError):
        sources.USSources(session=Session([Response({'chart': {'result': [None]}})]), backoff_seconds=0).market('MU')


@pytest.mark.parametrize('broken_part', ['chart', 'meta', 'quote', 'indicators', 'adjclose', 'timestamps', 'close_values'])
def test_nested_malformed_benchmark_keeps_successful_stock_and_other_benchmark(broken_part):
    sources = module('sources')
    malformed = yahoo('SPY')
    result = malformed['chart']['result'][0]
    if broken_part == 'chart':
        malformed['chart'] = [1]
    elif broken_part == 'meta':
        result['meta'] = [1]
    elif broken_part == 'quote':
        result['indicators']['quote'] = [None]
    elif broken_part == 'indicators':
        result['indicators'] = [1]
    elif broken_part == 'adjclose':
        result['indicators']['adjclose'] = [None]
    elif broken_part == 'timestamps':
        result['timestamp'] = {'unexpected': 1}
    else:
        result['indicators']['quote'][0]['close'] = {'unexpected': 10}
    session = Session([Response(yahoo('MU')), Response(malformed), Response(yahoo('QQQ'))])
    output = sources.USSources(session=session, backoff_seconds=0).market('MU')
    assert output['bars'][0]['close'] == 10
    assert output['benchmarks']['SPY'] == []
    assert len(output['benchmarks']['QQQ']) == 2
    assert any('SPY unavailable' in x for x in output['limitations'])
    assert len(output['raw_snapshots']) == 2


def freeze_collection_time(monkeypatch, iso_time):
    from datetime import datetime
    frozen = datetime.fromisoformat(iso_time)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

    monkeypatch.setattr(module('sources'), 'datetime', FixedDatetime)


def session_chart(symbol, previous_day='2025-07-15', current_day='2025-07-16', session_end='2025-07-16T20:00:00+00:00'):
    from datetime import datetime
    payload = yahoo(symbol)
    result = payload['chart']['result'][0]
    # Daily bars are timestamped at the exchange's regular-session open.
    result['timestamp'] = [int(datetime.fromisoformat(d+('T14:30:00+00:00' if '-11-' in d else 'T13:30:00+00:00')).timestamp())
                           for d in [previous_day, current_day]]
    result['meta']['regularMarketTime'] = result['timestamp'][-1]
    if session_end:
        result['meta']['currentTradingPeriod'] = {'regular': {
            'start': result['timestamp'][-1],
            'end': int(datetime.fromisoformat(session_end).timestamp()),
            'timezone': 'EDT', 'gmtoffset': -14400}}
    return payload


@pytest.mark.parametrize('now,previous_day,current_day,session_end,expected_last', [
    ('2025-07-16T18:00:00+00:00', '2025-07-15', '2025-07-16', '2025-07-16T20:00:00+00:00', '2025-07-15'),
    ('2025-07-16T20:30:00+00:00', '2025-07-15', '2025-07-16', '2025-07-16T20:00:00+00:00', '2025-07-16'),
    # UTC next date is still the same New York trading date.
    ('2025-07-17T00:30:00+00:00', '2025-07-15', '2025-07-16', '2025-07-16T20:00:00+00:00', '2025-07-16'),
    ('2025-11-28T17:30:00+00:00', '2025-11-26', '2025-11-28', '2025-11-28T18:00:00+00:00', '2025-11-26'),
    ('2025-11-28T18:30:00+00:00', '2025-11-26', '2025-11-28', '2025-11-28T18:00:00+00:00', '2025-11-28'),
    ('2025-07-16T22:00:00+00:00', '2025-07-15', '2025-07-16', None, '2025-07-15'),
    # A previous session's close is not proof that today's bar is complete.
    ('2025-07-16T22:00:00+00:00', '2025-07-15', '2025-07-16', '2025-07-15T20:00:00+00:00', '2025-07-15'),
])
def test_daily_bars_require_a_completed_exchange_session(monkeypatch, now, previous_day, current_day, session_end, expected_last):
    sources = module('sources')
    freeze_collection_time(monkeypatch, now)
    session = Session([Response(session_chart(t, previous_day, current_day, session_end)) for t in ['MU', 'SPY', 'QQQ']])
    output = sources.USSources(session=session, backoff_seconds=0).market('MU')
    assert output['bars'][-1]['date'] == expected_last
    assert output['benchmarks']['SPY'][-1]['date'] == expected_last
    assert output['benchmarks']['QQQ'][-1]['date'] == expected_last
    assert output['quote']['price_basis'] == 'provider_quote'
    performance = module('metrics').performance_view(output['bars'], output['benchmarks'])
    assert performance['windows']['3m']['end'] == expected_last
    if expected_last != current_day:
        assert any('incomplete' in value.lower() or 'unverified' in value.lower() for value in output['limitations'])


def test_malformed_optional_session_metadata_excludes_only_today(monkeypatch):
    sources = module('sources')
    freeze_collection_time(monkeypatch, '2025-07-16T22:00:00+00:00')
    replies = []
    for ticker in ['MU', 'SPY', 'QQQ']:
        payload = session_chart(ticker)
        payload['chart']['result'][0]['meta']['currentTradingPeriod'] = {'regular': [1]}
        replies.append(Response(payload))
    output = sources.USSources(session=Session(replies), backoff_seconds=0).market('MU')
    assert output['bars'][-1]['date'] == '2025-07-15'
    assert output['benchmarks']['SPY'][-1]['date'] == '2025-07-15'


def test_future_dated_bar_is_rejected(monkeypatch):
    sources = module('sources')
    freeze_collection_time(monkeypatch, '2025-07-16T22:00:00+00:00')
    with pytest.raises(sources.SourceError, match='future'):
        sources.USSources(session=Session([Response(session_chart('MU', current_day='2025-07-17'))]), backoff_seconds=0).market('MU')


def test_future_dated_benchmark_is_isolated_from_stock(monkeypatch):
    sources = module('sources')
    freeze_collection_time(monkeypatch, '2025-07-16T22:00:00+00:00')
    session = Session([Response(session_chart('MU')), Response(session_chart('SPY', current_day='2025-07-17')),
                       Response(session_chart('QQQ'))])
    output = sources.USSources(session=session, backoff_seconds=0).market('MU')
    assert output['bars'][-1]['date'] == '2025-07-16'
    assert output['benchmarks']['SPY'] == []
    assert output['benchmarks']['QQQ'][-1]['date'] == '2025-07-16'
