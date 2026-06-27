import investment_assistant.services.tickers as _tickers
from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register


@register("GET", exact="/api/tickers/trends")
def _trends(path, query, payload):
    rows = _tickers.ticker_trend_rows()
    return ApiResponse({"rows": rows, "count": len(rows)})


@register("POST", exact="/api/tickers/trends/scan")
def _scan(path, query, payload):
    return ApiResponse(_tickers.run_ticker_trend_scan(payload or {}))
