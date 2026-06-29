from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.db import connect, due_scheduled_jobs, reschedule_job
from investment_assistant.tasks import filings as filings_task
from investment_assistant.tasks import metrics as metrics_task
from investment_assistant.tasks import nightly_scores as scores_task

logger = logging.getLogger(__name__)

REGISTRY: dict[str, Callable[[AssistantConfig], dict[str, Any]]] = {
    "metrics": metrics_task.run,
    "filings": filings_task.run,
    "scores": scores_task.run,
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


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config(None)
    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    tick_seconds = int(os.environ.get("SCHEDULER_TICK_SECONDS", "60"))
    logger.info("scheduler started; tick=%ss", tick_seconds)
    while True:
        try:
            with connect(database_url) as conn:
                run_due_jobs(conn, config, now=datetime.now(UTC))
        except Exception:  # 主循环兜底，记录后继续
            logger.exception("scheduler tick failed")
        time.sleep(tick_seconds)


if __name__ == "__main__":
    main()
