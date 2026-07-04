from typing import Any

from fastapi import APIRouter, Body

import investment_assistant.services.watchlist as _watchlist

router = APIRouter()


@router.get("/api/watchlist")
def list_items():
    rows = _watchlist.watchlist_rows()
    return {"rows": rows, "count": len(rows)}


@router.post("/api/watchlist")
def add(payload: dict[str, Any] = Body(default_factory=dict)):
    return {"item": _watchlist.add_watchlist_item(payload)}


@router.delete("/api/watchlist/{ticker}")
def delete(ticker: str):
    return _watchlist.delete_watchlist_item(ticker)
