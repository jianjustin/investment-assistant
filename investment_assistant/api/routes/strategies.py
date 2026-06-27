import investment_assistant.services.strategies as _strategies
from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register


@register("GET", exact="/api/strategies/scores")
def _scores(path, query, payload):
    rows = _strategies.strategy_score_rows()
    return ApiResponse({"rows": rows, "count": len(rows)})


@register("POST", exact="/api/strategies/scores/run")
def _run(path, query, payload):
    return ApiResponse(_strategies.run_strategy_score_scan(payload or {}))
