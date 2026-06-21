from investment_assistant.strategies.trend_relative_strength import score_trend_relative_strength


def test_score_trend_relative_strength_returns_evidence_and_limits():
    snapshot = {
        "ticker": "TSLA",
        "trend_state": "uptrend",
        "attention_level": "high",
        "trigger_reason": ["above_ma_stack", "outperform_spy", "volume_expansion"],
    }
    market = {"macro_state": "offense"}

    result = score_trend_relative_strength(snapshot, market)

    assert result["strategy"] == "trend_relative_strength"
    assert result["score"] >= 70
    assert "above_ma_stack" in result["evidence"]
    assert result["limits"]
