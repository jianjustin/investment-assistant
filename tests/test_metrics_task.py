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
    monkeypatch.setattr(metrics, "_core", lambda config: {"market_status": "green"})
    captured = {}

    def fake_run_task(task, fn, *, config):
        captured["task"] = task
        return {"task": task, "status": "success", "summary": fn()}

    monkeypatch.setattr(metrics, "run_task", fake_run_task)
    out = metrics.run(AssistantConfig())
    assert captured["task"] == "metrics" and out["summary"]["market_status"] == "green"
