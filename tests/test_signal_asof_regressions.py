"""Offline regressions for dated technical inputs and truthful batch reports."""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from investment_assistant.config import AssistantConfig
from investment_assistant.data.calendar import is_trading_day
from investment_assistant.services import strategies, tickers
from investment_assistant.tasks import _harness, metrics, nightly_scores
from investment_assistant.tickers import trend

TARGET = date(2024, 6, 14)


def prices(end=TARGET, periods=230, start=100.0):
    index = pd.bdate_range(end=end, periods=periods)
    index = index[[is_trading_day(ts.date()) for ts in index]]
    values = [start + i for i in range(len(index))]
    return pd.DataFrame({"Close": values, "Volume": [1000] * len(index)}, index=index)


def snapshot(day=TARGET, ticker="NVDA"):
    return {"id": 1, "ticker": ticker, "signal_date": day, "price_date": day,
            "calculation_version": "signal-asof-v2", "trend_state": "uptrend",
            "attention_level": "high", "trigger_reason": ["above_ma_stack"]}


def market_row(day=TARGET):
    return {"signal_date": day, "market_status": "green", "spy_above_200ma": True,
            "spy_close": 120.0, "spy_ma200": 100.0, "vix_close": 15.0,
            "details": {"spy_latest_index": f"{day} 00:00:00-04:00",
                        "vix_latest_index": f"{day} 00:00:00-04:00"}}


def test_default_scan_fetches_asof_with_calendar_buffer(monkeypatch):
    from investment_assistant.data import price

    calls = []

    class Ticker:
        def history(self, **kwargs):
            calls.append(kwargs)
            if "start" in kwargs:
                frame = prices(end=date.fromisoformat(kwargs["end"]) - timedelta(days=1), periods=260)
            else:
                # Real 260 calendar days cannot supply 200 trading observations.
                frame = prices(end=TARGET, periods=185)
            return frame.assign(Open=frame.Close, High=frame.Close, Low=frame.Close)

    monkeypatch.setattr(price.yf, "Ticker", lambda ticker: Ticker())
    rows = trend.scan_ticker_trends(["NVDA"], signal_date=TARGET)
    assert rows[0]["error"] is None
    assert rows[0]["signal_date"] == TARGET
    assert rows[0]["price_date"] == TARGET
    assert all(c["end"] == "2024-06-15" for c in calls)
    assert all((TARGET - date.fromisoformat(c["start"])).days >= 400 for c in calls)


def test_legacy_fetcher_is_preserved_but_future_bars_are_clipped():
    frame = prices(end=date(2024, 7, 1), periods=260)
    requested_days = []

    def fetch(ticker, days):
        requested_days.append(days)
        return frame.iloc[::-1]  # Sorting must precede all rolling/tail operations.

    row = trend.scan_ticker_trends(["NVDA"], signal_date=TARGET, price_fetcher=fetch)[0]
    expected = frame.loc[:str(TARGET)]
    assert row["error"] is None
    assert row["close"] == expected.Close.iloc[-1]
    assert row["ma200"] == expected.Close.tail(200).mean()
    assert min(requested_days) >= 400


def test_date_aware_fetcher_receives_target_and_trading_window():
    seen = []

    def fetch(ticker, end_date, days):
        seen.append((ticker, end_date, days))
        return prices()

    row = trend.scan_ticker_trends(["NVDA"], signal_date=TARGET, asof_price_fetcher=fetch)[0]
    assert row["error"] is None
    assert [s[0] for s in seen] == ["NVDA", "SPY", "QQQ"]
    assert all(s[1] == TARGET and s[2] >= 200 for s in seen)


@pytest.mark.parametrize("day", [date(2024, 6, 15), date(2024, 7, 4)])
def test_nontrading_date_does_not_relabel_previous_close(day):
    row = trend.scan_ticker_trends(["NVDA"], signal_date=day, price_fetcher=lambda *a: prices())[0]
    assert row["error"]
    assert row["close"] is None
    assert row["signal_date"] == day


@pytest.mark.parametrize("ticker", ["NVDA", "SPY", "QQQ"])
def test_missing_target_bar_is_not_substituted(ticker):
    row = trend.scan_ticker_trends(
        ["NVDA"], signal_date=TARGET,
        price_fetcher=lambda symbol, days: prices().iloc[:-1] if symbol == ticker else prices(),
    )[0]
    assert row["error"] and ticker in row["error"]
    assert row["close"] is None


def test_relative_strength_requires_matching_observation_dates():
    frame = prices()
    row = trend.scan_ticker_trends(
        ["NVDA"], signal_date=TARGET,
        price_fetcher=lambda symbol, days: frame.drop(frame.index[-21]) if symbol == "SPY" else frame,
    )[0]
    assert row["error"]
    assert row["relative_strength_spy"] is None


@pytest.mark.parametrize("kind", ["undated", "duplicate", "nan", "infinity"])
def test_invalid_price_inputs_are_rejected(kind):
    frame = prices()
    if kind == "undated":
        frame = frame.reset_index(drop=True)
    elif kind == "duplicate":
        frame = pd.concat([frame, frame.tail(1)])
    else:
        frame.loc[frame.index[-1], "Close"] = float("nan" if kind == "nan" else "inf")
    row = trend.scan_ticker_trends(["NVDA"], signal_date=TARGET, price_fetcher=lambda *a: frame)[0]
    assert row["error"]
    assert row["close"] is None


def test_unclosed_and_future_sessions_are_rejected_without_fetching():
    called = []
    for target in (TARGET, date(2024, 6, 17)):
        row = trend.scan_ticker_trends(
            ["NVDA"], signal_date=target, price_fetcher=lambda *a: called.append(a) or prices(),
            clock=lambda: datetime(2024, 6, 14, 19, 59, tzinfo=UTC),
        )[0]
        assert row["error"]
    assert called == []


def test_regular_close_delay_and_early_close_are_conservative():
    assert trend.latest_completed_signal_date(datetime(2024, 6, 14, 20, 14, tzinfo=UTC)) == date(2024, 6, 13)
    assert trend.latest_completed_signal_date(datetime(2024, 6, 14, 20, 15, tzinfo=UTC)) == TARGET
    # No early-close calendar: even July 3 waits until the normal close + delay.
    assert trend.latest_completed_signal_date(datetime(2024, 7, 3, 18, tzinfo=UTC)) == date(2024, 7, 2)


def test_service_default_uses_latest_completed_session(monkeypatch):
    seen = []
    monkeypatch.setattr(tickers, "latest_completed_signal_date", lambda: TARGET, raising=False)
    monkeypatch.setattr(tickers, "scan_ticker_trends", lambda ts, **kw: seen.append(kw) or [])
    monkeypatch.setattr(tickers, "_persist_ticker_trend_snapshots", lambda rows: {
        "inserted_count": 0, "skipped_count": 0, "skipped": []})
    out = tickers.run_ticker_trend_scan({"tickers": ["NVDA"]})
    assert out["requested"]["date"] == TARGET.isoformat()
    assert seen[0]["signal_date"] == TARGET


@pytest.fixture
def score_io(monkeypatch):
    persisted = []
    monkeypatch.setattr(strategies, "_persist_strategy_scores", lambda rows: persisted.extend(rows) or {
        "inserted_count": len(rows), "skipped_count": 0, "skipped": []})
    monkeypatch.setattr(strategies, "latest_strategy_market_context",
                        lambda: pytest.fail("historical score used current macro state"))
    return persisted


def test_historical_score_uses_only_dated_macro_rows(monkeypatch, score_io):
    from investment_assistant.services import market

    queries = []
    monkeypatch.setattr(strategies, "strategy_input_snapshots", lambda **kw: [snapshot()])
    monkeypatch.setattr(market, "market_signal_rows", lambda q: queries.append(q) or [market_row()])
    out = strategies.run_strategy_score_scan({"date": TARGET.isoformat()})
    assert out["count"] == 1 and out["failures"] == []
    assert queries == [{"to": [TARGET.isoformat()], "limit": ["30"]}]
    assert "macro_offense" in out["rows"][0]["evidence"]
    assert out["rows"][0]["score_date"] == TARGET.isoformat()
    assert score_io == out["rows"]


@pytest.mark.parametrize("bad", ["missing", "undated", "future", "stale", "invalid", "bar_mismatch", "bar_unknown"])
def test_invalid_macro_context_refuses_scoring(monkeypatch, score_io, bad):
    from investment_assistant.services import market

    row = market_row()
    rows = [row]
    if bad == "missing":
        rows = []
    elif bad == "undated":
        row.pop("signal_date")
    elif bad == "future":
        rows.append(market_row(date(2024, 6, 17)))
    elif bad == "stale":
        rows = [market_row(date(2024, 6, 13))]
    elif bad == "invalid":
        row["vix_close"] = None
    elif bad == "bar_unknown":
        row.pop("details")
    else:
        row["details"]["vix_latest_index"] = "2024-06-13 00:00:00-04:00"
    monkeypatch.setattr(strategies, "strategy_input_snapshots", lambda **kw: [snapshot()])
    monkeypatch.setattr(market, "market_signal_rows", lambda q: rows)
    out = strategies.run_strategy_score_scan({"date": TARGET.isoformat()})
    assert out["count"] == 0 and score_io == []
    assert out["failures"][0]["ticker"] == "NVDA"
    assert out["failures"][0]["error"]


@pytest.mark.parametrize("day", [None, "not-a-date", "2099-01-01", "2024-06-13"])
def test_invalid_or_mismatched_snapshot_date_refuses_scoring(monkeypatch, score_io, day):
    monkeypatch.setattr(strategies, "strategy_input_snapshots", lambda **kw: [snapshot(day)])
    monkeypatch.setattr(strategies, "historical_strategy_market_context", lambda d: {"macro_state": "offense"}, raising=False)
    out = strategies.run_strategy_score_scan({"date": TARGET.isoformat()})
    assert out["count"] == 0 and out["failures"] and score_io == []


def test_missing_snapshots_is_reported_as_failure(monkeypatch, score_io):
    monkeypatch.setattr(strategies, "strategy_input_snapshots", lambda **kw: [])
    out = strategies.run_strategy_score_scan({"date": TARGET.isoformat()})
    assert out["count"] == 0 and out["failures"]
    assert score_io == []


def test_undated_request_groups_macro_by_snapshot_date(monkeypatch, score_io):
    from investment_assistant.services import market

    dates = [date(2024, 6, 13), TARGET]
    queries = []
    monkeypatch.setattr(strategies, "strategy_input_snapshots", lambda **kw: [snapshot(d, str(i)) for i, d in enumerate(dates)])
    monkeypatch.setattr(market, "market_signal_rows", lambda q: queries.append(q) or [market_row(date.fromisoformat(q["to"][0]))])
    out = strategies.run_strategy_score_scan({})
    assert out["count"] == 2 and out["failures"] == []
    assert {q["to"][0] for q in queries} == {str(d) for d in dates}


def test_metrics_backfill_keeps_per_ticker_failure_details(monkeypatch):
    signal = SimpleNamespace(market_status="green", vix_close=15.0, signal_date=TARGET, details=market_row()["details"])
    failure = {"ticker": "BAD", "error": "missing target bar"}
    monkeypatch.setattr(metrics, "compute_market_signal_for_date", lambda *a, **kw: signal)
    monkeypatch.setattr(metrics, "_persist_signal", lambda *a: {
        "inserted_count": 1, "skipped_count": 0, "skipped": []})
    monkeypatch.setattr(metrics, "run_ticker_trend_scan", lambda p: {"count": 2, "rows": [], "failures": [failure]})
    out = metrics._core(AssistantConfig(), start_date=TARGET)
    assert out["errors"][0]["date"] == TARGET.isoformat()
    assert out["errors"][0]["ticker"] == "BAD"
    assert out["errors"][0]["error"] == "missing target bar"


def test_scores_backfill_keeps_failed_days_and_tickers(monkeypatch):
    def run(payload):
        if payload["date"] == "2024-06-13":
            return {"count": 1, "failures": [{"ticker": "BAD", "error": "no macro"}]}
        raise ValueError("no snapshots")

    monkeypatch.setattr(strategies, "run_strategy_score_scan", run)
    out = nightly_scores._core(AssistantConfig(), start_date=date(2024, 6, 13), end_date=TARGET)
    assert len(out["errors"]) == 2
    assert out["errors"][0]["ticker"] == "BAD"
    assert out["errors"][1]["date"] == TARGET.isoformat()
    assert out["errors"][1]["error"] == "no snapshots"
    assert "当前状态" not in out.get("note", "")


def test_harness_does_not_report_success_for_returned_failures(monkeypatch):
    recorded = []
    monkeypatch.setattr(_harness, "_record", lambda **kw: recorded.append(kw))
    out = _harness.run_task("scores", lambda: {"failures": [{"ticker": "BAD", "error": "broken"}]},
                            config=AssistantConfig(), notify=False)
    assert out["status"] == "error"
    assert recorded[0]["status"] == "error"


def test_failed_input_snapshots_are_not_silently_filtered_from_query(monkeypatch):
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params):
            calls.append((sql, params))

        def fetchall(self):
            return [(1, "BAD", TARGET, "unknown", "low", [], None, None, None,
                     "test-run", None, None, "missing target bar", None, "signal-asof-v2")]

    class Conn(Cursor):
        def cursor(self):
            return Cursor()

    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://mock-only")
    monkeypatch.setattr(strategies, "connect", lambda url: Conn())
    rows = strategies.strategy_input_snapshots(TARGET)
    assert "error IS NULL" not in calls[0][0]
    assert calls[0][1]["signal_date"] == TARGET
    assert rows[0]["error"] == "missing target bar"


def test_failed_snapshot_retains_source_error_without_scoring(monkeypatch, score_io):
    bad = {**snapshot(), "error": "missing target price bar"}
    monkeypatch.setattr(strategies, "strategy_input_snapshots", lambda **kw: [bad])
    monkeypatch.setattr(strategies, "historical_strategy_market_context",
                        lambda d: pytest.fail("failed snapshot must not be scored"))
    out = strategies.run_strategy_score_scan({"date": str(TARGET)})
    assert out["count"] == 0 and score_io == []
    assert "missing target price bar" in out["failures"][0]["error"]


def test_metrics_rejects_mislabeled_market_bars_before_persist(monkeypatch):
    signal = SimpleNamespace(market_status="green", signal_date=TARGET,
                             details={"spy_latest_index": str(TARGET), "vix_latest_index": "2024-06-13"})
    monkeypatch.setattr(metrics, "compute_market_signal_for_date", lambda *a, **kw: signal)
    monkeypatch.setattr(metrics, "_persist_signal", lambda *a: pytest.fail("invalid market row was persisted"))
    monkeypatch.setattr(metrics, "run_ticker_trend_scan", lambda *a: pytest.fail("invalid market row used"))
    out = metrics._core(AssistantConfig(), start_date=TARGET)
    assert out["errors"] and "mismatch" in out["errors"][0]["error"]


def test_future_bars_cannot_supply_the_200_day_warmup():
    frame = prices(end=date(2024, 8, 1), periods=240)
    row = trend.scan_ticker_trends(["NVDA"], signal_date=TARGET, price_fetcher=lambda *a: frame)[0]
    assert row["error"] and "200" in row["error"]


def test_timezone_aware_bars_keep_provider_session_dates():
    frame = prices()
    frame.index = frame.index.tz_localize("America/New_York")
    row = trend.scan_ticker_trends(["NVDA"], signal_date=TARGET, price_fetcher=lambda *a: frame)[0]
    assert row["error"] is None
    assert row["price_date"] == TARGET


@pytest.mark.parametrize("module", [metrics, nightly_scores])
def test_backfill_failure_sets_recorded_harness_status(monkeypatch, module):
    recorded = []
    monkeypatch.setattr(_harness, "_record", lambda **kw: recorded.append(kw))
    monkeypatch.setattr(_harness, "dispatch", lambda *a, **kw: None)
    failure = {"ticker": "BAD", "error": "input unavailable"}
    if module is metrics:
        signal = SimpleNamespace(market_status="green", vix_close=15.0, signal_date=TARGET, details=market_row()["details"])
        monkeypatch.setattr(metrics, "compute_market_signal_for_date", lambda *a, **kw: signal)
        monkeypatch.setattr(metrics, "_persist_signal", lambda *a: {
        "inserted_count": 1, "skipped_count": 0, "skipped": []})
        monkeypatch.setattr(metrics, "run_ticker_trend_scan", lambda p: {"count": 1, "failures": [failure]})
    else:
        monkeypatch.setattr(strategies, "run_strategy_score_scan", lambda p: {"count": 1, "failures": [failure]})
    out = module.run(AssistantConfig(), start_date=TARGET)
    assert out["status"] == "error"
    assert recorded[0]["status"] == "error"
    assert recorded[0]["summary"]["errors"][0]["ticker"] == "BAD"


@pytest.mark.parametrize("module", [metrics, nightly_scores])
def test_backfill_rejects_inverted_range(module):
    with pytest.raises(ValueError, match="end_date"):
        module._core(AssistantConfig(), start_date=TARGET, end_date=date(2024, 6, 13))


class MemorySQL:
    """SQL-boundary double: persisted rows survive calls; no database is opened."""

    def __init__(self):
        self.tables = {"ticker_signal_snapshots": {}, "strategy_scores": {}, "market_signals": {}}
        self.calls = []
        self.commits = 0
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self

    def commit(self):
        self.commits += 1

    def execute(self, sql, params=None):
        import copy
        import json

        normalized = " ".join(sql.split())
        self.calls.append((normalized, copy.deepcopy(params)))
        if not normalized.startswith("INSERT INTO"):
            return
        table = normalized.split()[2]
        row = copy.deepcopy(params)
        key = (row["signal_date"],) if table == "market_signals" else (
            (row["ticker"], row["signal_date"]) if table == "ticker_signal_snapshots" else
            (row["ticker"], row["score_date"], row["strategy"]))
        existing = self.tables[table].get(key)
        if existing is not None and "DO NOTHING" in normalized:
            self.result = None
            return
        for field in ("evidence", "limits", "trigger_reason"):
            if isinstance(row.get(field), str):
                row[field] = json.loads(row[field])
        row["id"] = existing["id"] if existing else len(self.tables[table]) + 1
        self.tables[table][key] = row
        self.result = (row["id"],)

    def fetchone(self):
        return self.result

    def fetchall(self):
        # Project in SQL SELECT order, catching omissions/misordered result keys.
        sql = self.calls[-1][0]
        projection = sql.split(" FROM ")[0].removeprefix("SELECT ")
        projection = projection.removeprefix("DISTINCT ON (ticker) ")
        table = sql.split(" FROM ")[1].split()[0]
        fields = [field.strip() for field in projection.split(",")]
        return [tuple(row.get(field) for field in fields) for row in self.tables[table].values()]


def sql_io(monkeypatch, conn):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://mock-only")
    for module in (tickers, strategies, metrics):
        monkeypatch.setattr(module, "connect", lambda url: conn)


def full_signal(day=TARGET):
    return SimpleNamespace(**market_row(day))


def computed_snapshot(error=None):
    row = trend.scan_ticker_trends(["NVDA"], signal_date=TARGET, price_fetcher=lambda *a: prices())[0]
    if error:
        row.update(error=error, trend_state="unknown", price_date=None, close=None)
    return row


def test_scan_emits_current_provenance_on_success_and_failure():
    good = computed_snapshot()
    bad = trend.scan_ticker_trends(["NVDA"], signal_date=TARGET, price_fetcher=lambda *a: prices().iloc[:-1])[0]
    assert good["calculation_version"] == "signal-asof-v2"
    assert good["price_date"] == TARGET
    assert bad["calculation_version"] == "signal-asof-v2" and bad["price_date"] is None


@pytest.mark.parametrize("failed_rerun", [False, True])
def test_scan_conflicts_preserve_existing_success_with_truthful_counts(monkeypatch, failed_rerun):
    import copy

    conn = MemorySQL()
    sql_io(monkeypatch, conn)
    good = computed_snapshot()
    monkeypatch.setattr(tickers, "scan_ticker_trends", lambda *a, **kw: [good])
    first = tickers.run_ticker_trend_scan({"tickers": ["NVDA"], "date": str(TARGET)})
    stored = copy.deepcopy(conn.tables["ticker_signal_snapshots"])
    rerun = {**good, "close": 99999, "run_id": "rerun"}
    if failed_rerun:
        rerun.update(error="provider unavailable", price_date=None, trend_state="unknown")
    monkeypatch.setattr(tickers, "scan_ticker_trends", lambda *a, **kw: [rerun])
    second = tickers.run_ticker_trend_scan({"tickers": ["NVDA"], "date": str(TARGET)})
    assert conn.tables["ticker_signal_snapshots"] == stored
    assert first["inserted_count"] == 1 and first["skipped_count"] == 0
    assert second["inserted_count"] == 0 and second["skipped_count"] == 1
    assert second["computed_count"] == (0 if failed_rerun else 1)
    assert second["skipped"][0]["reason"] == "existing_record_preserved"
    assert bool(second["failures"]) == failed_rerun
    assert all("DO UPDATE" not in sql and "RETURNING id" in sql for sql, _ in conn.calls)


def test_snapshot_provenance_roundtrips_through_insert_and_both_readers(monkeypatch):
    conn = MemorySQL()
    sql_io(monkeypatch, conn)
    tickers._persist_ticker_trend_snapshots([computed_snapshot()])
    listed = tickers.ticker_trend_rows()[0]
    selected = strategies.strategy_input_snapshots(TARGET)[0]
    for row in (listed, selected):
        assert row["price_date"] == TARGET
        assert row["calculation_version"] == "signal-asof-v2"
    assert selected["id"] == 1
    assert all("price_date" in sql and "calculation_version" in sql for sql, _ in conn.calls)


@pytest.mark.parametrize("metadata", [
    {"price_date": None}, {"price_date": date(2024, 6, 13)},
    {"calculation_version": None}, {"calculation_version": "signal-asof-v1"},
    {"id": None}, {"id": 0}, {"id": True},
])
def test_scoring_rejects_unverifiable_persisted_snapshot(monkeypatch, score_io, metadata):
    row = {**snapshot(), **metadata}
    monkeypatch.setattr(strategies, "strategy_input_snapshots", lambda **kw: [row])
    monkeypatch.setattr(strategies, "historical_strategy_market_context",
                        lambda day: {"signal_date": day, "macro_state": "offense"})
    result = strategies.run_strategy_score_scan({"date": str(TARGET)})
    assert result["count"] == 0 and score_io == []
    assert result["failures"][0]["error"]


def test_old_snapshot_from_database_is_explicit_failure_not_new_score(monkeypatch):
    conn = MemorySQL()
    sql_io(monkeypatch, conn)
    old = {**snapshot(), "price_date": None, "calculation_version": None}
    conn.tables["ticker_signal_snapshots"][("NVDA", TARGET)] = old
    monkeypatch.setattr(strategies, "historical_strategy_market_context",
                        lambda day: pytest.fail("legacy DB row reached scoring"))
    result = strategies.run_strategy_score_scan({})
    assert result["count"] == 0 and result["failures"]
    assert "provenance" in result["failures"][0]["error"].lower()
    assert conn.tables["strategy_scores"] == {}
    assert conn.tables["ticker_signal_snapshots"][("NVDA", TARGET)] == old


def test_score_sql_preserves_existing_and_returns_versioned_source(monkeypatch):
    import copy
    from investment_assistant.services import market

    conn = MemorySQL()
    sql_io(monkeypatch, conn)
    tickers._persist_ticker_trend_snapshots([computed_snapshot()])
    monkeypatch.setattr(market, "market_signal_rows", lambda q: [market_row()])
    first = strategies.run_strategy_score_scan({})
    stored = copy.deepcopy(conn.tables["strategy_scores"])
    second = strategies.run_strategy_score_scan({"date": str(TARGET)})
    assert conn.tables["strategy_scores"] == stored
    assert first["computed_count"] == first["inserted_count"] == 1
    assert second["computed_count"] == 1 and second["inserted_count"] == 0
    assert second["skipped_count"] == 1
    assert second["actual_dates"] == [str(TARGET)]
    row = strategies.strategy_score_rows()[0]
    assert row["calculation_version"] == "score-asof-v2" and row["source_snapshot_id"] == 1
    assert first["rows"][0]["calculation_version"] == "score-asof-v2"
    inserts = [sql for sql, _ in conn.calls if sql.startswith("INSERT INTO strategy_scores")]
    assert all("DO NOTHING" in sql and "DO UPDATE" not in sql for sql in inserts)


@pytest.mark.parametrize("preserve", [False, True])
def test_market_db_upsert_has_explicit_preserve_mode_without_changing_default(preserve):
    from investment_assistant import db

    conn = MemorySQL()
    db.upsert_market_signal(conn, full_signal())
    rerun = full_signal()
    rerun.market_status = "red"
    if preserve:
        assert db.upsert_market_signal(conn, rerun, preserve_existing=True) is False
        assert conn.tables["market_signals"][(TARGET,)]["market_status"] == "green"
        assert "DO NOTHING" in conn.calls[-1][0]
    else:
        db.upsert_market_signal(conn, rerun)
        assert conn.tables["market_signals"][(TARGET,)]["market_status"] == "red"
        assert "DO UPDATE" in conn.calls[-1][0]


@pytest.mark.parametrize("backfill", [False, True])
def test_metrics_sql_preserves_market_row_and_reports_skips(monkeypatch, backfill):
    import copy

    conn = MemorySQL()
    sql_io(monkeypatch, conn)
    monkeypatch.setattr(metrics, "latest_completed_signal_date", lambda: TARGET)
    monkeypatch.setattr(metrics, "compute_market_signal_for_date", lambda *a, **kw: full_signal())
    monkeypatch.setattr(tickers, "scan_ticker_trends", lambda *a, **kw: [computed_snapshot()])
    monkeypatch.setattr("investment_assistant.services.watchlist.current_watchlist", lambda: ["NVDA"])
    kwargs = {"start_date": TARGET} if backfill else {}
    first = metrics._core(AssistantConfig(), **kwargs)
    original = copy.deepcopy(conn.tables)
    second = metrics._core(AssistantConfig(), **kwargs)
    assert conn.tables == original
    assert first["market_inserted_count"] == 1
    assert second["market_inserted_count"] == second["ticker_inserted_count"] == 0
    assert second["market_skipped_count"] == second["ticker_skipped_count"] == 1
    assert second["market_computed_count"] == second["ticker_computed_count"] == 1
    assert len(second["skipped"]) == 2


def test_metrics_freezes_default_target_across_close_threshold(monkeypatch):
    days = iter([date(2024, 6, 13), TARGET])
    seen = []
    recorded = []
    monkeypatch.setattr(metrics, "latest_completed_signal_date", lambda: next(days))
    monkeypatch.setattr(metrics, "compute_market_signal_for_date",
                        lambda cfg, day, **kw: seen.append(day) or full_signal(day))
    monkeypatch.setattr(metrics, "_persist_signal", lambda *a: {
        "inserted_count": 0, "skipped_count": 1, "skipped": []})
    monkeypatch.setattr(metrics, "run_ticker_trend_scan", lambda p: {"rows": [], "failures": []})
    monkeypatch.setattr(_harness, "_record", lambda **kw: recorded.append(kw))
    monkeypatch.setattr(_harness, "dispatch", lambda *a, **kw: None)
    metrics.run(AssistantConfig())
    assert seen == [date(2024, 6, 13)]
    assert recorded[0]["target_start_date"] == recorded[0]["target_end_date"] == seen[0]
    assert recorded[0]["summary"]["actual_dates"] == ["2024-06-13"]


@pytest.mark.parametrize("bad", ["status", "bar_date", "missing_value"])
def test_invalid_older_macro_row_is_quarantined_with_coverage(monkeypatch, score_io, bad):
    import copy
    from investment_assistant.services import market

    older = market_row(date(2024, 6, 13))
    if bad == "status":
        older["market_status"] = "invalid"
    elif bad == "bar_date":
        older["details"] = {}
    else:
        older["vix_close"] = None
    original = copy.deepcopy(older)
    monkeypatch.setattr(market, "market_signal_rows", lambda q: [market_row(), older])
    monkeypatch.setattr(strategies, "strategy_input_snapshots", lambda **kw: [snapshot()])
    context = strategies.historical_strategy_market_context(TARGET)
    assert context["sample_size"] == 1
    assert context["coverage"]["valid_sessions"] == 1
    assert context["coverage"]["required_sessions"] == 30
    assert context["coverage"]["complete_30_sessions"] is False
    assert context["excluded_rows"][0]["signal_date"] == "2024-06-13"
    assert context["excluded_rows"][0]["reason"]
    out = strategies.run_strategy_score_scan({})
    assert out["count"] == 1 and out["failures"] == []
    assert out["market_contexts"][str(TARGET)]["excluded_rows"] == context["excluded_rows"]
    assert any("1/30" in limit for limit in out["rows"][0]["limits"])
    assert any("2024-06-13" in limit for limit in out["rows"][0]["limits"])
    assert older == original


def test_macro_coverage_requires_thirty_actual_sessions_not_thirty_old_rows(monkeypatch):
    from investment_assistant.services import market

    sessions = []
    day = TARGET
    while len(sessions) < 31:
        if is_trading_day(day):
            sessions.append(day)
        day -= timedelta(days=1)
    monkeypatch.setattr(market, "market_signal_rows", lambda q: [market_row(d) for d in sessions[:30]])
    assert strategies.historical_strategy_market_context(TARGET)["coverage"]["complete_30_sessions"] is True
    monkeypatch.setattr(market, "market_signal_rows",
                        lambda q: [market_row(d) for d in [sessions[0], *sessions[2:31]]])
    context = strategies.historical_strategy_market_context(TARGET)
    assert context["coverage"]["complete_30_sessions"] is False
    assert str(sessions[1]) in context["coverage"]["missing_dates"]


@pytest.mark.parametrize("case", ["success", "failure", "mixed_dates", "empty", "exception"])
def test_default_scores_report_actual_selected_dates_not_wall_clock(monkeypatch, case):
    recorded = []
    sent = []
    selected = [] if case == "empty" else [snapshot(date(2024, 6, 13))]
    if case == "mixed_dates":
        selected.append(snapshot(TARGET, "MSFT"))
    if case == "failure":
        selected[0]["calculation_version"] = None
    monkeypatch.setattr(strategies, "strategy_input_snapshots", lambda **kw: selected)
    monkeypatch.setattr(strategies, "historical_strategy_market_context",
                        lambda day: {"signal_date": day, "macro_state": "offense"})
    monkeypatch.setattr(strategies, "_persist_strategy_scores", lambda rows: {
        "inserted_count": len(rows), "skipped_count": 0, "skipped": []})
    monkeypatch.setattr(_harness, "_record", lambda **kw: recorded.append(kw))
    monkeypatch.setattr(_harness, "dispatch", lambda *a, **kw: sent.append(kw))
    if case == "exception":
        monkeypatch.setattr(strategies, "run_strategy_score_scan",
                            lambda p: (_ for _ in ()).throw(ValueError("database unavailable")))
    out = nightly_scores.run(AssistantConfig())
    expected = [] if case in {"empty", "exception"} else (
        ["2024-06-13", "2024-06-14"] if case == "mixed_dates" else ["2024-06-13"])
    assert out["summary"]["actual_dates"] == expected
    assert recorded[0]["target_start_date"] == (date.fromisoformat(expected[0]) if expected else None)
    assert recorded[0]["target_end_date"] == (date.fromisoformat(expected[-1]) if expected else None)
    assert sent[0]["target_start_date"] == recorded[0]["target_start_date"]
    assert out["status"] == ("error" if case in {"failure", "empty", "exception"} else "success")


def test_score_backfill_distinguishes_computed_from_inserted_and_skipped(monkeypatch):
    monkeypatch.setattr(strategies, "run_strategy_score_scan", lambda p: {
        "count": 2, "computed_count": 2, "inserted_count": 0, "skipped_count": 2,
        "skipped": [{"ticker": "NVDA", "date": p["date"], "reason": "existing_record_preserved"},
                    {"ticker": "MSFT", "date": p["date"], "reason": "existing_record_preserved"}],
        "actual_dates": [p["date"]], "failures": [],
    })
    result = nightly_scores._core(AssistantConfig(), start_date=TARGET)
    assert result["computed_count"] == 2 and result["inserted_count"] == 0
    assert result["skipped_count"] == 2
    assert result["days"][0]["inserted_count"] == 0
    assert len(result["skipped"]) == 2

