from __future__ import annotations

import os
from typing import Any

from investment_assistant.api.http import parse_payload_tags
from investment_assistant.config import load_config
from investment_assistant.db import connect, delete_watchlist_item as db_delete_watchlist_item, list_watchlist_items, upsert_watchlist_item


def watchlist_rows() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return _config_watchlist_rows()
    try:
        with connect(database_url) as conn:
            return list_watchlist_items(conn)
    except Exception:
        return _config_watchlist_rows()


def current_watchlist() -> list[str]:
    rows = watchlist_rows()
    active = [str(row.get("ticker", "")).upper() for row in rows if row.get("status", "active") == "active" and row.get("ticker")]
    return active or list(load_config().watchlist)


def add_watchlist_item(payload: dict[str, Any]) -> dict[str, Any]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        raise ValueError("INVESTMENT_ASSISTANT_DATABASE_URL missing")
    ticker = str(payload.get("ticker", ""))
    status = str(payload.get("status") or "active")
    thesis = str(payload.get("thesis") or "").strip() or None
    tags = parse_payload_tags(payload.get("tags"))
    with connect(database_url) as conn:
        return upsert_watchlist_item(conn, ticker=ticker, status=status, thesis=thesis, tags=tags)


def delete_watchlist_item(ticker: str) -> dict[str, Any]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        raise ValueError("INVESTMENT_ASSISTANT_DATABASE_URL missing")
    with connect(database_url) as conn:
        return db_delete_watchlist_item(conn, ticker)


def _config_watchlist_rows() -> list[dict[str, Any]]:
    return [{"ticker": ticker, "status": "active", "thesis": "来自配置文件的默认标的", "tags": [], "source": "config"} for ticker in load_config().watchlist]
