from datetime import UTC, datetime, timedelta

from investment_assistant.services import health
from investment_assistant.tasks import scheduler


def test_check_scheduler_disabled_by_env(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    out = health.check_scheduler()
    assert out["id"] == "scheduler"
    assert out["category"] == "infrastructure"
    assert out["status"] == "degraded"
    assert out["meta"]["enabled"] is False


def test_check_scheduler_disabled_without_database(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = health.check_scheduler()
    assert out["status"] == "degraded"
    assert out["meta"]["enabled"] is False


def test_check_scheduler_enabled_but_no_tick_yet(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(scheduler, "_last_tick_at", None)
    out = health.check_scheduler()
    assert out["status"] == "degraded"
    assert out["meta"]["last_tick_at"] is None


def test_check_scheduler_running(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(scheduler, "_last_tick_at", datetime.now(UTC))
    out = health.check_scheduler()
    assert out["status"] == "up"


def test_check_scheduler_stale_tick_reports_down(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("SCHEDULER_TICK_SECONDS", "60")
    monkeypatch.setattr(scheduler, "_last_tick_at",
                        datetime.now(UTC) - timedelta(seconds=600))
    out = health.check_scheduler()
    assert out["status"] == "down"


def test_check_scheduler_registered_in_checks():
    assert health.check_scheduler in health.CHECKS
