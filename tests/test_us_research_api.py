import importlib.util
import pytest


def service():
    assert importlib.util.find_spec('investment_assistant.us_research.service'), 'missing research read API'
    from investment_assistant.us_research import service
    return service


@pytest.mark.parametrize('body', [{'symbols': []}, {'symbols':['688008.SH']}, {'symbols':'MU'}, {'datasets':[]}, {'datasets':['other']}, {'retry_failed':'yes'}])
def test_invalid_sync_never_schedules(client, monkeypatch, body):
    from investment_assistant.tasks import runner
    def forbidden(*a, **kw): pytest.fail('invalid request scheduled work')
    monkeypatch.setattr(runner, 'submit', forbidden)
    assert client.post('/api/us-research/sync', json=body).status_code == 400


def test_get_uses_local_view_and_passes_cutoff(client, monkeypatch):
    s = service()
    def view(ticker, *, as_of=None):
        assert (ticker, as_of) == ('MU', '2026-10-01T00:00:00Z')
        return {'security_id':'US:stock:MU','pit':{'strict':False}}
    monkeypatch.setattr(s, 'view', view)
    assert client.get('/api/us-research/MU?as_of=2026-10-01T00:00:00Z').json()['security_id'] == 'US:stock:MU'


def test_sync_background_job_keeps_task_result_available(client, monkeypatch):
    service()
    from investment_assistant.tasks import runner, us_research
    import time
    monkeypatch.setattr(us_research, 'run', lambda **kw: {'notifications':'disabled','symbols':kw['symbols']})
    response = client.post('/api/us-research/sync', json={'symbols':['mu'],'datasets':['financials']})
    assert response.status_code == 200
    payload = response.json()
    for _ in range(100):
        rec = runner.get(payload['run_id'])
        if rec['status'] != 'pending': break
        time.sleep(.005)
    assert rec['status'] == 'done'
    assert rec['result']['symbols'] == ['MU']
