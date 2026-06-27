from __future__ import annotations

import importlib

import pytest

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.hermes import deepseek_client


def test_config_has_real_default_model():
    cfg = AssistantConfig()
    assert cfg.model_default == "deepseek-chat"
    assert cfg.llm.model == "deepseek-chat"
    assert cfg.llm.deep_research_model == "deepseek-reasoner"
    assert cfg.llm.model != "deepseek-v4-pro"


def test_config_parses_nested_overrides(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(
        '{"llm": {"max_retries": 5}, "notify": {"email_enabled": false},'
        ' "prices": {"max_retries": 7}}',
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.llm.max_retries == 5
    assert cfg.notify.email_enabled is False
    assert cfg.prices.max_retries == 7


def test_deepseek_returns_structured_error_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    result, status = deepseek_client.request_json_completion_verbose(
        system_prompt="s", user_payload={"x": 1}
    )
    assert result is None
    assert status["ok"] is False
    assert "DEEPSEEK_API_KEY" in status["error"]


def test_dashboard_refuses_public_bind_without_optin(monkeypatch):
    monkeypatch.setenv("HERMES_DASHBOARD_HOST", "0.0.0.0")
    monkeypatch.delenv("HERMES_DASHBOARD_ALLOW_PUBLIC", raising=False)
    server = importlib.reload(importlib.import_module("investment_assistant.dashboard.server"))
    with pytest.raises(SystemExit):
        server._resolve_bind_host()
    monkeypatch.setenv("HERMES_DASHBOARD_HOST", "127.0.0.1")
    importlib.reload(server)


def test_dashboard_allows_localhost_bind(monkeypatch):
    monkeypatch.setenv("HERMES_DASHBOARD_HOST", "127.0.0.1")
    server = importlib.reload(importlib.import_module("investment_assistant.dashboard.server"))
    assert server._resolve_bind_host() == "127.0.0.1"
