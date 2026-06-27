import investment_assistant.services.watchlist as _watchlist
from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register


@register("GET", exact="/api/watchlist")
def _list(path, query, payload):
    rows = _watchlist.watchlist_rows()
    return ApiResponse({"rows": rows, "count": len(rows)})


@register("POST", exact="/api/watchlist")
def _add(path, query, payload):
    return ApiResponse({"item": _watchlist.add_watchlist_item(payload or {})})


@register("DELETE", prefix="/api/watchlist/")
def _delete(path, query, payload):
    ticker = path.rsplit("/", 1)[-1]
    return ApiResponse(_watchlist.delete_watchlist_item(ticker))
