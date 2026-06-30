# Phase 1 数据地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 Phase 1 数据地基——OHLCV 落库（可复现基底）、市场广度指标、精简宏观（HY 利差 + 2s10s）、EPS surprise 结构化，并为每类采集任务提供「定时 + 手动历史回补」双入口，全部经现有 `_harness` 审计。

**Architecture:** 严格沿用现有分层 `api/routes/* → services/* → db.py / tasks/* / data/*`。每类数据：纯核心函数（注入式、可测）→ `services/*` 编排（降级 + 组装结构化 summary）→ `tasks/*.py` 的 `run()`（定时）与 `main()`（手动回补，传历史区间）共享同一核心 → `db.py` 仓储（`ON CONFLICT` upsert）→ migration（幂等）→ `api/routes/data.py` 薄路由（只读 + 触发回补）。定时与手动入口都经 `tasks/_harness.run_task`，自动获得 `job_reports` + run_log + 结构化 summary 审计。

**Tech Stack:** Python 3.11、psycopg3 + psycopg_pool、PostgreSQL 16、pandas、yfinance、FRED REST、pytest。

设计依据：`docs/superpowers/specs/2026-06-30-phase1-data-foundation-design.md`。

## Global Constraints

- **分支**：沿用当前隔离 worktree 分支；不主动 push；每次提交结尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **TDD**：先写失败测试再实现；外部依赖（DB / 网络 / yfinance / FRED / SEC）**全部 mock 或注入**，离线可跑。
- **分层**：`api/routes/*`（薄）→ `services/*` → `db.py` / `tasks/*` / `data/*`。
- **DB 写法对齐现有**：`with conn.cursor() as cur` + 具名参数（`%(name)s`）+ `conn.commit()`；读函数 `dict(zip(keys, row))`。
- **迁移幂等**：`CREATE TABLE IF NOT EXISTS` + 必要索引 + `ON CONFLICT DO NOTHING`。Phase 1 从 **009** 起：009 ohlcv_bars、010 market_breadth、011 macro_indicators、012 fundamentals、013 phase1 排程行。**与并行 Phase 0 agent 可能争用 012**：落地时若编号被先占，按落地顺序顺延，同步改 SQL 文件名与测试中的路径断言。
- **精简取舍（来自 roadmap 00 方向篇，务必遵守）**：FRED 只采 `BAMLH0A0HYM2`（HY OAS）+ `T10Y2Y`（2s10s，FRED 已发布序列），不采全部；财报只抽 EPS 实际/预期/surprise + 营收，不做全 XBRL；价格单源 yfinance + 落库 + 重试，不引入付费源；市场状态阈值用经验值，本期不寻优。
- **优雅降级**：缺 `INVESTMENT_ASSISTANT_DATABASE_URL` 或缺 `FRED_API_KEY` 时降级不崩；不静默吞错（`except` 必结构化记录）；敏感值（FRED key）绝不回显到 summary/日志/响应。
- **审计**：所有采集任务经 `tasks/_harness.run_task(task, fn, config=config)`，task 名 `prices/breadth/macro/fundamentals`，summary 含「触发参数 + 抓取范围 + 结果 + 缺口」。
- **路由注册**：新增 `api/routes/*.py` 必须加入 `investment_assistant/api/routes/__init__.py` 的 import 才生效。

---

## File Structure

```
migrations/
  009_ohlcv_bars.sql              # 新
  010_market_breadth.sql          # 新
  011_macro_indicators.sql        # 新
  012_fundamentals.sql            # 新
  013_phase1_scheduled_jobs.sql   # 新（prices/breadth/macro/fundamentals 默认排程行）
investment_assistant/
  config.py                       # 改：MacroConfig.fred_series→2；MarketConfig +广度/HY 阈值
  data/price.py                   # 改：+fetch_ohlcv（区间+复权+重试）
  data/fred.py                    # 新
  data/fundamentals.py            # 新
  market/breadth.py               # 新（纯函数）
  market/service.py               # 改：signal_date 新鲜度修复 + 多因子门控
  db.py                           # 改：+ohlcv/breadth/macro/fundamentals 仓储
  services/prices.py              # 新
  services/breadth.py             # 新
  services/macro.py               # 新
  services/fundamentals.py        # 新
  tasks/prices.py                 # 新（run + main 历史回补）
  tasks/breadth.py                # 新
  tasks/macro.py                  # 新
  tasks/fundamentals.py           # 新
  tasks/scheduler.py              # 改：REGISTRY +4 任务
  api/routes/data.py              # 新
  api/routes/__init__.py          # 改：import data
tests/
  test_db_sql.py                  # 追加 009–013 断言
  test_data_price_ohlcv.py  test_data_fred.py  test_data_fundamentals.py
  test_market_breadth.py    test_market_signal_freshness.py
  test_ohlcv_repository.py   test_breadth_repository.py  test_macro_repository.py  test_fundamentals_repository.py
  test_services_prices.py   test_services_breadth.py  test_services_macro.py  test_services_fundamentals.py
  test_tasks_phase1_entrypoints.py
  test_api_contract.py            # 追加 /api/data/* 断言
```

任务顺序遵循依赖：迁移 → data 取数 → db 仓储 → services 编排 → market 改造 → tasks 入口 → API。每个 Task 自带 TDD + commit。

---

## Task 1：迁移 009–013（建表 + 默认排程行）

**Files:**
- Create: `migrations/009_ohlcv_bars.sql`, `migrations/010_market_breadth.sql`, `migrations/011_macro_indicators.sql`, `migrations/012_fundamentals.sql`, `migrations/013_phase1_scheduled_jobs.sql`
- Test: `tests/test_db_sql.py`（追加）

**Interfaces:**
- Produces: 表 `ohlcv_bars(ticker,bar_date PK)`、`market_breadth(breadth_date PK)`、`macro_indicators(series_id,obs_date PK)`、`fundamentals(ticker,period_end PK)`；`scheduled_jobs` 新增 4 行（`prices/breadth/macro/fundamentals`，默认 `enabled=false`）。
- Consumes: 现有 `migrations/007_scheduled_jobs.sql` 的 `scheduled_jobs` 表结构（列 `name,time_local,weekday_mask,timezone,enabled`）。

- [ ] **Step 1: 写迁移断言测试** —— 在 `tests/test_db_sql.py` 末尾追加：

```python
def test_ohlcv_bars_migration():
    sql = Path("migrations/009_ohlcv_bars.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS ohlcv_bars" in sql
    assert "PRIMARY KEY (ticker, bar_date)" in sql
    assert "adj_close" in sql
    assert "volume      BIGINT" in sql or "volume BIGINT" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date" in sql


def test_market_breadth_migration():
    sql = Path("migrations/010_market_breadth.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS market_breadth" in sql
    assert "breadth_date         DATE PRIMARY KEY" in sql or "breadth_date DATE PRIMARY KEY" in sql
    assert "pct_above_200ma" in sql
    assert "advance_decline" in sql
    assert "universe_size" in sql
    assert "details              JSONB" in sql or "details JSONB" in sql


def test_macro_indicators_migration():
    sql = Path("migrations/011_macro_indicators.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS macro_indicators" in sql
    assert "PRIMARY KEY (series_id, obs_date)" in sql
    assert "value" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_macro_indicators_series_date" in sql


def test_fundamentals_migration():
    sql = Path("migrations/012_fundamentals.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS fundamentals" in sql
    assert "PRIMARY KEY (ticker, period_end)" in sql
    assert "eps_surprise" in sql
    assert "report_date" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_fundamentals_report" in sql


def test_phase1_scheduled_jobs_migration():
    sql = Path("migrations/013_phase1_scheduled_jobs.sql").read_text()
    assert "INSERT INTO scheduled_jobs" in sql
    for name in ("prices", "breadth", "macro", "fundamentals"):
        assert f"'{name}'" in sql
    assert "ON CONFLICT (name) DO NOTHING" in sql
    assert "FALSE" in sql or "false" in sql
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_db_sql.py -k "ohlcv or breadth or macro or fundamentals or phase1" -v`
Expected: FAIL（文件不存在，FileNotFoundError）。

- [ ] **Step 3: 写 `migrations/009_ohlcv_bars.sql`**

```sql
CREATE TABLE IF NOT EXISTS ohlcv_bars (
  ticker      TEXT NOT NULL,
  bar_date    DATE NOT NULL,
  open        NUMERIC(18,6),
  high        NUMERIC(18,6),
  low         NUMERIC(18,6),
  close       NUMERIC(18,6),
  adj_close   NUMERIC(18,6),
  volume      BIGINT,
  source      TEXT NOT NULL DEFAULT 'yfinance',
  fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, bar_date)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv_bars (ticker, bar_date DESC);
```

- [ ] **Step 4: 写 `migrations/010_market_breadth.sql`**

```sql
CREATE TABLE IF NOT EXISTS market_breadth (
  breadth_date         DATE PRIMARY KEY,
  pct_above_200ma      NUMERIC(6,2),
  pct_above_50ma       NUMERIC(6,2),
  new_highs_minus_lows INT,
  advance_decline      INT,
  universe_size        INT NOT NULL,
  details              JSONB NOT NULL DEFAULT '{}'::jsonb,
  computed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_market_breadth_date ON market_breadth (breadth_date DESC);
```

- [ ] **Step 5: 写 `migrations/011_macro_indicators.sql`**

```sql
CREATE TABLE IF NOT EXISTS macro_indicators (
  obs_date     DATE NOT NULL,
  series_id    TEXT NOT NULL,
  value        NUMERIC(18,6),
  source       TEXT NOT NULL DEFAULT 'fred',
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (series_id, obs_date)
);
CREATE INDEX IF NOT EXISTS idx_macro_indicators_series_date ON macro_indicators (series_id, obs_date DESC);
```

- [ ] **Step 6: 写 `migrations/012_fundamentals.sql`**

```sql
CREATE TABLE IF NOT EXISTS fundamentals (
  ticker           TEXT NOT NULL,
  period_end       DATE NOT NULL,
  report_date      DATE,
  eps_actual       NUMERIC(18,6),
  eps_estimate     NUMERIC(18,6),
  eps_surprise     NUMERIC(18,6),
  revenue_actual   NUMERIC(20,2),
  revenue_estimate NUMERIC(20,2),
  source           TEXT NOT NULL DEFAULT 'yfinance',
  fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, period_end)
);
CREATE INDEX IF NOT EXISTS idx_fundamentals_report ON fundamentals (ticker, report_date DESC);
```

- [ ] **Step 7: 写 `migrations/013_phase1_scheduled_jobs.sql`**

```sql
-- Phase 1 采集任务默认排程行；默认 disabled，配置好数据源/key 后在 UI 启用
INSERT INTO scheduled_jobs (name, time_local, weekday_mask, timezone, enabled) VALUES
  ('prices',       '07:30', '1-5', 'America/New_York', FALSE),
  ('breadth',      '07:45', '1-5', 'America/New_York', FALSE),
  ('macro',        '07:50', '1-5', 'America/New_York', FALSE),
  ('fundamentals', '07:55', '1-5', 'America/New_York', FALSE)
ON CONFLICT (name) DO NOTHING;
```

- [ ] **Step 8: 运行测试确认通过**

Run: `pytest tests/test_db_sql.py -k "ohlcv or breadth or macro or fundamentals or phase1" -v`
Expected: PASS（5 个新测试全绿）。

- [ ] **Step 9: Commit**

```bash
git add migrations/009_ohlcv_bars.sql migrations/010_market_breadth.sql \
        migrations/011_macro_indicators.sql migrations/012_fundamentals.sql \
        migrations/013_phase1_scheduled_jobs.sql tests/test_db_sql.py
git commit -m "feat(db): Phase 1 migrations 009-013 (ohlcv/breadth/macro/fundamentals + schedules)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2：`data/price.py` — `fetch_ohlcv`（区间 + 复权 + 重试）

**Files:**
- Modify: `investment_assistant/data/price.py`
- Test: `tests/test_data_price_ohlcv.py`

**Interfaces:**
- Produces:
  - `fetch_ohlcv(ticker, *, start, end, max_retries=3, backoff_seconds=1.0, ticker_factory=None, sleep=time.sleep) -> pd.DataFrame`：返回列 `["Open","High","Low","Close","Adj Close","Volume"]`，index 为 DatetimeIndex。连续失败时退避重试，最终仍失败抛 `ValueError`。`ticker_factory(ticker)` 注入（默认 `yf.Ticker`）；用 `auto_adjust=False` 以同时拿到 `Close` 与 `Adj Close`。
- Consumes: 无（最底层）。

- [ ] **Step 1: 写失败测试** —— `tests/test_data_price_ohlcv.py`：

```python
from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from investment_assistant.data.price import fetch_ohlcv


def _frame():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {
            "Open": [1.0, 1.1], "High": [2.0, 2.1], "Low": [0.5, 0.6],
            "Close": [1.5, 1.6], "Adj Close": [1.4, 1.5], "Volume": [100, 200],
        },
        index=idx,
    )


def test_fetch_ohlcv_returns_adjclose_and_calls_history_with_range():
    fake = MagicMock()
    fake.history.return_value = _frame()
    factory = MagicMock(return_value=fake)
    out = fetch_ohlcv("NVDA", start=date(2024, 1, 1), end=date(2024, 1, 4), ticker_factory=factory)
    factory.assert_called_once_with("NVDA")
    _, kwargs = fake.history.call_args
    assert kwargs["start"] == "2024-01-01"
    assert kwargs["end"] == "2024-01-04"
    assert kwargs["auto_adjust"] is False
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


def test_fetch_ohlcv_retries_then_succeeds():
    fake = MagicMock()
    fake.history.side_effect = [pd.DataFrame(), _frame()]  # 第一次空→重试
    sleeps = []
    out = fetch_ohlcv(
        "MU", start=date(2024, 1, 1), end=date(2024, 1, 4),
        ticker_factory=MagicMock(return_value=fake), max_retries=2,
        sleep=lambda s: sleeps.append(s),
    )
    assert len(out) == 2
    assert fake.history.call_count == 2
    assert sleeps  # 退避被调用过


def test_fetch_ohlcv_raises_after_exhausting_retries():
    fake = MagicMock()
    fake.history.return_value = pd.DataFrame()
    with pytest.raises(ValueError):
        fetch_ohlcv(
            "ZZZZ", start=date(2024, 1, 1), end=date(2024, 1, 4),
            ticker_factory=MagicMock(return_value=fake), max_retries=1, sleep=lambda s: None,
        )
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_data_price_ohlcv.py -v`
Expected: FAIL（`fetch_ohlcv` 不存在，ImportError）。

- [ ] **Step 3: 实现 `fetch_ohlcv`** —— 在 `investment_assistant/data/price.py` 顶部加 `import time`、`from datetime import date`，并追加：

```python
def fetch_ohlcv(
    ticker: str,
    *,
    start: "date",
    end: "date",
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
    ticker_factory=None,
    sleep=time.sleep,
) -> pd.DataFrame:
    """Fetch OHLCV+Adj Close for ``ticker`` over [start, end) with retry/backoff.

    ``auto_adjust=False`` keeps both raw Close and Adj Close. ``ticker_factory``
    is injected for testing; defaults to ``yf.Ticker``.
    """
    factory = ticker_factory or yf.Ticker
    cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    last_error = "unknown"
    for attempt in range(max_retries + 1):
        try:
            df = factory(ticker).history(
                start=start.isoformat(), end=end.isoformat(), auto_adjust=False
            )
        except Exception as exc:  # 网络/解析异常 → 结构化重试
            last_error = f"history error: {exc}"
            df = pd.DataFrame()
        if not df.empty and {"Close", "Volume"}.issubset(df.columns):
            for col in cols:
                if col not in df.columns:
                    df[col] = None
            return df[cols]
        last_error = last_error if last_error != "unknown" else "empty frame"
        if attempt < max_retries:
            sleep(min(backoff_seconds * (2 ** attempt), 30.0))
    raise ValueError(f"No OHLCV for {ticker} [{start}..{end}): {last_error}")
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_data_price_ohlcv.py -v`
Expected: PASS（3 个测试全绿）。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/data/price.py tests/test_data_price_ohlcv.py
git commit -m "feat(data): fetch_ohlcv with date range, adj_close, retry/backoff

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3：`data/fred.py` — FRED 取数（精简 2 序列 + 缺 key 降级）

**Files:**
- Create: `investment_assistant/data/fred.py`
- Test: `tests/test_data_fred.py`

**Interfaces:**
- Produces:
  - `fetch_fred_series(series_id, *, start, end, api_key=None, getter=None) -> tuple[list[dict] | None, dict]`：返回 `(rows, status)`；`rows` 为 `[{"obs_date": date, "value": float|None}]`，`status` 形如 `{"ok": bool, "error": str|None, "skipped": bool}`。缺 `api_key` → `(None, {"ok": False, "skipped": True, "error": "FRED_API_KEY missing"})`，**不含 key 值**。`getter` 默认 `investment_assistant.data.http.get_json`（注入式）。FRED 缺测值 `"."` → `value=None`。
- Consumes: `investment_assistant.data.http.get_json(url, *, params, headers, timeout, max_retries, backoff_seconds) -> tuple[dict|None, dict]`。

- [ ] **Step 1: 写失败测试** —— `tests/test_data_fred.py`：

```python
from datetime import date

from investment_assistant.data.fred import fetch_fred_series


def test_fetch_fred_parses_observations():
    payload = {"observations": [
        {"date": "2024-01-02", "value": "7.45"},
        {"date": "2024-01-03", "value": "."},
    ]}
    captured = {}

    def getter(url, *, params=None, headers=None, timeout=30, max_retries=3, backoff_seconds=1.0):
        captured["url"] = url
        captured["params"] = params
        return payload, {"ok": True, "error": None, "status_code": 200}

    rows, status = fetch_fred_series(
        "BAMLH0A0HYM2", start=date(2024, 1, 1), end=date(2024, 1, 4),
        api_key="secret-key", getter=getter,
    )
    assert status["ok"] is True
    assert rows[0]["obs_date"] == date(2024, 1, 2)
    assert rows[0]["value"] == 7.45
    assert rows[1]["value"] is None        # "." → None
    assert captured["params"]["series_id"] == "BAMLH0A0HYM2"
    assert captured["params"]["api_key"] == "secret-key"


def test_fetch_fred_skips_without_key_and_hides_secret():
    rows, status = fetch_fred_series(
        "T10Y2Y", start=date(2024, 1, 1), end=date(2024, 1, 4), api_key=None,
    )
    assert rows is None
    assert status["skipped"] is True
    assert status["ok"] is False
    assert "missing" in status["error"].lower()


def test_fetch_fred_returns_error_on_getter_failure():
    def getter(url, **kwargs):
        return None, {"ok": False, "error": "http 500", "status_code": 500}

    rows, status = fetch_fred_series(
        "T10Y2Y", start=date(2024, 1, 1), end=date(2024, 1, 4),
        api_key="k", getter=getter,
    )
    assert rows is None
    assert status["ok"] is False
    assert status["skipped"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_data_fred.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `investment_assistant/data/fred.py`**

```python
from __future__ import annotations

from datetime import date
from typing import Any, Callable

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

Getter = Callable[..., tuple[dict[str, Any] | None, dict[str, Any]]]


def _parse_value(raw: Any) -> float | None:
    if raw in (None, ".", ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def fetch_fred_series(
    series_id: str,
    *,
    start: date,
    end: date,
    api_key: str | None = None,
    getter: Getter | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """Fetch one FRED series. Degrades (no crash) when api_key is missing.

    The api_key is never echoed into the returned status/error text.
    """
    if not api_key:
        return None, {"ok": False, "skipped": True, "error": "FRED_API_KEY missing"}
    if getter is None:
        from investment_assistant.data import http

        getter = http.get_json
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
    }
    payload, status = getter(FRED_OBSERVATIONS_URL, params=params)
    if not status.get("ok") or not payload:
        return None, {"ok": False, "skipped": False, "error": status.get("error", "fred error")}
    rows: list[dict[str, Any]] = []
    for obs in payload.get("observations", []):
        try:
            obs_date = date.fromisoformat(str(obs["date"]))
        except (KeyError, ValueError):
            continue
        rows.append({"obs_date": obs_date, "value": _parse_value(obs.get("value"))})
    return rows, {"ok": True, "skipped": False, "error": None}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_data_fred.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/data/fred.py tests/test_data_fred.py
git commit -m "feat(data): FRED series fetch (HY/2s10s) with missing-key degrade, no secret echo

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4：`data/fundamentals.py` — EPS surprise 抽取

**Files:**
- Create: `investment_assistant/data/fundamentals.py`
- Test: `tests/test_data_fundamentals.py`

**Interfaces:**
- Produces:
  - `compute_eps_surprise(actual, estimate) -> float | None`：`(actual-estimate)/abs(estimate)`；`estimate in (None, 0)` 或 `actual is None` → None（除零保护）。
  - `fetch_earnings(ticker, *, ticker_factory=None) -> list[dict]`：返回 `[{"period_end": date|None, "report_date": date|None, "eps_actual": float|None, "eps_estimate": float|None, "eps_surprise": float|None, "revenue_actual": float|None, "revenue_estimate": float|None}]`。从 yfinance `get_earnings_dates()`（DataFrame，index=报告日，列含 `EPS Estimate`/`Reported EPS`）解析；字段缺失 → None。`ticker_factory` 注入。
- Consumes: 无。

- [ ] **Step 1: 写失败测试** —— `tests/test_data_fundamentals.py`：

```python
from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from investment_assistant.data.fundamentals import compute_eps_surprise, fetch_earnings


def test_compute_eps_surprise_basic():
    assert compute_eps_surprise(1.2, 1.0) == 0.2 / 1.0
    assert compute_eps_surprise(0.8, 1.0) == (0.8 - 1.0) / 1.0


def test_compute_eps_surprise_guards_zero_and_none():
    assert compute_eps_surprise(1.0, 0) is None
    assert compute_eps_surprise(1.0, None) is None
    assert compute_eps_surprise(None, 1.0) is None


def test_fetch_earnings_parses_yf_frame():
    idx = pd.to_datetime(["2024-02-21", "2023-11-21"])
    frame = pd.DataFrame(
        {"EPS Estimate": [0.50, 0.40], "Reported EPS": [0.52, 0.38]}, index=idx
    )
    fake = MagicMock()
    fake.get_earnings_dates.return_value = frame
    rows = fetch_earnings("NVDA", ticker_factory=MagicMock(return_value=fake))
    first = next(r for r in rows if r["report_date"] == date(2024, 2, 21))
    assert first["eps_actual"] == 0.52
    assert first["eps_estimate"] == 0.50
    assert abs(first["eps_surprise"] - (0.52 - 0.50) / 0.50) < 1e-9


def test_fetch_earnings_handles_empty():
    fake = MagicMock()
    fake.get_earnings_dates.return_value = pd.DataFrame()
    rows = fetch_earnings("ZZZZ", ticker_factory=MagicMock(return_value=fake))
    assert rows == []
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_data_fundamentals.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `investment_assistant/data/fundamentals.py`**

```python
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def compute_eps_surprise(actual: float | None, estimate: float | None) -> float | None:
    """(actual - estimate) / abs(estimate), guarding None and estimate==0."""
    if actual is None or estimate is None or estimate == 0:
        return None
    return (actual - estimate) / abs(estimate)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def fetch_earnings(ticker: str, *, ticker_factory=None) -> list[dict[str, Any]]:
    """Pull per-quarter EPS actual/estimate (+revenue if present) from yfinance.

    Uses get_earnings_dates(); index is the report date. Missing fields -> None.
    ``ticker_factory`` is injected for testing (defaults to yf.Ticker).
    """
    if ticker_factory is None:
        import yfinance as yf

        ticker_factory = yf.Ticker
    obj = ticker_factory(ticker)
    try:
        frame = obj.get_earnings_dates()
    except Exception:
        frame = None
    if frame is None or getattr(frame, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    for idx, record in frame.iterrows():
        report_date = _to_date(idx)
        eps_actual = _to_float(record.get("Reported EPS"))
        eps_estimate = _to_float(record.get("EPS Estimate"))
        rows.append(
            {
                "period_end": report_date,   # yfinance 不直接给季度末；以 report_date 近似，落库 PK 用之
                "report_date": report_date,
                "eps_actual": eps_actual,
                "eps_estimate": eps_estimate,
                "eps_surprise": compute_eps_surprise(eps_actual, eps_estimate),
                "revenue_actual": _to_float(record.get("Reported Revenue")),
                "revenue_estimate": _to_float(record.get("Revenue Estimate")),
            }
        )
    return rows
```

> 注：yfinance `get_earnings_dates()` 不直接给「季度末」，本期以 `report_date` 作为 `period_end` 的近似（PK 仍唯一）。若后续接 SEC XBRL 拿到真实 `period_end`，在 services 层覆盖即可。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_data_fundamentals.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/data/fundamentals.py tests/test_data_fundamentals.py
git commit -m "feat(data): earnings/EPS surprise extraction with zero-divide guard

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5：`market/breadth.py` — 广度指标纯函数

**Files:**
- Create: `investment_assistant/market/breadth.py`
- Test: `tests/test_market_breadth.py`

**Interfaces:**
- Produces:
  - `compute_breadth(price_frames, *, breadth_date) -> dict`：`price_frames` 为 `dict[str, pd.DataFrame]`（每标的截至 `breadth_date` 的日线，含 `Close` 列，按日期升序）。返回 `{"breadth_date": breadth_date, "pct_above_200ma": float|None, "pct_above_50ma": float|None, "new_highs_minus_lows": int|None, "advance_decline": int|None, "universe_size": int, "details": {...}}`。空池 → `universe_size=0` 且各指标 None。百分比为 0..100 保留 2 位。52 周窗口=252 交易日；新高/低=最新 close 是否为窗口内最大/最小；A/D=最新 close vs 前一日 close 的净涨跌家数。
- Consumes: 无（纯函数）。

- [ ] **Step 1: 写失败测试** —— `tests/test_market_breadth.py`：

```python
from datetime import date

import pandas as pd

from investment_assistant.market.breadth import compute_breadth


def _series(values):
    idx = pd.date_range("2022-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"Close": values}, index=idx)


def test_compute_breadth_basic_counts():
    # A: 一路上行（站上均线、创新高、当日上涨）
    up = list(range(1, 261))            # 260 日，递增
    # B: 一路下行（跌破均线、创新低、当日下跌）
    down = list(range(260, 0, -1))
    frames = {"A": _series([float(v) for v in up]), "B": _series([float(v) for v in down])}
    out = compute_breadth(frames, breadth_date=date(2022, 12, 31))
    assert out["universe_size"] == 2
    assert out["pct_above_200ma"] == 50.0     # 只有 A 站上 200MA
    assert out["pct_above_50ma"] == 50.0
    assert out["new_highs_minus_lows"] == 0   # A 新高(+1) - B 新低(1) = 0
    assert out["advance_decline"] == 0        # A 涨(+1) - B 跌(1) = 0


def test_compute_breadth_all_up():
    up = [float(v) for v in range(1, 261)]
    frames = {"A": _series(up), "B": _series(up)}
    out = compute_breadth(frames, breadth_date=date(2022, 12, 31))
    assert out["pct_above_200ma"] == 100.0
    assert out["new_highs_minus_lows"] == 2
    assert out["advance_decline"] == 2


def test_compute_breadth_empty_universe_degrades():
    out = compute_breadth({}, breadth_date=date(2022, 12, 31))
    assert out["universe_size"] == 0
    assert out["pct_above_200ma"] is None
    assert out["new_highs_minus_lows"] is None
    assert out["advance_decline"] is None


def test_compute_breadth_skips_short_series():
    out = compute_breadth({"A": _series([1.0, 2.0, 3.0])}, breadth_date=date(2022, 1, 3))
    # 不足 200 日 → 不计入 200MA 分母，但仍计入 universe / AD
    assert out["universe_size"] == 1
    assert out["pct_above_200ma"] is None or out["pct_above_200ma"] == 0.0
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_market_breadth.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `investment_assistant/market/breadth.py`**

```python
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def _round2(num: float, den: int) -> float | None:
    if den <= 0:
        return None
    return round(100.0 * num / den, 2)


def compute_breadth(
    price_frames: dict[str, pd.DataFrame], *, breadth_date: date
) -> dict[str, Any]:
    """Compute market-breadth metrics from per-constituent Close series.

    Degrades gracefully: empty universe -> universe_size 0 and None metrics.
    """
    universe_size = len(price_frames)
    if universe_size == 0:
        return {
            "breadth_date": breadth_date,
            "pct_above_200ma": None,
            "pct_above_50ma": None,
            "new_highs_minus_lows": None,
            "advance_decline": None,
            "universe_size": 0,
            "details": {"reason": "empty universe"},
        }

    above_200 = above_50 = den_200 = den_50 = 0
    new_highs = new_lows = advances = declines = 0
    skipped: list[str] = []

    for ticker, frame in price_frames.items():
        if frame is None or frame.empty or "Close" not in frame.columns:
            skipped.append(ticker)
            continue
        closes = frame["Close"].dropna()
        if closes.empty:
            skipped.append(ticker)
            continue
        last = float(closes.iloc[-1])

        if len(closes) >= 200:
            den_200 += 1
            if last > float(closes.tail(200).mean()):
                above_200 += 1
        if len(closes) >= 50:
            den_50 += 1
            if last > float(closes.tail(50).mean()):
                above_50 += 1

        window = closes.tail(252)
        if len(window) >= 2:
            if last >= float(window.max()):
                new_highs += 1
            if last <= float(window.min()):
                new_lows += 1
            prev = float(closes.iloc[-2])
            if last > prev:
                advances += 1
            elif last < prev:
                declines += 1

    return {
        "breadth_date": breadth_date,
        "pct_above_200ma": _round2(above_200, den_200),
        "pct_above_50ma": _round2(above_50, den_50),
        "new_highs_minus_lows": new_highs - new_lows,
        "advance_decline": advances - declines,
        "universe_size": universe_size,
        "details": {
            "den_200": den_200,
            "den_50": den_50,
            "skipped": skipped,
        },
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_market_breadth.py -v`
Expected: PASS。

> 自检：`test_compute_breadth_basic_counts` 中 A 递增 → den_200=1、above=1；B 递减 → den_200=1、above=0 → `pct_above_200ma = 100*1/2 = 50.0`。A 最新=最大→new_high；B 最新=最小→new_low → `1-1=0`。A 当日涨、B 当日跌 → `1-1=0`。与断言一致。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/market/breadth.py tests/test_market_breadth.py
git commit -m "feat(market): breadth metrics (pct>200/50MA, new highs-lows, A/D) with empty-universe degrade

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6：`db.py` — OHLCV/广度/宏观/财报 仓储

**Files:**
- Modify: `investment_assistant/db.py`
- Test: `tests/test_ohlcv_repository.py`, `tests/test_breadth_repository.py`, `tests/test_macro_repository.py`, `tests/test_fundamentals_repository.py`

**Interfaces:**
- Produces（全部接受 `conn`，对齐现有 `with conn.cursor() as cur` + 具名参数 + `dict(zip(keys,row))`）：
  - `upsert_ohlcv_bars(conn, ticker, rows) -> int`（rows: `[{bar_date, open, high, low, close, adj_close, volume}]`）
  - `get_ohlcv_bars(conn, ticker, *, start=None, end=None, limit=1000) -> list[dict]`
  - `latest_bar_date(conn, ticker) -> date | None`
  - `upsert_market_breadth(conn, row) -> None`
  - `get_market_breadth(conn, *, start=None, end=None, limit=200) -> list[dict]`
  - `latest_market_breadth(conn) -> dict | None`
  - `upsert_macro_observations(conn, series_id, rows) -> int`（rows: `[{obs_date, value}]`）
  - `get_macro_series(conn, series_id, *, start=None, end=None, limit=500) -> list[dict]`
  - `latest_macro_value(conn, series_id) -> dict | None`
  - `upsert_fundamentals(conn, ticker, rows) -> int`
  - `get_fundamentals(conn, ticker, *, start=None, end=None, limit=40) -> list[dict]`
  - `list_eps_events(conn, *, start=None, end=None, limit=500) -> list[dict]`（`report_date IS NOT NULL`，供 Phase 0 锚点）
- Consumes: 表 009–012。

测试用与 `tests/test_job_reports_repository.py` 相同的 `FakeConn/FakeCursor`（execute 记录 SQL+params；fetchall 返回预置 rows）。

- [ ] **Step 1: 写失败测试 `tests/test_ohlcv_repository.py`**

```python
from datetime import date

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

    def executemany(self, sql, seq):
        self.store.append((sql, list(seq)))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(self, rows=None):
        self.store, self.commits, self.rows = [], 0, rows or []

    def cursor(self):
        return FakeCursor(self.store, self.rows)

    def commit(self):
        self.commits += 1


def test_upsert_ohlcv_bars_uses_on_conflict():
    conn = FakeConn()
    n = db.upsert_ohlcv_bars(conn, "NVDA", [
        {"bar_date": date(2024, 1, 2), "open": 1, "high": 2, "low": 0.5,
         "close": 1.5, "adj_close": 1.4, "volume": 100},
    ])
    assert n == 1
    sql = conn.store[0][0]
    assert "INSERT INTO ohlcv_bars" in sql
    assert "ON CONFLICT (ticker, bar_date) DO UPDATE" in sql
    assert conn.commits == 1


def test_get_ohlcv_bars_maps_rows():
    rows = [("NVDA", date(2024, 1, 2), 1, 2, 0.5, 1.5, 1.4, 100, "yfinance", None)]
    conn = FakeConn(rows=rows)
    out = db.get_ohlcv_bars(conn, "NVDA", start=date(2024, 1, 1))
    assert out[0]["ticker"] == "NVDA"
    assert out[0]["adj_close"] == 1.4


def test_latest_bar_date_returns_none_when_empty():
    assert db.latest_bar_date(FakeConn(rows=[]), "NVDA") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_ohlcv_repository.py -v`
Expected: FAIL（函数不存在）。

- [ ] **Step 3: 实现 OHLCV 仓储** —— 在 `investment_assistant/db.py` 末尾追加：

```python
def upsert_ohlcv_bars(conn, ticker: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO ohlcv_bars (
                  ticker, bar_date, open, high, low, close, adj_close, volume, source
                ) VALUES (
                  %(ticker)s, %(bar_date)s, %(open)s, %(high)s, %(low)s, %(close)s,
                  %(adj_close)s, %(volume)s, %(source)s
                )
                ON CONFLICT (ticker, bar_date) DO UPDATE SET
                  open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                  close = EXCLUDED.close, adj_close = EXCLUDED.adj_close,
                  volume = EXCLUDED.volume, source = EXCLUDED.source,
                  fetched_at = now()
                """,
                {
                    "ticker": ticker,
                    "bar_date": row.get("bar_date"),
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "adj_close": row.get("adj_close"),
                    "volume": row.get("volume"),
                    "source": row.get("source", "yfinance"),
                },
            )
    conn.commit()
    return len(rows)


_OHLCV_KEYS = ["ticker", "bar_date", "open", "high", "low", "close",
               "adj_close", "volume", "source", "fetched_at"]


def get_ohlcv_bars(conn, ticker: str, *, start=None, end=None, limit: int = 1000) -> list[dict[str, Any]]:
    clauses = ["ticker = %(ticker)s"]
    params: dict[str, Any] = {"ticker": ticker, "limit": limit}
    if start is not None:
        clauses.append("bar_date >= %(start)s")
        params["start"] = start
    if end is not None:
        clauses.append("bar_date <= %(end)s")
        params["end"] = end
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ticker, bar_date, open, high, low, close, adj_close, volume, source, fetched_at
            FROM ohlcv_bars
            WHERE {' AND '.join(clauses)}
            ORDER BY bar_date ASC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()
    return [dict(zip(_OHLCV_KEYS, row)) for row in rows]


def latest_bar_date(conn, ticker: str):
    with conn.cursor() as cur:
        cur.execute("SELECT max(bar_date) FROM ohlcv_bars WHERE ticker = %(ticker)s", {"ticker": ticker})
        row = cur.fetchone()
    return row[0] if row else None
```

- [ ] **Step 4: 运行 OHLCV 测试确认通过**

Run: `pytest tests/test_ohlcv_repository.py -v`
Expected: PASS。

- [ ] **Step 5: 写失败测试 `tests/test_breadth_repository.py`**（复用同款 FakeConn/FakeCursor，从 `tests/test_ohlcv_repository.py` 复制类定义到本文件顶部）

```python
from datetime import date

from investment_assistant import db
from tests.test_ohlcv_repository import FakeConn  # 复用


def test_upsert_market_breadth_on_conflict():
    conn = FakeConn()
    db.upsert_market_breadth(conn, {
        "breadth_date": date(2024, 1, 2), "pct_above_200ma": 55.0, "pct_above_50ma": 60.0,
        "new_highs_minus_lows": 3, "advance_decline": 2, "universe_size": 10, "details": {"x": 1},
    })
    sql = conn.store[0][0]
    assert "INSERT INTO market_breadth" in sql
    assert "ON CONFLICT (breadth_date) DO UPDATE" in sql
    assert conn.commits == 1


def test_get_market_breadth_maps_rows():
    rows = [(date(2024, 1, 2), 55.0, 60.0, 3, 2, 10, {"x": 1}, None)]
    out = db.get_market_breadth(FakeConn(rows=rows))
    assert out[0]["pct_above_200ma"] == 55.0
    assert out[0]["universe_size"] == 10
```

- [ ] **Step 6: 实现广度仓储** —— 在 `db.py` 追加（注意 `details` 用 `json.dumps` + `::jsonb`，对齐 `insert_job_report`）：

```python
def upsert_market_breadth(conn, row: dict[str, Any]) -> None:
    payload = {
        "breadth_date": row.get("breadth_date"),
        "pct_above_200ma": row.get("pct_above_200ma"),
        "pct_above_50ma": row.get("pct_above_50ma"),
        "new_highs_minus_lows": row.get("new_highs_minus_lows"),
        "advance_decline": row.get("advance_decline"),
        "universe_size": row.get("universe_size", 0),
        "details": json.dumps(row.get("details") or {}, ensure_ascii=False, default=str),
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market_breadth (
              breadth_date, pct_above_200ma, pct_above_50ma, new_highs_minus_lows,
              advance_decline, universe_size, details
            ) VALUES (
              %(breadth_date)s, %(pct_above_200ma)s, %(pct_above_50ma)s, %(new_highs_minus_lows)s,
              %(advance_decline)s, %(universe_size)s, %(details)s::jsonb
            )
            ON CONFLICT (breadth_date) DO UPDATE SET
              pct_above_200ma = EXCLUDED.pct_above_200ma,
              pct_above_50ma = EXCLUDED.pct_above_50ma,
              new_highs_minus_lows = EXCLUDED.new_highs_minus_lows,
              advance_decline = EXCLUDED.advance_decline,
              universe_size = EXCLUDED.universe_size,
              details = EXCLUDED.details,
              computed_at = now()
            """,
            payload,
        )
    conn.commit()


_BREADTH_KEYS = ["breadth_date", "pct_above_200ma", "pct_above_50ma", "new_highs_minus_lows",
                 "advance_decline", "universe_size", "details", "computed_at"]


def get_market_breadth(conn, *, start=None, end=None, limit: int = 200) -> list[dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if start is not None:
        clauses.append("breadth_date >= %(start)s")
        params["start"] = start
    if end is not None:
        clauses.append("breadth_date <= %(end)s")
        params["end"] = end
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT breadth_date, pct_above_200ma, pct_above_50ma, new_highs_minus_lows,
                   advance_decline, universe_size, details, computed_at
            FROM market_breadth {where}
            ORDER BY breadth_date DESC LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()
    return [dict(zip(_BREADTH_KEYS, row)) for row in rows]


def latest_market_breadth(conn):
    rows = get_market_breadth(conn, limit=1)
    return rows[0] if rows else None
```

- [ ] **Step 7: 写失败测试 `tests/test_macro_repository.py`**

```python
from datetime import date

from investment_assistant import db
from tests.test_ohlcv_repository import FakeConn


def test_upsert_macro_observations_on_conflict():
    conn = FakeConn()
    n = db.upsert_macro_observations(conn, "BAMLH0A0HYM2", [
        {"obs_date": date(2024, 1, 2), "value": 7.45},
        {"obs_date": date(2024, 1, 3), "value": None},
    ])
    assert n == 2
    sql = conn.store[0][0]
    assert "INSERT INTO macro_indicators" in sql
    assert "ON CONFLICT (series_id, obs_date) DO UPDATE" in sql


def test_get_macro_series_maps_rows():
    rows = [("BAMLH0A0HYM2", date(2024, 1, 2), 7.45, "fred", None)]
    out = db.get_macro_series(FakeConn(rows=rows), "BAMLH0A0HYM2")
    assert out[0]["series_id"] == "BAMLH0A0HYM2"
    assert out[0]["value"] == 7.45
```

- [ ] **Step 8: 实现宏观仓储** —— 在 `db.py` 追加：

```python
def upsert_macro_observations(conn, series_id: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO macro_indicators (series_id, obs_date, value, source)
                VALUES (%(series_id)s, %(obs_date)s, %(value)s, %(source)s)
                ON CONFLICT (series_id, obs_date) DO UPDATE SET
                  value = EXCLUDED.value, source = EXCLUDED.source, fetched_at = now()
                """,
                {
                    "series_id": series_id,
                    "obs_date": row.get("obs_date"),
                    "value": row.get("value"),
                    "source": row.get("source", "fred"),
                },
            )
    conn.commit()
    return len(rows)


_MACRO_KEYS = ["series_id", "obs_date", "value", "source", "fetched_at"]


def get_macro_series(conn, series_id: str, *, start=None, end=None, limit: int = 500) -> list[dict[str, Any]]:
    clauses = ["series_id = %(series_id)s"]
    params: dict[str, Any] = {"series_id": series_id, "limit": limit}
    if start is not None:
        clauses.append("obs_date >= %(start)s")
        params["start"] = start
    if end is not None:
        clauses.append("obs_date <= %(end)s")
        params["end"] = end
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT series_id, obs_date, value, source, fetched_at
            FROM macro_indicators
            WHERE {' AND '.join(clauses)}
            ORDER BY obs_date DESC LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()
    return [dict(zip(_MACRO_KEYS, row)) for row in rows]


def latest_macro_value(conn, series_id: str):
    rows = get_macro_series(conn, series_id, limit=1)
    return rows[0] if rows else None
```

- [ ] **Step 9: 写失败测试 `tests/test_fundamentals_repository.py`**

```python
from datetime import date

from investment_assistant import db
from tests.test_ohlcv_repository import FakeConn


def test_upsert_fundamentals_on_conflict():
    conn = FakeConn()
    n = db.upsert_fundamentals(conn, "NVDA", [
        {"period_end": date(2024, 1, 28), "report_date": date(2024, 2, 21),
         "eps_actual": 0.52, "eps_estimate": 0.50, "eps_surprise": 0.04,
         "revenue_actual": 2.2e10, "revenue_estimate": 2.0e10},
    ])
    assert n == 1
    sql = conn.store[0][0]
    assert "INSERT INTO fundamentals" in sql
    assert "ON CONFLICT (ticker, period_end) DO UPDATE" in sql


def test_list_eps_events_filters_report_date_not_null():
    rows = [("NVDA", date(2024, 1, 28), date(2024, 2, 21), 0.52, 0.50, 0.04, None, None, "yfinance", None)]
    conn = FakeConn(rows=rows)
    out = db.list_eps_events(conn)
    assert out[0]["ticker"] == "NVDA"
    assert "report_date IS NOT NULL" in conn.store[0][0]
```

- [ ] **Step 10: 实现财报仓储** —— 在 `db.py` 追加：

```python
_FUND_KEYS = ["ticker", "period_end", "report_date", "eps_actual", "eps_estimate",
              "eps_surprise", "revenue_actual", "revenue_estimate", "source", "fetched_at"]


def upsert_fundamentals(conn, ticker: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        for row in rows:
            if row.get("period_end") is None:
                continue
            cur.execute(
                """
                INSERT INTO fundamentals (
                  ticker, period_end, report_date, eps_actual, eps_estimate, eps_surprise,
                  revenue_actual, revenue_estimate, source
                ) VALUES (
                  %(ticker)s, %(period_end)s, %(report_date)s, %(eps_actual)s, %(eps_estimate)s,
                  %(eps_surprise)s, %(revenue_actual)s, %(revenue_estimate)s, %(source)s
                )
                ON CONFLICT (ticker, period_end) DO UPDATE SET
                  report_date = EXCLUDED.report_date,
                  eps_actual = EXCLUDED.eps_actual, eps_estimate = EXCLUDED.eps_estimate,
                  eps_surprise = EXCLUDED.eps_surprise,
                  revenue_actual = EXCLUDED.revenue_actual, revenue_estimate = EXCLUDED.revenue_estimate,
                  source = EXCLUDED.source, fetched_at = now()
                """,
                {
                    "ticker": ticker,
                    "period_end": row.get("period_end"),
                    "report_date": row.get("report_date"),
                    "eps_actual": row.get("eps_actual"),
                    "eps_estimate": row.get("eps_estimate"),
                    "eps_surprise": row.get("eps_surprise"),
                    "revenue_actual": row.get("revenue_actual"),
                    "revenue_estimate": row.get("revenue_estimate"),
                    "source": row.get("source", "yfinance"),
                },
            )
    conn.commit()
    return len(rows)


def get_fundamentals(conn, ticker: str, *, start=None, end=None, limit: int = 40) -> list[dict[str, Any]]:
    clauses = ["ticker = %(ticker)s"]
    params: dict[str, Any] = {"ticker": ticker, "limit": limit}
    if start is not None:
        clauses.append("report_date >= %(start)s")
        params["start"] = start
    if end is not None:
        clauses.append("report_date <= %(end)s")
        params["end"] = end
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ticker, period_end, report_date, eps_actual, eps_estimate, eps_surprise,
                   revenue_actual, revenue_estimate, source, fetched_at
            FROM fundamentals
            WHERE {' AND '.join(clauses)}
            ORDER BY report_date DESC NULLS LAST LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()
    return [dict(zip(_FUND_KEYS, row)) for row in rows]


def list_eps_events(conn, *, start=None, end=None, limit: int = 500) -> list[dict[str, Any]]:
    clauses = ["report_date IS NOT NULL"]
    params: dict[str, Any] = {"limit": limit}
    if start is not None:
        clauses.append("report_date >= %(start)s")
        params["start"] = start
    if end is not None:
        clauses.append("report_date <= %(end)s")
        params["end"] = end
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ticker, period_end, report_date, eps_actual, eps_estimate, eps_surprise,
                   revenue_actual, revenue_estimate, source, fetched_at
            FROM fundamentals
            WHERE {' AND '.join(clauses)}
            ORDER BY report_date DESC LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()
    return [dict(zip(_FUND_KEYS, row)) for row in rows]
```

- [ ] **Step 11: 运行全部仓储测试确认通过**

Run: `pytest tests/test_ohlcv_repository.py tests/test_breadth_repository.py tests/test_macro_repository.py tests/test_fundamentals_repository.py -v`
Expected: PASS。

- [ ] **Step 12: Commit**

```bash
git add investment_assistant/db.py tests/test_ohlcv_repository.py tests/test_breadth_repository.py \
        tests/test_macro_repository.py tests/test_fundamentals_repository.py
git commit -m "feat(db): ohlcv/breadth/macro/fundamentals repositories (upsert + read)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7：`config.py` — 精简 FRED 序列 + 广度/HY 阈值

**Files:**
- Modify: `investment_assistant/config.py`
- Test: `tests/test_config.py`（追加）

**Interfaces:**
- Produces: `MacroConfig.fred_series` 默认 `["BAMLH0A0HYM2", "T10Y2Y"]`；`MarketConfig` 新增 `breadth_red_pct: float = 20.0`、`breadth_yellow_pct: float = 40.0`、`hy_widen_delta: float = 1.0`、`hy_lookback_days: int = 20`。
- Consumes: 无。

- [ ] **Step 1: 写失败测试** —— 在 `tests/test_config.py` 追加：

```python
def test_macro_config_is_trimmed_to_two_series():
    from investment_assistant.config import AssistantConfig

    cfg = AssistantConfig()
    assert cfg.macro.fred_series == ["BAMLH0A0HYM2", "T10Y2Y"]


def test_market_config_has_breadth_and_hy_thresholds():
    from investment_assistant.config import AssistantConfig

    m = AssistantConfig().market
    assert m.breadth_red_pct == 20.0
    assert m.breadth_yellow_pct == 40.0
    assert m.hy_widen_delta == 1.0
    assert m.hy_lookback_days == 20
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_config.py -k "trimmed or breadth_and_hy" -v`
Expected: FAIL。

- [ ] **Step 3: 改 `MarketConfig`** —— 在 `investment_assistant/config.py` 的 `MarketConfig` 中追加四个字段：

```python
@dataclass(frozen=True)
class MarketConfig:
    spy_ticker: str = "SPY"
    vix_ticker: str = "^VIX"
    ma_days: int = 200
    history_days: int = 300
    yellow_vix: float = 20.0
    red_vix: float = 30.0
    breadth_red_pct: float = 20.0
    breadth_yellow_pct: float = 40.0
    hy_widen_delta: float = 1.0
    hy_lookback_days: int = 20
```

- [ ] **Step 4: 改 `MacroConfig.fred_series` 默认值**

```python
@dataclass(frozen=True)
class MacroConfig:
    """FRED macro-indicator collection (Phase 1, trimmed to risk-off signals)."""

    fred_series: list[str] = field(
        default_factory=lambda: ["BAMLH0A0HYM2", "T10Y2Y"]
    )
    lookback_days: int = 400
```

- [ ] **Step 5: 同步 `_market_from_dict` 的 allowed 映射** —— 让新字段可被 config 文件覆盖。在 `_market_from_dict` 的 `allowed` 字典追加：

```python
    allowed = {
        "spy_ticker": str,
        "vix_ticker": str,
        "ma_days": int,
        "history_days": int,
        "yellow_vix": float,
        "red_vix": float,
        "breadth_red_pct": float,
        "breadth_yellow_pct": float,
        "hy_widen_delta": float,
        "hy_lookback_days": int,
    }
```

- [ ] **Step 6: 运行确认通过 + 回归**

Run: `pytest tests/test_config.py -v`
Expected: PASS（含原有 config 测试不破）。

- [ ] **Step 7: Commit**

```bash
git add investment_assistant/config.py tests/test_config.py
git commit -m "feat(config): trim FRED series to HY+2s10s; add breadth/HY gating thresholds

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8：`services/prices.py` — 采集编排 + DB-first 取价

**Files:**
- Create: `investment_assistant/services/prices.py`
- Test: `tests/test_services_prices.py`

**Interfaces:**
- Consumes: `data.price.fetch_ohlcv`（Task 2）、`db.upsert_ohlcv_bars`/`get_ohlcv_bars`/`latest_bar_date`（Task 6）。
- Produces:
  - `ingest_ohlcv(tickers, *, start, end, fetcher=None, conn_factory=None, run_id=None) -> dict`：对每 ticker 取数→upsert，返回 `{"tickers":[...], "range":{"from":str,"to":str}, "written":{ticker:rows}, "gaps":[...], "failures":[...], "degraded":bool}`。缺 DB（`conn_factory=None` 且无 env）→ `degraded=True`，不写库。
  - `BREADTH_UNIVERSE`（在本任务先定义一个 `PRICE_DEFAULT_TICKERS`？不需要）——成分池常量放 services/breadth（Task 9）。
  - `frame_from_bars(rows) -> pd.DataFrame`：把 `get_ohlcv_bars` 的 dict 列表转成含 `Open/High/Low/Close/Volume` 列、DatetimeIndex 的 DataFrame（供 market/trend DB-first 用）。

- [ ] **Step 1: 写失败测试** —— `tests/test_services_prices.py`：

```python
from datetime import date

import pandas as pd

from investment_assistant.services import prices


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fetcher_ok(ticker, *, start, end, **kw):
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {"Open": [1, 1], "High": [2, 2], "Low": [0.5, 0.5], "Close": [1.5, 1.6],
         "Adj Close": [1.4, 1.5], "Volume": [100, 200]}, index=idx,
    )


def test_ingest_ohlcv_writes_and_summarizes(monkeypatch):
    written = {}

    def fake_upsert(conn, ticker, rows):
        written[ticker] = len(rows)
        return len(rows)

    monkeypatch.setattr(prices.db, "upsert_ohlcv_bars", fake_upsert)
    out = prices.ingest_ohlcv(
        ["NVDA"], start=date(2024, 1, 1), end=date(2024, 1, 4),
        fetcher=_fetcher_ok, conn_factory=lambda: _Conn(), run_id="t1",
    )
    assert out["written"]["NVDA"] == 2
    assert out["degraded"] is False
    assert out["range"]["from"] == "2024-01-01"


def test_ingest_ohlcv_records_failures_without_crashing():
    def boom(ticker, *, start, end, **kw):
        raise ValueError("no data")

    out = prices.ingest_ohlcv(
        ["ZZZZ"], start=date(2024, 1, 1), end=date(2024, 1, 4),
        fetcher=boom, conn_factory=lambda: _Conn(),
    )
    assert out["failures"] and out["failures"][0]["ticker"] == "ZZZZ"
    assert out["written"].get("ZZZZ", 0) == 0


def test_ingest_ohlcv_degrades_without_db():
    out = prices.ingest_ohlcv(
        ["NVDA"], start=date(2024, 1, 1), end=date(2024, 1, 4),
        fetcher=_fetcher_ok, conn_factory=None,
    )
    assert out["degraded"] is True
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services_prices.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `investment_assistant/services/prices.py`**

```python
from __future__ import annotations

import os
from datetime import date
from typing import Any, Callable

import pandas as pd

from investment_assistant import db
from investment_assistant.data.price import fetch_ohlcv


def _default_conn_factory():
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        return None
    from investment_assistant.db import connect

    return connect(url)


def _bars_from_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, rec in frame.iterrows():
        rows.append({
            "bar_date": pd.Timestamp(idx).date(),
            "open": _num(rec.get("Open")),
            "high": _num(rec.get("High")),
            "low": _num(rec.get("Low")),
            "close": _num(rec.get("Close")),
            "adj_close": _num(rec.get("Adj Close")),
            "volume": _int(rec.get("Volume")),
        })
    return rows


def _num(v: Any) -> float | None:
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None else None


def ingest_ohlcv(
    tickers: list[str],
    *,
    start: date,
    end: date,
    fetcher: Callable[..., pd.DataFrame] | None = None,
    conn_factory: Callable[[], Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    fetcher = fetcher or fetch_ohlcv
    if conn_factory is None:
        conn_factory = _default_conn_factory
    written: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    cm = conn_factory() if conn_factory else None
    degraded = cm is None
    try:
        conn = cm.__enter__() if cm is not None else None
        for raw in tickers:
            ticker = str(raw or "").strip().upper()
            if not ticker:
                continue
            try:
                frame = fetcher(ticker, start=start, end=end)
                bars = _bars_from_frame(frame)
                if conn is not None:
                    written[ticker] = db.upsert_ohlcv_bars(conn, ticker, bars)
                else:
                    written[ticker] = 0
                if not bars:
                    gaps.append({"ticker": ticker, "reason": "empty"})
            except Exception as exc:  # 逐 ticker 容错，不中断
                failures.append({"ticker": ticker, "error": str(exc)})
        if cm is not None:
            cm.__exit__(None, None, None)
    except Exception as exc:
        if cm is not None:
            cm.__exit__(type(exc), exc, exc.__traceback__)
        raise
    return {
        "tickers": [str(t).strip().upper() for t in tickers if str(t).strip()],
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "written": written,
        "gaps": gaps,
        "failures": failures,
        "degraded": degraded,
        "run_id": run_id,
    }


def frame_from_bars(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    data = {
        "Open": [r.get("open") for r in rows],
        "High": [r.get("high") for r in rows],
        "Low": [r.get("low") for r in rows],
        "Close": [r.get("close") for r in rows],
        "Volume": [r.get("volume") for r in rows],
    }
    idx = pd.to_datetime([r.get("bar_date") for r in rows])
    return pd.DataFrame(data, index=idx)


def query_ohlcv(ticker: str, *, start=None, end=None, limit: int = 1000) -> dict[str, Any]:
    if not os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"):
        return {"rows": [], "degraded": True}
    from investment_assistant.db import connect

    with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
        return {"rows": db.get_ohlcv_bars(conn, ticker, start=start, end=end, limit=limit), "degraded": False}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services_prices.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/services/prices.py tests/test_services_prices.py
git commit -m "feat(services): OHLCV ingest orchestration (per-ticker tolerance, DB degrade, summary)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9：`services/breadth.py` — 广度编排 + 历史回放

**Files:**
- Create: `investment_assistant/services/breadth.py`
- Test: `tests/test_services_breadth.py`

**Interfaces:**
- Consumes: `market.breadth.compute_breadth`（Task 5）、`db.get_ohlcv_bars`/`upsert_market_breadth`（Task 6）、`services.prices.frame_from_bars`（Task 8）。
- Produces:
  - `BREADTH_UNIVERSE: list[str]`（固定代表性篮子常量，如 `["SPY","QQQ","IWM","AAPL","MSFT","NVDA","AMZN","GOOGL","META","JPM"]`）。
  - `resolve_universe(config) -> list[str]`：`BREADTH_UNIVERSE ∪ config.watchlist`，去重大写。
  - `compute_breadth_for_date(target_date, *, universe, conn_factory=None, run_id=None) -> dict`：从 `ohlcv_bars` 读各成分截至 `target_date` 序列 → `compute_breadth` → upsert，返回 summary `{"breadth_date","universe_size","metrics":{...},"missing_constituents":[...],"degraded":bool}`。
  - `compute_breadth_range(start, end, *, universe, conn_factory=None, run_id=None) -> dict`：逐日历日（仅有 bar 的日期产生记录）回放，返回 `{"range":{...},"days":int,"failures":[...],"degraded":bool}`。

- [ ] **Step 1: 写失败测试** —— `tests/test_services_breadth.py`：

```python
from datetime import date

from investment_assistant.services import breadth


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_resolve_universe_merges_watchlist():
    class Cfg:
        watchlist = ["NVDA", "CRDO"]

    uni = breadth.resolve_universe(Cfg())
    assert "SPY" in uni and "CRDO" in uni
    assert len(uni) == len(set(uni))  # 去重


def test_compute_breadth_for_date_writes(monkeypatch):
    # 每个成分给 200+ 天递增序列 → 站上均线
    def fake_get_bars(conn, ticker, *, start=None, end=None, limit=1000):
        return [{"bar_date": date(2022, 1, 1), "close": float(i)} for i in range(1, 261)]

    captured = {}

    def fake_upsert(conn, row):
        captured["row"] = row

    monkeypatch.setattr(breadth.db, "get_ohlcv_bars", fake_get_bars)
    monkeypatch.setattr(breadth.db, "upsert_market_breadth", fake_upsert)
    out = breadth.compute_breadth_for_date(
        date(2022, 12, 31), universe=["A", "B"], conn_factory=lambda: _Conn(), run_id="t",
    )
    assert out["universe_size"] == 2
    assert out["degraded"] is False
    assert captured["row"]["breadth_date"] == date(2022, 12, 31)


def test_compute_breadth_for_date_degrades_without_db():
    out = breadth.compute_breadth_for_date(date(2022, 12, 31), universe=["A"], conn_factory=None)
    assert out["degraded"] is True
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services_breadth.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `investment_assistant/services/breadth.py`**

```python
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd

from investment_assistant import db
from investment_assistant.market.breadth import compute_breadth
from investment_assistant.services.prices import frame_from_bars

BREADTH_UNIVERSE: list[str] = [
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM",
]


def _default_conn_factory():
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        return None
    from investment_assistant.db import connect

    return connect(url)


def resolve_universe(config: Any) -> list[str]:
    watchlist = list(getattr(config, "watchlist", []) or [])
    seen: dict[str, None] = {}
    for t in [*BREADTH_UNIVERSE, *watchlist]:
        key = str(t).strip().upper()
        if key:
            seen.setdefault(key, None)
    return list(seen.keys())


def compute_breadth_for_date(
    target_date: date,
    *,
    universe: list[str],
    conn_factory: Callable[[], Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    if conn_factory is None:
        conn_factory = _default_conn_factory
    cm = conn_factory() if conn_factory else None
    if cm is None:
        return {"breadth_date": target_date.isoformat(), "universe_size": 0,
                "metrics": {}, "missing_constituents": [], "degraded": True, "run_id": run_id}
    missing: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    conn = cm.__enter__()
    try:
        for ticker in universe:
            bars = db.get_ohlcv_bars(conn, ticker, end=target_date, limit=400)
            if not bars:
                missing.append(ticker)
                continue
            frames[ticker] = frame_from_bars(bars)
        metrics = compute_breadth(frames, breadth_date=target_date)
        db.upsert_market_breadth(conn, metrics)
    finally:
        cm.__exit__(None, None, None)
    return {
        "breadth_date": target_date.isoformat(),
        "universe_size": metrics["universe_size"],
        "metrics": {k: metrics[k] for k in
                    ("pct_above_200ma", "pct_above_50ma", "new_highs_minus_lows", "advance_decline")},
        "missing_constituents": missing,
        "degraded": False,
        "run_id": run_id,
    }


def compute_breadth_range(
    start: date,
    end: date,
    *,
    universe: list[str],
    conn_factory: Callable[[], Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    days = 0
    target = start
    degraded = False
    while target <= end:
        try:
            res = compute_breadth_for_date(target, universe=universe, conn_factory=conn_factory, run_id=run_id)
            degraded = degraded or res["degraded"]
            if not res["degraded"]:
                days += 1
        except Exception as exc:
            failures.append({"date": target.isoformat(), "error": str(exc)})
        target += timedelta(days=1)
    return {"range": {"from": start.isoformat(), "to": end.isoformat()},
            "days": days, "failures": failures, "degraded": degraded, "run_id": run_id}


def query_breadth(*, start=None, end=None, limit: int = 200) -> dict[str, Any]:
    if not os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"):
        return {"rows": [], "degraded": True}
    from investment_assistant.db import connect

    with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
        return {"rows": db.get_market_breadth(conn, start=start, end=end, limit=limit), "degraded": False}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services_breadth.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/services/breadth.py tests/test_services_breadth.py
git commit -m "feat(services): breadth orchestration + historical replay (range recompute)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10：`services/macro.py` — 宏观编排 + 缺 key 降级

**Files:**
- Create: `investment_assistant/services/macro.py`
- Test: `tests/test_services_macro.py`

**Interfaces:**
- Consumes: `data.fred.fetch_fred_series`（Task 3）、`db.upsert_macro_observations`/`get_macro_series`（Task 6）。
- Produces:
  - `ingest_macro(series_ids, *, start, end, getter=None, conn_factory=None, api_key=None, run_id=None) -> dict`：逐 series 取数→upsert，返回 `{"series":[...], "range":{...}, "written":{series:rows}, "skipped":[{series,reason}], "degraded":bool}`。缺 key → 全部 skipped、`degraded=True`，summary **不含 key 值**。
  - `query_macro(series_id, *, start=None, end=None) -> dict`。

- [ ] **Step 1: 写失败测试** —— `tests/test_services_macro.py`：

```python
from datetime import date

from investment_assistant.services import macro


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ingest_macro_writes(monkeypatch):
    def getter(url, *, params=None, **kw):
        return {"observations": [{"date": "2024-01-02", "value": "7.45"}]}, {"ok": True, "error": None}

    written = {}
    monkeypatch.setattr(macro.db, "upsert_macro_observations",
                        lambda conn, sid, rows: written.setdefault(sid, len(rows)) or len(rows))
    out = macro.ingest_macro(
        ["BAMLH0A0HYM2"], start=date(2024, 1, 1), end=date(2024, 1, 4),
        getter=getter, conn_factory=lambda: _Conn(), api_key="k", run_id="t",
    )
    assert out["written"]["BAMLH0A0HYM2"] == 1
    assert out["degraded"] is False


def test_ingest_macro_skips_without_key_and_hides_secret():
    out = macro.ingest_macro(
        ["BAMLH0A0HYM2", "T10Y2Y"], start=date(2024, 1, 1), end=date(2024, 1, 4),
        getter=None, conn_factory=lambda: _Conn(), api_key=None,
    )
    assert out["degraded"] is True
    assert {s["series"] for s in out["skipped"]} == {"BAMLH0A0HYM2", "T10Y2Y"}
    # 整个 summary 序列化后不得包含任何 key 值（这里 key 为 None，断言结构即可）
    assert all("reason" in s for s in out["skipped"])
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services_macro.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `investment_assistant/services/macro.py`**

```python
from __future__ import annotations

import os
from datetime import date
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.data.fred import fetch_fred_series


def _default_conn_factory():
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        return None
    from investment_assistant.db import connect

    return connect(url)


def ingest_macro(
    series_ids: list[str],
    *,
    start: date,
    end: date,
    getter: Callable[..., Any] | None = None,
    conn_factory: Callable[[], Any] | None = None,
    api_key: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    if api_key is None:
        api_key = os.environ.get("FRED_API_KEY")
    if conn_factory is None:
        conn_factory = _default_conn_factory
    written: dict[str, int] = {}
    skipped: list[dict[str, Any]] = []
    cm = conn_factory() if conn_factory else None
    no_db = cm is None
    conn = cm.__enter__() if cm is not None else None
    try:
        for series_id in series_ids:
            rows, status = fetch_fred_series(series_id, start=start, end=end, api_key=api_key, getter=getter)
            if rows is None:
                skipped.append({"series": series_id, "reason": status.get("error", "skipped")})
                continue
            if conn is not None:
                written[series_id] = db.upsert_macro_observations(conn, series_id, rows)
            else:
                written[series_id] = 0
    finally:
        if cm is not None:
            cm.__exit__(None, None, None)
    degraded = no_db or (not written and bool(skipped))
    return {
        "series": list(series_ids),
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "written": written,
        "skipped": skipped,
        "degraded": degraded,
        "run_id": run_id,
    }


def query_macro(series_id: str, *, start=None, end=None) -> dict[str, Any]:
    if not os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"):
        return {"rows": [], "degraded": True}
    from investment_assistant.db import connect

    with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
        return {"rows": db.get_macro_series(conn, series_id, start=start, end=end), "degraded": False}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services_macro.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/services/macro.py tests/test_services_macro.py
git commit -m "feat(services): macro (HY/2s10s) ingest with missing-key degrade, no secret in summary

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11：`services/fundamentals.py` — 财报编排 + 季度回填

**Files:**
- Create: `investment_assistant/services/fundamentals.py`
- Test: `tests/test_services_fundamentals.py`

**Interfaces:**
- Consumes: `data.fundamentals.fetch_earnings`（Task 4）、`db.upsert_fundamentals`/`get_fundamentals`（Task 6）。
- Produces:
  - `ingest_fundamentals(tickers, *, fetcher=None, conn_factory=None, since=None, until=None, run_id=None) -> dict`：逐 ticker 取数→（按 `report_date` 过滤 since/until）→upsert，返回 `{"tickers":[...], "quarters":{ticker:count}, "latest_surprise":{ticker:val}, "failures":[...], "degraded":bool}`。
  - `query_fundamentals(ticker, *, start=None, end=None) -> dict`。

- [ ] **Step 1: 写失败测试** —— `tests/test_services_fundamentals.py`：

```python
from datetime import date

from investment_assistant.services import fundamentals


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fetcher(ticker, *, ticker_factory=None):
    return [
        {"period_end": date(2024, 1, 28), "report_date": date(2024, 2, 21),
         "eps_actual": 0.52, "eps_estimate": 0.50, "eps_surprise": 0.04,
         "revenue_actual": None, "revenue_estimate": None},
        {"period_end": date(2019, 1, 1), "report_date": date(2019, 2, 1),
         "eps_actual": 0.1, "eps_estimate": 0.1, "eps_surprise": 0.0,
         "revenue_actual": None, "revenue_estimate": None},
    ]


def test_ingest_fundamentals_writes_and_summarizes(monkeypatch):
    captured = {}
    monkeypatch.setattr(fundamentals.db, "upsert_fundamentals",
                        lambda conn, t, rows: captured.setdefault(t, rows) or len(rows))
    out = fundamentals.ingest_fundamentals(
        ["NVDA"], fetcher=_fetcher, conn_factory=lambda: _Conn(), run_id="t",
    )
    assert out["quarters"]["NVDA"] == 2
    assert out["latest_surprise"]["NVDA"] == 0.04   # 最新 report_date 的 surprise
    assert out["degraded"] is False


def test_ingest_fundamentals_filters_by_since(monkeypatch):
    monkeypatch.setattr(fundamentals.db, "upsert_fundamentals", lambda conn, t, rows: len(rows))
    out = fundamentals.ingest_fundamentals(
        ["NVDA"], fetcher=_fetcher, conn_factory=lambda: _Conn(), since=date(2024, 1, 1),
    )
    assert out["quarters"]["NVDA"] == 1   # 仅 2024 季度留下


def test_ingest_fundamentals_records_failure():
    def boom(ticker, *, ticker_factory=None):
        raise ValueError("yf error")

    out = fundamentals.ingest_fundamentals(["ZZZZ"], fetcher=boom, conn_factory=lambda: _Conn())
    assert out["failures"][0]["ticker"] == "ZZZZ"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services_fundamentals.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `investment_assistant/services/fundamentals.py`**

```python
from __future__ import annotations

import os
from datetime import date
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.data.fundamentals import fetch_earnings


def _default_conn_factory():
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        return None
    from investment_assistant.db import connect

    return connect(url)


def _within(report_date, since, until) -> bool:
    if report_date is None:
        return since is None and until is None
    if since is not None and report_date < since:
        return False
    if until is not None and report_date > until:
        return False
    return True


def ingest_fundamentals(
    tickers: list[str],
    *,
    fetcher: Callable[..., list[dict[str, Any]]] | None = None,
    conn_factory: Callable[[], Any] | None = None,
    since: date | None = None,
    until: date | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    fetcher = fetcher or fetch_earnings
    if conn_factory is None:
        conn_factory = _default_conn_factory
    quarters: dict[str, int] = {}
    latest_surprise: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    cm = conn_factory() if conn_factory else None
    degraded = cm is None
    conn = cm.__enter__() if cm is not None else None
    try:
        for raw in tickers:
            ticker = str(raw or "").strip().upper()
            if not ticker:
                continue
            try:
                rows = [r for r in fetcher(ticker) if _within(r.get("report_date"), since, until)]
                if conn is not None:
                    db.upsert_fundamentals(conn, ticker, rows)
                quarters[ticker] = len(rows)
                dated = [r for r in rows if r.get("report_date")]
                if dated:
                    newest = max(dated, key=lambda r: r["report_date"])
                    latest_surprise[ticker] = newest.get("eps_surprise")
            except Exception as exc:
                failures.append({"ticker": ticker, "error": str(exc)})
    finally:
        if cm is not None:
            cm.__exit__(None, None, None)
    return {
        "tickers": [str(t).strip().upper() for t in tickers if str(t).strip()],
        "quarters": quarters,
        "latest_surprise": latest_surprise,
        "failures": failures,
        "degraded": degraded,
        "run_id": run_id,
    }


def query_fundamentals(ticker: str, *, start=None, end=None) -> dict[str, Any]:
    if not os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"):
        return {"rows": [], "degraded": True}
    from investment_assistant.db import connect

    with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
        return {"rows": db.get_fundamentals(conn, ticker, start=start, end=end), "degraded": False}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services_fundamentals.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/services/fundamentals.py tests/test_services_fundamentals.py
git commit -m "feat(services): fundamentals ingest + quarterly backfill (report_date filter)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12：`market/service.py` — signal_date 新鲜度修复 + 多因子门控

**Files:**
- Modify: `investment_assistant/market/service.py`
- Test: `tests/test_market_signal_freshness.py`

**Interfaces:**
- Consumes: `MarketConfig`（含 Task 7 新字段 `breadth_red_pct/breadth_yellow_pct/hy_widen_delta/hy_lookback_days`）。
- Produces:
  - `classify_market_status(*, vix_close, spy_above_200ma, config, pct_above_200ma=None, hy_widening=None) -> str`（纯函数，返回 `red/yellow/green`）。
  - `compute_market_signal(config, *, price_fetcher=None, run_id=None, signal_date=None, breadth=None, hy_widening=None) -> MarketSignal`：`signal_date` 默认改为「SPY 最新 bar 的实际日期」（非 `date.today()`）；门控调用 `classify_market_status`，多因子分量写入 `details`。
- 向后兼容：`breadth=None` 且 `hy_widening=None` 时退回原 VIX+SPY 两因子结果。

- [ ] **Step 1: 写失败测试** —— `tests/test_market_signal_freshness.py`：

```python
from datetime import date

import pandas as pd

from investment_assistant.config import MarketConfig
from investment_assistant.market.service import classify_market_status, compute_market_signal


def _frame(last_index: str, close: float, n: int = 220):
    idx = pd.date_range(end=last_index, periods=n, freq="D")
    return pd.DataFrame(
        {"Open": [close] * n, "High": [close] * n, "Low": [close] * n,
         "Close": [close] * n, "Volume": [1] * n}, index=idx,
    )


def test_signal_date_uses_latest_bar_not_today():
    cfg = MarketConfig()

    def fetcher(ticker, days):
        if ticker == cfg.vix_ticker:
            return _frame("2024-06-14", 15.0, n=5)
        return _frame("2024-06-14", 100.0, n=220)

    sig = compute_market_signal(cfg, price_fetcher=fetcher)
    assert sig.signal_date == date(2024, 6, 14)   # 取 bar 实际日，不是 today


def test_classify_red_when_breadth_collapses():
    cfg = MarketConfig()
    status = classify_market_status(
        vix_close=15.0, spy_above_200ma=True, config=cfg, pct_above_200ma=10.0,
    )
    assert status == "red"   # pct_above_200ma < breadth_red_pct(20)


def test_classify_yellow_on_weak_breadth():
    cfg = MarketConfig()
    status = classify_market_status(
        vix_close=15.0, spy_above_200ma=True, config=cfg, pct_above_200ma=35.0,
    )
    assert status == "yellow"  # < breadth_yellow_pct(40)


def test_classify_backward_compatible_without_breadth():
    cfg = MarketConfig()
    assert classify_market_status(vix_close=35.0, spy_above_200ma=True, config=cfg) == "red"
    assert classify_market_status(vix_close=15.0, spy_above_200ma=True, config=cfg) == "green"
    assert classify_market_status(vix_close=15.0, spy_above_200ma=False, config=cfg) == "yellow"


def test_classify_red_on_hy_widening():
    cfg = MarketConfig()
    status = classify_market_status(
        vix_close=15.0, spy_above_200ma=True, config=cfg, hy_widening=2.0,  # > hy_widen_delta(1.0)
    )
    assert status == "red"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_market_signal_freshness.py -v`
Expected: FAIL（`classify_market_status` 不存在；`signal_date` 仍为 today）。

- [ ] **Step 3: 实现 `classify_market_status` + 改 `compute_market_signal`** —— 改写 `investment_assistant/market/service.py` 的 `compute_market_signal` 并新增纯函数。完整替换 `compute_market_signal` 函数体为：

```python
def classify_market_status(
    *,
    vix_close: float,
    spy_above_200ma: bool,
    config: MarketConfig,
    pct_above_200ma: float | None = None,
    hy_widening: float | None = None,
) -> str:
    """Multi-factor market state. Falls back to VIX+SPY when extra inputs are None."""
    red = (
        vix_close > config.red_vix
        or (pct_above_200ma is not None and pct_above_200ma < config.breadth_red_pct)
        or (hy_widening is not None and hy_widening >= config.hy_widen_delta)
    )
    if red:
        return "red"
    yellow = (
        vix_close > config.yellow_vix
        or (not spy_above_200ma)
        or (pct_above_200ma is not None and pct_above_200ma < config.breadth_yellow_pct)
    )
    return "yellow" if yellow else "green"


def compute_market_signal(
    config: MarketConfig,
    *,
    price_fetcher: PriceFetcher | None = None,
    run_id: str | None = None,
    signal_date: date | None = None,
    breadth: float | None = None,
    hy_widening: float | None = None,
) -> MarketSignal:
    """Compute a row-ready broad-market signal from SPY and VIX data.

    signal_date defaults to SPY's latest bar date (freshness guard), not today.
    """
    fetcher = price_fetcher or _default_price_fetcher
    spy_df = fetcher(config.spy_ticker, config.history_days)
    vix_df = fetcher(config.vix_ticker, 5)
    _validate_price_frame(spy_df, config.spy_ticker, min_rows=config.ma_days)
    _validate_price_frame(vix_df, config.vix_ticker, min_rows=1)

    spy_close = float(spy_df["Close"].iloc[-1])
    spy_ma = float(spy_df["Close"].tail(config.ma_days).mean())
    spy_above_200ma = bool(spy_close > spy_ma)
    vix_close = float(vix_df["Close"].iloc[-1])

    status = classify_market_status(
        vix_close=vix_close,
        spy_above_200ma=spy_above_200ma,
        config=config,
        pct_above_200ma=breadth,
        hy_widening=hy_widening,
    )

    resolved_date = signal_date or _bar_date(spy_df)
    details = {
        "spy_rows": int(len(spy_df)),
        "vix_rows": int(len(vix_df)),
        "ma_days": config.ma_days,
        "history_days": config.history_days,
        "yellow_vix": config.yellow_vix,
        "red_vix": config.red_vix,
        "spy_latest_index": str(spy_df.index[-1]),
        "vix_latest_index": str(vix_df.index[-1]),
        "pct_above_200ma": breadth,
        "hy_widening": hy_widening,
        "breadth_red_pct": config.breadth_red_pct,
        "breadth_yellow_pct": config.breadth_yellow_pct,
    }
    return MarketSignal(
        signal_date=resolved_date,
        market_status=status,
        spy_ticker=config.spy_ticker,
        spy_close=spy_close,
        spy_ma200=spy_ma,
        spy_above_200ma=spy_above_200ma,
        vix_ticker=config.vix_ticker,
        vix_close=vix_close,
        details=details,
        run_id=run_id,
    )


def _bar_date(df: pd.DataFrame) -> date:
    """Latest bar's actual date (freshness guard); fall back to today if unparseable."""
    try:
        return pd.Timestamp(df.index[-1]).date()
    except (TypeError, ValueError, IndexError):
        return date.today()
```

> 注：`compute_market_signal_for_date` 不变（它显式传 `signal_date=target_date`，已覆盖默认值），无需改动。

- [ ] **Step 4: 运行确认通过 + 回归既有 market 测试**

Run: `pytest tests/test_market_signal_freshness.py tests/test_market_signal_service.py tests/test_metrics_task.py -v`
Expected: PASS（新测试绿；既有 market/metrics 测试不破——若既有测试硬编码了 `signal_date == today`，按实际报错改为断言 bar 日期，但既有 `compute_market_signal_for_date` 路径显式传日期不受影响）。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/market/service.py tests/test_market_signal_freshness.py
git commit -m "fix(market): signal_date uses latest bar; add multi-factor (VIX+breadth+HY) gating

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 13：`tasks/{prices,breadth,macro,fundamentals}.py` — 定时 run + 手动回补 CLI + scheduler 注册

**Files:**
- Create: `investment_assistant/tasks/prices.py`, `investment_assistant/tasks/breadth.py`, `investment_assistant/tasks/macro.py`, `investment_assistant/tasks/fundamentals.py`
- Modify: `investment_assistant/tasks/scheduler.py`
- Test: `tests/test_tasks_phase1_entrypoints.py`

**Interfaces:**
- Consumes: `services.prices.ingest_ohlcv`、`services.breadth.compute_breadth_for_date/compute_breadth_range/resolve_universe`、`services.macro.ingest_macro`、`services.fundamentals.ingest_fundamentals`、`tasks._harness.run_task`、`config.AssistantConfig/load_config`。
- Produces（每文件同形态，对齐 `tasks/metrics.py`/`filings.py`）：
  - `run(config) -> dict`：定时入口，`run_task(<task>, lambda: _core(config, <隐式截至今天区间>), config=config)`。
  - `main()`：argparse 解析 `--from/--to/--date/--tickers/--series/--config`，构造历史区间，经 `run_task` 调**同一 `_core`**（run_id 由 `run_task` 生成；手动场景靠 task 名 + summary 标记区分，summary 含 `trigger:"manual"`）。
  - `scheduler.REGISTRY` 追加 `prices/breadth/macro/fundamentals`。

DRY 关键：`run()` 与 `main()` 都走 `_core(config, start, end, tickers=...)`，仅区间来源不同。

- [ ] **Step 1: 写失败测试** —— `tests/test_tasks_phase1_entrypoints.py`：

```python
from datetime import date

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import prices as prices_task
from investment_assistant.tasks import breadth as breadth_task
from investment_assistant.tasks import macro as macro_task
from investment_assistant.tasks import fundamentals as fund_task
from investment_assistant.tasks.scheduler import REGISTRY


def test_all_phase1_tasks_registered():
    for name in ("prices", "breadth", "macro", "fundamentals"):
        assert name in REGISTRY


def test_prices_core_calls_ingest_with_range(monkeypatch):
    seen = {}

    def fake_ingest(tickers, *, start, end, **kw):
        seen["tickers"], seen["start"], seen["end"] = tickers, start, end
        return {"written": {}, "degraded": False}

    monkeypatch.setattr(prices_task, "ingest_ohlcv", fake_ingest)
    out = prices_task._core(AssistantConfig(), start=date(2024, 1, 1), end=date(2024, 1, 10), tickers=["NVDA"])
    assert seen["tickers"] == ["NVDA"]
    assert seen["start"] == date(2024, 1, 1)
    assert out["trigger"] in ("scheduled", "manual")


def test_breadth_core_range_branch(monkeypatch):
    called = {}
    monkeypatch.setattr(breadth_task, "compute_breadth_range",
                        lambda start, end, **kw: called.setdefault("range", (start, end)) or {"days": 1, "degraded": False})
    monkeypatch.setattr(breadth_task, "resolve_universe", lambda cfg: ["SPY"])
    out = breadth_task._core(AssistantConfig(), start=date(2023, 1, 1), end=date(2023, 1, 5))
    assert called["range"] == (date(2023, 1, 1), date(2023, 1, 5))


def test_macro_core_calls_ingest(monkeypatch):
    monkeypatch.setattr(macro_task, "ingest_macro",
                        lambda series_ids, *, start, end, **kw: {"series": series_ids, "degraded": False})
    out = macro_task._core(AssistantConfig(), start=date(2024, 1, 1), end=date(2024, 1, 10))
    assert out["series"] == ["BAMLH0A0HYM2", "T10Y2Y"]


def test_fundamentals_core_calls_ingest(monkeypatch):
    monkeypatch.setattr(fund_task, "ingest_fundamentals",
                        lambda tickers, *, since, until, **kw: {"tickers": tickers, "degraded": False})
    out = fund_task._core(AssistantConfig(), since=date(2019, 1, 1), until=date(2024, 1, 1), tickers=["NVDA"])
    assert out["tickers"] == ["NVDA"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_tasks_phase1_entrypoints.py -v`
Expected: FAIL（模块/注册不存在）。

- [ ] **Step 3: 写 `investment_assistant/tasks/prices.py`**

```python
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.services.prices import ingest_ohlcv
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig, *, start: date, end: date,
          tickers: list[str] | None = None, trigger: str = "scheduled") -> dict[str, Any]:
    targets = tickers or list(config.watchlist)
    result = ingest_ohlcv(targets, start=start, end=end)
    result["trigger"] = trigger
    return result


def run(config: AssistantConfig) -> dict[str, Any]:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=config.prices.history_days)
    return run_task("prices", lambda: _core(config, start=start, end=end), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="OHLCV ingest (scheduled or manual backfill)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--tickers", default=None, help="comma-separated; defaults to watchlist")
    parser.add_argument("--from", dest="start", default=None)
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    start, end = _resolve_range(args, default_days=config.prices.history_days)
    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    out = run_task("prices", lambda: _core(config, start=start, end=end, tickers=tickers, trigger="manual"), config=config)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


def _resolve_range(args, *, default_days: int) -> tuple[date, date]:
    if args.date:
        d = date.fromisoformat(args.date)
        return d, d
    end = date.fromisoformat(args.end) if args.end else datetime.now(UTC).date()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=default_days)
    if end < start:
        raise ValueError("--to must be >= --from")
    return start, end


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 写 `investment_assistant/tasks/breadth.py`**

```python
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.services.breadth import (
    compute_breadth_for_date,
    compute_breadth_range,
    resolve_universe,
)
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig, *, start: date | None = None, end: date | None = None,
          trigger: str = "scheduled") -> dict[str, Any]:
    universe = resolve_universe(config)
    if start is not None and end is not None and start != end:
        result = compute_breadth_range(start, end, universe=universe)
    else:
        target = end or start or datetime.now(UTC).date()
        result = compute_breadth_for_date(target, universe=universe)
    result["trigger"] = trigger
    return result


def run(config: AssistantConfig) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    return run_task("breadth", lambda: _core(config, start=today, end=today), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Market breadth (scheduled or historical replay)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--from", dest="start", default=None)
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.date:
        start = end = date.fromisoformat(args.date)
    else:
        end = date.fromisoformat(args.end) if args.end else datetime.now(UTC).date()
        start = date.fromisoformat(args.start) if args.start else end
        if end < start:
            raise ValueError("--to must be >= --from")
    out = run_task("breadth", lambda: _core(config, start=start, end=end, trigger="manual"), config=config)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 写 `investment_assistant/tasks/macro.py`**

```python
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.services.macro import ingest_macro
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig, *, start: date, end: date,
          series: list[str] | None = None, trigger: str = "scheduled") -> dict[str, Any]:
    series_ids = series or list(config.macro.fred_series)
    result = ingest_macro(series_ids, start=start, end=end)
    result["trigger"] = trigger
    return result


def run(config: AssistantConfig) -> dict[str, Any]:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=config.macro.lookback_days)
    return run_task("macro", lambda: _core(config, start=start, end=end), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="FRED macro ingest (scheduled or backfill)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--series", default=None, help="comma-separated FRED series ids")
    parser.add_argument("--from", dest="start", default=None)
    parser.add_argument("--to", dest="end", default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    end = date.fromisoformat(args.end) if args.end else datetime.now(UTC).date()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=config.macro.lookback_days)
    if end < start:
        raise ValueError("--to must be >= --from")
    series = [s.strip() for s in args.series.split(",")] if args.series else None
    out = run_task("macro", lambda: _core(config, start=start, end=end, series=series, trigger="manual"), config=config)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 写 `investment_assistant/tasks/fundamentals.py`**

```python
from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.services.fundamentals import ingest_fundamentals
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig, *, since: date | None = None, until: date | None = None,
          tickers: list[str] | None = None, trigger: str = "scheduled") -> dict[str, Any]:
    targets = tickers or list(config.watchlist)
    result = ingest_fundamentals(targets, since=since, until=until)
    result["trigger"] = trigger
    return result


def run(config: AssistantConfig) -> dict[str, Any]:
    return run_task("fundamentals", lambda: _core(config), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fundamentals/EPS ingest (scheduled or quarterly backfill)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--tickers", default=None)
    parser.add_argument("--from", dest="start", default=None)
    parser.add_argument("--to", dest="end", default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    since = date.fromisoformat(args.start) if args.start else None
    until = date.fromisoformat(args.end) if args.end else None
    if since and until and until < since:
        raise ValueError("--to must be >= --from")
    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    out = run_task("fundamentals", lambda: _core(config, since=since, until=until, tickers=tickers, trigger="manual"), config=config)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: 注册进 scheduler** —— 改 `investment_assistant/tasks/scheduler.py`：在 import 区追加，并扩展 `REGISTRY`：

```python
from investment_assistant.tasks import breadth as breadth_task
from investment_assistant.tasks import filings as filings_task
from investment_assistant.tasks import fundamentals as fundamentals_task
from investment_assistant.tasks import macro as macro_task
from investment_assistant.tasks import metrics as metrics_task
from investment_assistant.tasks import nightly_scores as scores_task
from investment_assistant.tasks import prices as prices_task

logger = logging.getLogger(__name__)

REGISTRY: dict[str, Callable[[AssistantConfig], dict[str, Any]]] = {
    "metrics": metrics_task.run,
    "filings": filings_task.run,
    "scores": scores_task.run,
    "prices": prices_task.run,
    "breadth": breadth_task.run,
    "macro": macro_task.run,
    "fundamentals": fundamentals_task.run,
}
```

- [ ] **Step 8: 运行确认通过**

Run: `pytest tests/test_tasks_phase1_entrypoints.py tests/test_scheduler.py -v`
Expected: PASS。

- [ ] **Step 9: Commit**

```bash
git add investment_assistant/tasks/prices.py investment_assistant/tasks/breadth.py \
        investment_assistant/tasks/macro.py investment_assistant/tasks/fundamentals.py \
        investment_assistant/tasks/scheduler.py tests/test_tasks_phase1_entrypoints.py
git commit -m "feat(tasks): prices/breadth/macro/fundamentals entrypoints (scheduled + manual backfill) + scheduler

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 14：`api/routes/data.py` — 只读查询 + 手动回补触发

**Files:**
- Create: `investment_assistant/api/routes/data.py`
- Modify: `investment_assistant/api/routes/__init__.py`
- Test: `tests/test_api_contract.py`（追加）

**Interfaces:**
- Consumes: `services.prices.query_ohlcv`、`services.breadth.query_breadth`、`services.macro.query_macro`、`services.fundamentals.query_fundamentals`、`tasks.runner.submit`、`tasks.scheduler.REGISTRY`、`api.http`（`ApiResponse/first/parse_int/parse_optional_date`）、`api.router.register`。
- Produces:
  - `GET /api/data/ohlcv?ticker=&from=&to=&limit=`
  - `GET /api/data/breadth?from=&to=&limit=`
  - `GET /api/data/macro?series=&from=&to=`
  - `GET /api/data/fundamentals?ticker=`
  - `POST /api/data/{kind}/backfill`（kind ∈ prices/breadth/macro/fundamentals）→ `runner.submit(kind, lambda: REGISTRY[kind](config))`，返回 `{run_id, status:"pending"}`。

> 说明：本期 backfill 触发走 `REGISTRY[kind]`（定时同款，取「截至今天」区间）。带历史区间的回补仍以 CLI `main()` 为主路径（区间参数化已在 Task 13）；API 历史区间参数化留待后续，避免本期把 `runner.submit` 签名复杂化。路由对未知 kind 返回 404。

- [ ] **Step 1: 写失败测试** —— 在 `tests/test_api_contract.py` 追加（沿用该文件已有的 dispatch 调用风格；若文件用 `from investment_assistant.api.router import dispatch`，复用之）：

```python
def test_data_ohlcv_route_degrades_without_db(monkeypatch):
    import investment_assistant.api.routes  # noqa: F401 确保路由注册
    from investment_assistant.api.router import dispatch

    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    resp = dispatch("GET", "/api/data/ohlcv?ticker=NVDA", None)
    assert resp is not None
    assert resp.payload["degraded"] is True


def test_data_backfill_unknown_kind_404():
    import investment_assistant.api.routes  # noqa: F401
    from investment_assistant.api.router import dispatch

    resp = dispatch("POST", "/api/data/nope/backfill", {})
    assert resp.status == 404


def test_data_backfill_returns_run_id(monkeypatch):
    import investment_assistant.api.routes  # noqa: F401
    from investment_assistant.api.router import dispatch
    from investment_assistant.api.routes import data as data_route

    monkeypatch.setattr(data_route.runner, "submit", lambda kind, fn: "prices-xyz")
    resp = dispatch("POST", "/api/data/prices/backfill", {})
    assert resp.payload["run_id"] == "prices-xyz"
    assert resp.payload["status"] == "pending"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_api_contract.py -k "data_" -v`
Expected: FAIL（路由不存在 → dispatch 返回 None / AttributeError）。

- [ ] **Step 3: 实现 `investment_assistant/api/routes/data.py`**

```python
from investment_assistant.api.http import ApiResponse, first, parse_int, parse_optional_date
from investment_assistant.api.router import register
from investment_assistant.config import load_config
from investment_assistant.services import breadth as _breadth
from investment_assistant.services import fundamentals as _fundamentals
from investment_assistant.services import macro as _macro
from investment_assistant.services import prices as _prices
from investment_assistant.tasks import runner
from investment_assistant.tasks.scheduler import REGISTRY

_BACKFILL_KINDS = {"prices", "breadth", "macro", "fundamentals"}


@register("GET", exact="/api/data/ohlcv")
def _ohlcv(path, query, payload):
    ticker = (first(query, "ticker") or "").strip().upper()
    if not ticker:
        return ApiResponse({"error": "ticker is required"}, status=400)
    start = parse_optional_date(first(query, "from"))
    end = parse_optional_date(first(query, "to"))
    limit = parse_int(first(query, "limit"), default=1000, minimum=1, maximum=5000)
    return ApiResponse(_prices.query_ohlcv(ticker, start=start, end=end, limit=limit))


@register("GET", exact="/api/data/breadth")
def _breadth_rows(path, query, payload):
    start = parse_optional_date(first(query, "from"))
    end = parse_optional_date(first(query, "to"))
    limit = parse_int(first(query, "limit"), default=200, minimum=1, maximum=1000)
    return ApiResponse(_breadth.query_breadth(start=start, end=end, limit=limit))


@register("GET", exact="/api/data/macro")
def _macro_rows(path, query, payload):
    series = (first(query, "series") or "BAMLH0A0HYM2").strip()
    start = parse_optional_date(first(query, "from"))
    end = parse_optional_date(first(query, "to"))
    return ApiResponse(_macro.query_macro(series, start=start, end=end))


@register("GET", exact="/api/data/fundamentals")
def _fundamentals_rows(path, query, payload):
    ticker = (first(query, "ticker") or "").strip().upper()
    if not ticker:
        return ApiResponse({"error": "ticker is required"}, status=400)
    start = parse_optional_date(first(query, "from"))
    end = parse_optional_date(first(query, "to"))
    return ApiResponse(_fundamentals.query_fundamentals(ticker, start=start, end=end))


@register("POST", prefix="/api/data/")
def _backfill(path, query, payload):
    suffix = path.removeprefix("/api/data/")
    if not suffix.endswith("/backfill"):
        return ApiResponse({"error": "not found"}, status=404)
    kind = suffix.removesuffix("/backfill")
    if kind not in _BACKFILL_KINDS:
        return ApiResponse({"error": f"unknown kind: {kind}"}, status=404)
    config = load_config()
    run_id = runner.submit(kind, lambda: REGISTRY[kind](config))
    return ApiResponse({"run_id": run_id, "status": "pending"})
```

- [ ] **Step 4: 注册路由** —— 改 `investment_assistant/api/routes/__init__.py`，把 `data` 加入 import：

```python
from . import status, market, tickers, strategies, hermes, watchlist, runs, data  # noqa: F401
```

> 若上游已加入 `jobs, settings`（见 dashboard 5-layer 计划），保持其在列并追加 `data`，不要删除既有项。

- [ ] **Step 5: 运行确认通过 + 全量回归**

Run: `pytest tests/test_api_contract.py -k "data_" -v && pytest -q`
Expected: PASS（新 data 路由测试绿；全量套件不破）。

- [ ] **Step 6: Commit**

```bash
git add investment_assistant/api/routes/data.py investment_assistant/api/routes/__init__.py tests/test_api_contract.py
git commit -m "feat(api): /api/data/* read endpoints + manual backfill trigger

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 15：全量回归 + 文档对齐（收尾）

**Files:**
- Modify: `docs/architecture.md`（若存在数据层/任务清单章节，追加 Phase 1 四任务与四表说明）
- Test: 全量 `pytest`

**Interfaces:**
- Consumes: 全部前序 Task 产物。
- Produces: 绿色全量测试；文档反映新数据层。

- [ ] **Step 1: 运行全量测试**

Run: `pytest -q`
Expected: 全绿。若有失败，定位到对应 Task 修复（常见：既有 market/metrics 测试硬编码 today；按 Task 12 注释处理）。

- [ ] **Step 2: 更新 `docs/architecture.md`**

在数据层/调度章节追加（若无对应章节则在文末加「## Phase 1 数据地基」）：

```markdown
### Phase 1 数据地基（2026-06-30）

- 表：`ohlcv_bars`(009) / `market_breadth`(010) / `macro_indicators`(011) / `fundamentals`(012)。
- 采集任务（均经 `_harness` 审计，写 `job_reports` + run_log）：
  - `prices`：OHLCV 增量落库 + 复权 + 重试。手动回补 `python -m investment_assistant.tasks.prices --tickers NVDA --from 2020-01-01 --to 2024-12-31`。
  - `breadth`：从 `ohlcv_bars` 计算市场广度（% 站上 200/50MA、新高-新低、A/D）。手动重算 `--from/--to`。
  - `macro`：FRED 仅采 HY 利差(BAMLH0A0HYM2) + 2s10s(T10Y2Y)；缺 `FRED_API_KEY` 降级。
  - `fundamentals`：yfinance EPS 实际/预期/surprise + 营收，喂 Phase 0 PEAD 事件研究。
- 市场状态升级为多因子门控（VIX + 广度 + HY 利差）；`signal_date` 取最新 bar 日期（新鲜度修复）。
- 只读 API：`/api/data/{ohlcv,breadth,macro,fundamentals}`；手动触发 `POST /api/data/{kind}/backfill`。
```

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs(architecture): Phase 1 data foundation (tables, tasks, multi-factor gating)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review（plan 自检结果）

**Spec coverage（spec §3–§7 → task 映射）：**
- §3.1 ohlcv_bars → Task 1；§3.2 market_breadth → Task 1；§3.3 macro_indicators(T10Y2Y 决策 D3) → Task 1；§3.4 fundamentals → Task 1；排程行 → Task 1（013）。
- Task 1.1 OHLCV（fetch + 仓储 + DB-first + 新鲜度）→ Task 2/6/8/12。
- Task 1.2 广度 → Task 5（纯函数）/6（仓储）/9（编排+回放）。
- Task 1.3 精简宏观 + 多因子门控 → Task 3/6/10 + Task 7（阈值）+ Task 12（门控）。
- Task 1.4 EPS surprise → Task 4/6/11。
- 硬约束①审计 → 所有 task 经 `run_task`（Task 13）+ summary 结构（Task 8/9/10/11）+ 排程行（Task 1）。
- 硬约束②手动回补 → 每 task 文件 `main()` + 区间参数（Task 13）+ services 的 `compute_breadth_range`/`since/until`（Task 9/11）。
- API 层 → Task 14。降级 → 各 services `query_*` + Task 14 测试。

**Placeholder scan：** 无 TBD/TODO；所有代码步骤含完整可运行代码（Task 6 Step 9 测试已为最终断言版本）。

**Type consistency：** `ingest_ohlcv`/`compute_breadth`/`ingest_macro`/`ingest_fundamentals`/`classify_market_status` 的签名在「定义任务」与「调用任务（Task 13/14）」间一致；`frame_from_bars` 在 Task 8 定义、Task 9 消费；`REGISTRY` 键名 `prices/breadth/macro/fundamentals` 全程一致；`conn_factory()` 返回上下文管理器（`__enter__/__exit__`）的约定在 services 与测试 `_Conn` 间一致。

**已知顺延点：** 迁移 012 可能与并行 Phase 0 agent 争用 → 落地时顺延编号并同步改 `tests/test_db_sql.py` 路径断言（Global Constraints 已声明）。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-30-phase1-data-foundation.md`. （本计划由自主 subagent 产出，交由监督 agent 决定执行方式：subagent-driven 或 inline executing-plans。）
