from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pandas as pd

from investment_assistant.config import MarketConfig
from investment_assistant.market.models import MarketSignal


PriceFetcher = Callable[[str, int], pd.DataFrame]


def compute_market_signal(
    config: MarketConfig,
    *,
    price_fetcher: PriceFetcher | None = None,
    run_id: str | None = None,
    signal_date: date | None = None,
) -> MarketSignal:
    """Compute a row-ready broad-market signal from SPY and VIX data."""
    fetcher = price_fetcher or _default_price_fetcher
    spy_df = fetcher(config.spy_ticker, config.history_days)
    vix_df = fetcher(config.vix_ticker, 5)
    _validate_price_frame(spy_df, config.spy_ticker, min_rows=config.ma_days)
    _validate_price_frame(vix_df, config.vix_ticker, min_rows=1)

    spy_close = float(spy_df["Close"].iloc[-1])
    spy_ma = float(spy_df["Close"].tail(config.ma_days).mean())
    spy_above_200ma = bool(spy_close > spy_ma)
    vix_close = float(vix_df["Close"].iloc[-1])

    if vix_close > config.red_vix:
        status = "red"
    elif (not spy_above_200ma) or vix_close > config.yellow_vix:
        status = "yellow"
    else:
        status = "green"

    details = {
        "spy_rows": int(len(spy_df)),
        "vix_rows": int(len(vix_df)),
        "ma_days": config.ma_days,
        "history_days": config.history_days,
        "yellow_vix": config.yellow_vix,
        "red_vix": config.red_vix,
        "spy_latest_index": str(spy_df.index[-1]),
        "vix_latest_index": str(vix_df.index[-1]),
    }
    return MarketSignal(
        signal_date=signal_date or date.today(),
        market_status=status,
        spy_ticker=config.spy_ticker,
        spy_close=spy_close,
        spy_ma200=spy_ma,
        spy_above_200ma=spy_above_200ma,
        vix_ticker=config.vix_ticker,
        vix_close=vix_close,
        details=details,
        run_id=run_id,
    )


def compute_market_signal_for_date(
    config: MarketConfig,
    target_date: date,
    *,
    price_fetcher: PriceFetcher | None = None,
    run_id: str | None = None,
) -> MarketSignal:
    fetcher = price_fetcher or (lambda ticker, days: _default_price_fetcher_until(ticker, days, target_date))
    return compute_market_signal(config, price_fetcher=fetcher, run_id=run_id, signal_date=target_date)


def _default_price_fetcher_until(ticker: str, days: int, target_date: date) -> pd.DataFrame:
    import yfinance as yf

    calendar_days = max(days * 2, days + 30)
    start = target_date - timedelta(days=calendar_days)
    end = target_date + timedelta(days=1)
    df = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat())
    if df.empty:
        raise ValueError(f"No price data returned for {ticker} through {target_date}")
    return df[["Open", "High", "Low", "Close", "Volume"]]


def _default_price_fetcher(ticker: str, days: int) -> pd.DataFrame:
    from data.price import get_price_history

    return get_price_history(ticker, days=days)


def _validate_price_frame(df: pd.DataFrame, ticker: str, *, min_rows: int) -> None:
    if df.empty or "Close" not in df.columns or len(df) < min_rows:
        raise ValueError(f"Insufficient price data for {ticker}: need {min_rows} Close rows")
