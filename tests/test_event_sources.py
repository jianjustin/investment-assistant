from datetime import date

from investment_assistant.research.event_sources import (
    collect_events,
    events_from_scores,
    events_from_snapshots,
)


def _snap(ticker, d, rs_spy, reasons, close=None, ma20=None, prev_close=None, prev_ma20=None):
    return {
        "ticker": ticker, "signal_date": d, "relative_strength_spy": rs_spy,
        "trigger_reason": reasons, "close": close, "ma20": ma20,
        "prev_close": prev_close, "prev_ma20": prev_ma20,
    }


def test_rs_strong_event_from_snapshot():
    rows = [_snap("NVDA", date(2024, 3, 1), 1.5, ["outperform_spy", "above_ma_stack"])]
    events = events_from_snapshots(rows, rs_strong=1.2)
    kinds = {(e.ticker, e.kind) for e in events}
    assert ("NVDA", "rs_strong") in kinds


def test_rs_strong_not_emitted_below_threshold():
    rows = [_snap("NVDA", date(2024, 3, 1), 0.5, ["outperform_spy"])]
    events = events_from_snapshots(rows, rs_strong=1.2)
    assert all(e.kind != "rs_strong" for e in events)


def test_ma_reclaim_event_on_cross_up():
    # 前一日 close<ma20，当日 close>ma20 → ma_reclaim
    rows = [_snap("MU", date(2024, 3, 4), 0.3, [],
                  close=50.0, ma20=49.0, prev_close=48.0, prev_ma20=49.5)]
    events = events_from_snapshots(rows)
    ma = [e for e in events if e.kind == "ma_reclaim"]
    assert len(ma) == 1
    assert ma[0].meta.get("approx") == "ma20_for_21ema"


def test_score_high_event_from_scores():
    rows = [{"ticker": "RKLB", "score_date": date(2024, 5, 1), "score": 80}]
    events = events_from_scores(rows, score_high=70)
    assert events and events[0].kind == "score_high" and events[0].ticker == "RKLB"


def test_asof_and_since_filter():
    rows = [
        _snap("AAA", date(2023, 1, 1), 1.5, ["outperform_spy"]),
        _snap("BBB", date(2024, 6, 1), 1.5, ["outperform_spy"]),
        _snap("CCC", date(2025, 1, 1), 1.5, ["outperform_spy"]),
    ]
    events = events_from_snapshots(rows, asof=date(2024, 12, 31), since=date(2024, 1, 1))
    tickers = {e.ticker for e in events}
    assert tickers == {"BBB"}  # AAA 早于 since，CCC 晚于 asof


def test_collect_events_degrades_without_sources():
    # 注入空 source（模拟无 DB）
    events = collect_events("rs_strong", snapshot_source=lambda: [], score_source=lambda: [])
    assert events == []


def test_collect_events_filters_by_kind():
    snap_rows = [_snap("NVDA", date(2024, 3, 1), 1.5, ["outperform_spy"])]
    score_rows = [{"ticker": "RKLB", "score_date": date(2024, 5, 1), "score": 90}]
    events = collect_events(
        "score_high", snapshot_source=lambda: snap_rows, score_source=lambda: score_rows,
    )
    assert all(e.kind == "score_high" for e in events)
    assert events[0].ticker == "RKLB"
