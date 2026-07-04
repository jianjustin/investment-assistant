from investment_assistant.api import auth


def test_unknown_api_path_returns_legacy_404_shape(client):
    resp = client.get("/api/does-not-exist-xyz")
    assert resp.status_code == 404
    assert resp.json() == {"error": "not found"}


def test_no_password_configured_allows_anonymous(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "")
    resp = client.get("/api/does-not-exist-xyz")
    assert resp.status_code == 404  # 通过认证，走到 404


def test_password_configured_rejects_anonymous_with_basic_challenge(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "secret")
    resp = client.get("/api/does-not-exist-xyz")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == 'Basic realm="Hermes Investment Assistant"'


def test_password_configured_accepts_valid_basic(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "secret")
    resp = client.get("/api/does-not-exist-xyz", auth=(auth.AUTH_USER, "secret"))
    assert resp.status_code == 404


def test_sse_events_route_registered(client):
    paths = {getattr(r, "path", None) for r in client.app.routes}
    assert "/api/events" in paths


def test_value_error_from_handler_returns_400(client, monkeypatch):
    import investment_assistant.services.market as _market
    monkeypatch.setattr(_market, "fetch_market_signals", lambda payload: (_ for _ in ()).throw(ValueError("bad date")))
    resp = client.post("/api/market/signals/fetch", json={})
    assert resp.status_code == 400
    assert resp.json() == {"error": "bad date"}


def test_event_stream_frames_events_and_survives_keepalive(monkeypatch):
    import queue as _queue

    from investment_assistant.api import app as app_mod
    from investment_assistant.tasks import runner

    unsubscribed = []
    monkeypatch.setattr(runner, "unsubscribe", lambda q: unsubscribed.append(q))

    class FakeQueue:
        def __init__(self):
            self.calls = 0

        def get(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                return {"run_id": "r1", "status": "done", "kind": "metrics"}
            if self.calls == 2:
                raise _queue.Empty
            return {"run_id": "r2", "status": "done", "kind": "metrics"}

    q = FakeQueue()
    gen = app_mod.event_stream(q)

    first = next(gen)
    assert first.startswith("data: ")
    assert '"run_id": "r1"' in first

    assert next(gen) == ": keep-alive\n\n"

    third = next(gen)  # 心跳后循环必须继续——持久连接契约
    assert '"run_id": "r2"' in third

    gen.close()
    assert unsubscribed == [q]


def test_get_unknown_run_returns_404(client):
    resp = client.get("/api/runs/nope-123")
    assert resp.status_code == 404
    assert resp.json() == {"error": "unknown run"}


def test_jobs_run_requires_run_suffix_contract(client, monkeypatch):
    from investment_assistant.services import jobs as jobs_svc
    monkeypatch.setattr(jobs_svc, "trigger_job", lambda name: {"run_id": f"{name}-1", "status": "pending"})
    resp = client.post("/api/jobs/metrics/run", json={})
    assert resp.status_code == 200
    assert resp.json()["run_id"] == "metrics-1"
