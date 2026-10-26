"""The data routes are thin wrappers: they delegate to data_view and map its errors."""
import pytest

from investment_assistant.workbench import data_view, service


def raiser(exc):
    def fn(*args, **kwargs):
        raise exc
    return fn


def test_routes_delegate(client, monkeypatch):
    calls = {}

    def overview(*, now):
        calls['now'] = now
        return {'overview': 'ok'}

    monkeypatch.setattr(data_view, 'overview', overview)
    monkeypatch.setattr(data_view, 'family_detail', lambda family_id, *, now: {'detail': family_id})

    def start_fetch(family_id, ticker):
        calls.update(family_id=family_id, ticker=ticker)
        return {'run_id': 'run-1', 'status': 'pending'}

    monkeypatch.setattr(data_view, 'start_fetch', start_fetch)

    def browse(family_id, *, now, ticker=None, series=None):
        return {'browse': family_id, 'ticker': ticker, 'series': series}

    monkeypatch.setattr(data_view, 'browse', browse)

    resp = client.get('/api/data/families')
    assert resp.status_code == 200 and resp.json() == {'overview': 'ok'}
    assert calls['now'].tzinfo is not None
    assert client.get('/api/data/families/bars').json() == {'detail': 'bars'}

    resp = client.post('/api/data/families/news/fetch', json={'ticker': ' mu '})
    assert resp.json() == {'run_id': 'run-1', 'status': 'pending'}
    assert calls == {'now': calls['now'], 'family_id': 'news', 'ticker': ' mu '}  # 原样传入，规范化在用例层
    client.post('/api/data/families/bars/fetch', json={})
    assert calls['ticker'] is None                     # body 不带 ticker 时传 None

    assert client.get('/api/data/browse/bars?ticker=NVDA').json() == {
        'browse': 'bars', 'ticker': 'NVDA', 'series': None}
    assert client.get('/api/data/browse/fred?series=T10Y2Y').json() == {
        'browse': 'fred', 'ticker': None, 'series': 'T10Y2Y'}
    assert client.get('/api/data/browse/universe').json() == {
        'browse': 'universe', 'ticker': None, 'series': None}
    assert client.get('/api/data/browse/bars?ticker=').json()['ticker'] is None   # 空串按缺省


@pytest.mark.parametrize('exc, code', [
    (service.Unavailable('需执行迁移 024'), 503),
    (LookupError('未知数据族：nope'), 404),
    (ValueError('派生族，请拉取日线'), 400),
    (data_view.FetchBusy('该族正在采集'), 409),
])
def test_error_mapping(client, monkeypatch, exc, code):
    monkeypatch.setattr(data_view, 'overview', raiser(exc))
    resp = client.get('/api/data/families')
    assert resp.status_code == code
    assert resp.json()['error'] == str(exc)


def test_busy_fetch_is_409(client, monkeypatch):
    monkeypatch.setattr(data_view, 'start_fetch', raiser(data_view.FetchBusy('该族正在采集')))
    resp = client.post('/api/data/families/bars/fetch', json={})
    assert resp.status_code == 409 and resp.json()['error'] == '该族正在采集'
