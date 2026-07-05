import threading
import time
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


def test_scheduler_module_has_no_cli_main():
    assert not hasattr(scheduler, "main")  # 独立调度进程入口已删除，防双跑
