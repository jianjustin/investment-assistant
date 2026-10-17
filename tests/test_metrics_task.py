from datetime import date
from types import SimpleNamespace

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import metrics


def _signal(day):
    return SimpleNamespace(market_status="green", vix_close=15.0, signal_date=day,
                           details={"spy_latest_index": str(day), "vix_latest_index": str(day)})


def test_core_builds_summary(monkeypatch):
    signal = _signal(date(2026, 6, 29))
    monkeypatch.setattr(metrics, "latest_completed_signal_date", lambda: signal.signal_date)
    monkeypatch.setattr(metrics, "compute_market_signal_for_date", lambda cfg, d, **kw: signal)
    monkeypatch.setattr(metrics, "run_ticker_trend_scan", lambda payload: {
        "rows": [{"ticker": "NVDA", "trend_state": "uptrend"}], "failures": []})
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)

    summary = metrics._core(AssistantConfig())
    assert summary["market_status"] == "green"
    assert summary["vix"] == 15.0
    assert summary["tickers"][0]["ticker"] == "NVDA"


def test_run_goes_through_harness(monkeypatch):
    monkeypatch.setattr(metrics, "_core", lambda config, **kw: {"market_status": "green"})
    captured = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured["task"] = task
        captured.update(kw)
        return {"task": task, "status": "success", "summary": fn()}

    monkeypatch.setattr(metrics, "run_task", fake_run_task)
    out = metrics.run(AssistantConfig())
    assert captured["task"] == "metrics" and out["summary"]["market_status"] == "green"


def test_core_backfill_iterates_weekdays_and_skips_weekend(monkeypatch):
    scans = []
    monkeypatch.setattr(
        metrics, "compute_market_signal_for_date",
        lambda cfg, d, **kw: _signal(d))
    monkeypatch.setattr(
        metrics, "run_ticker_trend_scan",
        lambda payload: scans.append(payload) or {"rows": [], "count": 2, "failures": []})
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)

    # July 3 is an observed holiday; July 4/5 are the weekend.
    summary = metrics._core(AssistantConfig(), start_date=date(2026, 7, 2), end_date=date(2026, 7, 6))
    assert [d["date"] for d in summary["days"]] == ["2026-07-02", "2026-07-06"]
    assert summary["tickers_scanned"] == 4
    assert scans[0]["date"] == "2026-07-02" and scans[0]["mode"] == "metrics"


def test_core_backfill_day_error_does_not_abort(monkeypatch):
    def boom(cfg, d, **kw):
        if d == date(2026, 7, 2):
            raise ValueError("no data")
        return _signal(d)

    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    monkeypatch.setattr(metrics, "compute_market_signal_for_date", boom)
    monkeypatch.setattr(metrics, "_persist_signal", lambda signal: {
        "inserted_count": 1, "skipped_count": 0, "skipped": []})
    monkeypatch.setattr(metrics, "run_ticker_trend_scan",
                        lambda payload: {"rows": [], "count": 0, "failures": []})
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)

    summary = metrics._core(AssistantConfig(), start_date=date(2026, 7, 2), end_date=date(2026, 7, 6))
    assert summary["days"][0] == {"date": "2026-07-02", "error": "no data"}
    assert summary["days"][1]["market_status"] == "green"
    assert len(summary["errors"]) == 1


def test_run_passes_target_dates_to_harness(monkeypatch):
    captured = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured.update(kw)
        return {"run_id": "x", "task": task, "status": "success", "summary": {}}

    monkeypatch.setattr(metrics, "run_task", fake_run_task)
    metrics.run(AssistantConfig(), start_date=date(2026, 6, 1), end_date=date(2026, 6, 5),
                trigger_source="manual")
    assert captured == {
        "target_start_date": date(2026, 6, 1),
        "target_end_date": date(2026, 6, 5),
        "trigger_source": "manual",
    }
