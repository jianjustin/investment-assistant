from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register
from investment_assistant.tasks import runner


@register("GET", prefix="/api/runs/")
def _get_run(path, query, payload):
    run_id = path.removeprefix("/api/runs/")
    rec = runner.get(run_id)
    if rec is None:
        return ApiResponse({"error": "unknown run"}, status=404)
    return ApiResponse(rec)
