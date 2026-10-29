"""data.http.get_json under fetch-1: two retries after 2 s and 8 s, 4xx fails at once, shape unchanged."""
import pytest

from investment_assistant.data import fetch_policy, http
from test_fetch_policy import FakeServer, reply

# production backoff (2 s, 8 s), short timeouts; the sleep is injected so nothing waits
FAST = fetch_policy.FetchPolicy(connect_s=0.5, total_s=1.0)


@pytest.fixture
def server():
    srv = FakeServer()
    yield srv
    srv.close()


def test_get_json_success(server):
    server.routes['/a'] = lambda h: reply(h, 200, b'{"a": 1}')
    payload, status = http.get_json(server.url('/a'), policy=FAST)
    assert payload == {'a': 1} and status['ok'] is True
    assert status['status_code'] == 200 and status['error'] is None and status['error_kind'] is None
    assert len(status['attempts']) == 1


def test_get_json_shape_keeps_the_old_keys(server):
    server.routes['/a'] = lambda h: reply(h, 200, b'{}')
    _, ok = http.get_json(server.url('/a'), policy=FAST)
    _, bad = http.get_json(server.url('/nope'), policy=FAST)
    assert {'ok', 'error', 'status_code'} <= set(ok) and {'ok', 'error', 'status_code'} <= set(bad)
    assert set(ok) == set(bad) == {'ok', 'error', 'status_code', 'attempts', 'error_kind'}


def test_get_json_retries_on_500_then_succeeds(server):
    seen = []

    def flaky(handler):
        seen.append(1)
        reply(handler, 500 if len(seen) == 1 else 200, b'{"ok": 1}')

    server.routes['/f'] = flaky
    sleeps = []
    payload, status = http.get_json(server.url('/f'), policy=FAST, sleep=sleeps.append)
    assert payload == {'ok': 1} and status['ok'] is True
    assert sleeps == [2] and [a['kind'] for a in status['attempts']] == ['http_5xx', None]


def test_get_json_retries_twice_with_2_and_8_then_fails(server):
    server.routes['/down'] = lambda h: reply(h, 502, b'bad gateway')
    sleeps = []
    payload, status = http.get_json(server.url('/down'), policy=FAST, sleep=sleeps.append)
    assert payload is None and status['ok'] is False
    assert server.hits['/down'] == 3 and sleeps == [2, 8]
    assert status['status_code'] == 502 and status['error_kind'] == 'http_5xx' and len(status['attempts']) == 3
    assert status['error'].startswith('http 502: bad gateway')


def test_get_json_4xx_fails_fast(server):
    server.routes['/gone'] = lambda h: reply(h, 404)
    sleeps = []
    payload, status = http.get_json(server.url('/gone'), policy=FAST, sleep=sleeps.append)
    assert payload is None and status['status_code'] == 404 and status['error_kind'] == 'http_4xx'
    assert server.hits['/gone'] == 1 and sleeps == []


def test_get_json_bad_json_is_not_retried(server):
    server.routes['/html'] = lambda h: reply(h, 200, b'<html>')
    sleeps = []
    payload, status = http.get_json(server.url('/html'), policy=FAST, sleep=sleeps.append)
    assert payload is None and status['status_code'] == 200 and status['error_kind'] == 'parse'
    assert status['error'].startswith('bad json') and server.hits['/html'] == 1 and sleeps == []


def test_default_policy_is_fetch_1():
    import inspect
    assert inspect.signature(http.get_json).parameters['policy'].default == fetch_policy.FetchPolicy()
    assert http._RETRYABLE == set(fetch_policy.RETRY_STATUSES)
