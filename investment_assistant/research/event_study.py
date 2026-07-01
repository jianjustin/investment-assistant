from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable

import pandas as pd

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


def _asof_close(ticker: str, on: date, *, price_fetcher: PriceFetcher) -> float | None:
    """取截至 on（含）的最后一个收盘价；缺失返回 None。"""
    try:
        frame = price_fetcher(ticker, on, days=10)
    except Exception:
        return None
    if frame is None or frame.empty or "Close" not in frame.columns:
        return None
    return float(frame["Close"].iloc[-1])


def forward_excess_return(
    ticker: str,
    event_date: date,
    horizon: int,
    *,
    benchmark: str,
    price_fetcher: PriceFetcher,
    add_trading_days_fn: AddTradingDays,
) -> float | None:
    """个股前瞻收益 − 同期基准前瞻收益（超额收益）。任一取价缺失 → None。"""
    forward_date = add_trading_days_fn(event_date, horizon)
    t0 = _asof_close(ticker, event_date, price_fetcher=price_fetcher)
    t1 = _asof_close(ticker, forward_date, price_fetcher=price_fetcher)
    b0 = _asof_close(benchmark, event_date, price_fetcher=price_fetcher)
    b1 = _asof_close(benchmark, forward_date, price_fetcher=price_fetcher)
    if None in (t0, t1, b0, b1) or t0 == 0 or b0 == 0:
        return None
    return (t1 / t0 - 1) - (b1 / b0 - 1)


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
    horizons: tuple[int, ...] = (1, 5, 20),
    benchmark: str = "SPY",
    price_fetcher: PriceFetcher | None = None,
    regime_fn: RegimeFn | None = None,
    add_trading_days_fn: AddTradingDays | None = None,
    min_sample: int = _MIN_SAMPLE_DEFAULT,
) -> EventStudyResult:
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
        try:
            regime = regime_fn(ev.date)
        except Exception as exc:  # 区制取不到不阻断；标 unknown
            regime = "unknown"
            skipped.append({"ticker": ev.ticker, "date": ev.date.isoformat(),
                            "stage": "regime", "error": str(exc)})
        for h in horizons:
            excess = forward_excess_return(
                ev.ticker, ev.date, h, benchmark=benchmark,
                price_fetcher=price_fetcher, add_trading_days_fn=add_trading_days_fn,
            )
            if excess is None:
                skipped.append({"ticker": ev.ticker, "date": ev.date.isoformat(),
                                "horizon": h, "stage": "price", "error": "missing price"})
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
    if skipped:
        caveats.append(f"{len(skipped)} 个事件/horizon 因取价或区制缺失被跳过")

    params = {
        "horizons": list(horizons),
        "benchmark": benchmark,
        "min_sample": min_sample,
        "events_in": len(events),
        "skipped": skipped,
    }
    return EventStudyResult(
        kind=kind, n=n, horizons=horizons_stats, by_regime=by_regime,
        caveats=caveats, generated_at=datetime.now(UTC), params=params,
    )


def _default_regime_fn(d: date) -> str:
    from investment_assistant.config import load_config
    from investment_assistant.market.service import compute_market_signal_for_date

    signal = compute_market_signal_for_date(load_config().market, d)
    return signal.market_status


def _cli_main() -> None:
    """委托到 tasks.event_study.main，对齐 roadmap 文档化的调用路径（DRY，不复制 argparse）。"""
    from investment_assistant.tasks.event_study import main as _task_main

    _task_main()


if __name__ == "__main__":
    _cli_main()
