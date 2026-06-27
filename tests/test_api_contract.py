"""Pin dashboard API routing and no-DB fallback behaviour before layering refactor."""
import importlib
import pytest

server = importlib.import_module("investment_assistant.dashboard.server")


@pytest.fixture(autouse=True)
def no_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)


def test_unknown_api_get_returns_none():
    assert server.api_response_for_path("/api/does-not-exist") is None


def test_status_get_route_resolves():
    resp = server.api_response_for_path("/api/status")
    assert resp is not None and resp.status == 200
    assert set(resp.payload.keys()) == {"database", "filings", "system"}


def test_operations_registry_shape():
    resp = server.api_response_for_path("/api/operations")
    ids = {op["id"] for op in resp.payload["operations"]}
    assert ids == {"fetch_market_signals", "sync_filings", "health_check"}


def test_watchlist_get_falls_back_to_config_without_db():
    resp = server.api_response_for_path("/api/watchlist")
    assert resp.payload["count"] >= 1
    assert all(row["source"] == "config" for row in resp.payload["rows"])


def test_post_market_fetch_requires_date():
    resp = server.api_post_response_for_path("/api/market/signals/fetch", {})
    assert resp.status == 400 and "error" in resp.payload


def test_delete_route_resolves():
    assert server.api_delete_response_for_path("/api/watchlist/NVDA") is not None
    assert server.api_delete_response_for_path("/api/nope") is None
