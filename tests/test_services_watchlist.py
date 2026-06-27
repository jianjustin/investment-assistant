import pytest
from investment_assistant.services import watchlist as wl


def test_config_fallback_without_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    rows = wl.watchlist_rows()
    assert rows and all(r["source"] == "config" for r in rows)


def test_add_requires_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    with pytest.raises(ValueError):
        wl.add_watchlist_item({"ticker": "NVDA"})
