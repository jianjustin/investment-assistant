from typing import Any

from fastapi import APIRouter, Body, HTTPException

import investment_assistant.services.watchlist as _watchlist

router = APIRouter()


@router.get("/api/watchlist")
def list_items(enriched: bool = False):
    rows = _watchlist.watchlist_rows(enriched=enriched) if enriched else _watchlist.watchlist_rows()
    return {"rows": rows, "count": len(rows)}


@router.get("/api/watchlist/resolve")
def resolve(symbol: str):
    return {"candidates": _watchlist.resolve_candidates(symbol)}


@router.post("/api/watchlist")
def add(payload: dict[str, Any] = Body(default_factory=dict)):
    from investment_assistant.db import WatchlistConflict
    try:
        return {"item": _watchlist.add_watchlist_item(payload)}
    except WatchlistConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/api/watchlist/{ticker}")
def delete(ticker: str):
    return _watchlist.delete_watchlist_item(ticker)
