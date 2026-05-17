import pandas as pd
import pytest
from unittest.mock import patch
from signals.market import get_market_condition, MarketCondition


def _spy_df(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1_000_000] * len(closes)},
        index=idx,
    )


def _vix_df(close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": [close], "High": [close], "Low": [close], "Close": [close], "Volume": [0]},
        index=pd.to_datetime(["2026-05-16"]),
    )


def test_green_when_spy_bull_and_low_vix():
    # SPY trending up, well above 200MA; VIX = 15
    spy_closes = [100.0] * 150 + [120.0] * 60
    with patch("signals.market.get_price_history") as mock:
        mock.side_effect = [_spy_df(spy_closes), _vix_df(15.0)]
        cond = get_market_condition()
        assert cond.status == "green"
        assert cond.spy_above_200ma is True
        assert cond.vix == pytest.approx(15.0)


def test_red_when_vix_above_30():
    spy_closes = [100.0] * 150 + [120.0] * 60
    with patch("signals.market.get_price_history") as mock:
        mock.side_effect = [_spy_df(spy_closes), _vix_df(35.0)]
        cond = get_market_condition()
        assert cond.status == "red"


def test_yellow_when_spy_below_200ma():
    # SPY drops below 200MA; VIX = 18 (below 20)
    spy_closes = [120.0] * 150 + [90.0] * 60
    with patch("signals.market.get_price_history") as mock:
        mock.side_effect = [_spy_df(spy_closes), _vix_df(18.0)]
        cond = get_market_condition()
        assert cond.status == "yellow"
        assert cond.spy_above_200ma is False


def test_yellow_when_vix_between_20_and_30():
    spy_closes = [100.0] * 150 + [110.0] * 60
    with patch("signals.market.get_price_history") as mock:
        mock.side_effect = [_spy_df(spy_closes), _vix_df(25.0)]
        cond = get_market_condition()
        assert cond.status == "yellow"
