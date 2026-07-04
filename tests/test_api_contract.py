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
    assert ids == {"fetch_market_signals", "sync_filings", "health_check"}


def test_watchlist_get_falls_back_to_config_without_db(client):
    resp = client.get("/api/watchlist")
    assert resp.json()["count"] >= 1
    assert all(row["source"] == "config" for row in resp.json()["rows"])


def test_post_market_fetch_requires_date(client):
    resp = client.post("/api/market/signals/fetch", json={})
    assert resp.status_code == 400 and "error" in resp.json()


def test_delete_route_resolves(monkeypatch, client):
    import investment_assistant.services.watchlist as watchlist_svc
    monkeypatch.setattr(watchlist_svc, "delete_watchlist_item", lambda ticker: {"ticker": ticker, "deleted": True})
    resp = client.delete("/api/watchlist/NVDA")
    assert resp.status_code != 404
    resp_nope = client.delete("/api/nope")
    assert resp_nope.status_code == 404
