from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

import investment_assistant.services.tickers as _tickers

router = APIRouter()


@router.get("/api/tickers/trends")
def trends():
    rows = _tickers.ticker_trend_rows()
    return {"rows": rows, "count": len(rows)}


@router.post("/api/tickers/trends/scan")
def scan(payload: dict[str, Any] = Body(default_factory=dict)):
    return _tickers.run_ticker_trend_scan(payload)


@router.get("/api/tickers/{ticker}/ohlcv")
def ohlcv(ticker: str, days: int = Query(default=250, ge=30, le=400)):
    try:
        return _tickers.ohlcv_series(ticker, days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
