import pandas as pd

from investment_assistant.config import MarketConfig
from investment_assistant.market.service import compute_market_signal


def _df(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {"Close": closes, "Open": closes, "High": closes, "Low": closes, "Volume": [1] * len(closes)},
        index=idx,
    )


def test_compute_market_signal_green_when_spy_above_ma_and_vix_low():
    def fetcher(ticker, days):
        if ticker == "SPY":
            return _df([100.0] * 100 + [120.0] * 219 + [130.0])
        return _df([15.0])

    signal = compute_market_signal(MarketConfig(), price_fetcher=fetcher, run_id="run-1")

    assert signal.market_status == "green"
    assert signal.spy_above_200ma is True
    assert signal.spy_close == 130.0
    assert signal.vix_close == 15.0
    assert signal.run_id == "run-1"
    assert signal.details["spy_rows"] == 320


def test_compute_market_signal_red_when_vix_above_threshold():
    def fetcher(ticker, days):
        if ticker == "SPY":
            return _df([100.0] * 100 + [120.0] * 220)
        return _df([35.0])

    signal = compute_market_signal(MarketConfig(), price_fetcher=fetcher)
