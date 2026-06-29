from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import scheduler


def test_compute_next_run_same_day_when_time_ahead():
    after = datetime(2026, 6, 29, 11, 0, tzinfo=UTC)  # Mon 07:00 ET
    nxt = scheduler.compute_next_run("08:00", "1-5", "America/New_York", after=after)
    local = nxt.astimezone(ZoneInfo("America/New_York"))
    assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 6, 29, 8, 0)


def test_compute_next_run_skips_weekend():
    after = datetime(2026, 6, 26, 18, 0, tzinfo=UTC)  # Fri afternoon ET
    nxt = scheduler.compute_next_run("08:00", "1-5", "America/New_York", after=after)
    local = nxt.astimezone(ZoneInfo("America/New_York"))
    assert local.isoweekday() == 1  # Monday


def test_run_due_jobs_runs_and_reschedules(monkeypatch):
    ran = []
    rescheduled = []
    monkeypatch.setattr(scheduler, "due_scheduled_jobs",
                        lambda conn, *, now: [{"id": 1, "name": "metrics", "time_local": "08:00",
                                               "weekday_mask": "1-5", "timezone": "America/New_York",
                                               "next_run_at": None}])
    monkeypatch.setattr(scheduler, "reschedule_job",
                        lambda conn, name, *, next_run_at, last_run_at: rescheduled.append((name, next_run_at)))
    registry = {"metrics": lambda config: ran.append("metrics") or {"ok": True}}
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    out = scheduler.run_due_jobs(object(), AssistantConfig(), now=now, registry=registry)
    assert ran == ["metrics"]
    assert rescheduled and rescheduled[0][0] == "metrics"
    assert out[0]["name"] == "metrics"


def test_run_due_jobs_unknown_name_records_error(monkeypatch):
    monkeypatch.setattr(scheduler, "due_scheduled_jobs",
                        lambda conn, *, now: [{"id": 9, "name": "ghost", "time_local": "08:00",
                                               "weekday_mask": "1-5", "timezone": "America/New_York",
                                               "next_run_at": None}])
    monkeypatch.setattr(scheduler, "reschedule_job", lambda *a, **k: None)
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    out = scheduler.run_due_jobs(object(), AssistantConfig(), now=now, registry={})
    assert out[0]["status"] == "error" and "unregistered" in out[0]["error"]
