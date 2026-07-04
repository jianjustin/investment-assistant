"""Test the route registry dispatch table."""
import pytest


def test_dispatch_unknown_returns_none():
    import investment_assistant.api.routes  # noqa: F401 — trigger registration
    from investment_assistant.api.router import dispatch
    assert dispatch("GET", "/api/nope", None) is None


def test_dispatch_status_get(monkeypatch, client):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"database", "filings", "system"}


def test_dispatch_delete_prefix():
    import investment_assistant.api.routes  # noqa: F401
    from investment_assistant.api.router import dispatch
    resp = dispatch("DELETE", "/api/watchlist/NVDA", None)
    assert resp is not None


def test_dispatch_post_validation():
    import investment_assistant.api.routes  # noqa: F401
    from investment_assistant.api.router import dispatch
    resp = dispatch("POST", "/api/market/signals/fetch", {})
    assert resp.status == 400
