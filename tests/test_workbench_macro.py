"""FRED collection: parsing, redaction and error contract (network stubbed)."""
from datetime import date, datetime, UTC
from decimal import Decimal

import pytest

from investment_assistant.workbench import macro

START, END = date(2026, 6, 25), date(2026, 10, 23)


def _fetcher(observations=None, *, error=None, seen=None):
    def fetch(url, *, params):
        if seen is not None:
            seen.append((url, params))
        if error is not None:
            raise error
        payload = {} if observations is None else {'observations': observations}
        return (payload, {'ok': True})
    return fetch


def test_parse_skips_dot_values():
    rows = macro.fetch_series('T10Y2Y', start=START, end=END, api_key='K',
                              fetcher=_fetcher([{'date': '2026-10-20', 'value': '.'},
                                                {'date': '2026-10-21', 'value': '0.15'}]))
    assert rows == [{'obs_date': date(2026, 10, 21), 'value': Decimal('0.15')}]


def test_not_configured_makes_no_request():
    def boom(*a, **kw):
        raise AssertionError('fetcher called')
    with pytest.raises(macro.NotConfigured):
        macro.fetch_series('T10Y2Y', start=START, end=END, api_key=None, fetcher=boom)
    with pytest.raises(macro.NotConfigured):
        macro.fetch_series('T10Y2Y', start=START, end=END, api_key='', fetcher=boom)


def test_request_params():
    seen = []
    macro.fetch_series('BAMLH0A0HYM2', start=START, end=END, api_key='SECRET123',
                       fetcher=_fetcher([], seen=seen))
    url, params = seen[0]
    assert url == 'https://api.stlouisfed.org/fred/series/observations'
    assert params['series_id'] == 'BAMLH0A0HYM2'
    assert params['file_type'] == 'json'
    assert params['api_key'] == 'SECRET123'
    assert params['observation_start'] == START.isoformat()
    assert params['observation_end'] == END.isoformat()


def test_error_text_redacts_key():
    fetcher = _fetcher(error=RuntimeError('getaddrinfo failed for api.stlouisfed.org?api_key=SECRET123&file_type=json'))
    with pytest.raises(RuntimeError) as exc:
        macro.fetch_series('T10Y2Y', start=START, end=END, api_key='SECRET123', fetcher=fetcher)
    assert 'SECRET123' not in str(exc.value)
    assert '***' in str(exc.value)


def test_http_failure_redacts_key_and_raises():
    def fetch(url, *, params):
        return (None, {'ok': False, 'status_code': 500, 'error': 'server error api_key=SECRET123'})
    with pytest.raises(RuntimeError) as exc:
        macro.fetch_series('T10Y2Y', start=START, end=END, api_key='SECRET123', fetcher=fetch)
    assert 'SECRET123' not in str(exc.value)


def test_missing_observations_raises():
    with pytest.raises(RuntimeError, match='observations'):
        macro.fetch_series('T10Y2Y', start=START, end=END, api_key='K', fetcher=_fetcher(None))


def test_constants():
    assert macro.MACRO_SERIES == ('BAMLH0A0HYM2', 'T10Y2Y')
    assert macro.MACRO_LOOKBACK_DAYS == 120
    assert macro.MACRO_CHANGE_OBS == 20


def test_redact_empty_secret_is_noop():
    assert macro.redact('plain api_key=SECRET123', None) == 'plain api_key=SECRET123'
    assert macro.redact('a SECRET123 b SECRET123', 'SECRET123') == 'a *** b ***'
