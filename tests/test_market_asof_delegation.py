from datetime import date

import pandas as pd

from investment_assistant.market import service


def test_default_price_fetcher_until_delegates_to_asof(monkeypatch):
    captured = {}

    def fake_asof(ticker, end_date, *, days, fetcher=None):
        captured["ticker"] = ticker
        captured["end_date"] = end_date
        captured["days"] = days
        idx = pd.to_datetime(["2024-02-27", "2024-02-28"])
        return pd.DataFrame(
            {"Open": [1, 1], "High": [1, 1], "Low": [1, 1], "Close": [1, 1], "Volume": [1, 1]},
            index=idx,
        )

    monkeypatch.setattr(service, "get_price_history_asof", fake_asof)
    out = service._default_price_fetcher_until("SPY", 60, date(2024, 2, 28))
    assert captured == {"ticker": "SPY", "end_date": date(2024, 2, 28), "days": 60}
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
