from datetime import date

import pandas as pd
import pytest

from investment_assistant.data.price import detect_split_jumps, get_price_history_asof


def _frame(dates, closes):
    idx = pd.to_datetime(dates)
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [100] * len(closes)},
        index=idx,
    )


def test_asof_excludes_bars_after_end_date():
    frame = _frame(
        ["2024-02-26", "2024-02-27", "2024-02-28", "2024-03-01", "2024-03-04"],
        [10.0, 11.0, 12.0, 13.0, 14.0],
    )
    fetched = get_price_history_asof("NVDA", date(2024, 2, 28), days=60, fetcher=lambda t, e, d: frame)
    assert str(fetched.index.max().date()) == "2024-02-28"
    assert all(ts.date() <= date(2024, 2, 28) for ts in fetched.index)


def test_asof_limits_row_count_to_days():
    frame = _frame([f"2024-01-{i:02d}" for i in range(1, 11)], list(range(1, 11)))
    fetched = get_price_history_asof("NVDA", date(2024, 1, 10), days=3, fetcher=lambda t, e, d: frame)
    assert len(fetched) == 3
    assert str(fetched.index.max().date()) == "2024-01-10"


def test_asof_raises_when_empty():
    empty = pd.DataFrame()
    with pytest.raises(ValueError):
        get_price_history_asof("ZZZZ", date(2024, 1, 10), fetcher=lambda t, e, d: empty)


def test_detect_split_jumps_flags_unadjusted_split():
    # 2:1 split 未复权：相邻收益约 -50%
    frame = _frame(["2024-06-07", "2024-06-10"], [120.0, 60.0])
    jumps = detect_split_jumps(frame, threshold=0.5)
    assert len(jumps) == 1
    assert jumps[0]["suspected"] == "unadjusted_split"
    assert str(jumps[0]["date"]) == "2024-06-10"


def test_detect_split_jumps_clean_series_no_flag():
    frame = _frame(["2024-06-07", "2024-06-10", "2024-06-11"], [120.0, 122.0, 119.0])
    assert detect_split_jumps(frame, threshold=0.5) == []


def test_detect_split_jumps_exempts_earnings_day():
    frame = _frame(["2024-06-07", "2024-06-10"], [120.0, 60.0])
    jumps = detect_split_jumps(frame, threshold=0.5, earnings_dates={date(2024, 6, 10)})
    assert jumps == []
