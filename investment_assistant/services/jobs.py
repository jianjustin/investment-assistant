from __future__ import annotations

import os
from datetime import date
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.config import load_config
from investment_assistant.db import connect
from investment_assistant.tasks import runner
from investment_assistant.tasks.scheduler import REGISTRY


def _with_conn(fn: Callable[[Any], Any]) -> Any:
    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    with connect(database_url) as conn:
        return fn(conn)


def _has_db() -> bool:
    return bool(os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"))


def scheduled_jobs() -> dict[str, Any]:
    from investment_assistant.services.health import check_scheduler

    scheduler_status = check_scheduler()
    if not _has_db():
        return {"jobs": [], "degraded": True, "scheduler": scheduler_status}
    return {"jobs": _with_conn(db.list_scheduled_jobs), "degraded": False, "scheduler": scheduler_status}


def job_reports(task: str | None = None, limit: int = 50) -> dict[str, Any]:
    if not _has_db():
        return {"reports": [], "degraded": True}
    reports = _with_conn(lambda conn: db.list_job_reports(conn, task=task, limit=limit))
    return {"reports": reports, "degraded": False}


class UnknownJobError(ValueError):
    """Requested job name is not registered."""


MAX_RANGE_DAYS = 92  # 所有任务共用：一次最多回补约一个季度


def _date_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    raw_date = payload.get("date")
    raw_from = payload.get("from") or payload.get("start_date")
    raw_to = payload.get("to") or payload.get("end_date")
    if raw_date:
        start = end = date.fromisoformat(str(raw_date))
    elif raw_from or raw_to:
        if not raw_from or not raw_to:
            raise ValueError("from and to are both required for a range")
        start = date.fromisoformat(str(raw_from))
        end = date.fromisoformat(str(raw_to))
    else:
        return {}
    if end < start:
        raise ValueError("to must be greater than or equal to from")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValueError(f"date range is limited to {MAX_RANGE_DAYS} days")
    if end > date.today():
        raise ValueError("date must not be in the future")
    return {"start_date": start, "end_date": end}


def trigger_job(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in REGISTRY:
        raise UnknownJobError(f"unknown job: {name}")
    config = load_config()
    kwargs = _date_kwargs(payload or {})
    run_id = runner.submit(name, lambda: REGISTRY[name](config, trigger_source="manual", **kwargs))
    return {"run_id": run_id, "status": "pending"}


def patch_scheduled_job(name: str, *, enabled=None, time_local=None) -> dict[str, Any]:
    if not _has_db():
        return {"updated": False, "degraded": True}
    _with_conn(lambda conn: db.update_scheduled_job(conn, name, enabled=enabled, time_local=time_local))
    return {"updated": True}
