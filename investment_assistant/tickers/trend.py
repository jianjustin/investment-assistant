from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from investment_assistant.data.calendar import is_trading_day
from investment_assistant.data.provenance import SIGNAL_CALCULATION_VERSION

_HISTORY_TRADING_DAYS = 260
_LEGACY_CALENDAR_DAYS = _HISTORY_TRADING_DAYS * 2
_NEW_YORK = ZoneInfo("America/New_York")


def latest_completed_signal_date(now: datetime | None = None) -> date:
    """Last completed US session; wait until 16:15 ET even on early-close days.

    This deliberately does not claim that an intraday/delayed daily bar is final.
    An explicit historical request is never rolled back to another session.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(_NEW_YORK)
    target = local.date()
    if local.time() < time(16, 15):
        target -= timedelta(days=1)
    while not is_trading_day(target):
        target -= timedelta(days=1)
    return target


def validate_signal_date(signal_date: date, now: datetime | None = None) -> None:
    if not is_trading_day(signal_date):
        raise ValueError(f"{signal_date} is not a US trading session")
    if signal_date > latest_completed_signal_date(now):
        raise ValueError(f"{signal_date} is a future or not-yet-closed US session")


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


# Legacy injection takes calendar days; the new injection takes a target date
# and a trading-observation budget. Neither may bypass the as-of validation.
PriceFetcher = Callable[[str, int], pd.DataFrame]
AsofPriceFetcher = Callable[[str, date, int], pd.DataFrame]


def scan_ticker_trends(
    tickers: list[str],
    *,
    signal_date: date,
    price_fetcher: PriceFetcher | None = None,
    run_id: str | None = None,
    asof_price_fetcher: AsofPriceFetcher | None = None,
    clock: Callable[[], datetime] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_ticker in tickers:
        ticker = str(raw_ticker or "").strip().upper()
        if not ticker:
            continue
        try:
            rows.append(compute_ticker_trend_snapshot(
                ticker, signal_date=signal_date, price_fetcher=price_fetcher,
                asof_price_fetcher=asof_price_fetcher, run_id=run_id, clock=clock,
            ))
        except Exception as exc:
            rows.append({
                "ticker": ticker,
                "signal_date": signal_date,
                "price_date": None,
                "calculation_version": SIGNAL_CALCULATION_VERSION,
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
    price_fetcher: PriceFetcher | None = None,
    run_id: str | None = None,
    asof_price_fetcher: AsofPriceFetcher | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    validate_signal_date(signal_date, (clock or (lambda: datetime.now(UTC)))())
    if price_fetcher is not None and asof_price_fetcher is not None:
        raise ValueError("Provide price_fetcher or asof_price_fetcher, not both")

    def fetch(symbol: str, min_rows: int) -> pd.DataFrame:
        if price_fetcher is not None:
            frame = price_fetcher(symbol, _LEGACY_CALENDAR_DAYS)
        else:
            frame = (asof_price_fetcher or _default_asof_price_fetcher)(
                symbol, signal_date, _HISTORY_TRADING_DAYS,
            )
        return _validate_frame(frame, symbol, signal_date=signal_date, min_rows=min_rows)

    price_frame = fetch(ticker, 200)
    spy_frame = fetch("SPY", 21)
    qqq_frame = fetch("QQQ", 21)

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
        "price_date": price_frame.index[-1].date(),
        "calculation_version": SIGNAL_CALCULATION_VERSION,
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
    # Compare exactly the same observed sessions; never compare two independent
    # positional tails, forward-fill missing bars, or silently shorten the window.
    observations = frame.tail(window + 1)
    aligned = benchmark.reindex(observations.index)
    if len(observations) != window + 1 or aligned["Close"].isna().any():
        raise ValueError("Relative strength requires matching ticker/benchmark observation dates")
    ticker_return = float(observations["Close"].iloc[-1] / observations["Close"].iloc[0] - 1)
    benchmark_return = float(aligned["Close"].iloc[-1] / aligned["Close"].iloc[0] - 1)
    return ticker_return - benchmark_return


def _validate_frame(frame: pd.DataFrame, ticker: str, *, signal_date: date, min_rows: int) -> pd.DataFrame:
    required = {"Close", "Volume"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        raise ValueError(f"Insufficient price data for {ticker}: need {min_rows} rows")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans:
        raise ValueError(f"Dated daily price bars are required for {ticker}")
    frame = frame.copy()
    # A daily candle's provider-local date is its session label, not a UTC instant.
    frame.index = frame.index.tz_localize(None).normalize()
    frame = frame.loc[frame.index <= pd.Timestamp(signal_date)].sort_index()
    if frame.index.has_duplicates:
        raise ValueError(f"Duplicate daily price bars for {ticker}")
    if frame.empty or frame.index[-1].date() != signal_date:
        actual = frame.index[-1].date() if not frame.empty else None
        raise ValueError(f"Missing {signal_date} price bar for {ticker}; latest available: {actual}")
    if len(frame) < min_rows:
        raise ValueError(f"Insufficient price data for {ticker}: need {min_rows} rows through {signal_date}")
    frame = frame.tail(_HISTORY_TRADING_DAYS)
    for column in ("Close", "Volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(frame[column]).all():
            raise ValueError(f"Invalid {column} data for {ticker}")
    if (frame["Close"] <= 0).any() or (frame["Volume"] < 0).any():
        raise ValueError(f"Invalid price/volume data for {ticker}")
    return frame


def _default_asof_price_fetcher(ticker: str, signal_date: date, days: int) -> pd.DataFrame:
    from investment_assistant.data.price import get_price_history_asof

    # The shared helper converts trading observations to >= 2x calendar days.
    return get_price_history_asof(ticker, signal_date, days=days)
