"""Pin API routing and no-DB fallback behaviour before layering refactor."""
import pytest

from investment_assistant.api.router import dispatch


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


def test_watchlist_get_falls_back_to_config_without_db():
    resp = dispatch("GET", "/api/watchlist", None)
    assert resp.payload["count"] >= 1
    assert all(row["source"] == "config" for row in resp.payload["rows"])


def test_post_market_fetch_requires_date():
    resp = dispatch("POST", "/api/market/signals/fetch", {})
    assert resp.status == 400 and "error" in resp.payload


def test_delete_route_resolves():
    assert dispatch("DELETE", "/api/watchlist/NVDA", None) is not None
    assert dispatch("DELETE", "/api/nope", None) is None
