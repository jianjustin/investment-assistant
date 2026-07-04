from investment_assistant.hermes import agents


def test_hermes_overview_exposes_capabilities_agents_and_ideas(monkeypatch, tmp_path, client):
    monkeypatch.setattr(agents, "AGENT_REGISTRY_PATH", tmp_path / "agents.json")
    response = client.get("/api/hermes")

    assert response.status_code == 200
    assert response.json()["capabilities"]
    assert response.json()["agents"]
    assert response.json()["ideas"]
    assert response.json()["capabilities"][0]["id"] == "macro_analyst"


def test_hermes_agent_post_creates_custom_agent(monkeypatch, tmp_path, client):
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

    response = client.post("/api/hermes/agents", json=payload)
    list_response = client.get("/api/hermes/agents")

    assert response.status_code == 200
    assert response.json()["agent"]["id"] == "risk-reviewer"
    assert response.json()["agent"]["custom"] is True
    assert any(agent["id"] == "risk-reviewer" for agent in list_response.json()["agents"])


def test_hermes_agent_post_rejects_invalid_id(monkeypatch, tmp_path, client):
    monkeypatch.setattr(agents, "AGENT_REGISTRY_PATH", tmp_path / "agents.json")

    response = client.post("/api/hermes/agents", json={"id": "bad id", "name": "bad"})

    assert response.status_code == 400
    assert "agent id" in response.json()["error"]
