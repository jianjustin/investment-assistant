from __future__ import annotations

from datetime import date
from typing import Any


def compare_signal(
    *,
    trend_state: str,
    attention_level: str,
    previous: dict[str, Any] | None,
    has_new_filing: bool,
) -> dict[str, Any]:
    if previous is None:
        if has_new_filing:
            return {"changed": True, "reason": "new_filing"}
        return {"changed": False, "reason": "baseline"}
    state_changed = (
        previous.get("trend_state") != trend_state
        or previous.get("attention_level") != attention_level
    )
    if state_changed:
        return {"changed": True, "reason": "state_changed"}
    if has_new_filing:
        return {"changed": True, "reason": "new_filing"}
    return {"changed": False, "reason": "unchanged"}


def should_research(*, named_by_user: bool, changed: bool) -> bool:
    return named_by_user or changed


def load_signal_change(conn, ticker: str, on_date: date) -> dict[str, Any]:
    current = _one(
        conn,
        """
        SELECT trend_state, attention_level
        FROM ticker_signal_snapshots
        WHERE ticker = %(ticker)s AND signal_date = %(on_date)s
          AND close IS NOT NULL AND error IS NULL
        """,
        {"ticker": ticker, "on_date": on_date},
        ["trend_state", "attention_level"],
    )
    if current is None:
        return {"changed": False, "reason": "snapshot_missing"}
    previous = _one(
        conn,
        """
        SELECT trend_state, attention_level, signal_date
        FROM ticker_signal_snapshots
        WHERE ticker = %(ticker)s AND signal_date < %(on_date)s
          AND close IS NOT NULL AND error IS NULL
        ORDER BY signal_date DESC
        LIMIT 1
        """,
        {"ticker": ticker, "on_date": on_date},
        ["trend_state", "attention_level", "signal_date"],
    )
    filing = _one(
        conn,
        """
        SELECT filing_date
        FROM filings
        WHERE ticker = %(ticker)s AND filing_date = %(on_date)s
        LIMIT 1
        """,
        {"ticker": ticker, "on_date": on_date},
        ["filing_date"],
    )
    result = compare_signal(
        trend_state=current["trend_state"],
        attention_level=current["attention_level"],
        previous=previous,
        has_new_filing=filing is not None,
    )
    if previous is not None:
        result["previous_date"] = str(previous["signal_date"])
    return result


def _one(conn, sql: str, params: dict[str, Any], keys: list[str]) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(keys, row))
