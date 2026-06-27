"""Test the route registry dispatch table."""
import pytest


def test_dispatch_unknown_returns_none():
    import investment_assistant.api.routes  # noqa: F401 — trigger registration
    from investment_assistant.api.router import dispatch
    assert dispatch("GET", "/api/nope", None) is None


def test_dispatch_status_get(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    import investment_assistant.api.routes  # noqa: F401
    from investment_assistant.api.router import dispatch
    resp = dispatch("GET", "/api/status", None)
    assert resp is not None and resp.status == 200


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
