from investment_assistant.dashboard import server
from investment_assistant.hermes import agents


def test_hermes_overview_exposes_capabilities_agents_and_ideas(monkeypatch, tmp_path):
    monkeypatch.setattr(agents, "AGENT_REGISTRY_PATH", tmp_path / "agents.json")
    response = server.api_response_for_path("/api/hermes")

    assert response.status == 200
    assert response.payload["capabilities"]
    assert response.payload["agents"]
    assert response.payload["ideas"]
    assert response.payload["capabilities"][0]["id"] == "macro_analyst"


def test_hermes_agent_post_creates_custom_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(agents, "AGENT_REGISTRY_PATH", tmp_path / "agents.json")
    payload = {
        "id": "risk-reviewer",
        "name": "风险复核 Agent",
        "role": "risk_reviewer",
        "description": "复核市场信号和持仓风险。",
        "system_prompt": "只输出风险检查清单。",
        "data_sources": ["market_signals", "watchlist"],
        "tools": ["market_signal_interpretation"],
        "enabled": True,
    }

    response = server.api_post_response_for_path("/api/hermes/agents", payload)
    list_response = server.api_response_for_path("/api/hermes/agents")

    assert response.status == 200
    assert response.payload["agent"]["id"] == "risk-reviewer"
    assert response.payload["agent"]["custom"] is True
    assert any(agent["id"] == "risk-reviewer" for agent in list_response.payload["agents"])


def test_hermes_agent_post_rejects_invalid_id(monkeypatch, tmp_path):
    monkeypatch.setattr(agents, "AGENT_REGISTRY_PATH", tmp_path / "agents.json")

    response = server.api_post_response_for_path("/api/hermes/agents", {"id": "bad id", "name": "bad"})

    assert response.status == 400
    assert "agent id" in response.payload["error"]
