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
    assert response.payload["source"] == "hermes.market_signals"
    assert response.payload["sections"][0]["title"]
    assert response.payload["actions"]
