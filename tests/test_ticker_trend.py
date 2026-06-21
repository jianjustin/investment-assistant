from investment_assistant.tickers.trend import classify_ticker_trend


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
