from datetime import date

import pandas as pd

from investment_assistant.tickers.trend import classify_ticker_trend, scan_ticker_trends


def test_classify_ticker_trend_marks_high_attention_uptrend():
    result = classify_ticker_trend(
        ticker="TSLA",
        close=120,
        ma20=110,
        ma50=100,
        ma200=90,
        volume_ratio=1.8,
        relative_strength_spy=0.06,
        relative_strength_qqq=0.04,
    )

    assert result["trend_state"] == "uptrend"
    assert result["attention_level"] == "high"
    assert "above_ma_stack" in result["trigger_reason"]
    assert "volume_expansion" in result["trigger_reason"]


def test_scan_ticker_trends_keeps_failed_ticker_without_stopping_batch():
    def frame(close_start: float) -> pd.DataFrame:
        values = [close_start + index for index in range(220)]
        return pd.DataFrame({
            "Open": values,
            "High": [value + 1 for value in values],
            "Low": [value - 1 for value in values],
            "Close": values,
            "Volume": [1000] * 219 + [2000],
        })

    def fetcher(ticker: str, days: int) -> pd.DataFrame:
        if ticker == "FAIL":
            raise ValueError("No price data returned for FAIL")
        if ticker == "SPY":
            return frame(300)
        if ticker == "QQQ":
            return frame(400)
        return frame(100)

    rows = scan_ticker_trends(["TSLA", "FAIL"], signal_date=date(2026, 6, 21), price_fetcher=fetcher, run_id="manual-test")

    assert [row["ticker"] for row in rows] == ["TSLA", "FAIL"]
    assert rows[0]["trend_state"] == "uptrend"
    assert rows[0]["error"] is None
    assert rows[0]["run_id"] == "manual-test"
    assert rows[1]["trend_state"] == "unknown"
    assert rows[1]["attention_level"] == "low"
    assert rows[1]["error"] == "No price data returned for FAIL"
