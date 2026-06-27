from datetime import date

import investment_assistant.services.market as market_svc
import investment_assistant.services.hermes as hermes_svc
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


def test_macro_analyst_can_attach_real_llm_interpretation():
    calls = []

    def fake_llm_client(*, system_prompt, user_payload, model):
        calls.append({"system_prompt": system_prompt, "user_payload": user_payload, "model": model})
        return {
            "summary": "LLM 判断：进攻但需要观察 VIX。",
            "key_changes": ["LLM key change"],
            "growth_implications": ["LLM growth implication"],
            "watchlist_implications": ["LLM watchlist implication"],
            "next_checks": ["LLM next check"],
            "actions": ["LLM action"],
            "risk_questions": ["LLM risk question"],
        }

    result = analyze_macro_environment(
        _rows(),
        window=30,
        watchlist=["TSLA", "NVDA"],
        use_llm=True,
        model="deepseek-v4-pro",
        llm_client=fake_llm_client,
    )

    assert calls
    assert calls[0]["model"] == "deepseek-v4-pro"
    assert calls[0]["user_payload"]["macro_snapshot"]["stage"] == "Research"
    assert result["llm"]["used"] is True
    assert result["llm"]["provider"] == "deepseek"
    assert result["llm"]["model"] == "deepseek-v4-pro"
    assert result["llm_interpretation"]["summary"] == "LLM 判断：进攻但需要观察 VIX。"
    assert result["summary"] == "LLM 判断：进攻但需要观察 VIX。"
    assert result["key_changes"] == ["LLM key change"]


def test_macro_analyst_reports_llm_fallback_when_model_is_unavailable():
    result = analyze_macro_environment(
        _rows(),
        window=30,
        use_llm=True,
        model="deepseek-v4-pro",
        llm_client=lambda **kwargs: None,
    )

    assert result["llm"]["used"] is False
    assert result["llm"]["mode"] == "fallback"
    assert result["llm"]["error"]
    assert result["llm_interpretation"] is None


def test_macro_analyst_api_replaces_market_signal_interpretation(monkeypatch):
    calls = []
    monkeypatch.setattr(market_svc, "market_signal_rows", lambda query: calls.append(query) or _rows())

    response = server.api_response_for_path("/api/hermes/macro-analysis?window=30&watchlist=TSLA,NVDA")
    legacy = server.api_response_for_path("/api/hermes/market-signals/interpretation?window=30")

    assert response.status == 200
    assert calls[0] == {"limit": ["30"]}
    assert response.payload["source"] == "hermes.macro_analyst"
    assert response.payload["macro_snapshot"]["watchlist"] == ["TSLA", "NVDA"]
    assert legacy.status == 200
    assert legacy.payload["source"] == "hermes.macro_analyst"


def test_macro_analyst_llm_run_endpoint_returns_pending(monkeypatch):
    response = server.api_post_response_for_path(
        "/api/hermes/macro-analysis/run",
        {"window": 30, "watchlist": ["TSLA", "NVDA"], "model": "deepseek-v4-pro"},
    )

    assert response.status == 200
    assert response.payload["status"] == "pending"
    assert response.payload["run_id"].startswith("macro-llm-")


def test_macro_analyst_llm_job_invokes_model_and_appends_audit(monkeypatch):
    calls = []
    audit_records = []

    def fake_analyze(rows, *, window, watchlist, use_llm=False, model=None, llm_client=None):
        calls.append({"rows": rows, "window": window, "watchlist": watchlist, "use_llm": use_llm, "model": model})
        return {
            "source": "hermes.macro_analyst",
            "agent_role": "macro_analyst",
            "macro_state": "offense",
            "stance_label": "进攻",
            "summary": "LLM macro summary",
            "llm": {"provider": "deepseek", "mode": "enabled", "used": True, "model": model},
            "llm_interpretation": {"summary": "LLM macro summary"},
            "macro_snapshot": {"stage": "Research", "artifact_type": "MacroSnapshot", "watchlist": watchlist},
            "key_changes": [],
            "growth_implications": [],
            "watchlist_implications": [],
            "next_checks": [],
            "actions": [],
        }

    monkeypatch.setattr(market_svc, "market_signal_rows", lambda query: _rows())
    monkeypatch.setattr(hermes_svc, "analyze_macro_environment", fake_analyze)
    monkeypatch.setattr(hermes_svc, "append_run", lambda record: audit_records.append(record))

    result = hermes_svc._macro_llm_job({"window": 30, "watchlist": ["TSLA", "NVDA"], "model": "deepseek-v4-pro"})

    assert result["run_id"].startswith("macro-llm-")
    assert result["analysis"]["llm"]["used"] is True
    assert calls[0]["window"] == 30
    assert audit_records[0]["type"] == "hermes_macro_llm_analysis"
    assert audit_records[0]["llm"]["used"] is True


def test_hermes_capabilities_and_default_agent_are_macro_analyst(monkeypatch, tmp_path):
    monkeypatch.setattr(agents, "AGENT_REGISTRY_PATH", tmp_path / "agents.json")

    capability_ids = [capability["id"] for capability in agents.hermes_capabilities()]
    default_agent = agents.default_agents()[0]

    assert capability_ids[0] == "macro_analyst"
    assert default_agent["id"] == "macro-analyst"
    assert default_agent["role"] == "macro_analyst"
    assert "macro_analysis" in default_agent["tools"]
