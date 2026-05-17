import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from data.price import get_price_history


def test_get_price_history_returns_dataframe():
    mock_df = pd.DataFrame(
        {"Open": [100.0], "High": [105.0], "Low": [99.0], "Close": [103.0], "Volume": [1_000_000]},
        index=pd.to_datetime(["2026-05-16"]),
    )
    with patch("data.price.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = mock_df
        result = get_price_history("AAPL", days=90)
        assert isinstance(result, pd.DataFrame)
        assert "Close" in result.columns
        assert len(result) >= 1


def test_get_price_history_raises_on_empty():
    with patch("data.price.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        with pytest.raises(ValueError, match="No price data"):
            get_price_history("FAKEFAKE", days=90)


def test_get_price_history_returns_correct_columns():
    mock_df = pd.DataFrame(
        {
            "Open": [100.0], "High": [105.0], "Low": [99.0],
            "Close": [103.0], "Volume": [1_000_000],
            "Dividends": [0.0], "Stock Splits": [0.0],
        },
        index=pd.to_datetime(["2026-05-16"]),
    )
    with patch("data.price.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = mock_df
        result = get_price_history("AAPL", days=90)
        assert set(result.columns) == {"Open", "High", "Low", "Close", "Volume"}
