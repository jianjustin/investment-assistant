from __future__ import annotations

from datetime import date
from typing import Any, Callable

import pandas as pd


def classify_ticker_trend(
    *,
    ticker: str,
    close: float,
    ma20: float,
    ma50: float,
    ma200: float,
    volume_ratio: float,
    relative_strength_spy: float,
    relative_strength_qqq: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    if close > ma20 > ma50 > ma200:
        reasons.append("above_ma_stack")
    if volume_ratio >= 1.5:
        reasons.append("volume_expansion")
    if relative_strength_spy > 0:
        reasons.append("outperform_spy")
    if relative_strength_qqq > 0:
        reasons.append("outperform_qqq")

    if "above_ma_stack" in reasons and ("outperform_spy" in reasons or "outperform_qqq" in reasons):
        trend_state = "uptrend"
    elif close < ma50 < ma200:
        trend_state = "downtrend"
    elif volume_ratio >= 2:
        trend_state = "volatile"
    else:
        trend_state = "base"

    attention_level = "high" if len(reasons) >= 3 else "medium" if reasons else "low"
    return {"ticker": ticker.upper(), "trend_state": trend_state, "attention_level": attention_level, "trigger_reason": reasons}


PriceFetcher = Callable[[str, int], pd.DataFrame]


def scan_ticker_trends(
    tickers: list[str],
    *,
    signal_date: date,
    price_fetcher: PriceFetcher | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    fetcher = price_fetcher or _default_price_fetcher
    rows: list[dict[str, Any]] = []
    for raw_ticker in tickers:
        ticker = str(raw_ticker or "").strip().upper()
        if not ticker:
            continue
        try:
            rows.append(compute_ticker_trend_snapshot(ticker, signal_date=signal_date, price_fetcher=fetcher, run_id=run_id))
        except Exception as exc:
            rows.append({
                "ticker": ticker,
                "signal_date": signal_date,
                "close": None,
                "ma20": None,
                "ma50": None,
                "ma200": None,
                "volume": None,
                "volume_ratio": None,
                "relative_strength_spy": None,
                "relative_strength_qqq": None,
                "trend_state": "unknown",
                "attention_level": "low",
                "trigger_reason": [],
                "source": "yfinance",
                "error": str(exc),
                "run_id": run_id,
            })
    return rows


def compute_ticker_trend_snapshot(
    ticker: str,
    *,
    signal_date: date,
    price_fetcher: PriceFetcher,
    run_id: str | None = None,
) -> dict[str, Any]:
    price_frame = _validate_frame(price_fetcher(ticker, 260), ticker, min_rows=200)
    spy_frame = _validate_frame(price_fetcher("SPY", 260), "SPY", min_rows=21)
    qqq_frame = _validate_frame(price_fetcher("QQQ", 260), "QQQ", min_rows=21)

    close = float(price_frame["Close"].iloc[-1])
    ma20 = float(price_frame["Close"].tail(20).mean())
    ma50 = float(price_frame["Close"].tail(50).mean())
    ma200 = float(price_frame["Close"].tail(200).mean())
    volume = int(price_frame["Volume"].iloc[-1])
    avg_volume = float(price_frame["Volume"].tail(60).mean())
    volume_ratio = volume / avg_volume if avg_volume else 0.0
    relative_strength_spy = _relative_strength(price_frame, spy_frame)
    relative_strength_qqq = _relative_strength(price_frame, qqq_frame)

    classified = classify_ticker_trend(
        ticker=ticker,
        close=close,
        ma20=ma20,
        ma50=ma50,
        ma200=ma200,
        volume_ratio=volume_ratio,
        relative_strength_spy=relative_strength_spy,
        relative_strength_qqq=relative_strength_qqq,
    )
    return {
        **classified,
        "signal_date": signal_date,
        "close": close,
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "volume": volume,
        "volume_ratio": volume_ratio,
        "relative_strength_spy": relative_strength_spy,
        "relative_strength_qqq": relative_strength_qqq,
        "source": "yfinance",
        "error": None,
        "run_id": run_id,
    }


def _relative_strength(frame: pd.DataFrame, benchmark: pd.DataFrame, window: int = 20) -> float:
    rows = min(window + 1, len(frame), len(benchmark))
    if rows < 2:
        return 0.0
    ticker_return = float(frame["Close"].iloc[-1] / frame["Close"].iloc[-rows] - 1)
    benchmark_return = float(benchmark["Close"].iloc[-1] / benchmark["Close"].iloc[-rows] - 1)
    return ticker_return - benchmark_return


def _validate_frame(frame: pd.DataFrame, ticker: str, *, min_rows: int) -> pd.DataFrame:
    required = {"Close", "Volume"}
    if frame.empty or not required.issubset(frame.columns) or len(frame) < min_rows:
        raise ValueError(f"Insufficient price data for {ticker}: need {min_rows} rows")
    return frame


def _default_price_fetcher(ticker: str, days: int) -> pd.DataFrame:
    from investment_assistant.data.price import get_price_history

    return get_price_history(ticker, days=days)
