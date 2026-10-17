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


def close_pools() -> None:
    """Close and drop all cached pools (best-effort, idempotent).

    One-shot CLIs (e.g. investment_assistant.migrate) must call this before
    exiting: on Python 3.13+ an unclosed ConnectionPool raises
    PythonFinalizationError from __del__ at interpreter shutdown.
    """
    with _POOLS_LOCK:
        for pool in _POOLS.values():
            try:
                pool.close()
            except Exception:
                pass
        _POOLS.clear()


_reset_pools = close_pools  # backwards-compatible test alias


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


def upsert_market_signal(conn, signal, *, preserve_existing: bool = False) -> bool | None:
    """Legacy callers may update; dated metrics explicitly preserve existing rows.

    In preserve mode return True only for an actual insert (False on conflict).
    The default keeps the previous update semantics and None return value.
    """
    payload = _signal_payload(signal)
    conflict = "DO NOTHING" if preserve_existing else """DO UPDATE SET
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
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO market_signals (
              signal_date, market_status, spy_ticker, spy_close, spy_ma200,
              spy_above_200ma, vix_ticker, vix_close, source, details, run_id
            ) VALUES (
              %(signal_date)s, %(market_status)s, %(spy_ticker)s, %(spy_close)s, %(spy_ma200)s,
              %(spy_above_200ma)s, %(vix_ticker)s, %(vix_close)s, %(source)s, %(details)s, %(run_id)s
            )
            ON CONFLICT (signal_date) {conflict}
            {"RETURNING signal_date" if preserve_existing else ""}
            """,
            payload,
        )
        inserted = cur.fetchone() is not None if preserve_existing else None
    conn.commit()
    return inserted


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


class WatchlistConflict(ValueError):
    """The record was edited or removed since the client read it."""


_WATCHLIST_UNSET = object()


def upsert_watchlist_item(conn, *, ticker: str, status=_WATCHLIST_UNSET,
                          thesis=_WATCHLIST_UNSET, tags=_WATCHLIST_UNSET,
                          expected_updated_at=None) -> dict[str, Any]:
    payload = {"ticker": _normalize_ticker(ticker)}
    supplied = {"status": status, "thesis": thesis, "tags": tags}
    defaults = {"status": "active", "thesis": None, "tags": []}
    for field, value in supplied.items():
        payload[field + "_supplied"] = value is not _WATCHLIST_UNSET
        payload[field] = defaults[field] if value is _WATCHLIST_UNSET else value
    if payload["status"] not in {"active", "paused", "archived"}:
        raise ValueError("status must be active, paused, or archived")
    if expected_updated_at is not None:
        from datetime import datetime
        try:
            expected = (datetime.fromisoformat(expected_updated_at.replace('Z', '+00:00'))
                        if isinstance(expected_updated_at, str) else expected_updated_at)
            if not isinstance(expected, datetime) or expected.tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('expected_updated_at must be a timezone-aware timestamp') from None
        payload['expected_updated_at'] = expected
    assignments = ', '.join(
        f"{field} = CASE WHEN %({field}_supplied)s THEN %({field})s ELSE watchlist_items.{field} END"
        for field in supplied)
    with conn.cursor() as cur:
        if expected_updated_at is not None:
            # A single compare-and-set UPDATE prevents lost edits and deleted-row resurrection.
            cur.execute(f"""UPDATE watchlist_items SET {assignments}, updated_at=clock_timestamp()
                WHERE ticker=%(ticker)s AND updated_at=%(expected_updated_at)s
                RETURNING ticker,status,thesis,tags,created_at,updated_at""", payload)
        else:
            cur.execute(f"""INSERT INTO watchlist_items(ticker,status,thesis,tags)
                VALUES (%(ticker)s,%(status)s,%(thesis)s,%(tags)s)
                ON CONFLICT(ticker) DO UPDATE SET {assignments}, updated_at=clock_timestamp()
                RETURNING ticker,status,thesis,tags,created_at,updated_at""", payload)
        row = cur.fetchone()
    if row is None:
        raise WatchlistConflict('关注记录已修改或删除，请重新读取后再编辑')
    conn.commit()
    return dict(zip(['ticker', 'status', 'thesis', 'tags', 'created_at', 'updated_at'], row))


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
    target_start_date=None,
    target_end_date=None,
    trigger_source: str = "scheduled",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_reports (
              task, run_id, status, started_at, finished_at, summary,
              target_start_date, target_end_date, trigger_source
            )
            VALUES (
              %(task)s, %(run_id)s, %(status)s, %(started_at)s, %(finished_at)s, %(summary)s::jsonb,
              %(target_start_date)s, %(target_end_date)s, %(trigger_source)s
            )
            """,
            {
                "task": task,
                "run_id": run_id,
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "summary": json.dumps(summary or {}, ensure_ascii=False, default=str),
                "target_start_date": target_start_date,
                "target_end_date": target_end_date,
                "trigger_source": trigger_source,
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
            SELECT task, run_id, status, started_at, finished_at, summary, created_at,
                   target_start_date, target_end_date, trigger_source
            FROM job_reports
            {where}
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """,
            {"task": task, "limit": limit},
        )
        rows = cur.fetchall()
    keys = ["task", "run_id", "status", "started_at", "finished_at", "summary", "created_at",
            "target_start_date", "target_end_date", "trigger_source"]
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


def get_notify_settings(conn) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT discord_enabled, webhooks, task_channels, task_enabled, channel, email "
            "FROM notify_settings WHERE id = 1"
        )
        rows = cur.fetchall()
    if not rows:
        return {}
    keys = ["discord_enabled", "webhooks", "task_channels", "task_enabled", "channel", "email"]
    return dict(zip(keys, rows[0]))


def update_notify_settings(
    conn, *, discord_enabled=None, webhooks=None, task_channels=None, task_enabled=None,
    channel=None, email=None,
) -> None:
    sets = ["updated_at = now()"]
    params: dict[str, Any] = {}
    if discord_enabled is not None:
        sets.append("discord_enabled = %(discord_enabled)s")
        params["discord_enabled"] = discord_enabled
    if channel is not None:
        sets.append("channel = %(channel)s")
        params["channel"] = channel
    for col, value in (("webhooks", webhooks), ("task_channels", task_channels),
                       ("task_enabled", task_enabled), ("email", email)):
        if value is not None:
            sets.append(f"{col} = {col} || %({col})s::jsonb")
            params[col] = json.dumps(value, ensure_ascii=False)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE notify_settings SET {', '.join(sets)} WHERE id = 1", params)
    conn.commit()


def upsert_event_study(conn, *, kind: str, params_hash: str, result: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO event_studies (kind, params_hash, result, generated_at)
            VALUES (%(kind)s, %(params_hash)s, %(result)s::jsonb, now())
            ON CONFLICT (kind, params_hash) DO UPDATE SET
              result = EXCLUDED.result,
              generated_at = EXCLUDED.generated_at,
              updated_at = now()
            """,
            {
                "kind": kind,
                "params_hash": params_hash,
                "result": json.dumps(result or {}, ensure_ascii=False, default=str),
            },
        )
    conn.commit()


def get_event_study(conn, *, kind: str, params_hash: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kind, params_hash, result, generated_at
            FROM event_studies
            WHERE kind = %(kind)s AND params_hash = %(params_hash)s
            """,
            {"kind": kind, "params_hash": params_hash},
        )
        rows = cur.fetchall()
    if not rows:
        return None
    keys = ["kind", "params_hash", "result", "generated_at"]
    return dict(zip(keys, rows[0]))


_FILING_KEYS = ["id", "ticker", "form", "filing_date", "accession_number",
                "primary_document", "file_path", "downloaded_at", "created_at"]


def upsert_filing(
    conn, *, ticker: str, form: str, filing_date, accession_number: str,
    primary_document: str, file_path: str, run_id: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filings (
              ticker, form, filing_date, accession_number, primary_document, file_path, run_id
            ) VALUES (
              %(ticker)s, %(form)s, %(filing_date)s, %(accession_number)s,
              %(primary_document)s, %(file_path)s, %(run_id)s
            )
            ON CONFLICT (accession_number, primary_document) DO UPDATE SET
              file_path = EXCLUDED.file_path,
              run_id = COALESCE(EXCLUDED.run_id, filings.run_id)
            """,
            {
                "ticker": ticker, "form": form, "filing_date": filing_date,
                "accession_number": accession_number, "primary_document": primary_document,
                "file_path": file_path, "run_id": run_id,
            },
        )
    conn.commit()


def list_filings(conn, *, ticker: str | None = None, form: str | None = None,
                 start_date=None, end_date=None, limit: int = 50) -> list[dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if ticker:
        clauses.append("ticker = %(ticker)s")
        params["ticker"] = ticker
    if form:
        clauses.append("form = %(form)s")
        params["form"] = form
    if start_date is not None:
        clauses.append("filing_date >= %(start_date)s")
        params["start_date"] = start_date
    if end_date is not None:
        clauses.append("filing_date <= %(end_date)s")
        params["end_date"] = end_date
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, ticker, form, filing_date, accession_number,
                   primary_document, file_path, downloaded_at, created_at
            FROM filings
            {where}
            ORDER BY filing_date DESC, ticker ASC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()
    return [dict(zip(_FILING_KEYS, row)) for row in rows]


def get_filing(conn, filing_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ticker, form, filing_date, accession_number,
                   primary_document, file_path, downloaded_at, created_at
            FROM filings
            WHERE id = %(id)s
            """,
            {"id": filing_id},
        )
        row = cur.fetchone()
    return dict(zip(_FILING_KEYS, row)) if row else None


def list_filing_tickers(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM filings ORDER BY ticker")
        rows = cur.fetchall()
    return [row[0] for row in rows]
