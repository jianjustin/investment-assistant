from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable

import pandas as pd

from investment_assistant.config import DEFAULT_BACKTEST_HORIZONS, MarketConfig
from investment_assistant.data.calendar import is_trading_day, last_completed_trading_day

# v3 adds versioned source evidence, adjacent-session MA and single-strategy scores.
# This is also part of the service cache key; never reuse v2 persisted results.
SEMANTICS_VERSION = "event-study-v3-source-provenance"
ASOF_POLICY = "previous_nyse_session"

PriceFetcher = Callable[..., pd.DataFrame]
RegimeFn = Callable[[date], str]
AddTradingDays = Callable[[date, int], date]

_MIN_SAMPLE_DEFAULT = 30


@dataclass(frozen=True)
class Event:
    ticker: str
    date: date
    kind: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HorizonStat:
    horizon: int
    n: int
    mean_excess: float
    median: float
    hit_rate: float
    t_stat: float
    ci95: tuple[float, float]
    std: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "n": self.n,
            "mean_excess": self.mean_excess,
            "median": self.median,
            "hit_rate": self.hit_rate,
            "t_stat": self.t_stat,
            "ci95": list(self.ci95),
            "std": self.std,
        }


@dataclass(frozen=True)
class EventStudyResult:
    kind: str
    n: int
    horizons: dict[int, HorizonStat]
    by_regime: dict[str, dict[int, HorizonStat]]
    caveats: list[str]
    generated_at: datetime
    params: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "n": self.n,
            "horizons": {str(h): s.to_dict() for h, s in self.horizons.items()},
            "by_regime": {
                regime: {str(h): s.to_dict() for h, s in stats.items()}
                for regime, stats in self.by_regime.items()
            },
            "caveats": list(self.caveats),
            "generated_at": self.generated_at.isoformat(),
            "params": self.params,
        }


def resolve_asof(asof: date | None = None) -> date:
    """Bound even an explicit future/today cutoff by the last conservative close."""
    latest = last_completed_trading_day()
    return min(asof, latest) if asof is not None else latest


def _validate_horizons(horizons: tuple[int, ...]) -> None:
    if not horizons or any(isinstance(h, bool) or not isinstance(h, int) or h <= 0 for h in horizons):
        raise ValueError("horizons must contain positive integer trading-session counts")
    if len(set(horizons)) != len(horizons):
        raise ValueError("horizons must not contain duplicates")


def _asof_close(ticker: str, on: date, *, price_fetcher: PriceFetcher) -> float | None:
    """Return ONLY the dated session's close, never a prior/future fallback.

    Daily DatetimeIndex labels retain their exchange-local date (including tz).
    An ambiguous duplicate, undated row, non-finite or non-positive close is not
    an available endpoint. Stock and benchmark use these same explicit dates.
    """
    try:
        frame = price_fetcher(ticker, on, days=10)
        if frame is None or frame.empty or "Close" not in frame.columns:
            return None
        if not isinstance(frame.index, pd.DatetimeIndex):
            return None
        rows = frame.loc[frame.index.date == on, "Close"]
        if len(rows) != 1:
            return None
        value = float(rows.iloc[0])
        return value if math.isfinite(value) and value > 0 else None
    except Exception:
        return None


def forward_excess_return(
    ticker: str,
    event_date: date,
    horizon: int,
    *,
    benchmark: str,
    price_fetcher: PriceFetcher,
    add_trading_days_fn: AddTradingDays,
    asof: date | None = None,
) -> float | None:
    """Mature, exact-session stock return minus the same benchmark return.

    `asof` bounds outcome availability, not just event selection. Missing or stale
    endpoints are excluded instead of shortening the holding period.
    """
    _validate_horizons((horizon,))
    cutoff = resolve_asof(asof)
    if event_date > cutoff or not is_trading_day(event_date):
        return None
    forward_date = add_trading_days_fn(event_date, horizon)
    if forward_date <= event_date or forward_date > cutoff or not is_trading_day(forward_date):
        return None
    t0 = _asof_close(ticker, event_date, price_fetcher=price_fetcher)
    t1 = _asof_close(ticker, forward_date, price_fetcher=price_fetcher)
    b0 = _asof_close(benchmark, event_date, price_fetcher=price_fetcher)
    b1 = _asof_close(benchmark, forward_date, price_fetcher=price_fetcher)
    if None in (t0, t1, b0, b1):
        return None
    excess = (t1 / t0 - 1) - (b1 / b0 - 1)
    return excess if math.isfinite(excess) else None


def _stat(horizon: int, samples: list[float]) -> HorizonStat:
    n = len(samples)
    if n == 0:
        return HorizonStat(horizon, 0, 0.0, 0.0, 0.0, 0.0, (0.0, 0.0), 0.0)
    mean = sum(samples) / n
    ordered = sorted(samples)
    mid = n // 2
    median = ordered[mid] if n % 2 == 1 else (ordered[mid - 1] + ordered[mid]) / 2
    hit_rate = sum(1 for s in samples if s > 0) / n
    if n > 1:
        var = sum((s - mean) ** 2 for s in samples) / (n - 1)
        std = math.sqrt(var)
    else:
        std = 0.0
    se = std / math.sqrt(n) if (std > 0 and n > 0) else 0.0
    t_stat = mean / se if se > 0 else 0.0
    ci95 = (mean - 1.96 * se, mean + 1.96 * se)
    return HorizonStat(horizon, n, mean, median, hit_rate, t_stat, ci95, std)


def run_event_study(
    events: list[Event],
    *,
    horizons: tuple[int, ...] = DEFAULT_BACKTEST_HORIZONS,
    benchmark: str = "SPY",
    asof: date | None = None,
    price_fetcher: PriceFetcher | None = None,
    regime_fn: RegimeFn | None = None,
    add_trading_days_fn: AddTradingDays | None = None,
    min_sample: int = _MIN_SAMPLE_DEFAULT,
) -> EventStudyResult:
    _validate_horizons(horizons)
    cutoff = resolve_asof(asof)
    if price_fetcher is None:
        from investment_assistant.data.price import get_price_history_asof
        price_fetcher = get_price_history_asof
    if add_trading_days_fn is None:
        from investment_assistant.data.calendar import add_trading_days
        add_trading_days_fn = add_trading_days
    if regime_fn is None:
        regime_fn = _default_regime_fn

    kind = events[0].kind if events else "unknown"

    pooled: dict[int, list[float]] = defaultdict(list)
    by_regime_samples: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    skipped: list[dict[str, Any]] = []

    for ev in events:
        identity = {"ticker": ev.ticker, "date": ev.date.isoformat()}
        if ev.date > cutoff:
            skipped.append({**identity, "stage": "event", "error": "event_after_asof"})
            continue
        if not is_trading_day(ev.date):
            skipped.append({**identity, "stage": "event", "error": "non_trading_event_date"})
            continue
        # No regime or price lookup is needed when every requested horizon is immature.
        mature: list[int] = []
        for h in horizons:
            forward_date = add_trading_days_fn(ev.date, h)
            if forward_date > cutoff:
                skipped.append({**identity, "horizon": h, "forward_date": forward_date.isoformat(),
                                "stage": "maturity", "error": "horizon_not_mature"})
            elif forward_date <= ev.date or not is_trading_day(forward_date):
                skipped.append({**identity, "horizon": h, "forward_date": forward_date.isoformat(),
                                "stage": "calendar", "error": "invalid_forward_session"})
            else:
                mature.append(h)
        if not mature:
            continue
        try:
            regime = regime_fn(ev.date)
        except Exception:  # 区制取不到不阻断；标 unknown。不保留异常文本，避免连接串等细节泄漏。
            regime = "unknown"
            skipped.append({**identity, "stage": "regime", "error": "regime_unavailable"})
        for h in mature:
            excess = forward_excess_return(
                ev.ticker, ev.date, h, benchmark=benchmark, asof=cutoff,
                price_fetcher=price_fetcher, add_trading_days_fn=add_trading_days_fn,
            )
            if excess is None:
                skipped.append({**identity, "horizon": h, "stage": "price",
                                "error": "missing_exact_session_price"})
                continue
            pooled[h].append(excess)
            by_regime_samples[regime][h].append(excess)

    horizons_stats = {h: _stat(h, pooled.get(h, [])) for h in horizons}
    by_regime = {
        regime: {h: _stat(h, samples.get(h, [])) for h in horizons}
        for regime, samples in by_regime_samples.items()
    }

    n = max((s.n for s in horizons_stats.values()), default=0)
    caveats: list[str] = []
    undersampled = [h for h, s in horizons_stats.items() if s.n < min_sample]
    if undersampled:
        caveats.append(f"n<{min_sample}, 结论不可信")
    if any(ev.meta.get("source") == "placeholder" for ev in events):
        caveats.append("事件来源含占位数据（yfinance earnings_dates），不作去留结论依据")
    if any(ev.kind == "ma_reclaim" for ev in events):
        caveats.append("ma_reclaim 是收盘价上穿20日简单移动平均线（SMA20），不是21EMA")
    if skipped:
        caveats.append(f"{len(skipped)} 个事件/horizon 因未成熟、日期/精确收盘价或区制不可用被跳过")
    source_quality = getattr(events, "source_quality", None)
    if source_quality and source_quality.get("excluded_count", 0):
        caveats.append(
            f"来源质量排除 {source_quality['excluded_count']} 行（日期/版本/连续性等证据不合格）；"
            "来源不足不代表信号无效，不作去留结论"
        )

    params = {
        "semantics_version": SEMANTICS_VERSION,
        "asof": cutoff.isoformat(),
        "asof_policy": ASOF_POLICY,
        "endpoint_policy": "exact_same_nyse_sessions_no_fill",
        "horizons": list(horizons),
        "benchmark": benchmark,
        "min_sample": min_sample,
        "events_in": len(events),
        "skipped": skipped,
    }
    if source_quality is not None:
        params["source_quality"] = source_quality
    return EventStudyResult(
        kind=kind, n=n, horizons=horizons_stats, by_regime=by_regime,
        caveats=caveats, generated_at=datetime.now(UTC), params=params,
    )


def regime_fn_for_config(market: MarketConfig) -> RegimeFn:
    """Bind the same market config used by the caller/cache key, without reloads."""
    def classify(d: date) -> str:
        from investment_assistant.market.service import compute_market_signal_for_date
        return compute_market_signal_for_date(market, d).market_status
    return classify


def _default_regime_fn(d: date) -> str:
    from investment_assistant.config import load_config
    return regime_fn_for_config(load_config().market)(d)


def _cli_main() -> None:
    """委托到 tasks.event_study.main，对齐 roadmap 文档化的调用路径（DRY，不复制 argparse）。"""
    from investment_assistant.tasks.event_study import main as _task_main

    _task_main()


if __name__ == "__main__":
    _cli_main()
