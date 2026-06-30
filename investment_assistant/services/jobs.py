from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
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
    if not _has_db():
        return {"jobs": [], "degraded": True}
    return {"jobs": _with_conn(db.list_scheduled_jobs), "degraded": False}


def job_reports(task: str | None = None, limit: int = 50) -> dict[str, Any]:
    if not _has_db():
        return {"reports": [], "degraded": True}
    reports = _with_conn(lambda conn: db.list_job_reports(conn, task=task, limit=limit))
    return {"reports": reports, "degraded": False}


def job_metrics(task: str | None = None, days: int = 7) -> dict[str, Any]:
    if not _has_db():
        return {"metrics": [], "degraded": True}
    since = datetime.now(UTC) - timedelta(days=days)
    metrics = _with_conn(lambda conn: db.job_report_metrics(conn, task=task, since=since))
    return {"metrics": metrics, "degraded": False}


def trigger_job(name: str) -> dict[str, Any]:
    if name not in REGISTRY:
        raise ValueError(f"unknown job: {name}")
    config = load_config()
    run_id = runner.submit(name, lambda: REGISTRY[name](config))
    return {"run_id": run_id, "status": "pending"}


def patch_scheduled_job(name: str, *, enabled=None, time_local=None) -> dict[str, Any]:
    if not _has_db():
        return {"updated": False, "degraded": True}
    _with_conn(lambda conn: db.update_scheduled_job(conn, name, enabled=enabled, time_local=time_local))
    return {"updated": True}
