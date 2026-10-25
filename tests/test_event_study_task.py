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
    summary = event_study._core(AssistantConfig(), kinds=["score_high"])
    assert "score_high" in summary["results"]
    assert summary["results"]["score_high"]["n"] == 1
    assert summary["params"]["kinds"] == ["score_high"]


def test_core_passes_asof_for_replay(monkeypatch):
    seen = {}

    def fake_collect(kind, *, asof=None, since=None, config=None, **kw):
        seen["asof"] = asof
        seen["since"] = since
        return []

    monkeypatch.setattr(event_study, "collect_events", fake_collect)
    summary = event_study._core(AssistantConfig(), asof=date(2024, 3, 1), since=date(2022, 1, 1),
                                kinds=["score_high"])
    assert seen["asof"] == date(2024, 3, 1)
    assert seen["since"] == date(2022, 1, 1)
    assert summary["results"]["score_high"]["params"]["asof"] == "2024-03-01"


def test_run_goes_through_harness(monkeypatch):
    monkeypatch.setattr(event_study, "_core", lambda config, **kw: {"results": {}})
    captured = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured["task"] = task
        return {"task": task, "status": "success", "summary": fn()}

    monkeypatch.setattr(event_study, "run_task", fake_run_task)
    out = event_study.run(AssistantConfig())
    assert captured["task"] == "event_study"
    assert out["status"] == "success"


def test_registered_in_scheduler():
    from investment_assistant.tasks.scheduler import REGISTRY
    assert "event_study" in REGISTRY


def test_run_maps_start_end_to_since_asof(monkeypatch):
    from datetime import date

    from investment_assistant.config import AssistantConfig
    from investment_assistant.tasks import event_study

    captured = {}
    core_args = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured.update(kw)
        fn()
        return {"status": "success"}

    monkeypatch.setattr(event_study, "run_task", fake_run_task)
    monkeypatch.setattr(event_study, "_core",
                        lambda config, **kw: core_args.update(kw) or {})
    event_study.run(AssistantConfig(), start_date=date(2026, 1, 1),
                    end_date=date(2026, 6, 30), trigger_source="manual")
    assert core_args == {"asof": date(2026, 6, 30), "since": date(2026, 1, 1)}
    assert captured["trigger_source"] == "manual"


def test_task_run_accepts_explicit_asof_and_records_effective_cutoff(monkeypatch):
    captured, core_args = {}, {}
    monkeypatch.setattr(event_study, "run_task", lambda task, fn, **kw: captured.update(kw) or fn())
    monkeypatch.setattr(event_study, "_core", lambda config, **kw: core_args.update(kw) or {})
    event_study.run(AssistantConfig(), asof=date(2024, 3, 8))
    assert core_args["asof"] == captured["target_end_date"] == date(2024, 3, 8)
    assert captured["target_start_date"] == date(2024, 3, 8)


def test_task_conflicting_end_date_and_asof_rejected():
    import pytest
    with pytest.raises(ValueError, match="asof.*end_date"):
        event_study.run(AssistantConfig(), asof=date(2024, 3, 8), end_date=date(2024, 3, 7))


def test_default_task_excludes_unavailable_definitions_and_resolves_cutoff(monkeypatch):
    calls = []
    monkeypatch.setattr(event_study, "resolve_asof", lambda asof: asof or date(2024, 3, 8))
    monkeypatch.setattr(event_study, "collect_events", lambda kind, **kw: calls.append((kind, kw)) or [])
    result = event_study._core(AssistantConfig())
    assert result["params"]["asof"] == "2024-03-08"
    assert result["params"]["horizons"] == [5, 10, 20]
    assert {kind for kind, kw in calls} == {"ma_reclaim", "score_high"}
    assert all(kw["asof"] == date(2024, 3, 8) for kind, kw in calls)


def test_cli_asof_reaches_engine_in_no_record_mode(monkeypatch, capsys):
    import json
    monkeypatch.setattr("sys.argv", ["event-study", "--no-record", "--kind", "score_high",
                                     "--asof", "2024-03-08", "--since", "2023-01-01"])
    monkeypatch.setattr(event_study, "collect_events", lambda *a, **kw: [])
    monkeypatch.setattr(event_study, "run_task", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no record")))
    event_study.main()
    summary = json.loads(capsys.readouterr().out)["summary"]
    assert summary["params"]["asof"] == "2024-03-08"
    assert summary["results"]["score_high"]["params"]["asof"] == "2024-03-08"


def test_explicit_unavailable_task_kind_raises_not_empty_success():
    import pytest
    with pytest.raises(ValueError, match="unavailable"):
        event_study._core(AssistantConfig(), kinds=["eps_beat"])


def test_task_source_unavailable_has_errors_not_zero_results():
    summary = event_study._core(AssistantConfig(), asof=date(2024, 3, 8))
    assert summary["results"] == {}
    assert summary["degraded"] is True
    assert set(summary["errors"]) == {"ma_reclaim", "score_high"}
    assert all(e["code"] == "database_unconfigured" for e in summary["errors"].values())


def test_task_source_error_reaches_harness_error_status_without_real_record_or_notify(monkeypatch):
    from investment_assistant.tasks import _harness
    from investment_assistant.services import settings
    monkeypatch.setattr(_harness, "_record", lambda **kw: None)
    monkeypatch.setattr(_harness, "dispatch", lambda *a, **kw: None)
    monkeypatch.setattr(settings, "effective_notify_config", lambda cfg: cfg)
    out = event_study.run(AssistantConfig(), asof=date(2024, 3, 8))
    assert out["status"] == "error"
    assert out["summary"]["errors"]["ma_reclaim"]["code"] == "database_unconfigured"


def test_task_legacy_only_source_reports_exclusion_not_signal_ineffectiveness(monkeypatch):
    from investment_assistant.research import event_sources
    monkeypatch.setattr(event_sources, "_default_snapshot_source", lambda: [
        {"ticker": "AAA", "signal_date": date(2024, 3, 4), "close": 100, "ma20": 99,
         "prev_close": 98, "prev_ma20": 99}
    ])
    summary = event_study._core(AssistantConfig(), asof=date(2024, 3, 8), kinds=["ma_reclaim"])
    assert summary["degraded"] is True
    assert summary["errors"]["ma_reclaim"]["code"] == "source_quality_excluded"
    assert summary["results"]["ma_reclaim"]["params"]["source_quality"]["excluded_count"] == 1
