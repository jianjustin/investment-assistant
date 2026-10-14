from investment_assistant.facts.signal import compare_signal, should_research


def test_first_snapshot_without_filing_is_only_a_baseline():
    result = compare_signal(
        trend_state="uptrend", attention_level="high", previous=None, has_new_filing=False,
    )
    assert result == {"changed": False, "reason": "baseline"}


def test_first_snapshot_with_filing_changes():
    result = compare_signal(
        trend_state="uptrend", attention_level="high", previous=None, has_new_filing=True,
    )
    assert result["changed"] is True
    assert result["reason"] == "new_filing"


def test_trend_or_attention_change_is_a_signal_change():
    previous = {"trend_state": "base", "attention_level": "low"}
    trend = compare_signal(
        trend_state="uptrend", attention_level="low", previous=previous, has_new_filing=False,
    )
    attention = compare_signal(
        trend_state="base", attention_level="high", previous=previous, has_new_filing=False,
    )
    assert trend["changed"] is True and trend["reason"] == "state_changed"
    assert attention["reason"] == "state_changed"


def test_same_state_without_filing_does_not_change():
    result = compare_signal(
        trend_state="base", attention_level="low",
        previous={"trend_state": "base", "attention_level": "low"},
        has_new_filing=False,
    )
    assert result == {"changed": False, "reason": "unchanged"}


def test_same_state_with_new_filing_changes():
    result = compare_signal(
        trend_state="base", attention_level="low",
        previous={"trend_state": "base", "attention_level": "low"},
        has_new_filing=True,
    )
    assert result["changed"] is True
    assert result["reason"] == "new_filing"


def test_named_ticker_is_researched_even_when_unchanged():
    assert should_research(named_by_user=True, changed=False) is True
    assert should_research(named_by_user=False, changed=False) is False
    assert should_research(named_by_user=False, changed=True) is True
