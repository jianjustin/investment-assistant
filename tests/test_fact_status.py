from datetime import date

from investment_assistant.facts.status import assess_fact


DAY = date(2026, 8, 26)


def _ok(**overrides):
    payload = {
        "on_date": DAY,
        "ticker": "NVDA",
        "market": {"market_status": "green"},
        "snapshot": {"close": 180, "error": None},
        "filings_report": {"status": "success", "summary": {"downloaded_count": 1, "errors": {}}},
        "score": {"score": 30},
    }
    payload.update(overrides)
    return payload


def test_complete_when_all_four_records_exist():
    result = assess_fact(**_ok())
    assert result == {"ready": True, "blocked": False, "reason": "complete"}


def test_zero_filing_downloads_still_complete():
    result = assess_fact(**_ok(
        on_date=date(2026, 10, 13),
        filings_report={"status": "success", "summary": {"downloaded_count": 0, "errors": {}}},
    ))
    assert result["ready"] is True
    assert result["reason"] == "complete"


def test_weekend_is_not_a_failure():
    result = assess_fact(**_ok(on_date=date(2026, 10, 10), market=None, snapshot=None, score=None))
    assert result == {"ready": False, "blocked": False, "reason": "weekend"}


def test_missing_market_blocks_the_ticker():
    result = assess_fact(**_ok(market=None))
    assert result == {"ready": False, "blocked": True, "reason": "market_missing"}


def test_snapshot_error_blocks_only_that_ticker():
    broken = assess_fact(**_ok(snapshot={"close": 10, "error": "no price"}))
    other = assess_fact(**_ok(ticker="MU"))
    assert broken["blocked"] is True and broken["reason"] == "snapshot_error"
    assert other["ready"] is True


def test_missing_close_blocks_without_using_another_day():
    result = assess_fact(**_ok(snapshot={"close": None, "error": None}))
    assert result == {"ready": False, "blocked": True, "reason": "price_missing"}


def test_filing_error_for_one_ticker_blocks_only_that_ticker():
    result = assess_fact(**_ok(
        filings_report={"status": "success", "summary": {"downloaded_count": 0, "errors": {"NVDA": "http 503"}}},
    ))
    assert result["reason"] == "filings_ticker_error"
    other = assess_fact(**_ok(ticker="MU", filings_report={
        "status": "success", "summary": {"downloaded_count": 0, "errors": {"NVDA": "http 503"}},
    }))
    assert other["ready"] is True


def test_missing_score_is_not_complete():
    result = assess_fact(**_ok(score=None))
    assert result == {"ready": False, "blocked": True, "reason": "score_missing"}
