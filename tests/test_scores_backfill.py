from datetime import date

from investment_assistant.config import AssistantConfig
from investment_assistant.services import strategies
from investment_assistant.tasks import nightly_scores


def test_scan_passes_date_to_snapshot_query(monkeypatch):
    seen = {}

    def fake_snapshots(signal_date=None):
        seen["signal_date"] = signal_date
        return []

    monkeypatch.setattr(strategies, "strategy_input_snapshots", fake_snapshots)
    monkeypatch.setattr(strategies, "latest_strategy_market_context",
                        lambda: {"macro_state": "neutral"})
    out = strategies.run_strategy_score_scan({"mode": "backfill", "date": "2026-06-15"})
    assert seen["signal_date"] == date(2026, 6, 15)
    assert out["count"] == 0


def test_scores_core_backfill_aggregates_days(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "investment_assistant.services.strategies.run_strategy_score_scan",
        lambda payload: calls.append(payload) or {"count": 3, "failures": [], "rows": []})

    # July 3 is the observed Independence Day holiday, not a trading session.
    summary = nightly_scores._core(
        AssistantConfig(), start_date=date(2026, 7, 2), end_date=date(2026, 7, 6))
    assert [d["date"] for d in summary["days"]] == ["2026-07-02", "2026-07-06"]
    assert summary["total"] == 6
    assert calls[0]["date"] == "2026-07-02"
    assert [d["date"] for d in summary["skipped"]] == ["2026-07-03", "2026-07-04", "2026-07-05"]
    assert "宏观" in summary["note"]


def test_scores_run_passes_target_dates(monkeypatch):
    captured = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured.update(kw)
        return {"status": "success"}

    monkeypatch.setattr(nightly_scores, "run_task", fake_run_task)
    nightly_scores.run(AssistantConfig(), start_date=date(2026, 6, 1),
                       end_date=date(2026, 6, 5), trigger_source="manual")
    assert captured["target_start_date"] == date(2026, 6, 1)
    assert captured["trigger_source"] == "manual"
