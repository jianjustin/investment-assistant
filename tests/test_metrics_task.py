from types import SimpleNamespace

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import metrics


def test_core_builds_summary(monkeypatch):
    signal = SimpleNamespace(market_status="green", vix_close=15.0, signal_date="2026-06-29")
    monkeypatch.setattr(metrics, "compute_market_signal", lambda cfg, **kw: signal)
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


from datetime import date


def test_core_backfill_iterates_weekdays_and_skips_weekend(monkeypatch):
    scans = []
    monkeypatch.setattr(
        metrics, "compute_market_signal_for_date",
        lambda cfg, d, **kw: SimpleNamespace(market_status="green", signal_date=d))
    monkeypatch.setattr(
        metrics, "run_ticker_trend_scan",
        lambda payload: scans.append(payload) or {"rows": [], "count": 2, "failures": []})
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)

    # 2026-07-03 周五，07-04/05 周末跳过，07-06 周一
    summary = metrics._core(AssistantConfig(), start_date=date(2026, 7, 3), end_date=date(2026, 7, 6))
    assert [d["date"] for d in summary["days"]] == ["2026-07-03", "2026-07-06"]
    assert summary["tickers_scanned"] == 4
    assert scans[0]["date"] == "2026-07-03" and scans[0]["mode"] == "metrics"


def test_core_backfill_day_error_does_not_abort(monkeypatch):
    def boom(cfg, d, **kw):
        if d == date(2026, 7, 3):
            raise ValueError("no data")
        return SimpleNamespace(market_status="green", signal_date=d)

    monkeypatch.setattr(metrics, "compute_market_signal_for_date", boom)
    monkeypatch.setattr(metrics, "run_ticker_trend_scan",
                        lambda payload: {"rows": [], "count": 0, "failures": []})
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)

    summary = metrics._core(AssistantConfig(), start_date=date(2026, 7, 3), end_date=date(2026, 7, 6))
    assert summary["days"][0] == {"date": "2026-07-03", "error": "no data"}
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
