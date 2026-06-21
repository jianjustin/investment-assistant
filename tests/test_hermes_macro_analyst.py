from datetime import date

from investment_assistant.dashboard import server
from investment_assistant.hermes import agents
from investment_assistant.hermes.macro_analyst import analyze_macro_environment


def _rows():
    return [
        {"signal_date": date(2026, 6, 21), "market_status": "green", "spy_close": 130, "spy_ma200": 120, "spy_above_200ma": True, "vix_close": 15},
        {"signal_date": date(2026, 6, 20), "market_status": "green", "spy_close": 128, "spy_ma200": 120, "spy_above_200ma": True, "vix_close": 16},
        {"signal_date": date(2026, 6, 19), "market_status": "yellow", "spy_close": 118, "spy_ma200": 120, "spy_above_200ma": False, "vix_close": 22},
    ]


def test_macro_analyst_builds_macro_snapshot_style_output():
    result = analyze_macro_environment(_rows(), window=30, watchlist=["TSLA", "NVDA"])

    assert result["source"] == "hermes.macro_analyst"
    assert result["agent_role"] == "macro_analyst"
    assert result["window"] == 30
    assert result["macro_state"] in {"offense", "cautious", "defense"}
    assert result["stance_label"] in {"进攻", "谨慎", "防守"}
    assert result["macro_snapshot"]["stage"] == "Research"
    assert result["macro_snapshot"]["artifact_type"] == "MacroSnapshot"
    assert result["macro_snapshot"]["watchlist"] == ["TSLA", "NVDA"]
    assert result["key_changes"]
    assert result["growth_implications"]
    assert result["watchlist_implications"]
    assert result["next_checks"]
    assert result["actions"]


def test_macro_analyst_api_replaces_market_signal_interpretation(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "market_signal_rows", lambda query: calls.append(query) or _rows())

    response = server.api_response_for_path("/api/hermes/macro-analysis?window=30&watchlist=TSLA,NVDA")
    legacy = server.api_response_for_path("/api/hermes/market-signals/interpretation?window=30")

    assert response.status == 200
    assert calls[0] == {"limit": ["30"]}
    assert response.payload["source"] == "hermes.macro_analyst"
    assert response.payload["macro_snapshot"]["watchlist"] == ["TSLA", "NVDA"]
    assert legacy.status == 200
    assert legacy.payload["source"] == "hermes.macro_analyst"


def test_hermes_capabilities_and_default_agent_are_macro_analyst(monkeypatch, tmp_path):
    monkeypatch.setattr(agents, "AGENT_REGISTRY_PATH", tmp_path / "agents.json")

    capability_ids = [capability["id"] for capability in agents.hermes_capabilities()]
    default_agent = agents.default_agents()[0]

    assert capability_ids[0] == "macro_analyst"
    assert default_agent["id"] == "macro-analyst"
    assert default_agent["role"] == "macro_analyst"
    assert "macro_analysis" in default_agent["tools"]
