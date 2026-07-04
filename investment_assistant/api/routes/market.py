from typing import Any

from fastapi import APIRouter, Body, Depends

import investment_assistant.services.market as _market
import investment_assistant.services.status as _status
from investment_assistant.api.params import query_lists

router = APIRouter()


@router.get("/api/market/signals")
def signals(query: dict[str, list[str]] = Depends(query_lists)):
    rows = _market.market_signal_rows(query)
    return {"rows": rows, "count": len(rows)}


@router.get("/api/market/signals/latest")
def latest():
    return _status.database_status().get("latest_market_signal")


@router.get("/api/market/signals/trend")
def trend(query: dict[str, list[str]] = Depends(query_lists)):
    return _market.market_signal_trend(query)


@router.post("/api/market/signals/fetch")
def fetch(payload: dict[str, Any] = Body(default_factory=dict)):
    return _market.fetch_market_signals(payload)
