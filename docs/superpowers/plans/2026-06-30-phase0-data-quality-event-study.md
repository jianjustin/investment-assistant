# Phase 0 — 数据质量地基 + 事件研究框架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Phase 0 落地「复权/PIT 取价质量地基 + 事件研究引擎（A 层）+ 定时任务与可历史回放的手动 CLI + 可审计只读 API」，最小成本回答「我关注的信号有没有边际信息」。

**Architecture:** 数据层新增 NYSE 交易日历与 as-of 取价器；`research/` 新增无副作用、依赖注入式事件研究引擎与事件来源；定时任务经现有 `tasks/_harness.run_task` 落 `run_log`+`job_reports`+Discord（复用现有审计骨架），并注册进 `scheduler.REGISTRY` 使 dashboard「立即运行」零额外代码可用；手动 CLI 与定时共享同一核心函数（DRY），通过 `--asof/--since` 支持历史周期回放；只读 API 走 `routes → services` 薄封装并优雅降级。

**Tech Stack:** Python 3.11、pandas、psycopg3 + psycopg_pool、PostgreSQL 16、pytest；yfinance（取价，测试中全 mock/注入）。

**Spec:** `docs/superpowers/specs/2026-06-30-phase0-data-quality-event-study-design.md`

## Global Constraints

- **分支/提交**：在当前隔离 worktree 分支开发，不主动 push；每个提交信息结尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **只动本 Phase 0 的新增文件 + 必要修改点**（`data/price.py`、`data/calendar.py`、`research/*`、`services/research.py`、`tasks/event_study.py`、`api/routes/research.py` 与 `api/routes/__init__.py`、`market/service.py` 薄封装、相关迁移与测试）。**不改其它已有文件**，避免与并行 agent 冲突。
- **TDD**：先写失败测试，再实现；外部依赖（DB / 网络 / yfinance）**全部 mock 或注入**，离线可跑。
- **分层**：`api/routes/* → services/* → db.py / research/* / tasks/*`，路由层薄封装。
- **迁移幂等**：`CREATE TABLE IF NOT EXISTS` + `ON CONFLICT DO NOTHING/UPDATE`。**新迁移编号在落地时实测**：先 `ls migrations/` 取下一个可用编号（当前 main 已到 `008_notify_settings`，故事件研究缓存表预期为 `009_event_studies.sql`；若区间被占用顺延），并同步所有引用。
- **优雅降级**：无 `INVESTMENT_ASSISTANT_DATABASE_URL` 时只读端点返回空/`null` + `{"degraded": true}`，不崩。
- **不静默吞错**：外部失败结构化返回 + 日志，不裸 `except` 后丢弃。
- **审计复用**：定时/手动产出一律经 `tasks/_harness.run_task` 落 `run_log`+`job_reports`+Discord，**不另造审计系统**。
- **统计诚实**：只报超额收益（减基准）；每个结论带 `n` + CI；`n<30` 自动 caveats；不做参数寻优。
- **DB 写法对齐现有**：`with conn.cursor() as cur` + 具名参数 + `conn.commit()`；读函数 `dict(zip(keys, row))`；JSONB 用 `json.dumps(..., ensure_ascii=False)` + `::jsonb`。
- **路由注册**：新增 `api/routes/research.py` 必须加入 `api/routes/__init__.py` 的 import 才生效。

---

## File Structure

```
investment_assistant/
  data/
    calendar.py        # 新：NYSE 交易日历（is_trading_day/add_trading_days/trading_days_between）
    price.py           # 改：显式复权口径；+get_price_history_asof；+detect_split_jumps
  research/
    event_study.py     # 新：Event/HorizonStat/EventStudyResult + run_event_study + main() CLI
    event_sources.py   # 新：collect_events(config,*,asof,since)
  services/
    research.py        # 新：event_study_view（只读+降级）+ 可选缓存读
  tasks/
    event_study.py     # 新：_core(config)+run(config)=run_task(...)+main()
  market/service.py    # 改：_default_price_fetcher_until 薄封装 get_price_history_asof
  api/routes/
    research.py        # 新：GET /api/research/event-study*
    __init__.py        # 改：import research
  db.py                # 改（仅 Task 8 可选）：+upsert/get event_study 缓存
migrations/
  0NN_event_studies.sql# 可选（Task 8）：实测下一个可用编号
tests/
  test_data_calendar.py  test_data_price_asof.py  test_event_study.py
  test_event_sources.py  test_services_research.py  test_event_study_task.py
  test_research_api.py    test_db_sql.py（Task 8 追加断言）
```

---

## Task 1: NYSE 交易日历 `data/calendar.py`

**Files:**
- Create: `investment_assistant/data/calendar.py`
- Test: `tests/test_data_calendar.py`

**Interfaces:**
- Produces:
  - `is_trading_day(d: date) -> bool`
  - `add_trading_days(d: date, n: int) -> date`（`n>0` 向后；`d` 当天不计入，返回第 n 个交易日）
  - `trading_days_between(start: date, end: date) -> list[date]`（含端点中的交易日，升序）
  - `nyse_holidays(year: int) -> set[date]`

- [ ] **Step 1: 写失败测试** —— `tests/test_data_calendar.py`：

```python
from datetime import date

from investment_assistant.data import calendar as cal


def test_weekends_are_not_trading_days():
    assert cal.is_trading_day(date(2024, 3, 2)) is False  # Saturday
    assert cal.is_trading_day(date(2024, 3, 3)) is False  # Sunday
    assert cal.is_trading_day(date(2024, 3, 4)) is True    # Monday


def test_fixed_holidays_observed():
    # 2024-01-01 元旦；2024-07-04 独立日；2024-12-25 圣诞
    assert cal.is_trading_day(date(2024, 1, 1)) is False
    assert cal.is_trading_day(date(2024, 7, 4)) is False
    assert cal.is_trading_day(date(2024, 12, 25)) is False


def test_floating_holidays_observed():
    assert cal.is_trading_day(date(2024, 1, 15)) is False   # MLK: 1月第3个周一
    assert cal.is_trading_day(date(2024, 11, 28)) is False  # 感恩节: 11月第4个周四
    assert cal.is_trading_day(date(2024, 9, 2)) is False     # 劳动节: 9月第1个周一
    assert cal.is_trading_day(date(2024, 3, 29)) is False    # Good Friday 2024


def test_holiday_on_weekend_observed_adjacent_weekday():
    # 2021-07-04 是周日 → 观察日 7-05 周一休市
    assert cal.is_trading_day(date(2021, 7, 5)) is False
    # 2021-12-25 是周六 → 观察日 12-24 周五休市
    assert cal.is_trading_day(date(2021, 12, 24)) is False


def test_add_trading_days_skips_weekend():
    # 周五 +1 交易日 → 下周一
    assert cal.add_trading_days(date(2024, 3, 1), 1) == date(2024, 3, 4)


def test_add_trading_days_skips_holiday():
    # 2024-01-12(周五) +1 交易日：1-13/14 周末、1-15 MLK → 落 1-16
    assert cal.add_trading_days(date(2024, 1, 12), 1) == date(2024, 1, 16)


def test_add_five_trading_days_over_holiday():
    # 2024-11-25(周一) +5 交易日，跨 11-28 感恩节(周四休) → 12-03
    assert cal.add_trading_days(date(2024, 11, 25), 5) == date(2024, 12, 3)


def test_trading_days_between_inclusive_sorted():
    days = cal.trading_days_between(date(2024, 3, 1), date(2024, 3, 6))
    # 3-1(五),3-4(一),3-5(二),3-6(三) ; 3-2/3-3 周末剔除
    assert days == [date(2024, 3, 1), date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6)]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_data_calendar.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `data/calendar.py`：**

```python
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# Good Friday（复活节前周五）——浮动且依赖教会历，近年用已知日期表覆盖。
_GOOD_FRIDAY: dict[int, date] = {
    2020: date(2020, 4, 10), 2021: date(2021, 4, 2), 2022: date(2022, 4, 15),
    2023: date(2023, 4, 7), 2024: date(2024, 3, 29), 2025: date(2025, 4, 18),
    2026: date(2026, 4, 3), 2027: date(2027, 3, 26), 2028: date(2028, 4, 14),
    2029: date(2029, 3, 30), 2030: date(2030, 4, 19),
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """该月第 n 个 weekday（weekday: 周一=1..周日=7）。"""
    d = date(year, month, 1)
    offset = (weekday - d.isoweekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """该月最后一个 weekday（用于阵亡将士纪念日：5月最后一个周一）。"""
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    while d.isoweekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed(d: date) -> date:
    """固定假日逢周末顺延规则：周六→前一个周五，周日→后一个周一。"""
    if d.isoweekday() == 6:
        return d - timedelta(days=1)
    if d.isoweekday() == 7:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def nyse_holidays(year: int) -> frozenset[date]:
    days: set[date] = set()
    # 固定假日（逢周末顺延到相邻工作日）
    days.add(_observed(date(year, 1, 1)))     # New Year's Day
    days.add(_observed(date(year, 6, 19)))     # Juneteenth（2021 起，早年无害）
    days.add(_observed(date(year, 7, 4)))      # Independence Day
    days.add(_observed(date(year, 12, 25)))    # Christmas
    # 浮动假日
    days.add(_nth_weekday(year, 1, 1, 3))      # MLK: 1月第3个周一
    days.add(_nth_weekday(year, 2, 1, 3))      # Presidents' Day: 2月第3个周一
    days.add(_last_weekday(year, 5, 1))         # Memorial Day: 5月最后一个周一
    days.add(_nth_weekday(year, 9, 1, 1))      # Labor Day: 9月第1个周一
    days.add(_nth_weekday(year, 11, 4, 4))     # Thanksgiving: 11月第4个周四
    if year in _GOOD_FRIDAY:
        days.add(_GOOD_FRIDAY[year])
    return frozenset(days)


def is_trading_day(d: date) -> bool:
    if d.isoweekday() >= 6:  # Sat/Sun
        return False
    return d not in nyse_holidays(d.year)


def add_trading_days(d: date, n: int) -> date:
    if n == 0:
        return d
    step = 1 if n > 0 else -1
    remaining = abs(n)
    cur = d
    while remaining > 0:
        cur = cur + timedelta(days=step)
        if is_trading_day(cur):
            remaining -= 1
    return cur


def trading_days_between(start: date, end: date) -> list[date]:
    if end < start:
        return []
    out: list[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_data_calendar.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/data/calendar.py tests/test_data_calendar.py
git commit -m "feat(data): NYSE trading calendar (is_trading_day/add_trading_days/between)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: PIT 取价器 + split 校验 `data/price.py`

**Files:**
- Modify: `investment_assistant/data/price.py`
- Test: `tests/test_data_price_asof.py`

**Interfaces:**
- Consumes: `data/calendar`（无直接调用，但 as-of 行数语义按交易日；本任务用 fetcher 注入测试）。
- Produces:
  - `get_price_history(ticker: str, days: int = 90) -> pd.DataFrame`（保持现签名；显式 `auto_adjust=True`）
  - `get_price_history_asof(ticker: str, end_date: date, *, days: int = 260, fetcher: AsofFetcher | None = None) -> pd.DataFrame`（返回截至 `end_date`（含）、最多 `days` 行的复权 OHLCV；二次裁剪防前视）
  - `detect_split_jumps(frame: pd.DataFrame, *, threshold: float = 0.5, earnings_dates: set[date] | None = None) -> list[dict]`
  - 类型别名 `AsofFetcher = Callable[[str, date, int], pd.DataFrame]`

> 注意：现有 `tests/test_data_price.py` 断言 `fake.history.assert_called_once_with(period="30d")`。本任务给 `get_price_history` 增加 `auto_adjust=True` 会改变该调用签名，需**同步更新该既有断言**（属本任务必要修改点，不算"改无关文件"）。

- [ ] **Step 1: 写失败测试** —— `tests/test_data_price_asof.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_data_price_asof.py -q`
Expected: FAIL（函数未定义）。

- [ ] **Step 3: 重写 `investment_assistant/data/price.py`：**

```python
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pandas as pd
import yfinance as yf

_OHLCV = ["Open", "High", "Low", "Close", "Volume"]

# as-of 取价器：给定 ticker / 截止日 / 期望交易日数，返回截至该日（含）的 OHLCV。
AsofFetcher = Callable[[str, date, int], pd.DataFrame]


def get_price_history(ticker: str, days: int = 90) -> pd.DataFrame:
    """Return adjusted OHLCV for ticker over the last `days` calendar days."""
    df = yf.Ticker(ticker).history(period=f"{days}d", auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data returned for {ticker}")
    return df[_OHLCV]


def _default_asof_fetcher(ticker: str, end_date: date, days: int) -> pd.DataFrame:
    # 交易日 ≈ 日历日 * 0.7，留足缓冲多取再裁剪。
    calendar_days = max(days * 2, days + 30)
    start = end_date - timedelta(days=calendar_days)
    end = end_date + timedelta(days=1)
    df = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(), auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data returned for {ticker} through {end_date}")
    return df[_OHLCV]


def get_price_history_asof(
    ticker: str,
    end_date: date,
    *,
    days: int = 260,
    fetcher: AsofFetcher | None = None,
) -> pd.DataFrame:
    """Point-in-time adjusted OHLCV up to and including end_date (no look-ahead).

    二次裁剪 `df.loc[:end_date]` 是防前视偏差的硬守卫。
    """
    fetch = fetcher or _default_asof_fetcher
    df = fetch(ticker, end_date, days)
    if df is None or df.empty:
        raise ValueError(f"No price data returned for {ticker} through {end_date}")
    df = df[[c for c in _OHLCV if c in df.columns]]
    cutoff = pd.Timestamp(end_date)
    sliced = df[df.index <= cutoff.tz_localize(df.index.tz) if df.index.tz else df.index <= cutoff]
    if days and len(sliced) > days:
        sliced = sliced.tail(days)
    if sliced.empty:
        raise ValueError(f"No price data on or before {end_date} for {ticker}")
    return sliced


def detect_split_jumps(
    frame: pd.DataFrame,
    *,
    threshold: float = 0.5,
    earnings_dates: set[date] | None = None,
) -> list[dict]:
    """扫描相邻日收益，|ret|>threshold 且非财报日 → 疑似未复权 split。只告警不改数。"""
    if frame.empty or "Close" not in frame.columns or len(frame) < 2:
        return []
    earnings = earnings_dates or set()
    closes = frame["Close"].astype(float)
    jumps: list[dict] = []
    prev_close = None
    prev_ts = None
    for ts, close in closes.items():
        if prev_close is not None and prev_close != 0:
            ret = close / prev_close - 1
            cur_day = ts.date() if hasattr(ts, "date") else ts
            if abs(ret) > threshold and cur_day not in earnings:
                jumps.append({
                    "date": cur_day,
                    "prev_date": prev_ts.date() if hasattr(prev_ts, "date") else prev_ts,
                    "prev_close": float(prev_close),
                    "close": float(close),
                    "ret": float(ret),
                    "suspected": "unadjusted_split",
                })
        prev_close = close
        prev_ts = ts
    return jumps
```

- [ ] **Step 4: 同步更新既有断言** —— 改 `tests/test_data_price.py` 第 17 行：

把
```python
    fake.history.assert_called_once_with(period="30d")
```
改为
```python
    fake.history.assert_called_once_with(period="30d", auto_adjust=True)
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_data_price_asof.py tests/test_data_price.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add investment_assistant/data/price.py tests/test_data_price_asof.py tests/test_data_price.py
git commit -m "feat(data): point-in-time asof price fetcher + split-jump validation + explicit adjust

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `market/service` 复用 as-of 取价器（薄封装，去重）

**Files:**
- Modify: `investment_assistant/market/service.py:76-85`（`_default_price_fetcher_until`）
- Test: `tests/test_market_asof_delegation.py`

**Interfaces:**
- Consumes: `data.price.get_price_history_asof`。
- Produces: `_default_price_fetcher_until(ticker, days, target_date)` 行为不变（向后兼容 `compute_market_signal_for_date`），内部改为委托 `get_price_history_asof`，消除重复的 yfinance 切片逻辑（DRY）。

- [ ] **Step 1: 写失败测试** —— `tests/test_market_asof_delegation.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_market_asof_delegation.py -q`
Expected: FAIL（`service.get_price_history_asof` 未导入 / 仍是旧实现）。

- [ ] **Step 3: 改 `market/service.py`** —— 在文件顶部 import 区（现有 `import pandas as pd` 之后）追加：

```python
from investment_assistant.data.price import get_price_history_asof
```

并把 `_default_price_fetcher_until`（第 76-85 行）整段替换为：

```python
def _default_price_fetcher_until(ticker: str, days: int, target_date: date) -> pd.DataFrame:
    return get_price_history_asof(ticker, target_date, days=days)
```

> 删除原函数体内的 `import yfinance as yf` 与手写区间切片——逻辑已收敛到 `data/price.get_price_history_asof`（DRY）。

- [ ] **Step 4: 运行确认通过 + 回归 market 服务**

Run: `python -m pytest tests/test_market_asof_delegation.py tests/test_market_signal_service.py tests/test_market_signal_admin_api.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/market/service.py tests/test_market_asof_delegation.py
git commit -m "refactor(market): delegate asof fetch to data.price.get_price_history_asof (DRY)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 事件研究引擎 `research/event_study.py`

**Files:**
- Create: `investment_assistant/research/event_study.py`
- Test: `tests/test_event_study.py`

**Interfaces:**
- Consumes: `data.price.get_price_history_asof`（默认 price_fetcher）、`data.calendar.add_trading_days`（默认 calendar）、`market.service.compute_market_signal_for_date`（默认 regime_fn，Task 5/6 才接，本任务用注入测试）。
- Produces:
  - `Event(ticker, date, kind, meta)` frozen dataclass
  - `HorizonStat(horizon, n, mean_excess, median, hit_rate, t_stat, ci95, std)` frozen dataclass
  - `EventStudyResult(kind, n, horizons, by_regime, caveats, generated_at, params)` frozen dataclass + `.to_dict()`
  - `run_event_study(events, *, horizons=(1,5,20), benchmark="SPY", price_fetcher=None, regime_fn=None, add_trading_days_fn=None, min_sample=30) -> EventStudyResult`
  - `forward_excess_return(ticker, event_date, horizon, *, benchmark, price_fetcher, add_trading_days_fn) -> float | None`（单事件单 horizon 超额收益；取价失败返回 None）

- [ ] **Step 1: 写失败测试** —— `tests/test_event_study.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_event_study.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `research/event_study.py`（引擎部分；CLI 在 Task 7 追加）：**

```python
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
    if n < min_sample:
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_event_study.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/research/event_study.py tests/test_event_study.py
git commit -m "feat(research): event-study engine (excess return / regime split / honest caveats)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 事件来源 `research/event_sources.py`

**Files:**
- Create: `investment_assistant/research/event_sources.py`
- Test: `tests/test_event_sources.py`

**Interfaces:**
- Consumes: `research.event_study.Event`；可注入的 `row_source: Callable[[], list[dict]]`（默认读 `ticker_signal_snapshots` + `strategy_scores`，无 DB 返回 `[]`）。
- Produces:
  - `events_from_snapshots(rows, *, asof=None, since=None, rs_strong=1.2) -> list[Event]`（纯函数，从快照行派生 `rs_strong`/`ma_reclaim`）
  - `events_from_scores(rows, *, asof=None, since=None, score_high=70) -> list[Event]`（派生 `score_high`）
  - `collect_events(kind, *, asof=None, since=None, config=None, snapshot_source=None, score_source=None) -> list[Event]`（聚合 + DB 读 + 降级）

> **设计说明**：派生为**纯函数**（吃行、吐 Event），DB 读取与过滤分离，离线可测。`asof` 用于历史回放（只保留 `event.date <= asof`），`since` 用于下界（`event.date >= since`）。`ma_reclaim` Phase 0 用「close 上穿 ma20」近似 21EMA，Event.meta 标 `approx:"ma20_for_21ema"`。

- [ ] **Step 1: 写失败测试** —— `tests/test_event_sources.py`：

```python
from datetime import date

from investment_assistant.research.event_sources import (
    collect_events,
    events_from_scores,
    events_from_snapshots,
)


def _snap(ticker, d, rs_spy, reasons, close=None, ma20=None, prev_close=None, prev_ma20=None):
    return {
        "ticker": ticker, "signal_date": d, "relative_strength_spy": rs_spy,
        "trigger_reason": reasons, "close": close, "ma20": ma20,
        "prev_close": prev_close, "prev_ma20": prev_ma20,
    }


def test_rs_strong_event_from_snapshot():
    rows = [_snap("NVDA", date(2024, 3, 1), 1.5, ["outperform_spy", "above_ma_stack"])]
    events = events_from_snapshots(rows, rs_strong=1.2)
    kinds = {(e.ticker, e.kind) for e in events}
    assert ("NVDA", "rs_strong") in kinds


def test_rs_strong_not_emitted_below_threshold():
    rows = [_snap("NVDA", date(2024, 3, 1), 0.5, ["outperform_spy"])]
    events = events_from_snapshots(rows, rs_strong=1.2)
    assert all(e.kind != "rs_strong" for e in events)


def test_ma_reclaim_event_on_cross_up():
    # 前一日 close<ma20，当日 close>ma20 → ma_reclaim
    rows = [_snap("MU", date(2024, 3, 4), 0.3, [],
                  close=50.0, ma20=49.0, prev_close=48.0, prev_ma20=49.5)]
    events = events_from_snapshots(rows)
    ma = [e for e in events if e.kind == "ma_reclaim"]
    assert len(ma) == 1
    assert ma[0].meta.get("approx") == "ma20_for_21ema"


def test_score_high_event_from_scores():
    rows = [{"ticker": "RKLB", "score_date": date(2024, 5, 1), "score": 80}]
    events = events_from_scores(rows, score_high=70)
    assert events and events[0].kind == "score_high" and events[0].ticker == "RKLB"


def test_asof_and_since_filter():
    rows = [
        _snap("AAA", date(2023, 1, 1), 1.5, ["outperform_spy"]),
        _snap("BBB", date(2024, 6, 1), 1.5, ["outperform_spy"]),
        _snap("CCC", date(2025, 1, 1), 1.5, ["outperform_spy"]),
    ]
    events = events_from_snapshots(rows, asof=date(2024, 12, 31), since=date(2024, 1, 1))
    tickers = {e.ticker for e in events}
    assert tickers == {"BBB"}  # AAA 早于 since，CCC 晚于 asof


def test_collect_events_degrades_without_sources():
    # 注入空 source（模拟无 DB）
    events = collect_events("rs_strong", snapshot_source=lambda: [], score_source=lambda: [])
    assert events == []


def test_collect_events_filters_by_kind():
    snap_rows = [_snap("NVDA", date(2024, 3, 1), 1.5, ["outperform_spy"])]
    score_rows = [{"ticker": "RKLB", "score_date": date(2024, 5, 1), "score": 90}]
    events = collect_events(
        "score_high", snapshot_source=lambda: snap_rows, score_source=lambda: score_rows,
    )
    assert all(e.kind == "score_high" for e in events)
    assert events[0].ticker == "RKLB"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_event_sources.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `research/event_sources.py`：**

```python
from __future__ import annotations

import os
from datetime import date
from typing import Any, Callable

from investment_assistant.research.event_study import Event

RowSource = Callable[[], list[dict[str, Any]]]


def _in_window(d: date, *, asof: date | None, since: date | None) -> bool:
    if asof is not None and d > asof:
        return False
    if since is not None and d < since:
        return False
    return True


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def events_from_snapshots(
    rows: list[dict[str, Any]],
    *,
    asof: date | None = None,
    since: date | None = None,
    rs_strong: float = 1.2,
) -> list[Event]:
    events: list[Event] = []
    for row in rows:
        d = _as_date(row.get("signal_date"))
        if d is None or not _in_window(d, asof=asof, since=since):
            continue
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        reasons = row.get("trigger_reason") or []
        rs = row.get("relative_strength_spy")
        if rs is not None and float(rs) >= rs_strong and "outperform_spy" in reasons:
            events.append(Event(ticker, d, "rs_strong", {"rs_spy": float(rs)}))
        close, ma20 = row.get("close"), row.get("ma20")
        prev_close, prev_ma20 = row.get("prev_close"), row.get("prev_ma20")
        if None not in (close, ma20, prev_close, prev_ma20):
            crossed_up = float(prev_close) <= float(prev_ma20) and float(close) > float(ma20)
            if crossed_up:
                events.append(Event(ticker, d, "ma_reclaim", {"approx": "ma20_for_21ema"}))
    return events


def events_from_scores(
    rows: list[dict[str, Any]],
    *,
    asof: date | None = None,
    since: date | None = None,
    score_high: int = 70,
) -> list[Event]:
    events: list[Event] = []
    for row in rows:
        d = _as_date(row.get("score_date"))
        if d is None or not _in_window(d, asof=asof, since=since):
            continue
        ticker = str(row.get("ticker", "")).upper()
        score = row.get("score")
        if ticker and score is not None and int(score) >= score_high:
            events.append(Event(ticker, d, "score_high", {"score": int(score)}))
    return events


def _default_snapshot_source() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return []
    from investment_assistant.db import connect
    try:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ticker, signal_date, close, ma20,
                           relative_strength_spy, trigger_reason,
                           lag(close) OVER w AS prev_close,
                           lag(ma20) OVER w AS prev_ma20
                    FROM ticker_signal_snapshots
                    WHERE error IS NULL
                    WINDOW w AS (PARTITION BY ticker ORDER BY signal_date)
                    ORDER BY signal_date
                    """
                )
                rows = cur.fetchall()
    except Exception:
        return []
    keys = ["ticker", "signal_date", "close", "ma20", "relative_strength_spy",
            "trigger_reason", "prev_close", "prev_ma20"]
    return [dict(zip(keys, row)) for row in rows]


def _default_score_source() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return []
    from investment_assistant.db import connect
    try:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ticker, score_date, score FROM strategy_scores ORDER BY score_date")
                rows = cur.fetchall()
    except Exception:
        return []
    return [dict(zip(["ticker", "score_date", "score"], row)) for row in rows]


def collect_events(
    kind: str,
    *,
    asof: date | None = None,
    since: date | None = None,
    config: Any = None,
    snapshot_source: RowSource | None = None,
    score_source: RowSource | None = None,
) -> list[Event]:
    rs_strong = 1.2
    score_high = 70
    if config is not None:
        rs_strong = float(getattr(config.strategy, "rs_strong", rs_strong))
    snap_src = snapshot_source or _default_snapshot_source
    score_src = score_source or _default_score_source

    events: list[Event] = []
    if kind in ("rs_strong", "ma_reclaim"):
        events += events_from_snapshots(snap_src(), asof=asof, since=since, rs_strong=rs_strong)
    if kind == "score_high":
        events += events_from_scores(score_src(), asof=asof, since=since, score_high=score_high)
    return [e for e in events if e.kind == kind]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_event_sources.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/research/event_sources.py tests/test_event_sources.py
git commit -m "feat(research): event sources derive Events from snapshots/scores (asof/since replay)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 定时任务 `tasks/event_study.py` + 注册 REGISTRY

**Files:**
- Create: `investment_assistant/tasks/event_study.py`
- Modify: `investment_assistant/tasks/scheduler.py`（REGISTRY 增 `event_study`）
- Test: `tests/test_event_study_task.py`

**Interfaces:**
- Consumes: `research.event_sources.collect_events`、`research.event_study.run_event_study`、`tasks._harness.run_task`、`config.AssistantConfig`。
- Produces:
  - `event_study._core(config, *, asof=None, since=None, kinds=None, record=True) -> dict`（组装结构化 summary：每个 kind 的 result.to_dict + 跳过计数）
  - `event_study.run(config) -> dict`（`run_task("event_study", lambda: _core(config), config=config)`，落审计）
  - `scheduler.REGISTRY["event_study"] = event_study.run`

> **审计落地（硬约束 1）**：`run` 经 `run_task` 自动写 `run_log`(文件) + `job_reports`(DB) + Discord；summary 含 `params`（asof/since/kinds）= 用什么参数、各 kind 的 n 与 caveats = 产生什么结果。dashboard 工具层 `GET /api/jobs/reports?task=event_study` 与「立即运行」`POST /api/jobs/event_study/run` 零额外代码可用（因已注册 REGISTRY）。

- [ ] **Step 1: 写失败测试** —— `tests/test_event_study_task.py`：

```python
from datetime import date

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import event_study


def test_core_aggregates_kinds(monkeypatch):
    from investment_assistant.research.event_study import Event

    monkeypatch.setattr(event_study, "collect_events",
                        lambda kind, **kw: [Event("NVDA", date(2024, 3, 1), kind)])

    def fake_run(events, **kw):
        from investment_assistant.research.event_study import EventStudyResult
        from datetime import UTC, datetime
        return EventStudyResult(
            kind=events[0].kind, n=1, horizons={}, by_regime={},
            caveats=["n<30, 结论不可信"], generated_at=datetime.now(UTC),
            params={"skipped": []},
        )

    monkeypatch.setattr(event_study, "run_event_study", fake_run)
    summary = event_study._core(AssistantConfig(), kinds=["rs_strong"])
    assert "rs_strong" in summary["results"]
    assert summary["results"]["rs_strong"]["n"] == 1
    assert summary["params"]["kinds"] == ["rs_strong"]


def test_core_passes_asof_for_replay(monkeypatch):
    seen = {}

    def fake_collect(kind, *, asof=None, since=None, config=None, **kw):
        seen["asof"] = asof
        seen["since"] = since
        return []

    monkeypatch.setattr(event_study, "collect_events", fake_collect)
    event_study._core(AssistantConfig(), asof=date(2024, 3, 1), since=date(2022, 1, 1),
                      kinds=["rs_strong"])
    assert seen["asof"] == date(2024, 3, 1)
    assert seen["since"] == date(2022, 1, 1)


def test_run_goes_through_harness(monkeypatch):
    monkeypatch.setattr(event_study, "_core", lambda config, **kw: {"results": {}})
    captured = {}

    def fake_run_task(task, fn, *, config):
        captured["task"] = task
        return {"task": task, "status": "success", "summary": fn()}

    monkeypatch.setattr(event_study, "run_task", fake_run_task)
    out = event_study.run(AssistantConfig())
    assert captured["task"] == "event_study"
    assert out["status"] == "success"


def test_registered_in_scheduler():
    from investment_assistant.tasks.scheduler import REGISTRY
    assert "event_study" in REGISTRY
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_event_study_task.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `tasks/event_study.py`：**

```python
from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.research.event_sources import collect_events
from investment_assistant.research.event_study import run_event_study
from investment_assistant.tasks._harness import run_task

DEFAULT_KINDS = ["rs_strong", "ma_reclaim", "score_high"]


def _core(
    config: AssistantConfig,
    *,
    asof: date | None = None,
    since: date | None = None,
    kinds: list[str] | None = None,
) -> dict[str, Any]:
    target_kinds = kinds or DEFAULT_KINDS
    horizons = tuple(getattr(config.backtest, "horizons", [5, 10, 20]))
    results: dict[str, Any] = {}
    skipped_total = 0
    for kind in target_kinds:
        events = collect_events(kind, asof=asof, since=since, config=config)
        result = run_event_study(events, horizons=horizons)
        results[kind] = result.to_dict()
        skipped_total += len(result.params.get("skipped", []))
    return {
        "results": results,
        "params": {
            "kinds": target_kinds,
            "asof": asof.isoformat() if asof else None,
            "since": since.isoformat() if since else None,
            "horizons": list(horizons),
        },
        "skipped_total": skipped_total,
    }


def run(config: AssistantConfig) -> dict[str, Any]:
    return run_task("event_study", lambda: _core(config), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Event study task (scheduled or manual replay)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--kind", action="append", dest="kinds", default=None,
                        help="事件类型，可多次传入；缺省跑全部")
    parser.add_argument("--asof", default=None, help="历史 as-of 日期 YYYY-MM-DD（回放用）")
    parser.add_argument("--since", default=None, help="事件下界日期 YYYY-MM-DD")
    parser.add_argument("--no-record", action="store_true", help="仅打印，不落 job_reports")
    args = parser.parse_args()
    config = load_config(args.config)
    asof = date.fromisoformat(args.asof) if args.asof else None
    since = date.fromisoformat(args.since) if args.since else None

    if args.no_record:
        summary = _core(config, asof=asof, since=since, kinds=args.kinds)
        out = {"task": "event_study", "status": "manual", "summary": summary}
    else:
        out = run_task(
            "event_study",
            lambda: _core(config, asof=asof, since=since, kinds=args.kinds),
            config=config,
        )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
```

> **DRY（硬约束 2）**：定时 `run()` 与手动 `main()` 都调用同一 `_core` + `run_event_study`，仅入口与 `asof/since/kinds` 参数不同。手动入口默认也经 `run_task` 落审计；`--no-record` 仅离线打印。

- [ ] **Step 4: 注册 REGISTRY** —— 改 `investment_assistant/tasks/scheduler.py`：

在 import 区（第 12-14 行附近，与 `metrics`/`filings`/`scores` 并列）追加：
```python
from investment_assistant.tasks import event_study as event_study_task
```
在 `REGISTRY` 字典（第 18-22 行）追加一项：
```python
REGISTRY: dict[str, Callable[[AssistantConfig], dict[str, Any]]] = {
    "metrics": metrics_task.run,
    "filings": filings_task.run,
    "scores": scores_task.run,
    "event_study": event_study_task.run,
}
```

- [ ] **Step 5: 运行确认通过 + 回归调度器**

Run: `python -m pytest tests/test_event_study_task.py tests/test_scheduler.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add investment_assistant/tasks/event_study.py investment_assistant/tasks/scheduler.py tests/test_event_study_task.py
git commit -m "feat(tasks): event_study scheduled task + manual replay CLI sharing one core (DRY); register REGISTRY

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 手动 CLI 入口 `research/event_study.py`（对齐 roadmap 调用路径）

**Files:**
- Modify: `investment_assistant/research/event_study.py`（文件末尾追加 `__main__` 委托）
- Test: `tests/test_event_study.py`（追加 CLI 委托断言）

**Interfaces:**
- Consumes: `tasks.event_study.main`。
- Produces: `python -m investment_assistant.research.event_study ...` 等价于 `python -m investment_assistant.tasks.event_study ...`（roadmap Task 0.3 文档化的调用路径），避免维护两套参数解析（DRY）。

> **为什么这样做**：roadmap Task 0.3 明确写 `python -m investment_assistant.research.event_study --kind eps_beat --since 2022-01-01`。但参数解析与执行已在 `tasks/event_study.main`（Task 6）实现。为同时满足"文档化路径"与 DRY，`research/event_study.py` 只提供一个委托式 `__main__`，不复制 argparse。

- [ ] **Step 1: 写失败测试** —— 追加到 `tests/test_event_study.py` 末尾：

```python
def test_research_cli_delegates_to_task(monkeypatch):
    import investment_assistant.research.event_study as rs
    called = {}
    monkeypatch.setattr("investment_assistant.tasks.event_study.main",
                        lambda: called.setdefault("ran", True))
    rs._cli_main()
    assert called.get("ran") is True
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_event_study.py::test_research_cli_delegates_to_task -q`
Expected: FAIL（`_cli_main` 未定义）。

- [ ] **Step 3: 在 `research/event_study.py` 末尾追加：**

```python
def _cli_main() -> None:
    """委托到 tasks.event_study.main，对齐 roadmap 文档化的调用路径（DRY，不复制 argparse）。"""
    from investment_assistant.tasks.event_study import main as _task_main

    _task_main()


if __name__ == "__main__":
    _cli_main()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_event_study.py -q`
Expected: PASS。

- [ ] **Step 5: 烟测两条调用路径等价（手动验证，不落库）**

Run: `python -m investment_assistant.research.event_study --kind rs_strong --no-record`
Expected: 打印 JSON（无 DB 时各 kind 事件为空、n=0、含 caveats），不抛异常、退出码 0。
Run: `python -m investment_assistant.tasks.event_study --kind rs_strong --no-record`
Expected: 同样打印 JSON。

- [ ] **Step 6: Commit**

```bash
git add investment_assistant/research/event_study.py tests/test_event_study.py
git commit -m "feat(research): event_study __main__ delegates to task CLI (roadmap path, DRY)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: 结果缓存表迁移 + db 仓储（可选增强）

**Files:**
- Create: `migrations/0NN_event_studies.sql`（**编号实测**：见下方 Step 0）
- Modify: `investment_assistant/db.py`（末尾追加 `upsert_event_study` / `get_event_study`）
- Test: `tests/test_db_sql.py`（追加迁移断言）、`tests/test_event_study_repository.py`

**Interfaces:**
- Produces:
  - `db.upsert_event_study(conn, *, kind, params_hash, result: dict) -> None`（`ON CONFLICT (kind, params_hash) DO UPDATE`）
  - `db.get_event_study(conn, *, kind, params_hash) -> dict | None`

> **可选性**：引擎无状态、可纯算（Task 4），缓存仅加速 dashboard 只读。若实施时间紧，可跳过 Task 8/9 的缓存读写，只读 API（Task 9）退化为"即时计算"。本任务存在是为让 `GET /api/research/event-study` 有低延迟来源。

- [ ] **Step 0: 实测迁移编号**

Run: `ls migrations/`
取**最大编号 + 1** 作为新文件名（当前 main 已含 `008_notify_settings.sql`，预期新文件为 `009_event_studies.sql`；若区间已被 Phase 1 占用，顺延为下一个可用编号）。下文以 `009_event_studies.sql` 为例，**实施时按实测编号替换所有出现处**。

- [ ] **Step 1: 写迁移断言** —— 追加到 `tests/test_db_sql.py` 末尾（路径用实测编号）：

```python
def test_event_studies_migration():
    from pathlib import Path
    sql = Path("migrations/009_event_studies.sql").read_text()  # 用实测编号
    assert "CREATE TABLE IF NOT EXISTS event_studies" in sql
    assert "kind" in sql and "params_hash" in sql
    assert "result" in sql and "JSONB" in sql
    assert "UNIQUE (kind, params_hash)" in sql
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_sql.py::test_event_studies_migration -q`
Expected: FAIL（文件不存在）。

- [ ] **Step 3: 写 `migrations/009_event_studies.sql`（用实测编号命名）：**

```sql
CREATE TABLE IF NOT EXISTS event_studies (
  id           BIGSERIAL PRIMARY KEY,
  kind         TEXT NOT NULL,
  params_hash  TEXT NOT NULL,
  result       JSONB NOT NULL DEFAULT '{}'::jsonb,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, params_hash)
);

CREATE INDEX IF NOT EXISTS idx_event_studies_kind
  ON event_studies (kind, generated_at DESC);
```

- [ ] **Step 4: 写仓储测试** —— `tests/test_event_study_repository.py`（复用 jobs 仓储测试同款 FakeConn）：

```python
from investment_assistant import db


class FakeCursor:
    def __init__(self, store, rows):
        self.store, self.rows = store, rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.store.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows=None):
        self.store, self.commits, self.rows = [], 0, rows or []

    def cursor(self):
        return FakeCursor(self.store, self.rows)

    def commit(self):
        self.commits += 1


def test_upsert_event_study_uses_conflict():
    conn = FakeConn()
    db.upsert_event_study(conn, kind="rs_strong", params_hash="h1", result={"n": 5})
    sql, params = conn.store[0]
    assert "INSERT INTO event_studies" in sql
    assert "ON CONFLICT (kind, params_hash) DO UPDATE" in sql
    assert params["kind"] == "rs_strong" and params["params_hash"] == "h1"
    assert conn.commits == 1


def test_get_event_study_maps_row():
    rows = [("rs_strong", "h1", {"n": 5}, None)]
    conn = FakeConn(rows=rows)
    out = db.get_event_study(conn, kind="rs_strong", params_hash="h1")
    assert out["kind"] == "rs_strong" and out["result"] == {"n": 5}


def test_get_event_study_none_when_missing():
    conn = FakeConn(rows=[])
    assert db.get_event_study(conn, kind="rs_strong", params_hash="zzz") is None
```

- [ ] **Step 5: 运行确认失败**

Run: `python -m pytest tests/test_event_study_repository.py -q`
Expected: FAIL（函数未定义）。

- [ ] **Step 6: 在 `db.py` 末尾追加：**

```python
def upsert_event_study(conn, *, kind: str, params_hash: str, result: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO event_studies (kind, params_hash, result, generated_at)
            VALUES (%(kind)s, %(params_hash)s, %(result)s::jsonb, now())
            ON CONFLICT (kind, params_hash) DO UPDATE SET
              result = EXCLUDED.result,
              generated_at = EXCLUDED.generated_at,
              updated_at = now()
            """,
            {
                "kind": kind,
                "params_hash": params_hash,
                "result": json.dumps(result or {}, ensure_ascii=False, default=str),
            },
        )
    conn.commit()


def get_event_study(conn, *, kind: str, params_hash: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kind, params_hash, result, generated_at
            FROM event_studies
            WHERE kind = %(kind)s AND params_hash = %(params_hash)s
            """,
            {"kind": kind, "params_hash": params_hash},
        )
        rows = cur.fetchall()
    if not rows:
        return None
    keys = ["kind", "params_hash", "result", "generated_at"]
    return dict(zip(keys, rows[0]))
```
> `db.py` 顶部已 `import json` 与 `from typing import Any`，无需新增 import。

- [ ] **Step 7: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_event_study_repository.py tests/test_db_sql.py -q`
Expected: PASS。
```bash
git add migrations/009_event_studies.sql investment_assistant/db.py tests/test_db_sql.py tests/test_event_study_repository.py
git commit -m "feat(db): event_studies cache migration + upsert/get repository

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: 只读服务 `services/research.py` + 路由 `api/routes/research.py`

**Files:**
- Create: `investment_assistant/services/research.py`
- Create: `investment_assistant/api/routes/research.py`
- Modify: `investment_assistant/api/routes/__init__.py`
- Test: `tests/test_services_research.py`、`tests/test_research_api.py`

**Interfaces:**
- Consumes: `db.{get_event_study,upsert_event_study}`、`research.event_sources.collect_events`、`research.event_study.run_event_study`、`config.load_config`、`api.http.{ApiResponse,first,parse_optional_date}`、`api.router.register`。
- Produces:
  - `services.research.event_study_view(kind, *, since=None, asof=None) -> dict`（`{"result": {...}|None, "degraded": bool, "source": "cache"|"computed"}`）
  - `services.research.available_kinds() -> dict`（`{"kinds": [...]}`）
  - `services.research._params_hash(kind, since, asof, horizons) -> str`
  - 路由：`GET /api/research/event-study`、`GET /api/research/event-study/kinds`

> **降级（优雅）**：无 `INVESTMENT_ASSISTANT_DATABASE_URL` 时，事件来源为空 → 即时计算返回 `result`（n=0、含 caveats）+ `degraded:true`、`source:"computed"`，不崩。有 DB 时优先读缓存，未命中则即时计算并回填缓存。

- [ ] **Step 1: 写服务测试** —— `tests/test_services_research.py`：

```python
from datetime import date

from investment_assistant.services import research


def test_available_kinds_lists_known():
    out = research.available_kinds()
    assert "rs_strong" in out["kinds"]
    assert "score_high" in out["kinds"]


def test_event_study_view_degraded_without_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    monkeypatch.setattr(research, "collect_events", lambda kind, **kw: [])
    out = research.event_study_view("rs_strong")
    assert out["degraded"] is True
    assert out["source"] == "computed"
    assert out["result"]["n"] == 0


def test_event_study_view_reads_cache(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(research, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(research.db, "get_event_study",
                        lambda conn, *, kind, params_hash: {"result": {"kind": kind, "n": 42}})
    out = research.event_study_view("rs_strong")
    assert out["degraded"] is False
    assert out["source"] == "cache"
    assert out["result"]["n"] == 42


def test_event_study_view_computes_and_caches_on_miss(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(research, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(research.db, "get_event_study", lambda conn, *, kind, params_hash: None)
    saved = {}
    monkeypatch.setattr(research.db, "upsert_event_study",
                        lambda conn, *, kind, params_hash, result: saved.update(result))
    from investment_assistant.research.event_study import Event
    monkeypatch.setattr(research, "collect_events",
                        lambda kind, **kw: [Event("NVDA", date(2024, 3, 1), kind)])
    monkeypatch.setattr(research, "run_event_study",
                        lambda events, **kw: _FakeResult(events[0].kind))
    out = research.event_study_view("rs_strong")
    assert out["source"] == "computed"
    assert saved.get("kind") == "rs_strong"  # 回填缓存被调用


class _FakeResult:
    def __init__(self, kind):
        self.kind = kind

    def to_dict(self):
        return {"kind": self.kind, "n": 1, "horizons": {}, "by_regime": {}, "caveats": []}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_services_research.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `services/research.py`：**

```python
from __future__ import annotations

import hashlib
import os
from datetime import date
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.config import load_config
from investment_assistant.db import connect
from investment_assistant.research.event_sources import collect_events
from investment_assistant.research.event_study import run_event_study

KNOWN_KINDS = ["rs_strong", "ma_reclaim", "score_high", "eps_beat", "eps_miss"]


def _has_db() -> bool:
    return bool(os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"))


def _with_conn(fn: Callable[[Any], Any]) -> Any:
    with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
        return fn(conn)


def available_kinds() -> dict[str, Any]:
    return {"kinds": KNOWN_KINDS}


def _params_hash(kind: str, since: date | None, asof: date | None, horizons: tuple[int, ...]) -> str:
    raw = f"{kind}|{since}|{asof}|{horizons}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _compute(kind: str, *, since: date | None, asof: date | None, horizons: tuple[int, ...]) -> dict[str, Any]:
    events = collect_events(kind, since=since, asof=asof, config=load_config())
    result = run_event_study(events, horizons=horizons)
    return result.to_dict()


def event_study_view(
    kind: str,
    *,
    since: date | None = None,
    asof: date | None = None,
) -> dict[str, Any]:
    config = load_config()
    horizons = tuple(getattr(config.backtest, "horizons", [5, 10, 20]))
    params_hash = _params_hash(kind, since, asof, horizons)

    if not _has_db():
        return {
            "result": _compute(kind, since=since, asof=asof, horizons=horizons),
            "degraded": True,
            "source": "computed",
        }

    cached = _with_conn(lambda conn: db.get_event_study(conn, kind=kind, params_hash=params_hash))
    if cached:
        return {"result": cached["result"], "degraded": False, "source": "cache"}

    result = _compute(kind, since=since, asof=asof, horizons=horizons)
    _with_conn(lambda conn: db.upsert_event_study(conn, kind=kind, params_hash=params_hash, result=result))
    return {"result": result, "degraded": False, "source": "computed"}
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_services_research.py -q`
Expected: PASS。

- [ ] **Step 5: 写 API 测试** —— `tests/test_research_api.py`：

```python
from investment_assistant.api import routes  # noqa: F401  触发路由注册
from investment_assistant.api.router import dispatch
from investment_assistant.services import research


def test_kinds_endpoint():
    resp = dispatch("GET", "/api/research/event-study/kinds", None)
    assert resp is not None
    assert "rs_strong" in resp.payload["kinds"]


def test_event_study_endpoint_passes_params(monkeypatch):
    seen = {}

    def fake_view(kind, *, since=None, asof=None):
        seen.update({"kind": kind, "since": since, "asof": asof})
        return {"result": {"kind": kind}, "degraded": False, "source": "computed"}

    monkeypatch.setattr(research, "event_study_view", fake_view)
    resp = dispatch("GET", "/api/research/event-study?kind=rs_strong&since=2022-01-01", None)
    assert resp is not None
    assert seen["kind"] == "rs_strong"
    assert str(seen["since"]) == "2022-01-01"
    assert resp.payload["result"]["kind"] == "rs_strong"


def test_event_study_endpoint_requires_kind():
    resp = dispatch("GET", "/api/research/event-study", None)
    assert resp is not None
    assert resp.status == 400
```

- [ ] **Step 6: 运行确认失败**

Run: `python -m pytest tests/test_research_api.py -q`
Expected: FAIL（路由未注册）。

- [ ] **Step 7: 实现 `api/routes/research.py`：**

```python
from investment_assistant.api.http import ApiResponse, first, parse_optional_date
from investment_assistant.api.router import register
from investment_assistant.services import research


@register("GET", exact="/api/research/event-study/kinds")
def _kinds(path, query, payload):
    return ApiResponse(research.available_kinds())


@register("GET", exact="/api/research/event-study")
def _event_study(path, query, payload):
    kind = first(query, "kind")
    if not kind:
        return ApiResponse({"error": "kind is required"}, status=400)
    since = parse_optional_date(first(query, "since"))
    asof = parse_optional_date(first(query, "asof"))
    return ApiResponse(research.event_study_view(kind, since=since, asof=asof))
```

> 路由顺序：`/kinds` 用 `exact` 精确匹配，与 `/api/research/event-study` 不冲突（router 先查 `_EXACT`）。

- [ ] **Step 8: 注册路由** —— 改 `investment_assistant/api/routes/__init__.py`：

```python
from . import status, market, tickers, strategies, hermes, watchlist, runs, jobs, settings, research  # noqa: F401
```

- [ ] **Step 9: 运行确认通过 + 集成**

Run: `python -m pytest tests/test_research_api.py tests/test_services_research.py -q`
Expected: PASS。
Run: `python -c "import investment_assistant.api.routes"`
Expected: 无 ImportError。

- [ ] **Step 10: Commit**

```bash
git add investment_assistant/services/research.py investment_assistant/api/routes/research.py investment_assistant/api/routes/__init__.py tests/test_services_research.py tests/test_research_api.py
git commit -m "feat(api): research event-study read endpoints (cache-or-compute, graceful degrade)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: 全量回归 + 收尾

**Files:** 无新增（验证性任务）。

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿。若有失败，定位到具体任务修复，不跳过。

- [ ] **Step 2: 导入烟测**

Run: `python -c "import investment_assistant.api.routes; from investment_assistant.tasks.scheduler import REGISTRY; assert 'event_study' in REGISTRY; print('ok')"`
Expected: 打印 `ok`。

- [ ] **Step 3: CLI 烟测（无 DB，离线）**

Run: `python -m investment_assistant.research.event_study --kind rs_strong --no-record`
Expected: JSON 输出，`results.rs_strong.n == 0`，含 caveats，退出码 0。

- [ ] **Step 4: 确认无遗留临时文件**

Run: `git status --short`
Expected: 仅本计划涉及的文件，无未追踪临时文件。

---

## Self-Review（对照 spec 完成）

- **Spec 覆盖**：
  - spec §1.2 Task 0.1 数据质量地基 → Task 1（日历）+ Task 2（asof/split/复权）+ Task 3（market 复用）。
  - spec §1.2 Task 0.2 事件研究引擎 → Task 4（引擎）+ Task 5（事件来源）。
  - spec §1.2 Task 0.3 报告入口（定时+手动回放）→ Task 6（定时任务+REGISTRY+CLI）+ Task 7（roadmap 文档化调用路径）。
  - spec §3.6 / §1.2 可选缓存表 → Task 8。
  - spec §3.9 只读 API + 前端衔接 → Task 9。
  - spec §3.7 审计 + 日志化 → Task 6（经 `_harness.run_task` 落 run_log+job_reports+Discord；dashboard 复用 jobs 路由）。
  - spec §3.8 定时/手动双入口 DRY → Task 6/7（共享 `_core`+`run_event_study`，手动 `--asof/--since` 回放）。
  - spec §6 测试策略 → 各 Task 的 TDD 步骤，全 mock/注入离线可跑。
- **占位符扫描**：无 TBD/TODO；每个代码步骤给出完整可运行代码。唯一"实测"项是 Task 8 迁移编号（合理：避免与并行 agent 冲突，已给实测命令 + 默认值 `009`）。
- **类型一致性**：
  - `Event(ticker,date,kind,meta)` 在 Task 4 定义，Task 5/6/9 一致构造。
  - `EventStudyResult.to_dict()` 在 Task 4 定义，Task 6（summary）、Task 9（缓存/返回）一致消费。
  - `run_event_study(events, *, horizons, benchmark, price_fetcher, regime_fn, add_trading_days_fn, min_sample)` 签名在 Task 4 定义，Task 6/9 按 `horizons=` 调用一致。
  - `collect_events(kind, *, asof, since, config, snapshot_source, score_source)` 在 Task 5 定义，Task 6/9 按 `asof/since/config` 调用一致。
  - `get_price_history_asof(ticker, end_date, *, days, fetcher)` 在 Task 2 定义，Task 3（market 委托）、Task 4（引擎 `_asof_close` 用 `price_fetcher(ticker, on, days=...)`）一致。
  - `db.upsert_event_study/get_event_study` 在 Task 8 定义，Task 9 service 一致消费。
- **已知实施期校验点**（非阻塞，步骤内已标注）：① 迁移编号实测（Task 8 Step 0）；② `tests/test_data_price.py` 既有断言需同步（Task 2 Step 4，已含）；③ `market/service.py` 行号 76-85 以实际为准（Task 3）。
