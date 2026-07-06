import pandas as pd
import pytest

from investment_assistant.api.routes import tickers as tickers_route
from investment_assistant.services import tickers as svc


def _frame(n=210, start=100.0):
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    close = [start + i for i in range(n)]
    return pd.DataFrame(
        {
            "Open": [c - 0.5 for c in close],
            "High": [c + 1 for c in close],
            "Low": [c - 1 for c in close],
            "Close": close,
            "Volume": [1000 + i for i in range(n)],
        },
        index=idx,
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    svc.clear_ohlcv_cache()
    yield
    svc.clear_ohlcv_cache()


def test_ohlcv_series_shapes_and_ma():
    out = svc.ohlcv_series("AAPL", days=210, fetcher=lambda t, d: _frame(210))
    assert out["ticker"] == "AAPL"
    assert len(out["bars"]) == 210
    for key in ("ma20", "ma50", "ma200"):
        assert len(out[key]) == 210
    # 前 n-1 个为 None
    assert out["ma20"][:19] == [None] * 19
    assert out["ma20"][19] is not None
    assert out["ma200"][198] is None
    assert out["ma200"][199] is not None
    # MA20 最后一个 = 最后 20 个 close 的均值
    closes = [b["close"] for b in out["bars"]]
    assert out["ma20"][-1] == pytest.approx(sum(closes[-20:]) / 20)
    # bar 字段齐全
    b0 = out["bars"][0]
    assert set(b0) == {"date", "open", "high", "low", "close", "volume"}
    assert b0["date"] == "2025-01-01"


def test_ohlcv_series_caches_within_ttl():
    calls = {"n": 0}

    def fetch(t, d):
        calls["n"] += 1
        return _frame(210)

    clock = {"t": 1000.0}
    svc.ohlcv_series("AAPL", days=210, fetcher=fetch, clock=lambda: clock["t"])
    svc.ohlcv_series("AAPL", days=210, fetcher=fetch, clock=lambda: clock["t"])
    assert calls["n"] == 1  # 第二次命中缓存


def test_ohlcv_series_refetches_after_ttl():
    calls = {"n": 0}

    def fetch(t, d):
        calls["n"] += 1
        return _frame(210)

    clock = {"t": 1000.0}
    svc.ohlcv_series("AAPL", days=210, fetcher=fetch, clock=lambda: clock["t"])
    clock["t"] = 1000.0 + 301  # 超过 300s TTL
    svc.ohlcv_series("AAPL", days=210, fetcher=fetch, clock=lambda: clock["t"])
    assert calls["n"] == 2


def test_ohlcv_route_returns_series(client, monkeypatch):
    monkeypatch.setattr(
        tickers_route._tickers, "ohlcv_series",
        lambda ticker, days=250: {"ticker": ticker.upper(), "bars": [], "ma20": [], "ma50": [], "ma200": []},
    )
    resp = client.get("/api/tickers/AAPL/ohlcv?days=120")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "AAPL"


def test_ohlcv_route_400_on_no_data(client, monkeypatch):
    def boom(ticker, days=250):
        raise ValueError("No price data returned for ZZZZ")

    monkeypatch.setattr(tickers_route._tickers, "ohlcv_series", boom)
    resp = client.get("/api/tickers/ZZZZ/ohlcv")
    assert resp.status_code == 400
