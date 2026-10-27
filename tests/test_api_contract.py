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
