from datetime import date

import pandas as pd
import pytest

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
    # 统计测试用确定性偏移；所选事件和端点仍须落在真实 NYSE 交易日。
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
        ("BBB", "2024-04-03"): 100.0, ("SPY", "2024-04-03"): 400.0,
        ("BBB", "2024-04-08"): 103.0, ("SPY", "2024-04-08"): 420.0,   # +3% vs +5% = -2%
    }
    events = [Event("AAA", date(2024, 3, 1), "rs_strong"),
              Event("BBB", date(2024, 4, 3), "rs_strong")]
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
        ("BBB", "2024-04-03"): 100.0, ("SPY", "2024-04-03"): 400.0,
        ("BBB", "2024-04-08"): 103.0, ("SPY", "2024-04-08"): 420.0,
    }
    events = [Event("AAA", date(2024, 3, 1), "rs_strong"),
              Event("BBB", date(2024, 4, 3), "rs_strong")]
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
              Event("BBB", date(2024, 4, 3), "rs_strong")]
    result = run_event_study(
        events, horizons=(5,), price_fetcher=_make_fetcher(price_map),
        regime_fn=lambda d: "green", add_trading_days_fn=_add_td,
    )
    assert result.horizons[5].n == 1
    assert len(result.params["skipped"]) == 1
    assert result.params["skipped"][0]["ticker"] == "BBB"


def test_caveat_fires_when_any_horizon_undersampled():
    # horizon=5 解析成功 (n=1)，horizon=20 缺失前瞻价 (n=0)
    # min_sample=1：旧 max(1,0)=1 不触发 caveat；新逻辑检测任意 horizon n<1 应触发
    price_map = {
        ("NVDA", "2024-03-01"): 100.0, ("SPY", "2024-03-01"): 400.0,
        ("NVDA", "2024-03-06"): 110.0, ("SPY", "2024-03-06"): 420.0,
        # horizon=20 的前瞻日 (2024-03-21) 故意缺失，迫使该 horizon n=0
    }
    events = [Event("NVDA", date(2024, 3, 1), "rs_strong")]
    result = run_event_study(
        events, horizons=(5, 20), price_fetcher=_make_fetcher(price_map),
        regime_fn=lambda d: "green", add_trading_days_fn=_add_td,
        min_sample=1,
    )
    # EventStudyResult.n 应保留 max(1, 0)=1（最佳覆盖数）
    assert result.n == 1
    # 但 horizon=20 的 n=0 < min_sample=1，统计诚实要求 caveat 必须出现
    assert any("n<1" in c for c in result.caveats), (
        f"期望含 'n<1' 的 caveat，实际 caveats={result.caveats}"
    )


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


def test_research_cli_delegates_to_task(monkeypatch):
    import investment_assistant.research.event_study as rs
    called = {}
    monkeypatch.setattr("investment_assistant.tasks.event_study.main",
                        lambda: called.setdefault("ran", True))
    rs._cli_main()
    assert called.get("ran") is True


def test_unmatured_horizon_never_fetches_prices_or_counts_last_available_close():
    calls = []

    def stale_fetcher(ticker, end_date, **kw):
        calls.append((ticker, end_date))
        return pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2024-03-01"]))

    result = run_event_study(
        [Event("AAA", date(2024, 3, 1), "score_high")], horizons=(5,),
        asof=date(2024, 3, 7), price_fetcher=stale_fetcher, regime_fn=lambda d: "green",
    )
    assert result.horizons[5].n == 0
    assert calls == []
    assert result.params["asof"] == "2024-03-07"
    assert result.params["skipped"][0]["error"] == "horizon_not_mature"
    assert result.params["skipped"][0]["forward_date"] == "2024-03-08"


def test_asof_censors_each_horizon_even_when_future_prices_exist():
    calls = []

    def future_fetcher(ticker, end_date, **kw):
        calls.append(end_date)
        return pd.DataFrame({"Close": [100.0, 110.0, 120.0, 999.0]},
                            index=pd.to_datetime(["2024-03-01", "2024-03-04", "2024-03-08", "2024-04-03"]))

    result = run_event_study(
        [Event("AAA", date(2024, 3, 1), "score_high")], horizons=(1, 5, 20),
        asof=date(2024, 3, 8), price_fetcher=future_fetcher, regime_fn=lambda d: "green",
    )
    assert [result.horizons[h].n for h in (1, 5, 20)] == [1, 1, 0]
    assert max(calls) == date(2024, 3, 8)
    assert result.horizons[5].mean_excess == 0.0


@pytest.mark.parametrize("bad_endpoint", [("AAA", "2024-03-01"), ("AAA", "2024-03-08"),
                                         ("SPY", "2024-03-01"), ("SPY", "2024-03-08")])
@pytest.mark.parametrize("mode", ["stale", "future", "nan", "inf", "zero", "negative", "duplicate", "undated"])
def test_each_stock_and_benchmark_endpoint_must_be_exact_finite_positive(bad_endpoint, mode):
    from datetime import timedelta
    from investment_assistant.research.event_study import forward_excess_return
    from investment_assistant.data.calendar import add_trading_days

    def fetcher(ticker, end_date, **kw):
        ds, values = [end_date], [100.0]
        if (ticker, end_date.isoformat()) == bad_endpoint:
            if mode == "stale":
                ds = [end_date - timedelta(days=1)]
            elif mode == "future":
                ds = [end_date + timedelta(days=1)]
            elif mode == "duplicate":
                ds, values = [end_date, end_date], [100.0, 101.0]
            elif mode == "undated":
                return pd.DataFrame({"Close": values})
            else:
                values = [{"nan": float("nan"), "inf": float("inf"), "zero": 0, "negative": -1}[mode]]
        return pd.DataFrame({"Close": values}, index=pd.to_datetime(ds))

    assert forward_excess_return(
        "AAA", date(2024, 3, 1), 5, benchmark="SPY", price_fetcher=fetcher,
        add_trading_days_fn=add_trading_days,
    ) is None


def test_exact_endpoints_are_selected_from_unsorted_timezone_aware_frames():
    from investment_assistant.research.event_study import forward_excess_return
    from investment_assistant.data.calendar import add_trading_days

    def fetcher(ticker, end_date, **kw):
        values = [110.0, 100.0, 999.0] if ticker == "AAA" else [420.0, 400.0, 999.0]
        return pd.DataFrame({"Close": values}, index=pd.to_datetime(
            ["2024-03-08", "2024-03-01", "2024-04-03"]).tz_localize("America/New_York"))

    assert forward_excess_return(
        "AAA", date(2024, 3, 1), 5, benchmark="SPY", price_fetcher=fetcher,
        add_trading_days_fn=add_trading_days,
    ) == pytest.approx(0.05)


@pytest.mark.parametrize("event_day,error", [(date(2024, 3, 11), "event_after_asof"),
                                              (date(2024, 3, 2), "non_trading_event_date")])
def test_invalid_event_date_never_reaches_price_or_regime(event_day, error):
    def forbidden(*a, **kw):
        pytest.fail("invalid event must be excluded before data lookup")

    result = run_event_study([Event("AAA", event_day, "score_high")], asof=date(2024, 3, 8),
                             price_fetcher=forbidden, regime_fn=forbidden)
    assert result.n == 0
    assert result.params["skipped"][0]["error"] == error


def test_default_horizons_match_existing_config_not_one_five_twenty():
    from investment_assistant.config import BacktestConfig
    result = run_event_study([])
    assert list(result.horizons) == BacktestConfig().horizons == [5, 10, 20]


def test_default_and_future_cutoff_exclude_today_even_if_fetcher_has_its_close(monkeypatch):
    import investment_assistant.research.event_study as study
    monkeypatch.setattr(study, "last_completed_trading_day", lambda: date(2024, 3, 7))
    for requested in (None, date(2024, 3, 8), date(2099, 1, 1)):
        result = study.run_event_study([], asof=requested)
        assert result.params["asof"] == "2024-03-07"
        assert result.params["asof_policy"] == "previous_nyse_session"


def test_ma_reclaim_result_is_not_labelled_ema():
    result = run_event_study([Event("AAA", date(2024, 3, 1), "ma_reclaim")],
                             asof=date(2024, 3, 1), regime_fn=lambda d: "green")
    assert any("SMA20" in c and "21EMA" in c for c in result.caveats)


@pytest.mark.parametrize("horizons", [(0,), (-1,), (1.5,), (True,), ()])
def test_invalid_horizons_are_rejected(horizons):
    with pytest.raises(ValueError, match="horizon"):
        run_event_study([], horizons=horizons)


def test_regime_failure_does_not_leak_database_details_into_result():
    def fail(d):
        raise RuntimeError("postgres://user:private-secret@host SELECT private_table")
    result = run_event_study(
        [Event("AAA", date(2024, 3, 1), "score_high")], horizons=(5,), asof=date(2024, 3, 8),
        price_fetcher=lambda *a, **kw: pd.DataFrame(), regime_fn=fail,
    ).to_dict()
    assert "private-secret" not in str(result) and "private_table" not in str(result)
    assert result["params"]["skipped"][0]["error"] == "regime_unavailable"
