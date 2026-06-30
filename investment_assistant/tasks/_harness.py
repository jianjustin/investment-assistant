from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

from investment_assistant.config import AssistantConfig
from investment_assistant.hermes.run_log import append_run
from investment_assistant.notify.notifier import dispatch


def run_task(task: str, fn: Callable[[], dict[str, Any]], *, config: AssistantConfig) -> dict[str, Any]:
    run_id = f"{task}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC)
    try:
        summary = fn() or {}
        status = "success"
    except Exception as exc:  # 结构化记录，不静默
        summary = {"error": str(exc)}
        status = "error"
    finished_at = datetime.now(UTC)
    _record(task=task, run_id=run_id, status=status, started_at=started_at,
            finished_at=finished_at, summary=summary)
    from investment_assistant.services.settings import effective_notify_config
    dispatch(task, status, summary, effective_notify_config(config.notify))
    return {"run_id": run_id, "task": task, "status": status, "summary": summary}


def _record(*, task: str, run_id: str, status: str, started_at, finished_at, summary: dict[str, Any]) -> None:
    append_run({"type": task, "run_id": run_id, "status": status, "summary": summary})
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return
    from investment_assistant.db import connect, insert_job_report

    with connect(database_url) as conn:
        insert_job_report(conn, task=task, run_id=run_id, status=status,
                          started_at=started_at, finished_at=finished_at, summary=summary)
