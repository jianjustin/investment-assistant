import pandas as pd
import pytest
from unittest.mock import patch
from signals.technicals import compute_technicals, TechnicalSignal


def _price_df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    vols = volumes or [1_000_000.0] * n
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": vols,
        },
        index=idx,
    )


def test_rs_score_above_1_when_ticker_outperforms_spy():
    # Ticker +30% over period, SPY +10%
    ticker_closes = [100.0] * 60 + [130.0] * 70   # 130 bars total
    spy_closes = [400.0] * 60 + [440.0] * 70
    with patch("signals.technicals.get_price_history") as mock:
        mock.side_effect = [_price_df(ticker_closes), _price_df(spy_closes)]
        sig = compute_technicals("NVDA")
        assert sig.rs_score > 1.0


def test_ma_reclaim_detected_when_price_crosses_21ema():
    # 25 bars at 50 to establish EMA, then dip to 45 (yesterday), then 55 (today)
    closes = [50.0] * 25 + [45.0] + [55.0]
    with patch("signals.technicals.get_price_history") as mock:
        mock.side_effect = [
            _price_df(closes),
            _price_df([400.0] * len(closes)),  # SPY flat, for RS
        ]
        sig = compute_technicals("AAPL")
        assert sig.ma_reclaim is True


def test_no_signal_on_flat_price():
    # Flat price with constant volume — no VCP, no MA reclaim, RS ≈ 1.0
    closes = [100.0] * 130
    with patch("signals.technicals.get_price_history") as mock:
        mock.side_effect = [_price_df(closes), _price_df(closes)]
        sig = compute_technicals("FLAT")
        assert sig.vcp is False
        assert sig.ma_reclaim is False
        assert sig.has_signal is False


def test_vcp_detected_when_atr_and_volume_contract():
    # High volatility + high volume for first 70 bars, then tight + low volume for 20 bars
    high_closes = [100.0 + (i % 10) * 2 for i in range(70)]  # oscillates 100-118
    tight_closes = [110.0 + (i % 2) * 0.5 for i in range(20)]  # oscillates 110-110.5

    high_vols = [2_000_000.0] * 70
    tight_vols = [500_000.0] * 20

    with patch("signals.technicals.get_price_history") as mock:
        mock.side_effect = [
            _price_df(high_closes + tight_closes, high_vols + tight_vols),
            _price_df([400.0] * 90),  # SPY flat
        ]
        sig = compute_technicals("VCP_STOCK")
        assert sig.vcp is True
