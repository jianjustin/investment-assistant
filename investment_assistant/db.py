from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url)


def apply_migration(conn, sql_path: str | Path) -> None:
    sql = Path(sql_path).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


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
