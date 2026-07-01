from datetime import date

import pandas as pd

from investment_assistant.research.event_study import (
    Event,
    EventStudyResult,
    run_event_study,
)


def _make_fetcher(price_map):
    """price_map: {(ticker, 'YYYY-MM-DD'): close}. 返回 asof fetcher 兼容签名。"""
    def fetcher(ticker, end_date, *, days=260, fetcher=None):
        key = (ticker, end_date.isoformat())
        if key not in price_map:
            raise ValueError(f"no price for {key}")
        close = price_map[key]
        idx = pd.to_datetime([end_date.isoformat()])
        return pd.DataFrame(
            {"Open": [close], "High": [close], "Low": [close], "Close": [close], "Volume": [1]},
            index=idx,
        )
    return fetcher


def _add_td(d, n):
    # 测试用确定性日历：+n 个自然日（避开真实假日逻辑，专注统计正确性）
    from datetime import timedelta
    return d + timedelta(days=n)


def test_mean_excess_and_basis_subtraction():
    # 事件 NVDA @2024-03-01；horizon=5。
    # 事件日(asof=event_date)价：NVDA=100, SPY=400
    # 前瞻日(event_date+5)价：NVDA=110 (+10%), SPY=420 (+5%)
    # 超额收益 = 10% - 5% = 5%
    price_map = {
        ("NVDA", "2024-03-01"): 100.0, ("SPY", "2024-03-01"): 400.0,
        ("NVDA", "2024-03-06"): 110.0, ("SPY", "2024-03-06"): 420.0,
    }
    events = [Event("NVDA", date(2024, 3, 1), "rs_strong")]
    result = run_event_study(
        events, horizons=(5,), benchmark="SPY",
        price_fetcher=_make_fetcher(price_map),
        regime_fn=lambda d: "green",
        add_trading_days_fn=_add_td,
    )
    assert isinstance(result, EventStudyResult)
    stat = result.horizons[5]
    assert stat.n == 1
    assert abs(stat.mean_excess - 0.05) < 1e-9
    assert stat.hit_rate == 1.0


def test_small_sample_caveat_added():
    price_map = {
        ("NVDA", "2024-03-01"): 100.0, ("SPY", "2024-03-01"): 400.0,
        ("NVDA", "2024-03-06"): 110.0, ("SPY", "2024-03-06"): 420.0,
    }
    events = [Event("NVDA", date(2024, 3, 1), "rs_strong")]
    result = run_event_study(
        events, horizons=(5,), price_fetcher=_make_fetcher(price_map),
        regime_fn=lambda d: "green", add_trading_days_fn=_add_td,
    )
    assert any("n<30" in c or "n < 30" in c for c in result.caveats)


def test_hit_rate_counts_positive_excess():
    # 两个事件：一个 +5% 超额，一个 -2% 超额 → hit_rate=0.5
    price_map = {
        ("AAA", "2024-03-01"): 100.0, ("SPY", "2024-03-01"): 400.0,
        ("AAA", "2024-03-06"): 110.0, ("SPY", "2024-03-06"): 420.0,   # +10% vs +5% = +5%
        ("BBB", "2024-04-01"): 100.0, ("SPY", "2024-04-01"): 400.0,
        ("BBB", "2024-04-06"): 103.0, ("SPY", "2024-04-06"): 420.0,   # +3% vs +5% = -2%
    }
    events = [Event("AAA", date(2024, 3, 1), "rs_strong"),
              Event("BBB", date(2024, 4, 1), "rs_strong")]
    result = run_event_study(
        events, horizons=(5,), price_fetcher=_make_fetcher(price_map),
        regime_fn=lambda d: "green", add_trading_days_fn=_add_td,
    )
    assert result.horizons[5].n == 2
    assert result.horizons[5].hit_rate == 0.5


def test_regime_partitioning_invokes_regime_fn():
    calls = []

    def regime_fn(d):
        calls.append(d)
        return "red" if d.month == 3 else "green"

    price_map = {
        ("AAA", "2024-03-01"): 100.0, ("SPY", "2024-03-01"): 400.0,
        ("AAA", "2024-03-06"): 110.0, ("SPY", "2024-03-06"): 420.0,
        ("BBB", "2024-04-01"): 100.0, ("SPY", "2024-04-01"): 400.0,
        ("BBB", "2024-04-06"): 103.0, ("SPY", "2024-04-06"): 420.0,
    }
    events = [Event("AAA", date(2024, 3, 1), "rs_strong"),
              Event("BBB", date(2024, 4, 1), "rs_strong")]
    result = run_event_study(
        events, horizons=(5,), price_fetcher=_make_fetcher(price_map),
        regime_fn=regime_fn, add_trading_days_fn=_add_td,
    )
    assert len(calls) >= 2
    assert "red" in result.by_regime and "green" in result.by_regime
    assert result.by_regime["red"][5].n == 1
    assert result.by_regime["green"][5].n == 1


def test_skipped_events_recorded_not_raised():
    # BBB 取价缺失 → 跳过，不报错；params.skipped 记录
    price_map = {
        ("AAA", "2024-03-01"): 100.0, ("SPY", "2024-03-01"): 400.0,
        ("AAA", "2024-03-06"): 110.0, ("SPY", "2024-03-06"): 420.0,
    }
    events = [Event("AAA", date(2024, 3, 1), "rs_strong"),
              Event("BBB", date(2024, 4, 1), "rs_strong")]
    result = run_event_study(
        events, horizons=(5,), price_fetcher=_make_fetcher(price_map),
        regime_fn=lambda d: "green", add_trading_days_fn=_add_td,
    )
    assert result.horizons[5].n == 1
    assert len(result.params["skipped"]) == 1
    assert result.params["skipped"][0]["ticker"] == "BBB"


def test_to_dict_is_json_friendly():
    price_map = {
        ("AAA", "2024-03-01"): 100.0, ("SPY", "2024-03-01"): 400.0,
        ("AAA", "2024-03-06"): 110.0, ("SPY", "2024-03-06"): 420.0,
    }
    events = [Event("AAA", date(2024, 3, 1), "rs_strong")]
    result = run_event_study(
        events, horizons=(5,), price_fetcher=_make_fetcher(price_map),
        regime_fn=lambda d: "green", add_trading_days_fn=_add_td,
    )
    d = result.to_dict()
    assert d["kind"] == "rs_strong"
    assert d["horizons"]["5"]["mean_excess"] is not None
    import json
    json.dumps(d)  # 不抛 = JSON 可序列化
