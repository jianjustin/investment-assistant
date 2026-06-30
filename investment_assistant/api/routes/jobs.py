from investment_assistant.api.http import ApiResponse, first, parse_int
from investment_assistant.api.router import register
from investment_assistant.services import jobs


@register("GET", exact="/api/jobs/scheduled")
def _scheduled(path, query, payload):
    return ApiResponse(jobs.scheduled_jobs())


@register("GET", exact="/api/jobs/reports")
def _reports(path, query, payload):
    task = first(query, "task")
    limit = parse_int(first(query, "limit"), default=50, minimum=1, maximum=200)
    return ApiResponse(jobs.job_reports(task=task, limit=limit))


@register("GET", exact="/api/jobs/metrics")
def _metrics(path, query, payload):
    task = first(query, "task")
    days = parse_int(first(query, "window"), default=7, minimum=1, maximum=90)
    return ApiResponse(jobs.job_metrics(task=task, days=days))


@register("POST", prefix="/api/jobs/")
def _run(path, query, payload):
    # only handles /api/jobs/{name}/run
    suffix = path.removeprefix("/api/jobs/")
    if not suffix.endswith("/run"):
        return ApiResponse({"error": "not found"}, status=404)
    name = suffix.removesuffix("/run")
    try:
        return ApiResponse(jobs.trigger_job(name))
    except ValueError as exc:
        return ApiResponse({"error": str(exc)}, status=404)


@register("PATCH", prefix="/api/jobs/scheduled/")
def _patch(path, query, payload):
    name = path.removeprefix("/api/jobs/scheduled/")
    body = payload or {}
    return ApiResponse(jobs.patch_scheduled_job(
        name, enabled=body.get("enabled"), time_local=body.get("time_local")
    ))
