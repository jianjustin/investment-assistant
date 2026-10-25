import threading
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import scheduler


@pytest.fixture(autouse=True)
def isolated_poll_state(monkeypatch):
    monkeypatch.setattr(scheduler, "_last_tick_at", None)
    monkeypatch.setattr(scheduler, "_tick_started_at", None)
    monkeypatch.setattr(scheduler, "_tick_in_progress", False)
    monkeypatch.setattr(scheduler, "_last_tick_failed", None)


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


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_run_forever_ticks_and_stops_via_stop_event(monkeypatch):
    ticks = []
    monkeypatch.setattr(scheduler, "connect", lambda url: _FakeConn())
    monkeypatch.setattr(scheduler, "run_due_jobs",
                        lambda conn, config, *, now: ticks.append(now) or [])
    stop = threading.Event()
    t = threading.Thread(
        target=scheduler.run_forever,
        kwargs={"stop_event": stop, "database_url": "postgresql://fake",
                "config": AssistantConfig(), "tick_seconds": 0.01},
        daemon=True,
    )
    t.start()
    for _ in range(200):  # 最多等 1s，等到第一个 tick
        if ticks:
            break
        time.sleep(0.005)
    stop.set()
    t.join(timeout=1)
    assert not t.is_alive()
    assert ticks
    assert scheduler.last_tick_at() is not None


def test_run_forever_survives_tick_exception(monkeypatch):
    calls = []

    def _boom(url):
        calls.append(1)
        raise RuntimeError("db down")

    monkeypatch.setattr(scheduler, "connect", _boom)
    stop = threading.Event()
    t = threading.Thread(
        target=scheduler.run_forever,
        kwargs={"stop_event": stop, "database_url": "postgresql://fake",
                "config": AssistantConfig(), "tick_seconds": 0.01},
        daemon=True,
    )
    t.start()
    for _ in range(200):  # 等到第 2 次调用，证明首次异常没有终止循环
        if len(calls) >= 2:
            break
        time.sleep(0.005)
    stop.set()
    t.join(timeout=1)
    assert len(calls) >= 2
    assert not t.is_alive()
    state = scheduler.poll_state()
    assert state["last_tick_at"] is not None
    assert state["last_tick_failed"] is True
    assert state["in_progress"] is False


class _StopAfterTicks:
    def __init__(self, count):
        self.count = count
        self.snapshots = []

    def is_set(self):
        return len(self.snapshots) >= self.count

    def wait(self, timeout):
        self.snapshots.append(scheduler.poll_state())


def test_poll_state_tracks_first_tick_before_it_finishes(monkeypatch):
    during = []
    monkeypatch.setattr(scheduler, "connect", lambda url: _FakeConn())
    monkeypatch.setattr(scheduler, "run_due_jobs",
                        lambda conn, config, *, now: during.append(scheduler.poll_state()) or [])
    stop = _StopAfterTicks(1)
    scheduler.run_forever(stop, database_url="postgresql://fake", config=AssistantConfig())

    assert during[0]["in_progress"] is True
    assert during[0]["started_at"] is not None
    assert during[0]["last_tick_at"] is None
    assert during[0]["last_tick_failed"] is None
    completed = stop.snapshots[0]
    assert completed["in_progress"] is False
    assert completed["last_tick_failed"] is False
    assert completed["started_at"] <= completed["last_tick_at"]
    assert scheduler.last_tick_at() == completed["last_tick_at"]

    completed["in_progress"] = True
    assert scheduler.poll_state()["in_progress"] is False


def test_poll_state_retains_failure_until_retry_succeeds(monkeypatch):
    attempts = []
    during_retry = []

    def connect(url):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("private connection details")
        return _FakeConn()

    monkeypatch.setattr(scheduler, "connect", connect)
    monkeypatch.setattr(scheduler, "run_due_jobs",
                        lambda conn, config, *, now: during_retry.append(scheduler.poll_state()) or [])
    stop = _StopAfterTicks(2)
    scheduler.run_forever(stop, database_url="postgresql://fake", config=AssistantConfig())

    failed, recovered = stop.snapshots
    assert failed["last_tick_at"] is not None
    assert failed["last_tick_failed"] is True
    assert failed["in_progress"] is False
    assert "private connection details" not in repr(failed)
    assert during_retry[0]["last_tick_failed"] is True
    assert during_retry[0]["in_progress"] is True
    assert recovered["last_tick_failed"] is False
    assert recovered["in_progress"] is False


def test_scheduler_module_has_no_cli_main():
    assert not hasattr(scheduler, "main")  # 独立调度进程入口已删除，防双跑


def test_registry_has_workbench_review():
    from investment_assistant.tasks import scheduler
    assert scheduler.REGISTRY['workbench_review'] is not None


def test_registry_has_no_ashares():
    assert 'ashares' not in scheduler.REGISTRY


def test_removed_jobs_are_skipped_and_rescheduled(monkeypatch):
    rescheduled = []
    monkeypatch.setattr(scheduler, "due_scheduled_jobs",
                        lambda conn, *, now: [{"name": "metrics", "time_local": "08:00",
                                               "weekday_mask": "1-5", "timezone": "America/New_York"}])
    monkeypatch.setattr(scheduler, "reschedule_job",
                        lambda conn, name, next_run_at, last_run_at: rescheduled.append(name))
    out = scheduler.run_due_jobs(None, AssistantConfig(), now=datetime(2026, 6, 29, 11, 0, tzinfo=UTC))
    # A legacy row in scheduled_jobs must not crash the tick: warn, record, reschedule.
    assert out == [{"name": "metrics", "status": "error", "error": "unregistered job"}]
    assert rescheduled == ["metrics"]
