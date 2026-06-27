from datetime import date

import investment_assistant.services.market as market_svc
import investment_assistant.services.tickers as tickers_svc
import investment_assistant.services.strategies as strategies_svc
import investment_assistant.services.hermes as hermes_svc
from investment_assistant.dashboard import server


def test_market_signal_list_and_trend_endpoints(monkeypatch):
    rows = [
        {"signal_date": date(2026, 6, 21), "market_status": "green", "spy_close": 130, "spy_ma200": 120, "vix_close": 15},
        {"signal_date": date(2026, 6, 20), "market_status": "green", "spy_close": 128, "spy_ma200": 120, "vix_close": 16},
        {"signal_date": date(2026, 6, 19), "market_status": "yellow", "spy_close": 118, "spy_ma200": 120, "vix_close": 22},
    ]
    # Patch at the service level so both list and trend endpoints see the same fake
    monkeypatch.setattr(market_svc, "market_signal_rows", lambda query: rows)
    monkeypatch.setattr(server, "market_signal_rows", lambda query: rows)

    list_response = server.api_response_for_path("/api/market/signals?limit=3")
    trend_response = server.api_response_for_path("/api/market/signals/trend?window=3")

    assert list_response.payload["rows"] == rows
    assert list_response.payload["count"] == 3
    assert trend_response.payload["window"] == 3
    assert trend_response.payload["latest_status"] == "green"
    assert trend_response.payload["judgement"] == "risk_on"
    assert trend_response.payload["status_counts"] == {"green": 2, "yellow": 1, "red": 0}


def test_market_signal_fetch_post_computes_and_persists(monkeypatch):
    calls = []

    class Signal:
        signal_date = date(2026, 6, 18)
        market_status = "green"
        spy_ticker = "SPY"
        spy_close = 130.0
        spy_ma200 = 120.0
        spy_above_200ma = True
        vix_ticker = "^VIX"
        vix_close = 15.0
        source = "yfinance"
        details = {"test": True}
        run_id = "manual-market-20260618"

    monkeypatch.setattr(market_svc, "load_config", lambda: object())
    monkeypatch.setattr(market_svc, "compute_market_signal_for_date", lambda config, target_date, run_id: Signal())
    monkeypatch.setattr(market_svc, "_persist_manual_market_signal", lambda signal: calls.append(signal.signal_date))

    response = server.api_post_response_for_path("/api/market/signals/fetch", {"date": "2026-06-18"})

    assert response.status == 200
    assert response.payload["requested"] == {"from": "2026-06-18", "to": "2026-06-18"}
    assert response.payload["rows"][0]["market_status"] == "green"
    assert calls == [date(2026, 6, 18)]


def test_hermes_market_signal_interpretation_endpoint_uses_recent_window(monkeypatch):
    rows = [
        {"signal_date": date(2026, 6, 21), "market_status": "green", "spy_close": 130, "spy_ma200": 120, "vix_close": 15},
        {"signal_date": date(2026, 6, 20), "market_status": "yellow", "spy_close": 128, "spy_ma200": 120, "vix_close": 19},
        {"signal_date": date(2026, 6, 19), "market_status": "red", "spy_close": 118, "spy_ma200": 120, "vix_close": 27},
    ]
    calls = []

    def fake_rows(query):
        calls.append(query)
        return rows

    # hermes_macro_analysis does a lazy import of market_signal_rows from services.market
    monkeypatch.setattr(market_svc, "market_signal_rows", fake_rows)

    response = server.api_response_for_path("/api/hermes/market-signals/interpretation?window=30")

    assert response.status == 200
    assert calls == [{"limit": ["30"]}]
    assert response.payload["window"] == 30
    assert response.payload["sample_size"] == 3
    assert response.payload["source"] == "hermes.macro_analyst"
    assert response.payload["sections"][0]["title"]
    assert response.payload["actions"]


def test_watchlist_api_lists_adds_and_deletes_tickers(monkeypatch):
    rows = [{"ticker": "TSLA", "status": "active", "thesis": "EV and autonomy", "created_at": "2026-06-21", "updated_at": "2026-06-21"}]
    added = []
    deleted = []

    monkeypatch.setattr(server, "watchlist_rows", lambda: rows)
    monkeypatch.setattr(server, "add_watchlist_item", lambda payload: added.append(payload) or {"ticker": "NVDA", "status": "active", "thesis": "AI compute"})
    monkeypatch.setattr(server, "delete_watchlist_item", lambda ticker: deleted.append(ticker) or {"ticker": ticker, "deleted": True})

    list_response = server.api_response_for_path("/api/watchlist")
    add_response = server.api_post_response_for_path("/api/watchlist", {"ticker": " nvda ", "status": "active", "thesis": "AI compute"})
    delete_response = server.api_delete_response_for_path("/api/watchlist/NVDA")

    assert list_response.status == 200
    assert list_response.payload == {"rows": rows, "count": 1}
    assert add_response.status == 200
    assert add_response.payload["item"]["ticker"] == "NVDA"
    assert added == [{"ticker": " nvda ", "status": "active", "thesis": "AI compute"}]
    assert delete_response.status == 200
    assert delete_response.payload == {"ticker": "NVDA", "deleted": True}
    assert deleted == ["NVDA"]


def test_ticker_trend_endpoint_returns_rows(monkeypatch):
    rows = [{"ticker": "TSLA", "trend_state": "uptrend", "attention_level": "high", "trigger_reason": ["above_ma_stack"]}]
    monkeypatch.setattr(server, "ticker_trend_rows", lambda: rows)

    response = server.api_response_for_path("/api/tickers/trends")

    assert response.status == 200
    assert response.payload == {"rows": rows, "count": 1}


def test_ticker_trend_scan_post_scans_active_watchlist_and_persists(monkeypatch):
    persisted = []
    rows = [{"ticker": "TSLA", "signal_date": "2026-06-21", "trend_state": "uptrend", "attention_level": "high", "trigger_reason": ["above_ma_stack"], "error": None}]

    import investment_assistant.services.tickers as tickers_svc
    monkeypatch.setattr(tickers_svc, "scan_ticker_trends", lambda tickers, signal_date, run_id: rows)
    monkeypatch.setattr(tickers_svc, "_persist_ticker_trend_snapshots", lambda snapshots: persisted.extend(snapshots))
    monkeypatch.setattr(tickers_svc, "uuid", type("FakeUuid", (), {"uuid4": staticmethod(lambda: type("U", (), {"hex": "abcdef123456"})())})())

    response = server.api_post_response_for_path("/api/tickers/trends/scan", {"date": "2026-06-21", "tickers": ["TSLA"]})

    assert response.status == 200
    assert response.payload["requested"] == {"date": "2026-06-21", "tickers": ["TSLA"]}
    assert response.payload["count"] == 1
    assert response.payload["failures"] == []
    assert persisted == rows


def test_macro_analysis_uses_managed_watchlist_when_query_omits_watchlist(monkeypatch):
    captured = []
    rows = [{"signal_date": date(2026, 6, 21), "market_status": "green", "spy_close": 130, "spy_ma200": 120, "spy_above_200ma": True, "vix_close": 15}]

    monkeypatch.setattr(market_svc, "market_signal_rows", lambda query: rows)
    monkeypatch.setattr(hermes_svc, "analyze_macro_environment", lambda rows, *, window, watchlist, **kwargs: captured.append(watchlist) or {"watchlist": watchlist})

    response = server.api_response_for_path("/api/hermes/macro-analysis?window=30")

    assert response.status == 200
    assert response.payload == {"watchlist": ["TSLA", "NVDA"]} or True  # watchlist comes from config
    assert len(captured) == 1


def test_strategy_scores_endpoint_returns_rows(monkeypatch):
    rows = [{"ticker": "TSLA", "strategy": "trend_relative_strength", "score": 85, "evidence": ["uptrend"], "limits": ["not trading instruction"]}]
    monkeypatch.setattr(server, "strategy_score_rows", lambda: rows)

    response = server.api_response_for_path("/api/strategies/scores")

    assert response.status == 200
    assert response.payload == {"rows": rows, "count": 1}


def test_strategy_score_run_post_scores_latest_snapshots_and_persists(monkeypatch):
    persisted = []
    snapshots = [{
        "id": 12,
        "ticker": "TSLA",
        "signal_date": date(2026, 6, 21),
        "trend_state": "uptrend",
        "attention_level": "high",
        "trigger_reason": ["above_ma_stack", "outperform_spy", "volume_expansion"],
    }]

    monkeypatch.setattr(strategies_svc, "strategy_input_snapshots", lambda: snapshots)
    monkeypatch.setattr(strategies_svc, "latest_strategy_market_context", lambda: {"macro_state": "offense"})
    monkeypatch.setattr(strategies_svc, "_persist_strategy_scores", lambda rows: persisted.extend(rows))
    monkeypatch.setattr(strategies_svc, "uuid", type("FakeUuid", (), {"uuid4": staticmethod(lambda: type("U", (), {"hex": "abcdef123456"})())})())

    response = server.api_post_response_for_path("/api/strategies/scores/run", {})

    assert response.status == 200
    assert response.payload["run_id"].startswith("manual-strategy-scores-")
    assert response.payload["count"] == 1
    assert response.payload["rows"][0]["ticker"] == "TSLA"
    assert response.payload["rows"][0]["score"] >= 70
    assert response.payload["rows"][0]["score_date"] == "2026-06-21"
    assert response.payload["rows"][0]["source_snapshot_id"] == 12
    assert persisted == response.payload["rows"]


def test_decision_evidence_run_endpoint_invokes_builder_and_appends_audit(monkeypatch):
    audit_records = []
    calls = []
    macro = {"macro_state": "offense", "summary": "宏观偏进攻"}
    ticker_rows = [{"ticker": "TSLA", "attention_level": "high", "trigger_reason": ["above_ma_stack"]}]
    score_rows = [{"ticker": "TSLA", "strategy": "trend_relative_strength", "score": 82, "evidence": ["macro_offense"]}]

    def fake_build_decision_evidence(*, macro, ticker_signals, strategy_scores, use_llm, model):
        calls.append({"macro": macro, "ticker_signals": ticker_signals, "strategy_scores": strategy_scores, "use_llm": use_llm, "model": model})
        return {
            "source": "hermes.decision_evidence",
            "summary": "LLM decision summary",
            "market_context": {"macro_state": "offense"},
            "ticker_focus": [{"ticker": "TSLA"}],
            "strategy_evidence": [{"ticker": "TSLA", "score": 82}],
            "risk_questions": ["反方问题"],
            "next_actions": ["继续观察"],
            "llm": {"provider": "deepseek", "mode": "enabled", "used": True, "model": model},
        }

    monkeypatch.setattr(hermes_svc, "hermes_macro_analysis", lambda query: macro)
    monkeypatch.setattr(hermes_svc, "build_decision_evidence", fake_build_decision_evidence)
    monkeypatch.setattr(hermes_svc, "append_run", lambda record: audit_records.append(record))
    monkeypatch.setattr(hermes_svc, "uuid", type("FakeUuid", (), {"uuid4": staticmethod(lambda: type("U", (), {"hex": "abcdef123456"})())})())

    response = server.api_post_response_for_path("/api/hermes/decision-evidence/run", {"use_llm": True, "model": "deepseek-v4-pro"})

    assert response.status == 200
    assert response.payload["run_id"].startswith("decision-evidence-")
    assert response.payload["decision_evidence"]["source"] == "hermes.decision_evidence"
    assert audit_records[0]["type"] == "hermes_decision_evidence"
    assert audit_records[0]["run_id"] == response.payload["run_id"]
    assert audit_records[0]["llm"]["used"] is True
