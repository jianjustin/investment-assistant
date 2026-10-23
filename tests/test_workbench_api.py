from datetime import UTC, date, datetime

import pytest

from investment_assistant.workbench import ledger, service


def raiser(exc):
    def fn(*args, **kwargs):
        raise exc
    return fn


@pytest.mark.parametrize('method, path, target', [
    ('get', '/api/workbench/today', 'today'),
    ('get', '/api/workbench/instruments/NVDA', 'instrument'),
    ('get', '/api/workbench/review/shadow', 'shadow'),
    ('get', '/api/workbench/review/trades', 'trade_review'),
    ('get', '/api/workbench/weekly-reviews', 'list_weekly'),
])
def test_unavailable_database_is_503_not_empty(client, monkeypatch, method, path, target):
    monkeypatch.setattr(service, target, raiser(service.Unavailable('工作台数据表未就绪')))
    resp = getattr(client, method)(path)
    assert resp.status_code == 503 and '未就绪' in resp.json()['error']


@pytest.mark.parametrize('exc, code', [
    (ledger.LedgerError('reason is required'), 400),
    (ledger.Conflict('newer decision'), 409),
    (service.Unavailable('down'), 503),
])
def test_decision_errors_map_to_status(client, monkeypatch, exc, code):
    monkeypatch.setattr(service, 'decide', raiser(exc))
    assert client.post('/api/workbench/decisions', json={}).status_code == code


def test_void_unknown_trade_is_404(client, monkeypatch):
    monkeypatch.setattr(service, 'void_trade', raiser(ledger.NotFound('trade not found')))
    assert client.post('/api/workbench/trades/abc/void', json={'reason': 'x'}).status_code == 404


def test_decision_passes_payload_and_server_time(client, monkeypatch):
    seen = {}

    def decide(payload, *, now):
        seen.update(payload=payload, now=now)
        return {'status': 'created', 'record': {'id': 'd1'}}
    monkeypatch.setattr(service, 'decide', decide)
    resp = client.post('/api/workbench/decisions', json={'reason': 'r', 'decided_at': '2000-01-01T00:00:00Z'})
    assert resp.status_code == 200 and resp.json()['status'] == 'created'
    assert seen['payload'] == {'reason': 'r', 'decided_at': '2000-01-01T00:00:00Z'}  # ignored by the ledger
    assert seen['now'].tzinfo is not None and seen['now'].year >= 2026


def test_weekly_review_post_parses_week(client, monkeypatch):
    calls = {}

    def generate(week_start, *, notes, supersedes_id, now):
        calls.update(week_start=week_start, notes=notes, supersedes_id=supersedes_id)
        return {'id': 'w1'}
    monkeypatch.setattr(service, 'generate_weekly', generate)
    resp = client.post('/api/workbench/weekly-reviews', json={'week_start': '2026-10-19', 'notes': '笔记'})
    assert resp.status_code == 200 and calls == {'week_start': date(2026, 10, 19), 'notes': '笔记', 'supersedes_id': None}
    assert client.post('/api/workbench/weekly-reviews', json={'week_start': 'bad'}).status_code == 400


def test_shadow_since_is_validated(client, monkeypatch):
    monkeypatch.setattr(service, 'shadow', lambda *, now, since: {'since': since})
    assert client.get('/api/workbench/review/shadow?since=2026-09-01').json() == {'since': '2026-09-01'}
    assert client.get('/api/workbench/review/shadow?since=nope').status_code == 400


def test_manual_run_is_submitted_in_background(client, monkeypatch):
    from investment_assistant.tasks import runner
    submitted = []
    monkeypatch.setattr(runner, 'submit', lambda kind, fn: submitted.append(kind) or 'run-1')
    resp = client.post('/api/workbench/run')
    assert resp.json() == {'run_id': 'run-1', 'status': 'pending'} and submitted == ['workbench']


def test_task_is_registered_with_scheduler():
    from investment_assistant.tasks import scheduler, workbench
    assert scheduler.REGISTRY['workbench'] is workbench.run


def test_task_reports_partial_failures_without_notifying(monkeypatch):
    from investment_assistant.config import AssistantConfig
    from investment_assistant.tasks import workbench
    recorded = {}

    def run_task(task, fn, *, config, trigger_source, notify):
        recorded.update(task=task, notify=notify, trigger_source=trigger_source, summary=fn())
        return {'status': 'ok'}
    monkeypatch.setattr(workbench, 'run_task', run_task)
    monkeypatch.setattr(workbench.service, 'run_batch',
                        lambda *, tickers, now, deps, skip_non_trading: {'tickers': tickers, 'skip': skip_non_trading})
    workbench.run(AssistantConfig(watchlist=['NVDA', '688008.SH']), now=datetime(2026, 10, 22, 22, tzinfo=UTC))
    assert recorded['task'] == 'workbench' and recorded['notify'] is False
    assert recorded['summary'] == {'tickers': ['NVDA'], 'skip': True}


def test_trade_list_endpoint(client, monkeypatch):
    monkeypatch.setattr(service, 'list_trades', lambda: [{'id': 't1'}])
    assert client.get('/api/workbench/trades').json() == {'trades': [{'id': 't1'}]}
    monkeypatch.setattr(service, 'list_trades', raiser(service.Unavailable('down')))
    assert client.get('/api/workbench/trades').status_code == 503
