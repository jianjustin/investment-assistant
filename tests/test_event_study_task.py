from datetime import date

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import event_study


def test_core_aggregates_kinds(monkeypatch):
    from investment_assistant.research.event_study import Event

    monkeypatch.setattr(event_study, "collect_events",
                        lambda kind, **kw: [Event("NVDA", date(2024, 3, 1), kind)])

    def fake_run(events, **kw):
        from investment_assistant.research.event_study import EventStudyResult
        from datetime import UTC, datetime
        return EventStudyResult(
            kind=events[0].kind, n=1, horizons={}, by_regime={},
            caveats=["n<30, 结论不可信"], generated_at=datetime.now(UTC),
            params={"skipped": []},
        )

    monkeypatch.setattr(event_study, "run_event_study", fake_run)
    summary = event_study._core(AssistantConfig(), kinds=["rs_strong"])
    assert "rs_strong" in summary["results"]
    assert summary["results"]["rs_strong"]["n"] == 1
    assert summary["params"]["kinds"] == ["rs_strong"]


def test_core_passes_asof_for_replay(monkeypatch):
    seen = {}

    def fake_collect(kind, *, asof=None, since=None, config=None, **kw):
        seen["asof"] = asof
        seen["since"] = since
        return []

    monkeypatch.setattr(event_study, "collect_events", fake_collect)
    event_study._core(AssistantConfig(), asof=date(2024, 3, 1), since=date(2022, 1, 1),
                      kinds=["rs_strong"])
    assert seen["asof"] == date(2024, 3, 1)
    assert seen["since"] == date(2022, 1, 1)


def test_run_goes_through_harness(monkeypatch):
    monkeypatch.setattr(event_study, "_core", lambda config, **kw: {"results": {}})
    captured = {}

    def fake_run_task(task, fn, *, config):
        captured["task"] = task
        return {"task": task, "status": "success", "summary": fn()}

    monkeypatch.setattr(event_study, "run_task", fake_run_task)
    out = event_study.run(AssistantConfig())
    assert captured["task"] == "event_study"
    assert out["status"] == "success"


def test_registered_in_scheduler():
    from investment_assistant.tasks.scheduler import REGISTRY
    assert "event_study" in REGISTRY
