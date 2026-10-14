from __future__ import annotations

from datetime import date
from typing import Any


def assess_fact(
    *,
    on_date: date,
    ticker: str,
    market: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    filings_report: dict[str, Any] | None,
    score: dict[str, Any] | None,
) -> dict[str, Any]:
    if on_date.weekday() >= 5:
        return {"ready": False, "blocked": False, "reason": "weekend"}
    if market is None:
        return {"ready": False, "blocked": True, "reason": "market_missing"}
    if snapshot is None:
        return {"ready": False, "blocked": True, "reason": "snapshot_missing"}
    if snapshot.get("error"):
        return {"ready": False, "blocked": True, "reason": "snapshot_error"}
    if snapshot.get("close") is None:
        return {"ready": False, "blocked": True, "reason": "price_missing"}
    if filings_report is None or filings_report.get("status") != "success":
        return {"ready": False, "blocked": True, "reason": "filings_incomplete"}
    errors = (filings_report.get("summary") or {}).get("errors") or {}
    if ticker in errors:
        return {"ready": False, "blocked": True, "reason": "filings_ticker_error"}
    if score is None:
        return {"ready": False, "blocked": True, "reason": "score_missing"}
    return {"ready": True, "blocked": False, "reason": "complete"}


def load_fact(conn, ticker: str, on_date: date) -> dict[str, Any]:
    market = _one(
        conn,
        """
        SELECT market_status
        FROM market_signals
        WHERE signal_date = %(on_date)s
        """,
        {"on_date": on_date},
        ["market_status"],
    )
    snapshot = _one(
        conn,
        """
        SELECT close, error
        FROM ticker_signal_snapshots
        WHERE ticker = %(ticker)s AND signal_date = %(on_date)s
        """,
        {"ticker": ticker, "on_date": on_date},
        ["close", "error"],
    )
    filings_report = _one(
        conn,
        """
        SELECT status, summary
        FROM job_reports
        WHERE task = 'filings'
          AND target_start_date <= %(on_date)s
          AND target_end_date >= %(on_date)s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"on_date": on_date},
        ["status", "summary"],
    )
    score = _one(
        conn,
        """
        SELECT score
        FROM strategy_scores
        WHERE ticker = %(ticker)s AND score_date = %(on_date)s
        LIMIT 1
        """,
        {"ticker": ticker, "on_date": on_date},
        ["score"],
    )
    return assess_fact(
        on_date=on_date,
        ticker=ticker,
        market=market,
        snapshot=snapshot,
        filings_report=filings_report,
        score=score,
    )


def _one(conn, sql: str, params: dict[str, Any], keys: list[str]) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(keys, row))
