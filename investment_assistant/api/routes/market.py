import investment_assistant.services.market as _market
import investment_assistant.services.status as _status
from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register


@register("GET", exact="/api/market/signals")
def _signals(path, query, payload):
    rows = _market.market_signal_rows(query)
    return ApiResponse({"rows": rows, "count": len(rows)})


@register("GET", exact="/api/market/signals/latest")
def _latest(path, query, payload):
    return ApiResponse(_status.database_status().get("latest_market_signal"))


@register("GET", exact="/api/market/signals/trend")
def _trend(path, query, payload):
    return ApiResponse(_market.market_signal_trend(query))


@register("POST", exact="/api/market/signals/fetch")
def _fetch(path, query, payload):
    return ApiResponse(_market.fetch_market_signals(payload or {}))
