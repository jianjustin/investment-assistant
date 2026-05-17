from dataclasses import dataclass
import pandas as pd
from data.price import get_price_history


@dataclass
class TechnicalSignal:
    rs_score: float
    vcp: bool
    ma_reclaim: bool

    @property
    def has_signal(self) -> bool:
        return bool(self.vcp or self.ma_reclaim or self.rs_score >= 1.2)


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    return pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_technicals(ticker: str) -> TechnicalSignal:
    """Compute RS score, VCP, and MA Reclaim signals for a ticker."""
    df = get_price_history(ticker, days=200)
    spy_df = get_price_history("SPY", days=200)

    # RS Score: 6-month (126 trading day approx) return ratio
    n = min(126, len(df) - 1, len(spy_df) - 1)
    ticker_return = df["Close"].iloc[-1] / df["Close"].iloc[-(n + 1)]
    spy_return = spy_df["Close"].iloc[-1] / spy_df["Close"].iloc[-(n + 1)]
    rs_score = ticker_return / spy_return if spy_return != 0 else 0.0

    # VCP: recent 20-bar ATR < 70% of 60-bar ATR, and recent volume contracting
    tr = _true_range(df)
    atr_20 = tr.tail(20).mean()
    atr_60 = tr.tail(60).mean()
    vol_20 = df["Volume"].tail(20).mean()
    vol_60 = df["Volume"].tail(60).mean()
    vcp = bool((atr_20 < atr_60 * 0.70) and (vol_20 < vol_60 * 0.70))

    # MA Reclaim: yesterday close < 21-EMA, today close > 21-EMA
    ema21 = _ema(df["Close"], 21)
    ma_reclaim = bool(
        df["Close"].iloc[-2] < ema21.iloc[-2]
        and df["Close"].iloc[-1] > ema21.iloc[-1]
    )

    return TechnicalSignal(rs_score=rs_score, vcp=vcp, ma_reclaim=ma_reclaim)
