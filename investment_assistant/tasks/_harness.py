from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from typing import Any, Callable

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks.run_log import append_run
from investment_assistant.notify.notifier import dispatch


def run_task(
    task: str,
    fn: Callable[[], dict[str, Any]],
    *,
    config: AssistantConfig,
    target_start_date: date | None = None,
    target_end_date: date | None = None,
    trigger_source: str = "scheduled",
    notify: bool = True,
    target_dates_from_summary: bool = False,
) -> dict[str, Any]:
    run_id = f"{task}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC)
    try:
        summary = fn() or {}
        if target_dates_from_summary:
            actual_dates = sorted({date.fromisoformat(str(day)) for day in summary.get("actual_dates", [])})
            summary["actual_dates"] = [day.isoformat() for day in actual_dates]
            target_start_date = actual_dates[0] if actual_dates else None
            target_end_date = actual_dates[-1] if actual_dates else None
            if not actual_dates and not (summary.get("error") or summary.get("errors") or summary.get("failures")):
                summary["error"] = "No actual input dates available; no dated completion can be reported"
        status = "error" if summary.get("error") or summary.get("errors") or summary.get("failures") else "success"
    except Exception as exc:  # 结构化记录，不静默
        summary = {"error": str(exc)}
        if target_dates_from_summary:
            summary["actual_dates"] = []
            target_start_date = target_end_date = None
        status = "error"
    finished_at = datetime.now(UTC)
    _record(task=task, run_id=run_id, status=status, started_at=started_at,
            finished_at=finished_at, summary=summary,
            target_start_date=target_start_date, target_end_date=target_end_date,
            trigger_source=trigger_source)
    if notify:
        from investment_assistant.services.settings import effective_notify_config
        dispatch(task, status, summary, effective_notify_config(config.notify),
                 target_start_date=target_start_date, target_end_date=target_end_date)
    return {"run_id": run_id, "task": task, "status": status, "summary": summary}


def _record(*, task: str, run_id: str, status: str, started_at, finished_at,
            summary: dict[str, Any], target_start_date=None, target_end_date=None,
            trigger_source: str = "scheduled") -> None:
    try:
        append_run({"type": task, "run_id": run_id, "status": status, "summary": summary})
    except OSError as exc:
        summary = {**summary, "run_log_error": str(exc)}
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return
    from investment_assistant.db import connect, insert_job_report

    with connect(database_url) as conn:
        insert_job_report(conn, task=task, run_id=run_id, status=status,
                          started_at=started_at, finished_at=finished_at, summary=summary,
                          target_start_date=target_start_date, target_end_date=target_end_date,
                          trigger_source=trigger_source)
