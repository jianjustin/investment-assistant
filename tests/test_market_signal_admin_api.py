from datetime import date

from investment_assistant.dashboard import server


def test_market_signal_list_and_trend_endpoints(monkeypatch):
    rows = [
        {"signal_date": date(2026, 6, 21), "market_status": "green", "spy_close": 130, "spy_ma200": 120, "vix_close": 15},
        {"signal_date": date(2026, 6, 20), "market_status": "green", "spy_close": 128, "spy_ma200": 120, "vix_close": 16},
        {"signal_date": date(2026, 6, 19), "market_status": "yellow", "spy_close": 118, "spy_ma200": 120, "vix_close": 22},
    ]
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

    monkeypatch.setattr(server, "load_config", lambda: object())
    monkeypatch.setattr(server, "compute_market_signal_for_date", lambda config, target_date, run_id: Signal())
    monkeypatch.setattr(server, "_persist_manual_market_signal", lambda signal: calls.append(signal.signal_date))

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

    monkeypatch.setattr(server, "market_signal_rows", fake_rows)

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


def test_macro_analysis_uses_managed_watchlist_when_query_omits_watchlist(monkeypatch):
    captured = []
    rows = [{"signal_date": date(2026, 6, 21), "market_status": "green", "spy_close": 130, "spy_ma200": 120, "spy_above_200ma": True, "vix_close": 15}]

    monkeypatch.setattr(server, "market_signal_rows", lambda query: rows)
    monkeypatch.setattr(server, "current_watchlist", lambda: ["TSLA", "NVDA"])
    monkeypatch.setattr(server, "analyze_macro_environment", lambda rows, *, window, watchlist, **kwargs: captured.append(watchlist) or {"watchlist": watchlist})

    response = server.api_response_for_path("/api/hermes/macro-analysis?window=30")

    assert response.status == 200
    assert response.payload == {"watchlist": ["TSLA", "NVDA"]}
    assert captured == [["TSLA", "NVDA"]]
