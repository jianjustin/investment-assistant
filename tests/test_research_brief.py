from investment_assistant.research.brief import build_research_brief


def test_build_research_brief_has_required_fields():
    result = build_research_brief(ticker="TSLA", thesis="高波动成长股样本", evidence=["证据1", "证据2", "证据3"])

    assert result["artifact_type"] == "ResearchBrief"
    assert result["ticker"] == "TSLA"
    assert len(result["evidence"]) == 3
    assert "invalidations" in result
    assert "next_action" in result
