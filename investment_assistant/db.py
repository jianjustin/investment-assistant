from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_POOLS: dict[str, Any] = {}
_POOLS_LOCK = threading.Lock()


def _get_pool(database_url: str):
    with _POOLS_LOCK:
        pool = _POOLS.get(database_url)
        if pool is None:
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(
                database_url,
                min_size=1,
                max_size=int(os.environ.get("INVESTMENT_ASSISTANT_DB_POOL_MAX", "8")),
                open=True,
            )
            _POOLS[database_url] = pool
        return pool


def connect(database_url: str):
    """Return a pooled connection context manager.

    Usage is unchanged from the old per-call psycopg.connect:
        with connect(url) as conn:
            ...
    On exit the connection is returned to the process-wide pool instead of
    being closed.
    """
    return _get_pool(database_url).connection()


def _reset_pools() -> None:
    """Test helper: drop cached pools (closing them best-effort)."""
    with _POOLS_LOCK:
        for pool in _POOLS.values():
            try:
                pool.close()
            except Exception:
                pass
        _POOLS.clear()


def apply_migration(conn, sql_path: str | Path) -> None:
    sql = Path(sql_path).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _ensure_migration_ledger(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              filename TEXT PRIMARY KEY,
              applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def applied_migrations(conn) -> set[str]:
    _ensure_migration_ledger(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_pending_migrations(conn, migrations_dir: str | Path) -> list[str]:
    """Apply every ``*.sql`` in ``migrations_dir`` not yet recorded, in order.

    Records each in ``schema_migrations`` so re-runs are no-ops and the suite
    supports ``ALTER``/data migrations (not only ``CREATE ... IF NOT EXISTS``).
    Returns the filenames that were applied this call.
    """
    done = applied_migrations(conn)
    applied: list[str] = []
    for sql_path in sorted(Path(migrations_dir).glob("*.sql")):
        if sql_path.name in done:
            continue
        sql = sql_path.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING",
                (sql_path.name,),
            )
        conn.commit()
        applied.append(sql_path.name)
    return applied


def upsert_market_signal(conn, signal) -> None:
    payload = _signal_payload(signal)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market_signals (
              signal_date, market_status, spy_ticker, spy_close, spy_ma200,
              spy_above_200ma, vix_ticker, vix_close, source, details, run_id
            ) VALUES (
              %(signal_date)s, %(market_status)s, %(spy_ticker)s, %(spy_close)s, %(spy_ma200)s,
              %(spy_above_200ma)s, %(vix_ticker)s, %(vix_close)s, %(source)s, %(details)s, %(run_id)s
            )
            ON CONFLICT (signal_date) DO UPDATE SET
              market_status = EXCLUDED.market_status,
              spy_ticker = EXCLUDED.spy_ticker,
              spy_close = EXCLUDED.spy_close,
              spy_ma200 = EXCLUDED.spy_ma200,
              spy_above_200ma = EXCLUDED.spy_above_200ma,
              vix_ticker = EXCLUDED.vix_ticker,
              vix_close = EXCLUDED.vix_close,
              source = EXCLUDED.source,
              details = EXCLUDED.details,
              run_id = EXCLUDED.run_id,
              updated_at = now()
            """,
            payload,
        )
    conn.commit()


def get_latest_market_signal(conn) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT signal_date, market_status, spy_ticker, spy_close, spy_ma200,
                   spy_above_200ma, vix_ticker, vix_close, source, details, run_id,
                   created_at, updated_at
            FROM market_signals
            ORDER BY signal_date DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if row is None:
        return None
    keys = [
        "signal_date", "market_status", "spy_ticker", "spy_close", "spy_ma200",
        "spy_above_200ma", "vix_ticker", "vix_close", "source", "details", "run_id",
        "created_at", "updated_at",
    ]
    return dict(zip(keys, row))


def _signal_payload(signal) -> dict[str, Any]:
    details = getattr(signal, "details", {}) or {}
    return {
        "signal_date": getattr(signal, "signal_date"),
        "market_status": getattr(signal, "market_status"),
        "spy_ticker": getattr(signal, "spy_ticker", "SPY"),
        "spy_close": getattr(signal, "spy_close"),
        "spy_ma200": getattr(signal, "spy_ma200"),
        "spy_above_200ma": getattr(signal, "spy_above_200ma"),
        "vix_ticker": getattr(signal, "vix_ticker", "^VIX"),
        "vix_close": getattr(signal, "vix_close"),
        "source": getattr(signal, "source", "yfinance"),
        "details": json.dumps(details, ensure_ascii=False),
        "run_id": getattr(signal, "run_id", None),
    }



def list_market_signals(conn, *, start_date=None, end_date=None, limit: int = 100) -> list[dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if start_date is not None:
        clauses.append("signal_date >= %(start_date)s")
        params["start_date"] = start_date
    if end_date is not None:
        clauses.append("signal_date <= %(end_date)s")
        params["end_date"] = end_date
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT signal_date, market_status, spy_ticker, spy_close, spy_ma200,
                   spy_above_200ma, vix_ticker, vix_close, source, details, run_id,
                   created_at, updated_at
            FROM market_signals
            {where}
            ORDER BY signal_date DESC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()
    keys = [
        "signal_date", "market_status", "spy_ticker", "spy_close", "spy_ma200",
        "spy_above_200ma", "vix_ticker", "vix_close", "source", "details", "run_id",
        "created_at", "updated_at",
    ]
    return [dict(zip(keys, row)) for row in rows]


def list_watchlist_items(conn, *, include_archived: bool = False) -> list[dict[str, Any]]:
    where = "" if include_archived else "WHERE status <> 'archived'"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ticker, status, thesis, tags, created_at, updated_at
            FROM watchlist_items
            {where}
            ORDER BY ticker ASC
            """
        )
        rows = cur.fetchall()
    keys = ["ticker", "status", "thesis", "tags", "created_at", "updated_at"]
    return [dict(zip(keys, row)) for row in rows]


def upsert_watchlist_item(conn, *, ticker: str, status: str = "active", thesis: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    payload = {
        "ticker": _normalize_ticker(ticker),
        "status": status or "active",
        "thesis": thesis or None,
        "tags": tags or [],
    }
    if payload["status"] not in {"active", "paused", "archived"}:
        raise ValueError("status must be active, paused, or archived")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO watchlist_items (ticker, status, thesis, tags)
            VALUES (%(ticker)s, %(status)s, %(thesis)s, %(tags)s)
            ON CONFLICT (ticker) DO UPDATE SET
              status = EXCLUDED.status,
              thesis = EXCLUDED.thesis,
              tags = EXCLUDED.tags,
              updated_at = now()
            RETURNING ticker, status, thesis, tags, created_at, updated_at
            """,
            payload,
        )
        row = cur.fetchone()
    conn.commit()
    keys = ["ticker", "status", "thesis", "tags", "created_at", "updated_at"]
    return dict(zip(keys, row))


def delete_watchlist_item(conn, ticker: str) -> dict[str, Any]:
    normalized = _normalize_ticker(ticker)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM watchlist_items WHERE ticker = %(ticker)s RETURNING ticker", {"ticker": normalized})
        row = cur.fetchone()
    conn.commit()
    return {"ticker": normalized, "deleted": row is not None}


def _normalize_ticker(ticker: str) -> str:
    normalized = str(ticker or "").strip().upper()
    if not normalized:
        raise ValueError("ticker is required")
    if not normalized.replace(".", "").replace("-", "").isalnum():
        raise ValueError("ticker contains unsupported characters")
    return normalized


def insert_job_report(
    conn,
    *,
    task: str,
    run_id: str,
    status: str,
    started_at,
    finished_at,
    summary: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_reports (task, run_id, status, started_at, finished_at, summary)
            VALUES (%(task)s, %(run_id)s, %(status)s, %(started_at)s, %(finished_at)s, %(summary)s::jsonb)
            """,
            {
                "task": task,
                "run_id": run_id,
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "summary": json.dumps(summary or {}, ensure_ascii=False, default=str),
            },
        )
        cur.execute("DELETE FROM job_reports WHERE created_at < now() - INTERVAL '30 days'")
    conn.commit()


def due_scheduled_jobs(conn, *, now) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, time_local, weekday_mask, timezone, next_run_at
            FROM scheduled_jobs
            WHERE enabled AND (next_run_at IS NULL OR next_run_at <= %(now)s)
            FOR UPDATE SKIP LOCKED
            """,
            {"now": now},
        )
        rows = cur.fetchall()
    keys = ["id", "name", "time_local", "weekday_mask", "timezone", "next_run_at"]
    return [dict(zip(keys, row)) for row in rows]


def reschedule_job(conn, name: str, *, next_run_at, last_run_at) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scheduled_jobs
            SET next_run_at = %(next_run_at)s, last_run_at = %(last_run_at)s, updated_at = now()
            WHERE name = %(name)s
            """,
            {"name": name, "next_run_at": next_run_at, "last_run_at": last_run_at},
        )
    conn.commit()


def list_scheduled_jobs(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, time_local, weekday_mask, timezone, enabled, next_run_at, last_run_at
            FROM scheduled_jobs
            ORDER BY name
            """
        )
        rows = cur.fetchall()
    keys = ["name", "time_local", "weekday_mask", "timezone", "enabled", "next_run_at", "last_run_at"]
    return [dict(zip(keys, row)) for row in rows]


def list_job_reports(conn, *, task: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    where = "WHERE task = %(task)s" if task else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT task, run_id, status, started_at, finished_at, summary, created_at
            FROM job_reports
            {where}
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """,
            {"task": task, "limit": limit},
        )
        rows = cur.fetchall()
    keys = ["task", "run_id", "status", "started_at", "finished_at", "summary", "created_at"]
    return [dict(zip(keys, row)) for row in rows]


def job_report_metrics(conn, *, task: str | None = None, since) -> list[dict[str, Any]]:
    where = "WHERE created_at >= %(since)s" + (" AND task = %(task)s" if task else "")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
              task,
              count(*) AS total,
              count(*) FILTER (WHERE status = 'success') AS success,
              avg(EXTRACT(EPOCH FROM (finished_at - started_at))) AS avg_seconds,
              coalesce(
                jsonb_agg(jsonb_build_object('day', to_char(created_at, 'YYYY-MM-DD'), 'count', 1))
                  FILTER (WHERE status = 'error'),
                '[]'::jsonb
              ) AS error_days
            FROM job_reports
            {where}
            GROUP BY task
            ORDER BY task
            """,
            {"task": task, "since": since},
        )
        rows = cur.fetchall()
    keys = ["task", "total", "success", "avg_seconds", "error_days"]
    return [dict(zip(keys, row)) for row in rows]


def update_scheduled_job(conn, name: str, *, enabled=None, time_local=None) -> None:
    sets = ["updated_at = now()"]
    params: dict[str, Any] = {"name": name}
    if enabled is not None:
        sets.append("enabled = %(enabled)s")
        params["enabled"] = enabled
    if time_local is not None:
        sets.append("time_local = %(time_local)s")
        sets.append("next_run_at = NULL")  # 改时间 → 下一 tick 重算
        params["time_local"] = time_local
    with conn.cursor() as cur:
        cur.execute(f"UPDATE scheduled_jobs SET {', '.join(sets)} WHERE name = %(name)s", params)
    conn.commit()
