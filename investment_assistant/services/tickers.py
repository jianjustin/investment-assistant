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
from investment_assistant.data.provenance import SIGNAL_CALCULATION_VERSION
from investment_assistant.db import connect
from investment_assistant.tickers.trend import latest_completed_signal_date, scan_ticker_trends

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
    """Return OHLCV + MA series for *days* trading candles.

    Strategy: over-fetch a calendar-day buffer large enough to cover
    ``days`` trading candles PLUS the 200-trading-day warmup that
    ``Close.rolling(200).mean()`` needs.  After computing MAs on the
    FULL fetched frame (so warmup rows are included), we tail each
    series to the last ``days`` entries before assembling the result.

    Calendar-day buffer formula:
        calendar_days = int((days + 200) * 7 / 5) + 15
    (trading→calendar ≈ ×7/5; +200 warmup; +15 slack for holidays)

    Cache is keyed by (ticker, days) — identical to before.
    The ``fetcher`` and ``clock`` injection points are unchanged.
    """
    now = (clock or time.monotonic)()
    key = (ticker.upper(), days)
    cached = _ohlcv_cache.get(key)
    if cached and now - cached[0] < _OHLCV_TTL_SECONDS:
        return cached[1]

    # Over-fetch: request enough calendar days to guarantee 200 warmup rows.
    calendar_days = int((days + 200) * 7 / 5) + 15
    fetch = fetcher or get_price_history
    frame = fetch(ticker.upper(), calendar_days)
    if frame is None or frame.empty:
        raise ValueError(f"No price data returned for {ticker}")

    # Compute MAs over the FULL frame (preserves warmup).
    closes = frame["Close"].astype(float)
    all_bars = [
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
    all_ma20 = _ma_series(closes, 20)
    all_ma50 = _ma_series(closes, 50)
    all_ma200 = _ma_series(closes, 200)

    # Tail to the requested number of trading candles.
    result = {
        "ticker": ticker.upper(),
        "bars": all_bars[-days:],
        "ma20": all_ma20[-days:],
        "ma50": all_ma50[-days:],
        "ma200": all_ma200[-days:],
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
                           run_id, created_at, updated_at, price_date, calculation_version
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
        "run_id", "created_at", "updated_at", "price_date", "calculation_version",
    ]
    return [dict(zip(keys, row)) for row in rows]


def run_ticker_trend_scan(payload: dict[str, Any]) -> dict[str, Any]:
    from investment_assistant.services.watchlist import current_watchlist
    target_date = (date.fromisoformat(str(payload.get("date")))
                   if payload.get("date") else latest_completed_signal_date())
    tickers = parse_payload_watchlist(payload.get("tickers")) or current_watchlist()
    if not tickers:
        raise ValueError("tickers or active watchlist is required")
    run_id = f"manual-ticker-trends-{target_date.isoformat()}-{uuid.uuid4().hex[:8]}"
    rows = scan_ticker_trends(tickers, signal_date=target_date, run_id=run_id)
    persistence = _persist_ticker_trend_snapshots(rows)
    failures = [row for row in rows if row.get("error")]
    return {
        "run_id": run_id,
        "requested": {"date": target_date.isoformat(), "tickers": tickers},
        "actual_dates": [target_date.isoformat()],
        # Rows/count describe this computation, not newly stored observations.
        "rows": rows,
        "count": len(rows),
        "computed_count": len(rows) - len(failures),
        "failures": failures,
        **persistence,
    }


def _persist_ticker_trend_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"inserted_count": 0, "inserted_success_count": 0,
                              "skipped_count": 0, "skipped": []}
    if not snapshots:
        return result
    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            for snapshot in snapshots:
                payload = dict(snapshot)
                if payload.get("calculation_version") != SIGNAL_CALCULATION_VERSION:
                    raise ValueError("Snapshot provenance requires the current calculation version")
                if not payload.get("error") and (
                    payload.get("price_date") is None
                    or str(payload["price_date"]) != str(payload.get("signal_date"))
                ):
                    raise ValueError("Snapshot provenance requires price_date = signal_date")
                payload["trigger_reason"] = json.dumps(payload.get("trigger_reason") or [], ensure_ascii=False)
                cur.execute(
                    """
                    INSERT INTO ticker_signal_snapshots (
                      ticker, signal_date, close, ma20, ma50, ma200, volume, volume_ratio,
                      relative_strength_spy, relative_strength_qqq, trend_state, attention_level,
                      trigger_reason, source, error, run_id, price_date, calculation_version
                    ) VALUES (
                      %(ticker)s, %(signal_date)s, %(close)s, %(ma20)s, %(ma50)s, %(ma200)s, %(volume)s, %(volume_ratio)s,
                      %(relative_strength_spy)s, %(relative_strength_qqq)s, %(trend_state)s, %(attention_level)s,
                      %(trigger_reason)s::jsonb, %(source)s, %(error)s, %(run_id)s,
                      %(price_date)s, %(calculation_version)s
                    )
                    ON CONFLICT (ticker, signal_date) DO NOTHING
                    RETURNING id
                    """,
                    payload,
                )
                if cur.fetchone() is not None:
                    result["inserted_count"] += 1
                    result["inserted_success_count"] += int(not payload.get("error"))
                else:
                    result["skipped_count"] += 1
                    result["skipped"].append({"ticker": payload["ticker"], "date": str(payload["signal_date"]),
                                              "stage": "ticker_snapshot", "reason": "existing_record_preserved"})
        conn.commit()
    return result
