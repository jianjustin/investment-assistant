from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from investment_assistant import db
from investment_assistant.db import connect


def _parse_date(raw: str | None) -> date | None:
    return date.fromisoformat(str(raw)) if raw else None


def filing_records(*, ticker: str | None = None, form: str | None = None,
                   from_: str | None = None, to: str | None = None,
                   limit: int = 50) -> dict[str, Any]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return {"records": [], "tickers": [], "degraded": True}
    start_date = _parse_date(from_)
    end_date = _parse_date(to)
    with connect(database_url) as conn:
        records = db.list_filings(conn, ticker=ticker or None, form=form or None,
                                  start_date=start_date, end_date=end_date, limit=limit)
        tickers = db.list_filing_tickers(conn)
    return {"records": records, "tickers": tickers, "degraded": False}


def filing_download_path(filing_id: int) -> Path:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        raise LookupError("database is not configured")
    with connect(database_url) as conn:
        row = db.get_filing(conn, filing_id)
    if row is None:
        raise LookupError(f"filing {filing_id} not found")
    path = Path(row["file_path"])
    if not path.is_file():
        raise FileNotFoundError(f"filing file missing: {path}")
    return path
