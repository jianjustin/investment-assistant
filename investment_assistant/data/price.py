from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pandas as pd
import yfinance as yf

_OHLCV = ["Open", "High", "Low", "Close", "Volume"]

# as-of 取价器：给定 ticker / 截止日 / 期望交易日数，返回截至该日（含）的 OHLCV。
AsofFetcher = Callable[[str, date, int], pd.DataFrame]


def get_price_history(ticker: str, days: int = 90) -> pd.DataFrame:
    """Return adjusted OHLCV for ticker over the last `days` calendar days."""
    df = yf.Ticker(ticker).history(period=f"{days}d", auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data returned for {ticker}")
    return df[_OHLCV]


def _default_asof_fetcher(ticker: str, end_date: date, days: int) -> pd.DataFrame:
    # 交易日 ≈ 日历日 * 0.7，留足缓冲多取再裁剪。
    calendar_days = max(days * 2, days + 30)
    start = end_date - timedelta(days=calendar_days)
    end = end_date + timedelta(days=1)
    df = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(), auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data returned for {ticker} through {end_date}")
    return df[_OHLCV]


def get_price_history_asof(
    ticker: str,
    end_date: date,
    *,
    days: int = 260,
    fetcher: AsofFetcher | None = None,
) -> pd.DataFrame:
    """Point-in-time adjusted OHLCV up to and including end_date (no look-ahead).

    二次裁剪 `df.loc[:end_date]` 是防前视偏差的硬守卫。
    """
    fetch = fetcher or _default_asof_fetcher
    df = fetch(ticker, end_date, days)
    if df is None or df.empty:
        raise ValueError(f"No price data returned for {ticker} through {end_date}")
    df = df[[c for c in _OHLCV if c in df.columns]]
    cutoff = pd.Timestamp(end_date)
    sliced = df[df.index <= cutoff.tz_localize(df.index.tz) if df.index.tz else df.index <= cutoff]
    if days and len(sliced) > days:
        sliced = sliced.tail(days)
    if sliced.empty:
        raise ValueError(f"No price data on or before {end_date} for {ticker}")
    return sliced


def detect_split_jumps(
    frame: pd.DataFrame,
    *,
    threshold: float = 0.5,
    earnings_dates: set[date] | None = None,
) -> list[dict]:
    """扫描相邻日收益，|ret|>=threshold 且非财报日 → 疑似未复权 split。只告警不改数。"""
    if frame.empty or "Close" not in frame.columns or len(frame) < 2:
        return []
    earnings = earnings_dates or set()
    closes = frame["Close"].astype(float)
    jumps: list[dict] = []
    prev_close = None
    prev_ts = None
    for ts, close in closes.items():
        if prev_close is not None and prev_close != 0:
            ret = close / prev_close - 1
            cur_day = ts.date() if hasattr(ts, "date") else ts
            if abs(ret) >= threshold and cur_day not in earnings:
                jumps.append({
                    "date": cur_day,
                    "prev_date": prev_ts.date() if hasattr(prev_ts, "date") else prev_ts,
                    "prev_close": float(prev_close),
                    "close": float(close),
                    "ret": float(ret),
                    "suspected": "unadjusted_split",
                })
        prev_close = close
        prev_ts = ts
    return jumps
