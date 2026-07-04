from typing import Any

from fastapi import APIRouter, Body

import investment_assistant.services.tickers as _tickers

router = APIRouter()


@router.get("/api/tickers/trends")
def trends():
    rows = _tickers.ticker_trend_rows()
    return {"rows": rows, "count": len(rows)}


@router.post("/api/tickers/trends/scan")
def scan(payload: dict[str, Any] = Body(default_factory=dict)):
    return _tickers.run_ticker_trend_scan(payload)
