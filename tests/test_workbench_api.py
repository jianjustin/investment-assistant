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


@pytest.mark.parametrize('method, path, target, kwargs', [
    ('get', '/api/workbench/account/snapshots', 'account_view', {}),
    ('get', '/api/workbench/account/flows', 'account_view', {}),
    ('post', '/api/workbench/account/snapshots', 'add_snapshot', {'json': {}}),
    ('post', '/api/workbench/account/flows', 'add_flow', {'json': {}}),
    ('post', '/api/workbench/account/flows/x/void', 'void_flow', {'json': {'reason': 'r'}}),
])
def test_account_routes_503_without_db(client, monkeypatch, method, path, target, kwargs):
    monkeypatch.setattr(service, target, raiser(service.Unavailable('工作台数据表未就绪')))
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 503 and '未就绪' in resp.json()['error']


def test_post_flow_400_on_zero(client, monkeypatch):
    monkeypatch.setattr(service, 'add_flow', raiser(ledger.LedgerError('amount must be non-zero')))
    assert client.post('/api/workbench/account/flows', json={'amount': 0}).status_code == 400


def test_bad_own_levels_400_and_nothing_written(client, workbench_db, monkeypatch):
    from contextlib import contextmanager
    from datetime import UTC, date, datetime
    from decimal import Decimal

    from investment_assistant.workbench import repository
    from investment_assistant.workbench.rules import Candidate

    @contextmanager
    def connection():
        yield workbench_db

    monkeypatch.setattr(service, 'connection', connection)
    now = datetime(2026, 10, 23, 1, 0, tzinfo=UTC)
    unit_day = date(2026, 10, 22)
    repository.store_candidate(workbench_db, 'NVDA', unit_day,
                               Candidate('trend_reclaim', 'buy', {'signal_date': unit_day.isoformat()}), run_id='r')
    repository.insert_plan(workbench_db, {
        'ticker': 'NVDA', 'signal_date': unit_day, 'kind': 'rule', 'based_on_id': None, 'plan_version': 'plan-1',
        'ref_price': Decimal('100'), 'atr': Decimal('2'), 'entry_low': Decimal('99'), 'entry_high': Decimal('101'),
        'stop': Decimal('94'), 'target1': Decimal('108'), 'trail_atr_multiple': Decimal('3'),
        'valid_from': date(2026, 10, 23), 'valid_until': date(2026, 10, 27), 'sizing': {}, 'status': 'ok',
        'invalid_reasons': [], 'warnings': [], 'inputs': {}, 'request_id': None, 'request_hash': None})

    cid = workbench_db.execute('SELECT id FROM signal_candidates').fetchone()[0]
    resp = client.post('/api/workbench/decisions', json={
        'request_id': '6f1d1c1e-6666-4444-8888-000000000001', 'ticker': 'NVDA', 'signal_date': unit_day.isoformat(),
        'candidate_ids': [str(cid)], 'proposed_action': 'buy', 'final_action': 'buy', 'decision': 'accept',
        'reason': '自定价位', 'own_plan': {'request_id': '6f1d1c1e-7777-4444-8888-000000000002',
                                            'entry_low': 'abc', 'entry_high': '101.5', 'stop': '94',
                                            'target1': '112'}})
    assert resp.status_code == 400
    assert workbench_db.execute("SELECT count(*) FROM trade_plans WHERE kind = 'own'").fetchone()[0] == 0
    assert workbench_db.execute('SELECT count(*) FROM signal_decisions').fetchone()[0] == 0


def test_plan_shadow_503_without_db(client, monkeypatch):
    monkeypatch.setattr(service, 'plan_shadow', raiser(service.Unavailable('工作台数据表未就绪')))
    resp = client.get('/api/workbench/plans/shadow')
    assert resp.status_code == 503 and '未就绪' in resp.json()['error']


def test_plan_shadow_since_is_validated(client):
    assert client.get('/api/workbench/plans/shadow', params={'since': '2026-13-01'}).status_code == 400


def test_discipline_503_without_db(client, monkeypatch):
    monkeypatch.setattr(service, 'discipline', raiser(service.Unavailable('工作台数据表未就绪')))
    assert client.get('/api/workbench/discipline').status_code == 503
