from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date
from typing import Any, Callable

import pandas as pd

from investment_assistant.api.http import parse_payload_watchlist
from investment_assistant.data.price import get_price_history
from investment_assistant.db import connect
from investment_assistant.tickers.trend import scan_ticker_trends

_OHLCV_TTL_SECONDS = 300.0
_ohlcv_cache: dict[tuple[str, int], tuple[float, dict]] = {}


def clear_ohlcv_cache() -> None:
    _ohlcv_cache.clear()


def _ma_series(closes: pd.Series, window: int) -> list:
    ma = closes.rolling(window).mean()
    return [None if pd.isna(v) else round(float(v), 4) for v in ma]


def ohlcv_series(
    ticker: str,
    days: int = 250,
    *,
    fetcher: Callable[[str, int], pd.DataFrame] | None = None,
    clock: Callable[[], float] | None = None,
) -> dict:
    now = (clock or time.monotonic)()
    key = (ticker.upper(), days)
    cached = _ohlcv_cache.get(key)
    if cached and now - cached[0] < _OHLCV_TTL_SECONDS:
        return cached[1]

    fetch = fetcher or get_price_history
    frame = fetch(ticker.upper(), days)
    if frame is None or frame.empty:
        raise ValueError(f"No price data returned for {ticker}")

    closes = frame["Close"].astype(float)
    bars = [
        {
            "date": (idx.date().isoformat() if hasattr(idx, "date") else str(idx)),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]),
        }
        for idx, row in frame.iterrows()
    ]
    result = {
        "ticker": ticker.upper(),
        "bars": bars,
        "ma20": _ma_series(closes, 20),
        "ma50": _ma_series(closes, 50),
        "ma200": _ma_series(closes, 200),
    }
    _ohlcv_cache[key] = (now, result)
    return result


def ticker_trend_rows() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return []
    try:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ticker, signal_date, close, ma20, ma50, ma200,
                           volume, volume_ratio, relative_strength_spy, relative_strength_qqq,
                           trend_state, attention_level, trigger_reason, source, error,
                           run_id, created_at, updated_at
                    FROM ticker_signal_snapshots
                    ORDER BY signal_date DESC, attention_level ASC, ticker ASC
                    LIMIT 100
                    """
                )
                rows = cur.fetchall()
    except Exception:
        return []
    keys = [
        "ticker", "signal_date", "close", "ma20", "ma50", "ma200",
        "volume", "volume_ratio", "relative_strength_spy", "relative_strength_qqq",
        "trend_state", "attention_level", "trigger_reason", "source", "error",
        "run_id", "created_at", "updated_at",
    ]
    return [dict(zip(keys, row)) for row in rows]


def run_ticker_trend_scan(payload: dict[str, Any]) -> dict[str, Any]:
    from investment_assistant.services.watchlist import current_watchlist
    target_date = date.fromisoformat(str(payload.get("date"))) if payload.get("date") else date.today()
    tickers = parse_payload_watchlist(payload.get("tickers")) or current_watchlist()
    if not tickers:
        raise ValueError("tickers or active watchlist is required")
    run_id = f"manual-ticker-trends-{target_date.isoformat()}-{uuid.uuid4().hex[:8]}"
    rows = scan_ticker_trends(tickers, signal_date=target_date, run_id=run_id)
    _persist_ticker_trend_snapshots(rows)
    failures = [row for row in rows if row.get("error")]
    return {
        "run_id": run_id,
        "requested": {"date": target_date.isoformat(), "tickers": tickers},
        "rows": rows,
        "count": len(rows),
        "failures": failures,
    }


def _persist_ticker_trend_snapshots(snapshots: list[dict[str, Any]]) -> None:
    if not snapshots:
        return
    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            for snapshot in snapshots:
                payload = dict(snapshot)
                payload["trigger_reason"] = json.dumps(payload.get("trigger_reason") or [], ensure_ascii=False)
                cur.execute(
                    """
                    INSERT INTO ticker_signal_snapshots (
                      ticker, signal_date, close, ma20, ma50, ma200, volume, volume_ratio,
                      relative_strength_spy, relative_strength_qqq, trend_state, attention_level,
                      trigger_reason, source, error, run_id
                    ) VALUES (
                      %(ticker)s, %(signal_date)s, %(close)s, %(ma20)s, %(ma50)s, %(ma200)s, %(volume)s, %(volume_ratio)s,
                      %(relative_strength_spy)s, %(relative_strength_qqq)s, %(trend_state)s, %(attention_level)s,
                      %(trigger_reason)s::jsonb, %(source)s, %(error)s, %(run_id)s
                    )
                    ON CONFLICT (ticker, signal_date) DO UPDATE SET
                      close = EXCLUDED.close,
                      ma20 = EXCLUDED.ma20,
                      ma50 = EXCLUDED.ma50,
                      ma200 = EXCLUDED.ma200,
                      volume = EXCLUDED.volume,
                      volume_ratio = EXCLUDED.volume_ratio,
                      relative_strength_spy = EXCLUDED.relative_strength_spy,
                      relative_strength_qqq = EXCLUDED.relative_strength_qqq,
                      trend_state = EXCLUDED.trend_state,
                      attention_level = EXCLUDED.attention_level,
                      trigger_reason = EXCLUDED.trigger_reason,
                      source = EXCLUDED.source,
                      error = EXCLUDED.error,
                      run_id = EXCLUDED.run_id,
                      updated_at = now()
                    """,
                    payload,
                )
        conn.commit()
