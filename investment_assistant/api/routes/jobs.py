from typing import Any

from fastapi import APIRouter, Body, HTTPException

from investment_assistant.api.http import parse_int
from investment_assistant.services import jobs

router = APIRouter()


@router.get("/api/jobs/scheduled")
def scheduled():
    return jobs.scheduled_jobs()


@router.get("/api/jobs/reports")
def reports(task: str | None = None, limit: str | None = None):
    return jobs.job_reports(task=task, limit=parse_int(limit, default=50, minimum=1, maximum=200))


@router.get("/api/jobs/metrics")
def metrics(task: str | None = None, window: str | None = None):
    return jobs.job_metrics(task=task, days=parse_int(window, default=7, minimum=1, maximum=90))


@router.post("/api/jobs/{name}/run")
def run_job(name: str, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return jobs.trigger_job(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))  # 旧契约：未知任务 404


@router.patch("/api/jobs/scheduled/{name}")
def patch_job(name: str, payload: dict[str, Any] = Body(default_factory=dict)):
    return jobs.patch_scheduled_job(name, enabled=payload.get("enabled"), time_local=payload.get("time_local"))
