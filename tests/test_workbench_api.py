from datetime import UTC, date, datetime

import pytest

from investment_assistant.workbench import derivation_view, ledger, service


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


def test_scheduled_task_uses_db_pool(monkeypatch):
    from investment_assistant.config import AssistantConfig
    from investment_assistant.tasks import workbench
    recorded = {}

    def run_task(task, fn, *, config, trigger_source, notify, pass_run_id=False):
        summary = fn('workbench-fake-run') if pass_run_id else fn()
        recorded.update(task=task, notify=notify, trigger_source=trigger_source, summary=summary)
        return {'status': 'ok'}
    monkeypatch.setattr(workbench, 'run_task', run_task)

    def run_batch(**kw):
        recorded.update(batch_kwargs=kw)
        return {'pool': {'core': 2, 'extended': 3, 'holdings': 0, 'changes': []}}
    monkeypatch.setattr(workbench.service, 'run_batch', run_batch)
    monkeypatch.setattr(workbench.service, 'push',
                        lambda **_: {'session': '2026-10-22', 'sent': True, 'messages': 4})
    rows = []
    monkeypatch.setattr(workbench.stages_module, 'write_stage_row', rows.append)   # 不碰真实库
    workbench.run(AssistantConfig(watchlist=['NVDA', '688008.SH']), now=datetime(2026, 10, 22, 22, tzinfo=UTC))
    assert recorded['task'] == 'workbench' and recorded['notify'] is False
    assert 'tickers' not in recorded['batch_kwargs']
    assert recorded['batch_kwargs']['skip_non_trading'] is True
    assert recorded['batch_kwargs']['stages'].run_id == 'workbench-fake-run'
    assert recorded['summary'] == {'pool': {'core': 2, 'extended': 3, 'holdings': 0, 'changes': []},
                                   'push': {'session': '2026-10-22', 'sent': True, 'messages': 4},
                                   'stage_status': {'written': 7, 'error': None}}
    push = [row for row in rows if row['stage'] == 'push']        # 桩批处理没记前六阶段：close 补 not_reached
    assert len(rows) == 7 and push[0]['status'] == 'success' and push[0]['output_count'] == 4


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


def test_monthly_reviews_routes(client, monkeypatch):
    monkeypatch.setattr(service, 'list_monthly', raiser(service.Unavailable('工作台数据表未就绪')))
    assert client.get('/api/workbench/monthly-reviews').status_code == 503
    monkeypatch.setattr(service, 'generate_monthly', raiser(service.Unavailable('工作台数据表未就绪')))
    assert client.post('/api/workbench/monthly-reviews', json={'month': '2026-10-01'}).status_code == 503
    assert client.post('/api/workbench/monthly-reviews', json={}).status_code == 400
    assert client.post('/api/workbench/monthly-reviews', json={'month': '2026-10-15'}).status_code == 400


def test_push_route_forces(client, monkeypatch):
    seen = {}

    def push(*, now, force, notify_cfg=None, client=None):
        seen['force'] = force
        return {'session': '2026-10-22', 'sent': True, 'messages': 4}

    monkeypatch.setattr(service, 'push', push)
    resp = client.post('/api/workbench/push')
    assert resp.status_code == 200 and seen['force'] is True and resp.json()['sent'] is True


def test_backcheck_route_runs_and_lists(client, monkeypatch):
    from investment_assistant.workbench import service
    seen = {}

    def run_backcheck(*, now, tickers=None):
        seen['tickers'] = tickers
        return {'id': 'b1', 'calc_version': 'backcheck-1', 'stats': {'all': {'triggers': 0}}}
    monkeypatch.setattr(service, 'run_backcheck', run_backcheck)
    monkeypatch.setattr(service, 'list_backchecks', lambda limit=10: [{'id': 'b1', 'calc_version': 'backcheck-1'}])
    resp = client.post('/api/workbench/backchecks', json={'tickers': ['NVDA', 'MU']})
    assert resp.status_code == 200 and resp.json()['id'] == 'b1'
    assert seen['tickers'] == ['NVDA', 'MU']
    listing = client.get('/api/workbench/backchecks')
    assert listing.status_code == 200
    assert listing.json() == {'backchecks': [{'id': 'b1', 'calc_version': 'backcheck-1'}]}


def test_agent_run_routes(client, monkeypatch):
    # GET 列表与覆盖率
    monkeypatch.setattr(service, 'agent_runs', lambda *, now, since=None: {
        'since': '2026-10-08', 'runs': [{'id': 'r1', 'ticker': 'NVDA'}],
        'coverage': {'units': 1, 'covered': 1, 'missing': []}})
    resp = client.get('/api/workbench/agent-runs')
    assert resp.status_code == 200 and resp.json()['coverage']['units'] == 1
    assert client.get('/api/workbench/agent-runs?since=2026-10-01').status_code == 200

    # GET 详情：404 与正常
    monkeypatch.setattr(service, 'agent_run_detail', raiser(LookupError('no such run')))
    assert client.get('/api/workbench/agent-runs/abc').status_code == 404
    monkeypatch.setattr(service, 'agent_run_detail', lambda run_id: {'id': run_id, 'tool_calls': []})
    assert client.get('/api/workbench/agent-runs/abc').status_code == 200

    # POST：400（非买入）、409（已有建议）、503（库未就绪）、200（成功）
    body = {'ticker': 'AMD', 'signal_date': '2026-10-21'}
    monkeypatch.setattr(service, 'run_agent', raiser(ValueError('not a buy unit')))
    assert client.post('/api/workbench/agent-runs', json=body).status_code == 400
    monkeypatch.setattr(service, 'run_agent', raiser(service.AgentConflict('already ok')))
    assert client.post('/api/workbench/agent-runs', json=body).status_code == 409
    monkeypatch.setattr(service, 'run_agent', raiser(service.Unavailable('数据库不可达')))
    assert client.post('/api/workbench/agent-runs', json=body).status_code == 503
    monkeypatch.setattr(service, 'run_agent',
                        lambda ticker, signal_date, *, now, deps=None: {'id': 'r9', 'status': 'ok',
                                                                         'reason': None})
    resp = client.post('/api/workbench/agent-runs', json=body)
    assert resp.status_code == 200 and resp.json() == {'id': 'r9', 'status': 'ok', 'reason': None}
    assert client.post('/api/workbench/agent-runs', json={'ticker': 'AMD'}).status_code == 400


def test_tracks_route_bad_date_400(client):
    assert client.get('/api/workbench/review/tracks', params={'since': '2026-10-xx'}).status_code == 400


def test_tracks_route_since_after_until_400(client):
    resp = client.get('/api/workbench/review/tracks',
                      params={'since': '2026-11-01', 'until': '2026-10-01'})
    assert resp.status_code == 400


def test_tracks_route_passes_dates(client, monkeypatch):
    calls = {}

    def tracks(*, now, since=None, until=None):
        calls.update(since=since, until=until)
        return {'units': [], 'summary': {}}
    monkeypatch.setattr(service, 'tracks', tracks)
    resp = client.get('/api/workbench/review/tracks',
                      params={'since': '2026-10-01', 'until': '2026-10-22'})
    assert resp.status_code == 200
    assert calls == {'since': date(2026, 10, 1), 'until': date(2026, 10, 22)}


def test_review_push_route_validation(client, monkeypatch):
    from investment_assistant.workbench import ledger, service

    monkeypatch.setattr(service, 'push_review',
                        raiser(ledger.NotFound('没有快照')))
    resp = client.post('/api/workbench/review-pushes', json={'kind': 'weekly', 'period': '2026-10-19'})
    assert resp.status_code == 404
    monkeypatch.setattr(service, 'push_review', raiser(ledger.LedgerError('period 必须是周一')))
    assert client.post('/api/workbench/review-pushes',
                       json={'kind': 'weekly', 'period': '2026-10-21'}).status_code == 400
    calls = {}

    def push_review(kind, period, **kwargs):
        calls.update(kind=kind, period=period)
        return {'kind': kind, 'period': period, 'sent': True}
    monkeypatch.setattr(service, 'push_review', push_review)
    resp = client.post('/api/workbench/review-pushes', json={'kind': 'weekly', 'period': '2026-10-19'})
    assert resp.status_code == 200
    assert calls == {'kind': 'weekly', 'period': date(2026, 10, 19)}


def test_review_pushes_list_route(client, monkeypatch):
    monkeypatch.setattr(service, 'list_review_pushes', lambda limit=20: [{'id': 1}])
    assert client.get('/api/workbench/review-pushes').json() == {'pushes': [{'id': 1}]}
    assert client.get('/api/workbench/review-pushes', params={'limit': 5}).status_code == 200
    assert client.get('/api/workbench/review-pushes', params={'limit': 0}).status_code == 400
    assert client.get('/api/workbench/review-pushes', params={'limit': 101}).status_code == 400


def test_screen_view_passthrough(client, monkeypatch):
    monkeypatch.setattr(service, 'screen_view',
                        lambda *, now, session=None, full=False: {'report': {'full': full, 'session': session}})
    resp = client.get('/api/workbench/screen')
    assert resp.status_code == 200
    assert resp.json()['report'] == {'full': False, 'session': None}
    resp = client.get('/api/workbench/screen?session=2026-10-22&full=1')
    assert resp.status_code == 200
    assert resp.json()['report'] == {'full': True, 'session': date(2026, 10, 22).isoformat()}


def test_screen_replay_route(client, monkeypatch):
    seen = {}

    def replay_screen(*, now, sessions):
        seen['sessions'] = sessions
        return {'reports': [{'session': '2026-10-22'}]}

    monkeypatch.setattr(service, 'replay_screen', replay_screen)
    resp = client.post('/api/workbench/screen/replay', json={'sessions': 21})
    assert resp.status_code == 400
    resp = client.post('/api/workbench/screen/replay', json={})
    assert resp.status_code == 200 and seen['sessions'] == 5
    assert resp.json()['reports'][0]['session'] == '2026-10-22'


PLAN_ID = '6f1d1c1e-6666-4444-8888-000000000001'


def test_plan_derivation_route_delegates(client, monkeypatch):
    seen = {}

    def plan_derivation(plan_id):
        seen['plan_id'] = plan_id
        return {'derivation_version': 'derivation-1', 'plan': {'id': 'p1'},
                'trigger': [{'rule_id': 'trend_reclaim'}], 'inputs': {}, 'steps': [], 'checks': [],
                'consistency': {'status': 'consistent'}, 'evidence': '证据状态',
                'trigger_note': '触发段只复核冻结取值', 'run': {'ready': True, 'run_id': 'r1'}}

    monkeypatch.setattr(derivation_view, 'plan_derivation', plan_derivation)
    resp = client.get(f'/api/workbench/plans/{PLAN_ID}/derivation')
    assert resp.status_code == 200
    assert seen == {'plan_id': PLAN_ID}                                  # id 原样传给用例
    body = resp.json()
    assert body['trigger'] == {'note': '触发段只复核冻结取值',        # 说明收进 trigger 段，不是顶层键
                               'candidates': [{'rule_id': 'trend_reclaim'}]}
    assert 'trigger_note' not in body and body['run'] == {'ready': True, 'run_id': 'r1'}


def test_unit_derivation_route_delegates(client, monkeypatch):
    seen = {}

    def unit_derivation(ticker, signal_date):
        seen.update(ticker=ticker, signal_date=signal_date)
        return {'derivation_version': 'derivation-1', 'trigger': [], 'consistency': {'status': 'consistent'},
                'evidence': '证据状态', 'note': '触发段只复核冻结取值', 'plan_ids': [PLAN_ID]}

    monkeypatch.setattr(derivation_view, 'unit_derivation', unit_derivation)
    resp = client.get('/api/workbench/units/AAPL/2026-10-22/derivation')
    assert resp.status_code == 200 and resp.json()['plan_ids'] == [PLAN_ID]
    assert seen == {'ticker': 'AAPL', 'signal_date': date(2026, 10, 22)}  # ticker 原样、日期已解析
    assert client.get('/api/workbench/units/AAPL/2026-13-01/derivation').status_code == 400


def test_stage_runs_route_delegates_and_serializes_stages(client, monkeypatch):
    from investment_assistant.workbench import stages as stages_module
    seen = {}

    def stage_runs_view(*, session=None, run_id=None):
        seen.update(session=session, run_id=run_id)
        return {'stages': list(stages_module.STAGES[:2]), 'stage_runs_ready': True,
                'runs': [{'run_id': 'r1', 'rows': [{'stage': 'collect', 'session': date(2026, 10, 22),
                                                    'started_at': None}]}]}

    monkeypatch.setattr(derivation_view, 'stage_runs_view', stage_runs_view)
    resp = client.get('/api/workbench/stage-runs', params={'session': '2026-10-22'})
    assert resp.status_code == 200
    assert seen == {'session': date(2026, 10, 22), 'run_id': None}
    body = resp.json()
    assert body['stages'] == [{'id': s.id, 'title': s.title, 'purpose': s.purpose}
                              for s in stages_module.STAGES[:2]]          # StageDef 显式序列化成 dict
    assert body['stage_runs_ready'] is True
    assert body['runs'][0]['rows'][0]['session'] == '2026-10-22'
    assert client.get('/api/workbench/stage-runs', params={'run_id': 'r1'}).status_code == 200
    assert seen == {'session': None, 'run_id': 'r1'}


def test_derivation_bad_uuid_is_400(client):
    assert client.get('/api/workbench/plans/not-a-uuid/derivation').status_code == 400


def test_derivation_unknown_plan_is_404(client, monkeypatch):
    monkeypatch.setattr(derivation_view, 'plan_derivation', raiser(LookupError(f'计划不存在：{PLAN_ID}')))
    assert client.get(f'/api/workbench/plans/{PLAN_ID}/derivation').status_code == 404


def test_unit_derivation_bad_ticker_is_400(client):
    assert client.get('/api/workbench/units/1234/2026-10-22/derivation').status_code == 400


def test_unit_derivation_without_candidates_is_404(client, monkeypatch):
    monkeypatch.setattr(derivation_view, 'unit_derivation', raiser(LookupError('该单元没有候选')))
    assert client.get('/api/workbench/units/NVDA/2026-10-22/derivation').status_code == 404


def test_stage_runs_needs_exactly_one_param(client):
    assert client.get('/api/workbench/stage-runs').status_code == 400                     # 两个都缺
    assert client.get('/api/workbench/stage-runs',
                      params={'session': '2026-10-22', 'run_id': 'r1'}).status_code == 400  # 两个都给


def test_stage_runs_bad_session_is_400(client):
    assert client.get('/api/workbench/stage-runs', params={'session': '2026-13-01'}).status_code == 400


@pytest.mark.parametrize('path, target, kwargs', [
    (f'/api/workbench/plans/{PLAN_ID}/derivation', 'plan_derivation', {}),
    ('/api/workbench/units/NVDA/2026-10-22/derivation', 'unit_derivation', {}),
    ('/api/workbench/stage-runs', 'stage_runs_view', {'params': {'session': '2026-10-22'}}),
])
def test_derivation_routes_503_without_db(client, monkeypatch, path, target, kwargs):
    monkeypatch.setattr(derivation_view, target, raiser(service.Unavailable('工作台数据表未就绪')))
    resp = client.get(path, **kwargs)
    assert resp.status_code == 503 and '未就绪' in resp.json()['error']


# ---------------------------------------------------------------- v2.5 plan timeline (spec §12)

def test_chain_view_route_delegates(client, monkeypatch):
    from investment_assistant.workbench import plan_review
    seen = {}

    def chain_view(ticker, signal_date, *, now):
        seen.update(ticker=ticker, signal_date=signal_date, now=now)
        return {'state': {'state': 'entry'}, 'versions': [], 'reviews': [], 'inputs': []}

    monkeypatch.setattr(plan_review, 'chain_view', chain_view)
    resp = client.get('/api/workbench/chains/SYNTH/2026-09-01')
    assert resp.status_code == 200 and resp.json()['state'] == {'state': 'entry'}
    assert (seen['ticker'], seen['signal_date']) == ('SYNTH', date(2026, 9, 1)) and seen['now'].tzinfo is not None
    assert client.get('/api/workbench/chains/SYNTH/2026-13-01').status_code == 400


def test_plan_reviews_route_delegates(client, monkeypatch):
    from investment_assistant.workbench import plan_review
    monkeypatch.setattr(plan_review, 'reviews_view', lambda session: {'session': session, 'reviews': []})
    assert client.get('/api/workbench/plan-reviews', params={'session': '2026-09-02'}).json() == \
        {'session': '2026-09-02', 'reviews': []}
    assert client.get('/api/workbench/plan-reviews').status_code == 400
    assert client.get('/api/workbench/plan-reviews', params={'session': 'bad'}).status_code == 400


def test_recheck_route_checks_then_submits_with_request_time(client, monkeypatch):
    from investment_assistant.api.routes import workbench as routes
    from investment_assistant.tasks import runner
    from investment_assistant.workbench import plan_review
    t0 = datetime(2026, 9, 2, 22, 30, tzinfo=UTC)
    clock = iter([t0, t0.replace(minute=35)])
    monkeypatch.setattr(routes, '_now', lambda: next(clock))
    checked, ran, submitted = [], [], []
    monkeypatch.setattr(plan_review, 'recheck_check',
                        lambda ticker, signal_date, *, now: checked.append((ticker, signal_date, now)))
    monkeypatch.setattr(plan_review, 'recheck', lambda ticker, signal_date, *, now, run_id=None, deps=None:
                        ran.append((ticker, signal_date, now, run_id)) or {'id': 1})

    def submit(kind, fn, *, with_run_id=False):
        submitted.append((kind, fn, with_run_id))
        return 'plan_recheck-1'

    monkeypatch.setattr(runner, 'submit', submit)
    resp = client.post('/api/workbench/chains/SYNTH/2026-09-01/recheck')
    assert resp.status_code == 200 and resp.json() == {'run_id': 'plan_recheck-1', 'status': 'pending'}
    assert checked == [('SYNTH', date(2026, 9, 1), t0)]
    [(kind, fn, with_run_id)] = submitted
    assert kind == 'plan_recheck' and ran == []                       # 后台执行，路由里不跑复查
    routes._now()                                                    # 时间往前走：后台晚 5 分钟才开始
    fn('plan_recheck-1') if with_run_id else fn()
    assert ran[0][:3] == ('SYNTH', date(2026, 9, 1), t0)              # 截止时间仍是请求进入时刻
    if with_run_id:
        assert ran[0][3] == 'plan_recheck-1'


@pytest.mark.parametrize('exc, code, message', [
    ('conflict', 409, 'review_in_progress'),
    ('not_active', 409, 'chain_not_active'),
    ('agent', 409, 'agent_unavailable: not_configured'),
    ('lookup', 404, None),
    ('value', 400, None),
    ('unavailable', 503, '迁移 026 未执行'),
])
def test_recheck_route_errors_do_not_submit(client, monkeypatch, exc, code, message):
    from investment_assistant.tasks import runner
    from investment_assistant.workbench import plan_review
    error = {'conflict': plan_review.RecheckConflict('review_in_progress'),
             'not_active': plan_review.RecheckConflict('chain_not_active'),
             'agent': plan_review.RecheckConflict('agent_unavailable: not_configured'),
             'lookup': LookupError('没有计划链'), 'value': ValueError('Invalid US stock ticker'),
             'unavailable': service.Unavailable('迁移 026 未执行')}[exc]
    monkeypatch.setattr(plan_review, 'recheck_check', raiser(error))
    submitted = []
    monkeypatch.setattr(runner, 'submit', lambda *a, **k: submitted.append(a) or 'x')
    resp = client.post('/api/workbench/chains/SYNTH/2026-09-01/recheck')
    assert resp.status_code == code and submitted == []
    if message:
        assert resp.json()['error'] == message
    assert client.post('/api/workbench/chains/SYNTH/nope/recheck').status_code == 400


def test_user_inputs_routes_delegate(client, monkeypatch):
    from investment_assistant.workbench import user_inputs
    seen = {}

    def list_for(ticker, signal_date):
        seen.update(ticker=ticker, signal_date=signal_date)
        return [{'id': 1, 'ref': 'user:1'}]

    def add(payload, *, now):
        seen.update(payload=payload, now=now)
        return {'status': 'created', 'record': {'id': 2}}

    monkeypatch.setattr(user_inputs, 'list_for', list_for)
    monkeypatch.setattr(user_inputs, 'add', add)
    resp = client.get('/api/workbench/user-inputs', params={'ticker': 'SYNTH', 'signal_date': '2026-09-01'})
    assert resp.json() == {'inputs': [{'id': 1, 'ref': 'user:1'}]}
    assert seen == {'ticker': 'SYNTH', 'signal_date': date(2026, 9, 1)}
    client.get('/api/workbench/user-inputs', params={'ticker': 'SYNTH'})
    assert seen['signal_date'] is None
    assert client.get('/api/workbench/user-inputs').status_code == 400
    assert client.get('/api/workbench/user-inputs', params={'ticker': 'SYNTH', 'signal_date': 'x'}).status_code == 400
    body = {'request_id': 'r', 'ticker': 'SYNTH', 'kind': 'news', 'body': '新闻'}
    resp = client.post('/api/workbench/user-inputs', json=body)
    assert resp.json() == {'status': 'created', 'record': {'id': 2}}
    assert seen['payload'] == body and seen['now'].tzinfo is not None


@pytest.mark.parametrize('exc, code', [
    (ValueError('body must be 1–4000 characters'), 400),
    (LookupError('该单元没有候选'), 404),
    (ledger.Conflict('request_id was already used with different content'), 409),
    (service.Unavailable('迁移 026 未执行'), 503),
])
def test_user_inputs_post_errors(client, monkeypatch, exc, code):
    from investment_assistant.workbench import user_inputs
    monkeypatch.setattr(user_inputs, 'add', raiser(exc))
    resp = client.post('/api/workbench/user-inputs', json={})
    assert resp.status_code == code and resp.json()['error'] == str(exc)


@pytest.mark.parametrize('path, module, target', [
    ('/api/workbench/chains/SYNTH/2026-09-01', 'plan_review', 'chain_view'),
    ('/api/workbench/plan-reviews?session=2026-09-02', 'plan_review', 'reviews_view'),
    ('/api/workbench/user-inputs?ticker=SYNTH', 'user_inputs', 'list_for'),
])
def test_timeline_reads_map_errors(client, monkeypatch, path, module, target):
    import importlib
    mod = importlib.import_module(f'investment_assistant.workbench.{module}')
    for exc, code in ((service.Unavailable('迁移 026 未执行'), 503), (LookupError('没有'), 404),
                      (ValueError('Invalid US stock ticker'), 400)):
        monkeypatch.setattr(mod, target, raiser(exc))
        resp = client.get(path)
        assert resp.status_code == code and resp.json()['error'] == str(exc)
