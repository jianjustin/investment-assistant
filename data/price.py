import yfinance as yf
import pandas as pd


def get_price_history(ticker: str, days: int = 90) -> pd.DataFrame:
    """Return OHLCV DataFrame for ticker over the last `days` calendar days."""
    df = yf.Ticker(ticker).history(period=f"{days}d")
    if df.empty:
        raise ValueError(f"No price data returned for {ticker}")
    return df[["Open", "High", "Low", "Close", "Volume"]]
