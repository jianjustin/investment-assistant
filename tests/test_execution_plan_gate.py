from investment_assistant.research.execution_plan import create_execution_plan


def test_execution_plan_is_pending_review_by_default():
    result = create_execution_plan(ticker="TSLA", direction="watch", premise="macro must remain offense")

    assert result["artifact_type"] == "ExecutionPlan"
    assert result["approval_status"] == "pending_review"
    assert result["broker_action"] is None
    assert result["ticker"] == "TSLA"
