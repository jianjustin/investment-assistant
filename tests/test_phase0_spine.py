from __future__ import annotations

import importlib

import pytest

from investment_assistant.config import load_config


def test_config_parses_nested_overrides(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(
        '{"notify": {"channel": "email"}, "prices": {"max_retries": 7}}',
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.notify.channel == "email"
    assert cfg.prices.max_retries == 7


def test_dashboard_refuses_public_bind_without_optin(monkeypatch):
    monkeypatch.setenv("HERMES_DASHBOARD_HOST", "0.0.0.0")
    monkeypatch.delenv("HERMES_DASHBOARD_ALLOW_PUBLIC", raising=False)
    api_auth = importlib.reload(importlib.import_module("investment_assistant.api.auth"))
    with pytest.raises(SystemExit):
        api_auth.resolve_bind_host()


def test_dashboard_allows_localhost_bind(monkeypatch):
    monkeypatch.setenv("HERMES_DASHBOARD_HOST", "127.0.0.1")
    api_auth = importlib.reload(importlib.import_module("investment_assistant.api.auth"))
    assert api_auth.resolve_bind_host() == "127.0.0.1"
