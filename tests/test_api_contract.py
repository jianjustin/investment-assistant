"""Pin API routing and no-DB fallback behaviour before layering refactor."""
import pytest


@pytest.fixture(autouse=True)
def no_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)


def test_unknown_api_get_returns_404(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.json() == {"error": "not found"}


def test_status_get_route_resolves(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"database", "filings", "system"}


def test_operations_registry_shape(client):
    resp = client.get("/api/operations")
    assert resp.status_code == 200
    ids = {op["id"] for op in resp.json()["operations"]}
    assert ids == {"sync_filings", "health_check"}


def test_watchlist_get_falls_back_to_config_without_db(client):
    resp = client.get("/api/watchlist")
    assert resp.json()["count"] >= 1
    assert all(row["source"] == "config" for row in resp.json()["rows"])


def test_data_routes_without_db(client):
    resp = client.get("/api/data/families")
    assert resp.status_code == 503
    assert "数据库未配置" in resp.json()["error"]


def test_delete_route_resolves(monkeypatch, client):
    import investment_assistant.services.watchlist as watchlist_svc
    monkeypatch.setattr(watchlist_svc, "delete_watchlist_item", lambda ticker: {"ticker": ticker, "deleted": True})
    resp = client.delete("/api/watchlist/NVDA")
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "NVDA", "deleted": True}
    resp_nope = client.delete("/api/nope")
    assert resp_nope.status_code == 404


DERIVATION_PATHS = {
    "/api/workbench/plans/{plan_id}/derivation",
    "/api/workbench/units/{ticker}/{signal_date}/derivation",
    "/api/workbench/stage-runs",
}


def test_derivation_and_stage_runs_routes_in_openapi(client):
    spec = client.get("/openapi.json").json()
    assert DERIVATION_PATHS <= set(spec["paths"])
    for path in DERIVATION_PATHS:
        assert set(spec["paths"][path].keys()) == {"get"}          # 全部是只读 GET


def test_plan_derivation_response_top_level_keys(client, monkeypatch):
    from investment_assistant.workbench import derivation_view
    use_case = {"derivation_version": "derivation-1", "plan": {"id": "p1"}, "trigger": [],
                "inputs": {}, "steps": [], "checks": [], "consistency": {"status": "consistent"},
                "evidence": "evidence", "trigger_note": "note", "run": {"ready": True}}
    monkeypatch.setattr(derivation_view, "plan_derivation", lambda plan_id: dict(use_case))
    resp = client.get("/api/workbench/plans/6f1d1c1e-6666-4444-8888-000000000001/derivation")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"derivation_version", "plan", "trigger", "inputs", "steps",
                                       "checks", "consistency", "evidence", "run"}


TIMELINE_ROUTES = {
    "/api/workbench/chains": {"get"},
    "/api/workbench/chains/{ticker}/{signal_date}": {"get"},
    "/api/workbench/plan-reviews": {"get"},
    "/api/workbench/chains/{ticker}/{signal_date}/recheck": {"post"},
    "/api/workbench/user-inputs": {"get", "post"},
}


def test_plan_timeline_routes_in_openapi(client):
    spec = client.get("/openapi.json").json()
    for path, methods in TIMELINE_ROUTES.items():
        assert path in spec["paths"], path
        assert set(spec["paths"][path].keys()) == methods, path


def test_chain_view_response_top_level_keys(client, monkeypatch):
    from investment_assistant.workbench import plan_review
    use_case = {"ticker": "SYNTH", "signal_date": "2026-09-01", "session": "2026-09-02",
                "state": {"state": "entry", "mode": "entry", "basis": "未决定"},
                "head_plan_id": "p1", "version_no": 0, "latest_review": None,
                "versions": [], "reviews": [], "inputs": []}
    monkeypatch.setattr(plan_review, "chain_view", lambda ticker, signal_date, *, now: dict(use_case))
    resp = client.get("/api/workbench/chains/SYNTH/2026-09-01")
    assert resp.status_code == 200
    body = resp.json()
    assert {"state", "versions", "reviews", "inputs"} <= set(body)
    assert set(body) == set(use_case)


def test_timeline_routes_without_db_are_503(client):
    assert client.get("/api/workbench/chains/SYNTH/2026-09-01").status_code == 503
    assert client.get("/api/workbench/chains?ticker=SYNTH").status_code == 503
    assert client.get("/api/workbench/plan-reviews?session=2026-09-02").status_code == 503
    assert client.get("/api/workbench/user-inputs?ticker=SYNTH").status_code == 503
    assert client.post("/api/workbench/chains/SYNTH/2026-09-01/recheck").status_code == 503


def test_ticker_chains_response_shape(client, monkeypatch):
    from investment_assistant.workbench import plan_review
    use_case = {"ticker": "SYNTH", "chains": [{"signal_date": "2026-09-01", "state": "entry", "mode": "entry",
                                               "version_no": 1, "head_plan_id": "p1", "latest_review": None}]}
    monkeypatch.setattr(plan_review, "ticker_chains", lambda ticker, *, now: use_case)
    body = client.get("/api/workbench/chains?ticker=SYNTH").json()
    assert set(body) == {"ticker", "chains"}
    assert set(body["chains"][0]) == {"signal_date", "state", "mode", "version_no", "head_plan_id", "latest_review"}


KNOWLEDGE_PATHS = {
    "/api/knowledge/concepts",
    "/api/knowledge/concepts/{ref}",
    "/api/knowledge/principles",
}


def test_knowledge_routes_in_openapi_and_read_only(client):
    spec = client.get("/openapi.json").json()
    assert KNOWLEDGE_PATHS <= set(spec["paths"])
    for path in KNOWLEDGE_PATHS:
        assert set(spec["paths"][path].keys()) == {"get"}


def test_knowledge_routes_work_without_db(client):
    assert client.get("/api/knowledge/concepts").status_code == 200      # real docs/knowledge (may be empty)


UNDERSTANDING_PATHS = {
    "/api/workbench/run-overview",
    "/api/workbench/agent-runs/{run_id}/reasoning",
}


def test_run_overview_and_reasoning_routes_in_openapi_and_read_only(client):
    spec = client.get("/openapi.json").json()
    assert UNDERSTANDING_PATHS <= set(spec["paths"])
    for path in UNDERSTANDING_PATHS:
        assert set(spec["paths"][path].keys()) == {"get"}


def test_run_overview_and_reasoning_without_db_are_503(client):
    assert client.get("/api/workbench/run-overview?session=2026-10-27").status_code == 503
    assert client.get(
        "/api/workbench/agent-runs/6f1d1c1e-6666-4444-8888-000000000001/reasoning").status_code == 503
