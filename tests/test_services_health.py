from datetime import UTC, datetime, timedelta

import pytest

from investment_assistant.services import health
from investment_assistant.tasks import scheduler


@pytest.fixture(autouse=True)
def isolated_poll_state(monkeypatch):
    monkeypatch.setattr(scheduler, "_last_tick_at", None)
    monkeypatch.setattr(scheduler, "_tick_started_at", None)
    monkeypatch.setattr(scheduler, "_tick_in_progress", False)
    monkeypatch.setattr(scheduler, "_last_tick_failed", None)


def test_check_scheduler_disabled_by_env(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    out = health.check_scheduler()
    assert out["id"] == "scheduler"
    assert out["category"] == "infrastructure"
    assert out["status"] == "degraded"
    assert out["meta"]["enabled"] is False
    assert out["meta"]["reason"] == "env_disabled"
    assert "SCHEDULER_ENABLED=0" in out["detail"]


def test_check_scheduler_disabled_without_database(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = health.check_scheduler()
    assert out["status"] == "degraded"
    assert out["meta"]["enabled"] is False
    assert out["meta"]["reason"] == "database_missing"
    assert "未配置数据库" in out["detail"]
    assert "SCHEDULER_ENABLED=0" not in out["detail"]


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


@pytest.mark.parametrize("first_tick", [True, False])
def test_check_scheduler_long_running_tick_is_not_reported_as_dead(monkeypatch, first_tick):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("SCHEDULER_TICK_SECONDS", "60")
    now = datetime.now(UTC)
    monkeypatch.setattr(scheduler, "_tick_started_at", now - timedelta(seconds=600))
    monkeypatch.setattr(scheduler, "_tick_in_progress", True)
    if not first_tick:
        monkeypatch.setattr(scheduler, "_last_tick_at", now - timedelta(seconds=700))
        monkeypatch.setattr(scheduler, "_last_tick_failed", False)

    out = health.check_scheduler()
    assert out["status"] == "degraded"
    assert "仍在执行" in out["detail"]
    assert "心跳超时" not in out["detail"]
    assert out["meta"]["tick_in_progress"] is True


def test_check_scheduler_recent_failed_tick_is_not_up_and_recovers(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(scheduler, "_last_tick_at", datetime.now(UTC))
    monkeypatch.setattr(scheduler, "_last_tick_failed", True)

    failed = health.check_scheduler()
    assert failed["status"] == "down"
    assert "轮询失败" in failed["detail"]
    assert failed["meta"]["last_tick_failed"] is True

    monkeypatch.setattr(scheduler, "_last_tick_failed", False)
    recovered = health.check_scheduler()
    assert recovered["status"] == "up"
    assert recovered["meta"]["last_tick_failed"] is False


def test_check_scheduler_retry_in_progress_is_not_up(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(scheduler, "_last_tick_at", datetime.now(UTC))
    monkeypatch.setattr(scheduler, "_last_tick_failed", True)
    monkeypatch.setattr(scheduler, "_tick_started_at", datetime.now(UTC))
    monkeypatch.setattr(scheduler, "_tick_in_progress", True)

    out = health.check_scheduler()
    assert out["status"] == "degraded"
    assert "重试" in out["detail"]
    assert out["meta"]["tick_in_progress"] is True


def test_check_scheduler_first_tick_in_progress_is_visible(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(scheduler, "_tick_started_at", datetime.now(UTC))
    monkeypatch.setattr(scheduler, "_tick_in_progress", True)

    out = health.check_scheduler()
    assert out["status"] == "up"
    assert "正在执行" in out["detail"]
    assert out["meta"]["last_tick_at"] is None


def test_check_scheduler_registered_in_checks():
    assert health.check_scheduler in health.CHECKS
