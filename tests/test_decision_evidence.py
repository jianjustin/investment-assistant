from investment_assistant.hermes.decision_evidence import build_decision_evidence


def test_build_decision_evidence_combines_market_tickers_and_scores():
    result = build_decision_evidence(
        macro={"macro_state": "offense", "summary": "宏观偏进攻"},
        ticker_signals=[{"ticker": "TSLA", "attention_level": "high", "trigger_reason": ["above_ma_stack"]}],
        strategy_scores=[{"ticker": "TSLA", "strategy": "trend_relative_strength", "score": 82, "evidence": ["macro_offense"]}],
    )

    assert result["source"] == "hermes.decision_evidence"
    assert result["market_context"]
    assert result["ticker_focus"][0]["ticker"] == "TSLA"
    assert result["strategy_evidence"][0]["score"] == 82
    assert result["risk_questions"]
    assert result["next_actions"]
    assert result["llm"]["used"] is False


def test_decision_evidence_can_attach_llm_output():
    result = build_decision_evidence(
        macro={"macro_state": "offense", "summary": "宏观偏进攻"},
        ticker_signals=[],
        strategy_scores=[],
        use_llm=True,
        llm_client=lambda **kwargs: {"summary": "LLM summary", "risk_questions": ["反方问题"], "next_actions": ["继续观察"]},
    )

    assert result["llm"]["used"] is True
    assert result["summary"] == "LLM summary"
    assert result["risk_questions"] == ["反方问题"]
