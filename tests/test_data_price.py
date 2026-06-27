import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from investment_assistant.data.price import get_price_history


def test_get_price_history_returns_ohlcv_columns():
    frame = pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100], "Dividends": [0]}
    )
    fake = MagicMock()
    fake.history.return_value = frame
    with patch("investment_assistant.data.price.yf.Ticker", return_value=fake) as ticker:
        result = get_price_history("NVDA", days=30)
    ticker.assert_called_once_with("NVDA")
    fake.history.assert_called_once_with(period="30d")
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_get_price_history_raises_on_empty():
    fake = MagicMock()
    fake.history.return_value = pd.DataFrame()
    with patch("investment_assistant.data.price.yf.Ticker", return_value=fake):
        with pytest.raises(ValueError):
            get_price_history("ZZZZ")
