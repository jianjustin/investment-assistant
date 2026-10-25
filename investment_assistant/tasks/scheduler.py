from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from investment_assistant.config import AssistantConfig
from investment_assistant.db import connect, due_scheduled_jobs, reschedule_job
from investment_assistant.tasks import event_study as event_study_task
from investment_assistant.tasks import filings as filings_task
from investment_assistant.tasks import metrics as metrics_task
from investment_assistant.tasks import nightly_scores as scores_task
from investment_assistant.tasks import ashares as ashares_task
from investment_assistant.tasks import workbench as workbench_task
from investment_assistant.tasks import workbench_review as workbench_review_task

logger = logging.getLogger(__name__)

REGISTRY: dict[str, Callable[[AssistantConfig], dict[str, Any]]] = {
    "ashares": ashares_task.run,
    "metrics": metrics_task.run,
    "filings": filings_task.run,
    "scores": scores_task.run,
    "event_study": event_study_task.run,
    "workbench": workbench_task.run,
    "workbench_review": workbench_review_task.run,
}


def _parse_weekday_mask(mask: str) -> set[int]:
    days: set[int] = set()
    for part in str(mask).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            days.update(range(int(a), int(b) + 1))
        else:
            days.add(int(part))
    return days


def compute_next_run(time_local: str, weekday_mask: str, timezone: str, *, after: datetime) -> datetime:
    tz = ZoneInfo(timezone)
    hh, mm = (int(x) for x in time_local.split(":"))
    days = _parse_weekday_mask(weekday_mask)
    after_local = after.astimezone(tz)
    for offset in range(0, 8):
        cand_day = (after_local + timedelta(days=offset)).date()
        if cand_day.isoweekday() not in days:
            continue
        cand = datetime(cand_day.year, cand_day.month, cand_day.day, hh, mm, tzinfo=tz)
        if cand > after_local:
            return cand.astimezone(UTC)
    raise ValueError(f"no matching weekday in mask {weekday_mask!r}")


def run_due_jobs(conn, config: AssistantConfig, *, now: datetime, registry=REGISTRY) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for job in due_scheduled_jobs(conn, now=now):
        name = job["name"]
        fn = registry.get(name)
        if fn is None:
            logger.warning("scheduled job %s is not registered; skipping", name)
            results.append({"name": name, "status": "error", "error": "unregistered job"})
        else:
            try:
                outcome = fn(config)
                results.append({"name": name, "status": outcome.get("status", "success")})
            except Exception as exc:  # 任务自身异常已被 harness 记录；这里兜底不中断循环
                logger.exception("scheduled job %s crashed", name)
                results.append({"name": name, "status": "error", "error": str(exc)})
        next_run_at = compute_next_run(job["time_local"], job["weekday_mask"], job["timezone"], after=now)
        reschedule_job(conn, name, next_run_at=next_run_at, last_run_at=now)
    return results


_last_tick_at: datetime | None = None
_tick_started_at: datetime | None = None
_tick_in_progress = False
_last_tick_failed: bool | None = None
_poll_state_lock = threading.Lock()


def last_tick_at() -> datetime | None:
    """最近一次调度 tick 完成时间（UTC）；线程尚未跑过则为 None，供 health 心跳用。"""
    with _poll_state_lock:
        return _last_tick_at


def poll_state() -> dict[str, Any]:
    """只读轮询快照；失败仅暴露标记，不返回可能含凭据的异常内容。"""
    with _poll_state_lock:
        return {
            "started_at": _tick_started_at,
            "in_progress": _tick_in_progress,
            "last_tick_at": _last_tick_at,
            "last_tick_failed": _last_tick_failed,
        }


def run_forever(stop_event, *, database_url: str, config: AssistantConfig,
                tick_seconds: float = 60) -> None:
    """调度循环：驻留 API 进程的守护线程入口，stop_event 置位后在一个 tick 内退出。"""
    global _last_tick_at, _tick_started_at, _tick_in_progress, _last_tick_failed
    logger.info("scheduler thread started; tick=%ss", tick_seconds)
    while not stop_event.is_set():
        with _poll_state_lock:
            _tick_started_at = datetime.now(UTC)
            _tick_in_progress = True
        failed = True
        try:
            with connect(database_url) as conn:
                run_due_jobs(conn, config, now=datetime.now(UTC))
            failed = False
        except Exception:  # 主循环兜底，记录后继续
            logger.exception("scheduler tick failed")
        finally:
            with _poll_state_lock:
                _last_tick_at = datetime.now(UTC)
                _tick_in_progress = False
                _last_tick_failed = failed
        stop_event.wait(tick_seconds)
