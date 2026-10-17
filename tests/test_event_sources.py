from datetime import date, datetime

import pytest

from investment_assistant.research.event_sources import (
    collect_events,
    events_from_scores,
    events_from_snapshots,
)


def _snap(ticker, d, rs_spy=None, reasons=None, close=50, ma20=49, prev_close=48, prev_ma20=49.5):
    from investment_assistant.data.calendar import add_trading_days
    day = d.date() if isinstance(d, datetime) else d
    previous = add_trading_days(day, -1)
    return {
        "ticker": ticker, "signal_date": d, "relative_strength_spy": rs_spy,
        "trigger_reason": reasons or [], "close": close, "ma20": ma20,
        "prev_close": prev_close, "prev_ma20": prev_ma20,
        "price_date": day, "calculation_version": "signal-asof-v2", "error": None,
        "prev_signal_date": previous, "prev_price_date": previous,
        "prev_calculation_version": "signal-asof-v2", "prev_error": None,
    }


def _score(ticker="RKLB", d=date(2024, 5, 1), score=80, **overrides):
    return {
        "ticker": ticker, "score_date": d, "score": score,
        "strategy": "trend_relative_strength", "calculation_version": "score-asof-v2",
        "snapshot_signal_date": d, "snapshot_price_date": d,
        "snapshot_calculation_version": "signal-asof-v2", "snapshot_error": None,
        **overrides,
    }


@pytest.mark.parametrize("threshold", [1.2, 0.012, 0.2])
def test_rs_threshold_not_silently_reinterpreted_or_retuned(threshold):
    rows = [_snap("NVDA", date(2024, 3, 1), 1.5, ["outperform_spy"])]
    with pytest.raises(ValueError, match="rs_strong.*20.*decimal"):
        events_from_snapshots(rows, rs_strong=threshold)


def test_default_snapshot_conversion_does_not_emit_unconfirmed_rs_definition():
    rows = [_snap("NVDA", date(2024, 3, 1), 1.5, ["outperform_spy"])]
    assert all(e.kind != "rs_strong" for e in events_from_snapshots(rows))


def test_ma_reclaim_event_is_sma20_not_21ema():
    events = events_from_snapshots([_snap("MU", date(2024, 3, 4))])
    assert len(events) == 1 and events[0].kind == "ma_reclaim"
    assert events[0].meta["indicator"] == "SMA"
    assert events[0].meta["period"] == 20
    assert events[0].meta["not_equivalent_to"] == "21EMA"
    assert "approx" not in events[0].meta


def test_ma_reclaim_requires_cross_not_just_above_average():
    events = events_from_snapshots([_snap("MU", date(2024, 3, 4), prev_close=50)])
    assert events == []


def test_score_high_event_from_scores():
    rows = [_score()]
    events = events_from_scores(rows, score_high=70)
    assert events and events[0].kind == "score_high" and events[0].ticker == "RKLB"


def test_asof_and_since_filter():
    rows = [
        _snap("AAA", date(2023, 1, 1)),
        _snap("BBB", date(2024, 6, 3)),
        _snap("CCC", date(2025, 1, 1)),
    ]
    events = events_from_snapshots(rows, asof=date(2024, 12, 31), since=date(2024, 1, 1))
    assert {e.ticker for e in events} == {"BBB"}


def test_collect_events_degrades_without_sources_for_supported_kind():
    assert collect_events("ma_reclaim", snapshot_source=lambda: [], score_source=lambda: []) == []


def test_collect_events_filters_by_kind():
    events = collect_events("score_high", snapshot_source=lambda: [_snap("NVDA", date(2024, 3, 1))],
                            score_source=lambda: [_score(score=90)])
    assert all(e.kind == "score_high" for e in events)
    assert events[0].ticker == "RKLB"


@pytest.mark.parametrize("kind", ["rs_strong", "eps_beat", "eps_miss", "vcp", "vcp_breakout", "unknown"])
def test_unavailable_kinds_raise_before_loading_any_source(kind):
    def forbidden():
        pytest.fail("unavailable definition must not load data")
    with pytest.raises(ValueError, match="unavailable"):
        collect_events(kind, snapshot_source=forbidden, score_source=forbidden)


def test_as_date_normalizes_datetime_to_date():
    events = events_from_snapshots([_snap("NVDA", datetime(2024, 3, 1, 15, 30))])
    assert events and events[0].date == date(2024, 3, 1)


@pytest.mark.parametrize("source_name", ["_default_snapshot_source", "_default_score_source"])
@pytest.mark.parametrize("failure", ["unconfigured", "connect", "sql"])
def test_default_source_failures_are_structured_and_sanitized(monkeypatch, source_name, failure):
    from unittest.mock import MagicMock
    from investment_assistant import db
    from investment_assistant.research import event_sources as sources
    secret = "postgres://user:secret-password@host SELECT private_column"
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    if failure != "unconfigured":
        monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    if failure == "connect":
        monkeypatch.setattr(db, "connect", MagicMock(side_effect=RuntimeError(secret)))
    else:
        monkeypatch.setattr(db, "connect", lambda url: connection)
    if failure == "sql":
        cursor.execute.side_effect = RuntimeError(secret)
    with pytest.raises(RuntimeError) as caught:
        getattr(sources, source_name)()
    assert caught.value.code == ("database_unconfigured" if failure == "unconfigured" else "source_read_failed")
    assert "secret-password" not in str(caught.value)
    assert "private_column" not in str(caught.value)


@pytest.mark.parametrize("source_name", ["_default_snapshot_source", "_default_score_source"])
def test_default_source_successfully_empty_is_not_a_failure(monkeypatch, source_name):
    from unittest.mock import MagicMock
    from investment_assistant import db
    from investment_assistant.research import event_sources as sources
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    monkeypatch.setattr(db, "connect", lambda url: connection)
    assert getattr(sources, source_name)() == []


@pytest.mark.parametrize("overrides,reason", [
    ({"price_date": None}, "price_date_missing"),
    ({"price_date": date(2024, 3, 1)}, "price_date_mismatch"),
    ({"calculation_version": None}, "calculation_version_mismatch"),
    ({"calculation_version": "legacy"}, "calculation_version_mismatch"),
    ({"prev_signal_date": None}, "prev_signal_date_missing"),
    ({"prev_price_date": None}, "prev_price_date_missing"),
    ({"prev_price_date": date(2024, 2, 29)}, "prev_price_date_mismatch"),
    ({"prev_calculation_version": None}, "prev_calculation_version_mismatch"),
    ({"prev_calculation_version": "legacy"}, "prev_calculation_version_mismatch"),
    ({"error": "failed"}, "snapshot_error"),
    ({"prev_error": "failed"}, "prev_snapshot_error"),
    ({"prev_signal_date": date(2024, 2, 29), "prev_price_date": date(2024, 2, 29)}, "non_adjacent_sessions"),
    ({"close": float("inf")}, "invalid_indicator"),
])
def test_ma_requires_current_and_previous_trusted_adjacent_snapshot(overrides, reason):
    row = {**_snap("AAA", date(2024, 3, 4)), **overrides}
    events = events_from_snapshots([row])
    assert events == []
    assert events.source_quality["status"] == "excluded"
    assert events.source_quality["excluded_by_reason"] == {reason: 1}


@pytest.mark.parametrize("current,previous", [
    (date(2024, 3, 4), date(2024, 3, 1)),  # weekend
    (date(2024, 4, 1), date(2024, 3, 28)),  # Good Friday
    (date(2025, 1, 10), date(2025, 1, 8)),  # Carter closure
])
def test_ma_adjacency_uses_actual_nyse_sessions(current, previous):
    row = _snap("AAA", current)
    row.update(prev_signal_date=previous, prev_price_date=previous)
    events = events_from_snapshots([row])
    assert len(events) == 1
    assert events.source_quality["status"] == "ok"


def test_ma_non_session_snapshot_is_excluded_at_pure_helper_boundary():
    events = events_from_snapshots([_snap("AAA", date(2024, 3, 29))])
    assert events == []
    assert events.source_quality["excluded_by_reason"] == {"non_trading_signal_date": 1}


def test_snapshot_sql_lags_unfiltered_rows_with_full_date_and_version_evidence(monkeypatch):
    from unittest.mock import MagicMock
    from investment_assistant import db
    from investment_assistant.research import event_sources as sources
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    monkeypatch.setattr(db, "connect", lambda url: connection)
    sources._default_snapshot_source()
    sql = " ".join(cursor.execute.call_args.args[0].lower().split())
    assert "where error is null" not in sql
    for column in ("signal_date", "price_date", "calculation_version", "error"):
        assert f"lag({column}) over w as prev_{column}" in sql


@pytest.mark.parametrize("overrides,reason", [
    ({"strategy": "other_strategy"}, "strategy_mismatch"),
    ({"strategy": None}, "strategy_mismatch"),
    ({"calculation_version": None}, "score_calculation_version_mismatch"),
    ({"calculation_version": "legacy"}, "score_calculation_version_mismatch"),
    ({"snapshot_signal_date": None}, "snapshot_signal_date_missing"),
    ({"snapshot_signal_date": date(2024, 4, 30)}, "snapshot_signal_date_mismatch"),
    ({"snapshot_price_date": None}, "snapshot_price_date_missing"),
    ({"snapshot_price_date": date(2024, 4, 30)}, "snapshot_price_date_mismatch"),
    ({"snapshot_calculation_version": None}, "snapshot_calculation_version_mismatch"),
    ({"snapshot_calculation_version": "legacy"}, "snapshot_calculation_version_mismatch"),
    ({"snapshot_error": "failed"}, "snapshot_error"),
])
def test_score_requires_fixed_strategy_and_both_current_provenance_versions(overrides, reason):
    events = events_from_scores([_score(**overrides)])
    assert events == []
    assert events.source_quality["status"] == "excluded"
    assert events.source_quality["excluded_by_reason"] == {reason: 1}


def test_score_mixed_strategies_never_count_same_ticker_date_twice():
    events = events_from_scores([_score(), _score(strategy="other_strategy")])
    assert len(events) == 1
    assert events[0].meta["strategy"] == "trend_relative_strength"
    assert events.source_quality["excluded_by_reason"] == {"strategy_mismatch": 1}


def test_score_ambiguous_duplicate_same_key_excludes_both_not_arbitrary_winner():
    events = events_from_scores([_score(score=80), _score(score=90)])
    assert events == []
    assert events.source_quality["excluded_by_reason"] == {"duplicate_score_key": 2}


def test_score_sql_parameters_strategy_and_retains_untrusted_joined_snapshots(monkeypatch):
    from unittest.mock import MagicMock
    from investment_assistant import db
    from investment_assistant.research import event_sources as sources
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    monkeypatch.setattr(db, "connect", lambda url: connection)
    sources._default_score_source()
    sql = " ".join(cursor.execute.call_args.args[0].lower().split())
    assert "where s.strategy = %s" in sql
    assert cursor.execute.call_args.args[1] == ("trend_relative_strength",)
    assert "left join ticker_signal_snapshots" in sql
    assert "snap.ticker = s.ticker" in sql and "snap.signal_date = s.score_date" in sql
    assert "snap.price_date" in sql and "snap.calculation_version" in sql
    assert sources.EVENT_DEFINITIONS["score_high"]["strategy"] == "trend_relative_strength"


def test_quality_distinguishes_truly_empty_valid_non_event_and_legacy_exclusion():
    empty = events_from_scores([])
    non_event = events_from_scores([_score(score=20)])
    legacy = events_from_scores([_score(calculation_version=None)])
    assert empty == non_event == legacy == []
    assert empty.source_quality["status"] == "empty"
    assert non_event.source_quality["status"] == "ok"
    assert non_event.source_quality["rows_eligible"] == 1
    assert legacy.source_quality["status"] == "excluded"
    assert legacy.source_quality["excluded_count"] == 1
