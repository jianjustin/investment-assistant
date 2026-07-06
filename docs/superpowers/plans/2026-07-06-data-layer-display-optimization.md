# 数据层展示优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构「数据」区三个视图（信号总览 / 趋势分析 / 技术面趋势）的展示，并把技术面趋势升为按股票分 Tab 的独立个股页面，补齐量价强弱、开收盘、200 日均线等基础指标。

**Architecture:** 以前端为主。后端只新增 1 个只读端点 `GET /api/tickers/{ticker}/ohlcv`（实时代拉 yfinance + 服务端算 MA + 5 分钟 TTL 缓存）。前端把纯计算逻辑抽到 `lib/*.ts`（可单测），可视化拆成一组单一职责小组件，视图/页面负责组装。

**Tech Stack:** 后端 Python / FastAPI / pandas / yfinance / pytest；前端 Svelte 5（runes）/ TypeScript / lightweight-charts / vitest + @testing-library/svelte。

## Global Constraints

- **无 migration、无新环境变量**：本次不碰数据库 schema，不做 OHLCV 落库。
- **Svelte 5 runes**：组件用 `$props()` / `$state()` / `$derived()`，事件用 `onclick=` 属性形式（与现有 `Data.svelte` 一致）。
- **UI 文案中文**。
- **状态三态颜色统一**：green `#22c55e`、yellow `#eab308`、red `#ef4444`；缺失日 `#2a2a2a`。
- **信号窗口统一 30 天**（`getMarketSignals(30)` / `getMarketSignalsTrend(30)`）。
- **MA 数组与 bars 等长**，前 n-1 个为 `null`（`Close.rolling(n).mean()` 的 NaN → `None`）。
- **OHLCV 端点只返回 `bars + ma20/ma50/ma200`**；指标卡的 涨跌/量比/距200线 由前端从这些数组派生，端点不算这些。
- 后端路由错误沿用现有约定：service 抛 `ValueError` → 路由 `raise HTTPException(status_code=400/404, detail=str(exc))`。

## File Structure

**后端**
- Modify `investment_assistant/services/tickers.py` — 新增 `ohlcv_series()` + `_ma_series()` + 进程内 TTL 缓存。
- Modify `investment_assistant/api/routes/tickers.py` — 新增 `GET /api/tickers/{ticker}/ohlcv` 路由。
- Create `tests/test_ticker_ohlcv.py` — service 单测（MA/等长/缓存/TTL）+ 路由测（TestClient）。

**前端 · 纯逻辑（lib）**
- Create `web/src/lib/router.ts` — 从 `app.svelte` 抽出 `zones` + `parseHash()`（可单测）。
- Create `web/src/lib/signals.ts` — `buildDayCells()` / `countStatuses()`。
- Create `web/src/lib/technicals.ts` — `toLineData()` / `deriveCards()`。
- Create `web/src/lib/router.test.ts` / `signals.test.ts` / `technicals.test.ts`。

**前端 · 组件**
- Modify `web/src/lib/charts/CandleChart.svelte` — 新增可选 `overlays` prop。
- Create `web/src/lib/components/{StatusRibbon,DotMatrix,RatioBar,Gauge,StatCard,VolumeBars}.svelte`（各配 `.test.ts`）。

**前端 · 视图/页面/装配**
- Modify `web/src/lib/api.ts` — `getTickerOhlcv()` + 类型。
- Modify `web/src/routes/Data.svelte` — 重写 signals/trend 视图，移除 tickers Tab。
- Create `web/src/routes/Technicals.svelte`（+ `Technicals.test.ts`）。
- Modify `web/src/app.svelte` — 用 `lib/router.ts`，新增 `technicals` zone 分支。
- Modify `web/src/lib/components/SideNav.svelte` — 新增一级导航项、移除 data 下的 tickers。
- Modify `web/src/routes/Data.test.ts` — 更新为新的 signals/trend/filings 断言。

---

## Task 1: 后端 OHLCV 服务 + TTL 缓存

**Files:**
- Modify: `investment_assistant/services/tickers.py`
- Test: `tests/test_ticker_ohlcv.py`

**Interfaces:**
- Consumes: `investment_assistant.data.price.get_price_history(ticker, days) -> pd.DataFrame`（列 `Open/High/Low/Close/Volume`，index 为日期）。
- Produces:
  - `ohlcv_series(ticker: str, days: int = 250, *, fetcher: Callable[[str, int], pd.DataFrame] | None = None, clock: Callable[[], float] | None = None) -> dict` → `{"ticker": str, "bars": [{"date","open","high","low","close","volume"}], "ma20": list, "ma50": list, "ma200": list}`。
  - `clear_ohlcv_cache() -> None`（测试用，清空模块级缓存）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_ticker_ohlcv.py`：

```python
import pandas as pd
import pytest

from investment_assistant.services import tickers as svc


def _frame(n=210, start=100.0):
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    close = [start + i for i in range(n)]
    return pd.DataFrame(
        {
            "Open": [c - 0.5 for c in close],
            "High": [c + 1 for c in close],
            "Low": [c - 1 for c in close],
            "Close": close,
            "Volume": [1000 + i for i in range(n)],
        },
        index=idx,
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    svc.clear_ohlcv_cache()
    yield
    svc.clear_ohlcv_cache()


def test_ohlcv_series_shapes_and_ma():
    out = svc.ohlcv_series("AAPL", days=210, fetcher=lambda t, d: _frame(210))
    assert out["ticker"] == "AAPL"
    assert len(out["bars"]) == 210
    for key in ("ma20", "ma50", "ma200"):
        assert len(out[key]) == 210
    # 前 n-1 个为 None
    assert out["ma20"][:19] == [None] * 19
    assert out["ma20"][19] is not None
    assert out["ma200"][198] is None
    assert out["ma200"][199] is not None
    # MA20 最后一个 = 最后 20 个 close 的均值
    closes = [b["close"] for b in out["bars"]]
    assert out["ma20"][-1] == pytest.approx(sum(closes[-20:]) / 20)
    # bar 字段齐全
    b0 = out["bars"][0]
    assert set(b0) == {"date", "open", "high", "low", "close", "volume"}
    assert b0["date"] == "2025-01-01"


def test_ohlcv_series_caches_within_ttl():
    calls = {"n": 0}

    def fetch(t, d):
        calls["n"] += 1
        return _frame(210)

    clock = {"t": 1000.0}
    svc.ohlcv_series("AAPL", days=210, fetcher=fetch, clock=lambda: clock["t"])
    svc.ohlcv_series("AAPL", days=210, fetcher=fetch, clock=lambda: clock["t"])
    assert calls["n"] == 1  # 第二次命中缓存


def test_ohlcv_series_refetches_after_ttl():
    calls = {"n": 0}

    def fetch(t, d):
        calls["n"] += 1
        return _frame(210)

    clock = {"t": 1000.0}
    svc.ohlcv_series("AAPL", days=210, fetcher=fetch, clock=lambda: clock["t"])
    clock["t"] = 1000.0 + 301  # 超过 300s TTL
    svc.ohlcv_series("AAPL", days=210, fetcher=fetch, clock=lambda: clock["t"])
    assert calls["n"] == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_ticker_ohlcv.py -q`
Expected: FAIL（`AttributeError: module ... has no attribute 'ohlcv_series'`）

- [ ] **Step 3: 实现 service**

在 `investment_assistant/services/tickers.py` 顶部补依赖与缓存，并新增函数：

```python
import time
from typing import Callable

import pandas as pd

from investment_assistant.data.price import get_price_history

_OHLCV_TTL_SECONDS = 300.0
_ohlcv_cache: dict[tuple[str, int], tuple[float, dict]] = {}


def clear_ohlcv_cache() -> None:
    _ohlcv_cache.clear()


def _ma_series(closes: pd.Series, window: int) -> list:
    ma = closes.rolling(window).mean()
    return [None if pd.isna(v) else round(float(v), 4) for v in ma]


def ohlcv_series(
    ticker: str,
    days: int = 250,
    *,
    fetcher: Callable[[str, int], pd.DataFrame] | None = None,
    clock: Callable[[], float] | None = None,
) -> dict:
    now = (clock or time.monotonic)()
    key = (ticker.upper(), days)
    cached = _ohlcv_cache.get(key)
    if cached and now - cached[0] < _OHLCV_TTL_SECONDS:
        return cached[1]

    fetch = fetcher or get_price_history
    frame = fetch(ticker.upper(), days)
    if frame is None or frame.empty:
        raise ValueError(f"No price data returned for {ticker}")

    closes = frame["Close"].astype(float)
    bars = [
        {
            "date": (idx.date().isoformat() if hasattr(idx, "date") else str(idx)),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]),
        }
        for idx, row in frame.iterrows()
    ]
    result = {
        "ticker": ticker.upper(),
        "bars": bars,
        "ma20": _ma_series(closes, 20),
        "ma50": _ma_series(closes, 50),
        "ma200": _ma_series(closes, 200),
    }
    _ohlcv_cache[key] = (now, result)
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_ticker_ohlcv.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add investment_assistant/services/tickers.py tests/test_ticker_ohlcv.py
git commit -m "feat(tickers): ohlcv_series 服务 + 5 分钟 TTL 缓存"
```

---

## Task 2: 后端 OHLCV 路由

**Files:**
- Modify: `investment_assistant/api/routes/tickers.py`
- Test: `tests/test_ticker_ohlcv.py`（追加）

**Interfaces:**
- Consumes: `services.tickers.ohlcv_series(ticker, days)`（Task 1）。
- Produces: HTTP `GET /api/tickers/{ticker}/ohlcv?days=250` → Task 1 的返回 JSON；无数据 → 400。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_ticker_ohlcv.py`）

```python
from investment_assistant.api.routes import tickers as tickers_route


def test_ohlcv_route_returns_series(client, monkeypatch):
    monkeypatch.setattr(
        tickers_route._tickers, "ohlcv_series",
        lambda ticker, days=250: {"ticker": ticker.upper(), "bars": [], "ma20": [], "ma50": [], "ma200": []},
    )
    resp = client.get("/api/tickers/AAPL/ohlcv?days=120")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "AAPL"


def test_ohlcv_route_400_on_no_data(client, monkeypatch):
    def boom(ticker, days=250):
        raise ValueError("No price data returned for ZZZZ")

    monkeypatch.setattr(tickers_route._tickers, "ohlcv_series", boom)
    resp = client.get("/api/tickers/ZZZZ/ohlcv")
    assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_ticker_ohlcv.py -q`
Expected: FAIL（404 Not Found，因路由未定义）

- [ ] **Step 3: 实现路由**

修改 `investment_assistant/api/routes/tickers.py`：

```python
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

import investment_assistant.services.tickers as _tickers

router = APIRouter()


@router.get("/api/tickers/trends")
def trends():
    rows = _tickers.ticker_trend_rows()
    return {"rows": rows, "count": len(rows)}


@router.post("/api/tickers/trends/scan")
def scan(payload: dict[str, Any] = Body(default_factory=dict)):
    return _tickers.run_ticker_trend_scan(payload)


@router.get("/api/tickers/{ticker}/ohlcv")
def ohlcv(ticker: str, days: int = Query(default=250, ge=30, le=400)):
    try:
        return _tickers.ohlcv_series(ticker, days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_ticker_ohlcv.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add investment_assistant/api/routes/tickers.py tests/test_ticker_ohlcv.py
git commit -m "feat(api): GET /api/tickers/{ticker}/ohlcv 端点"
```

---

## Task 3: 前端 API 客户端 `getTickerOhlcv`

**Files:**
- Modify: `web/src/lib/api.ts`
- Test: `web/src/lib/api.test.ts`（追加）

**Interfaces:**
- Produces:
  - 类型 `Bar = { date: string; open: number; high: number; low: number; close: number; volume: number }`
  - 类型 `OhlcvResponse = { ticker: string; bars: Bar[]; ma20: (number|null)[]; ma50: (number|null)[]; ma200: (number|null)[] }`
  - `getTickerOhlcv(ticker: string, days?: number): Promise<OhlcvResponse>`

- [ ] **Step 1: 写失败测试**（追加到 `web/src/lib/api.test.ts`）

先看文件现有 import / fetch mock 风格，然后追加：

```ts
import { getTickerOhlcv } from './api'

describe('getTickerOhlcv', () => {
  it('requests the ohlcv path with days', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ticker: 'AAPL', bars: [], ma20: [], ma50: [], ma200: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const out = await getTickerOhlcv('AAPL', 120)
    expect(fetchMock).toHaveBeenCalledWith('/api/tickers/AAPL/ohlcv?days=120', expect.anything())
    expect(out.ticker).toBe('AAPL')
    vi.unstubAllGlobals()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: FAIL（`getTickerOhlcv is not exported`）

- [ ] **Step 3: 实现客户端**

在 `web/src/lib/api.ts` 末尾（便捷封装区）追加：

```ts
export interface Bar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}
export interface OhlcvResponse {
  ticker: string
  bars: Bar[]
  ma20: (number | null)[]
  ma50: (number | null)[]
  ma200: (number | null)[]
}
export const getTickerOhlcv = (ticker: string, days = 250) =>
  get<OhlcvResponse>(`/api/tickers/${ticker}/ohlcv?days=${days}`)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "feat(web): api.getTickerOhlcv 客户端"
```

---

## Task 4: 纯逻辑 `signals.ts`（点阵/时间带/计数）

**Files:**
- Create: `web/src/lib/signals.ts`
- Test: `web/src/lib/signals.test.ts`

**Interfaces:**
- Consumes: 信号行 `{ signal_date: string; market_status: string }[]`。
- Produces:
  - `type DayCell = { date: string; status: 'green'|'yellow'|'red'|'none' }`
  - `buildDayCells(rows, days?): DayCell[]` — 按日期升序，未知/缺失状态归 `'none'`，最多取最近 `days`（默认 30）条。
  - `countStatuses(rows): { green: number; yellow: number; red: number }`
  - `STATUS_COLORS: Record<'green'|'yellow'|'red'|'none', string>`

- [ ] **Step 1: 写失败测试** (`web/src/lib/signals.test.ts`)

```ts
import { describe, it, expect } from 'vitest'
import { buildDayCells, countStatuses, STATUS_COLORS } from './signals'

const rows = [
  { signal_date: '2026-07-03', market_status: 'green' },
  { signal_date: '2026-07-02', market_status: 'RED' },
  { signal_date: '2026-07-01', market_status: 'weird' },
]

describe('signals helpers', () => {
  it('buildDayCells sorts ascending and normalizes status', () => {
    const cells = buildDayCells(rows)
    expect(cells.map((c) => c.date)).toEqual(['2026-07-01', '2026-07-02', '2026-07-03'])
    expect(cells.map((c) => c.status)).toEqual(['none', 'red', 'green'])
  })

  it('buildDayCells caps to last N days', () => {
    expect(buildDayCells(rows, 2).length).toBe(2)
    expect(buildDayCells(rows, 2)[0].date).toBe('2026-07-02')
  })

  it('countStatuses tallies case-insensitively', () => {
    expect(countStatuses(rows)).toEqual({ green: 1, yellow: 0, red: 1 })
  })

  it('exposes status colors', () => {
    expect(STATUS_COLORS.green).toBe('#22c55e')
    expect(STATUS_COLORS.none).toBe('#2a2a2a')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/lib/signals.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`web/src/lib/signals.ts`：

```ts
export type Status = 'green' | 'yellow' | 'red' | 'none'
export type SignalRow = { signal_date: string; market_status: string }
export type DayCell = { date: string; status: Status }

export const STATUS_COLORS: Record<Status, string> = {
  green: '#22c55e',
  yellow: '#eab308',
  red: '#ef4444',
  none: '#2a2a2a',
}

function normalize(status: string): Status {
  const s = (status ?? '').toLowerCase()
  return s === 'green' || s === 'yellow' || s === 'red' ? s : 'none'
}

export function buildDayCells(rows: SignalRow[], days = 30): DayCell[] {
  const asc = [...rows].sort((a, b) => a.signal_date.localeCompare(b.signal_date))
  const cells = asc.map((r) => ({ date: r.signal_date, status: normalize(r.market_status) }))
  return days && cells.length > days ? cells.slice(cells.length - days) : cells
}

export function countStatuses(rows: SignalRow[]): { green: number; yellow: number; red: number } {
  const out = { green: 0, yellow: 0, red: 0 }
  for (const r of rows) {
    const s = normalize(r.market_status)
    if (s !== 'none') out[s] += 1
  }
  return out
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/lib/signals.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add web/src/lib/signals.ts web/src/lib/signals.test.ts
git commit -m "feat(web): signals 纯逻辑（点阵/计数/颜色）"
```

---

## Task 5: 纯逻辑 `technicals.ts`（K线线序列 + 指标卡派生）

**Files:**
- Create: `web/src/lib/technicals.ts`
- Test: `web/src/lib/technicals.test.ts`

**Interfaces:**
- Consumes: `Bar`（Task 3）、MA 数组、`/api/tickers/trends` 快照行（含 `relative_strength_spy`, `trend_state`, `attention_level`）。
- Produces:
  - `toLineData(bars: Bar[], ma: (number|null)[]): { time: string; value: number }[]` — 跳过 null。
  - `type Card = { label: string; value: string; tone: 'up'|'down'|'flat' }`
  - `deriveCards(bars: Bar[], ma200: (number|null)[], snapshot?: { relative_strength_spy?: number|null }): Card[]` — 顺序：收盘/开盘/涨跌/量比/RS·SPY/距200线。

- [ ] **Step 1: 写失败测试** (`web/src/lib/technicals.test.ts`)

```ts
import { describe, it, expect } from 'vitest'
import { toLineData, deriveCards } from './technicals'

const bars = Array.from({ length: 21 }, (_, i) => ({
  date: `2026-06-${String(i + 1).padStart(2, '0')}`,
  open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i, volume: 1000,
}))
bars[20] = { ...bars[20], volume: 3000, close: 200 } // 最后一日放量、拉高

describe('technicals helpers', () => {
  it('toLineData skips nulls and keeps time/value', () => {
    const ma = bars.map((_, i) => (i < 2 ? null : 100 + i))
    const line = toLineData(bars, ma)
    expect(line.length).toBe(19)
    expect(line[0]).toEqual({ time: '2026-06-03', value: 102 })
  })

  it('deriveCards computes change/volume-ratio/dist200', () => {
    const ma200 = bars.map(() => 100) // 距200线 = 200/100 - 1 = +100%
    const cards = deriveCards(bars, ma200, { relative_strength_spy: 0.031 })
    expect(cards.map((c) => c.label)).toEqual(['收盘', '开盘', '涨跌', '量比', 'RS·SPY', '距200线'])
    expect(cards[0].value).toBe('200.00')      // 收盘
    expect(cards[2].tone).toBe('up')           // 涨跌为正
    expect(cards[3].value).toBe('3.0×')        // 量比 = 3000 / 1000
    expect(cards[5].value).toBe('+100.0%')     // 距200线
  })

  it('deriveCards shows dash when snapshot missing RS', () => {
    const ma200 = bars.map(() => 100)
    const cards = deriveCards(bars, ma200, undefined)
    expect(cards[4].value).toBe('—')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/lib/technicals.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`web/src/lib/technicals.ts`：

```ts
import type { Bar } from './api'

export function toLineData(bars: Bar[], ma: (number | null)[]): { time: string; value: number }[] {
  const out: { time: string; value: number }[] = []
  for (let i = 0; i < bars.length; i++) {
    const v = ma[i]
    if (v != null) out.push({ time: bars[i].date, value: v })
  }
  return out
}

export type Card = { label: string; value: string; tone: 'up' | 'down' | 'flat' }

function pct(x: number): string {
  const sign = x > 0 ? '+' : ''
  return `${sign}${(x * 100).toFixed(1)}%`
}
function tone(x: number): 'up' | 'down' | 'flat' {
  return x > 0 ? 'up' : x < 0 ? 'down' : 'flat'
}

export function deriveCards(
  bars: Bar[],
  ma200: (number | null)[],
  snapshot?: { relative_strength_spy?: number | null },
): Card[] {
  const last = bars[bars.length - 1]
  const prev = bars[bars.length - 2]
  const change = prev ? last.close / prev.close - 1 : 0
  const vol20 = bars.slice(-20).reduce((s, b) => s + b.volume, 0) / Math.min(20, bars.length)
  const volRatio = vol20 ? last.volume / vol20 : 0
  const ma200Last = ma200[ma200.length - 1]
  const dist200 = ma200Last ? last.close / ma200Last - 1 : null
  const rs = snapshot?.relative_strength_spy

  return [
    { label: '收盘', value: last.close.toFixed(2), tone: 'flat' },
    { label: '开盘', value: last.open.toFixed(2), tone: 'flat' },
    { label: '涨跌', value: pct(change), tone: tone(change) },
    { label: '量比', value: `${volRatio.toFixed(1)}×`, tone: volRatio >= 1 ? 'up' : 'down' },
    { label: 'RS·SPY', value: rs == null ? '—' : (rs > 0 ? '+' : '') + rs.toFixed(3), tone: tone(rs ?? 0) },
    { label: '距200线', value: dist200 == null ? '—' : pct(dist200), tone: tone(dist200 ?? 0) },
  ]
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/lib/technicals.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add web/src/lib/technicals.ts web/src/lib/technicals.test.ts
git commit -m "feat(web): technicals 纯逻辑（线序列 + 指标卡派生）"
```

---

## Task 6: 信号可视化组件（StatusRibbon / DotMatrix / RatioBar）

**Files:**
- Create: `web/src/lib/components/StatusRibbon.svelte`
- Create: `web/src/lib/components/DotMatrix.svelte`
- Create: `web/src/lib/components/RatioBar.svelte`
- Test: `web/src/lib/components/SignalViz.test.ts`

**Interfaces:**
- Consumes: `DayCell`（Task 4）、`STATUS_COLORS`（Task 4）、计数对象。
- Produces（props）：
  - `StatusRibbon` — `{ cells: DayCell[] }`，渲染一排 `<span data-testid="ribbon-seg">`，每段一个格子。
  - `DotMatrix` — `{ cells: DayCell[] }`，渲染一排 `<span data-testid="dot">`。
  - `RatioBar` — `{ counts: {green,yellow,red} }`，渲染 3 段 `<span data-testid="ratio-seg">`，宽度按占比。

- [ ] **Step 1: 写失败测试** (`web/src/lib/components/SignalViz.test.ts`)

```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import StatusRibbon from './StatusRibbon.svelte'
import DotMatrix from './DotMatrix.svelte'
import RatioBar from './RatioBar.svelte'

const cells = [
  { date: '2026-07-01', status: 'green' as const },
  { date: '2026-07-02', status: 'red' as const },
]

describe('signal viz components', () => {
  it('DotMatrix renders one dot per cell', () => {
    render(DotMatrix, { props: { cells } })
    expect(screen.getAllByTestId('dot').length).toBe(2)
  })

  it('StatusRibbon renders one segment per cell', () => {
    render(StatusRibbon, { props: { cells } })
    expect(screen.getAllByTestId('ribbon-seg').length).toBe(2)
  })

  it('RatioBar renders three segments', () => {
    render(RatioBar, { props: { counts: { green: 6, yellow: 3, red: 1 } } })
    expect(screen.getAllByTestId('ratio-seg').length).toBe(3)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/lib/components/SignalViz.test.ts`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 实现三个组件**

`web/src/lib/components/DotMatrix.svelte`：

```svelte
<script lang="ts">
  import { STATUS_COLORS, type DayCell } from '../signals'
  let { cells }: { cells: DayCell[] } = $props()
</script>

<div class="flex flex-wrap gap-1" style="max-width:340px">
  {#each cells as c}
    <span
      data-testid="dot"
      title={c.date}
      style="width:15px;height:15px;border-radius:3px;background:{STATUS_COLORS[c.status]}"
    ></span>
  {/each}
</div>
```

`web/src/lib/components/StatusRibbon.svelte`：

```svelte
<script lang="ts">
  import { STATUS_COLORS, type DayCell } from '../signals'
  let { cells }: { cells: DayCell[] } = $props()
</script>

<div class="flex rounded-md overflow-hidden" style="height:34px;width:100%">
  {#each cells as c}
    <span
      data-testid="ribbon-seg"
      title={c.date}
      style="flex:1;height:100%;background:{STATUS_COLORS[c.status]}"
    ></span>
  {/each}
</div>
```

`web/src/lib/components/RatioBar.svelte`：

```svelte
<script lang="ts">
  import { STATUS_COLORS } from '../signals'
  let { counts }: { counts: { green: number; yellow: number; red: number } } = $props()
  const order = ['green', 'yellow', 'red'] as const
  let total = $derived(Math.max(counts.green + counts.yellow + counts.red, 1))
</script>

<div class="flex rounded-full overflow-hidden" style="height:14px;width:220px">
  {#each order as k}
    <span
      data-testid="ratio-seg"
      style="flex:{counts[k]};min-width:0;background:{STATUS_COLORS[k]}"
      title={`${k} ${counts[k]} (${Math.round((counts[k] / total) * 100)}%)`}
    ></span>
  {/each}
</div>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/lib/components/SignalViz.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add web/src/lib/components/StatusRibbon.svelte web/src/lib/components/DotMatrix.svelte web/src/lib/components/RatioBar.svelte web/src/lib/components/SignalViz.test.ts
git commit -m "feat(web): 信号可视化组件 StatusRibbon/DotMatrix/RatioBar"
```

---

## Task 7: 结论卡组件（Gauge / StatCard / VolumeBars）

**Files:**
- Create: `web/src/lib/components/Gauge.svelte`
- Create: `web/src/lib/components/StatCard.svelte`
- Create: `web/src/lib/components/VolumeBars.svelte`
- Test: `web/src/lib/components/TrendViz.test.ts`

**Interfaces:**
- Produces（props）：
  - `Gauge` — `{ judgement: string }`（`risk_off`|`neutral`|`risk_on`），渲染 `<svg data-testid="gauge">` + `<text>` 中文标签（偏空/中性/偏积极）。
  - `StatCard` — `{ label: string; value: string; tone?: 'up'|'down'|'flat' }`，渲染 `<div data-testid="stat-card">`。
  - `VolumeBars` — `{ bars: Bar[]; days?: number }`，渲染 `<rect data-testid="vol-bar">`，量 ≥ 1.5× 近 20 日均量高亮。

- [ ] **Step 1: 写失败测试** (`web/src/lib/components/TrendViz.test.ts`)

```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Gauge from './Gauge.svelte'
import StatCard from './StatCard.svelte'
import VolumeBars from './VolumeBars.svelte'

describe('trend/tech viz components', () => {
  it('Gauge shows Chinese label for judgement', () => {
    render(Gauge, { props: { judgement: 'risk_on' } })
    expect(screen.getByTestId('gauge')).toBeTruthy()
    expect(screen.getByText('偏积极')).toBeTruthy()
  })

  it('StatCard renders label and value', () => {
    render(StatCard, { props: { label: '收盘', value: '228.50' } })
    const card = screen.getByTestId('stat-card')
    expect(card.textContent).toContain('收盘')
    expect(card.textContent).toContain('228.50')
  })

  it('VolumeBars renders one bar per day', () => {
    const bars = Array.from({ length: 5 }, (_, i) => ({
      date: `2026-06-0${i + 1}`, open: 1, high: 1, low: 1, close: 1, volume: 1000,
    }))
    render(VolumeBars, { props: { bars } })
    expect(screen.getAllByTestId('vol-bar').length).toBe(5)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/lib/components/TrendViz.test.ts`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 实现三个组件**

`web/src/lib/components/Gauge.svelte`：

```svelte
<script lang="ts">
  let { judgement }: { judgement: string } = $props()
  const MAP: Record<string, { label: string; color: string; arc: string }> = {
    risk_off: { label: '偏空', color: '#ef4444', arc: 'M10 65 A50 50 0 0 1 45 22' },
    neutral: { label: '中性', color: '#eab308', arc: 'M10 65 A50 50 0 0 1 92 30' },
    risk_on: { label: '偏积极', color: '#22c55e', arc: 'M10 65 A50 50 0 0 1 92 30' },
  }
  let m = $derived(MAP[judgement] ?? MAP.neutral)
</script>

<svg data-testid="gauge" width="120" height="72" viewBox="0 0 120 72">
  <path d="M10 65 A50 50 0 0 1 110 65" fill="none" stroke="#2a2a2a" stroke-width="10" stroke-linecap="round" />
  <path d={m.arc} fill="none" stroke={m.color} stroke-width="10" stroke-linecap="round" />
  <text x="60" y="60" text-anchor="middle" fill={m.color} font-size="13" font-weight="700">{m.label}</text>
</svg>
```

`web/src/lib/components/StatCard.svelte`：

```svelte
<script lang="ts">
  let { label, value, tone = 'flat' }: { label: string; value: string; tone?: 'up' | 'down' | 'flat' } = $props()
  const COLOR = { up: '#22c55e', down: '#ef4444', flat: 'inherit' }
</script>

<div data-testid="stat-card" class="border border-border rounded-lg p-3">
  <div class="text-xs text-muted uppercase">{label}</div>
  <b class="text-lg block mt-1" style="color:{COLOR[tone]}">{value}</b>
</div>
```

`web/src/lib/components/VolumeBars.svelte`：

```svelte
<script lang="ts">
  import type { Bar } from '../api'
  let { bars, days = 60 }: { bars: Bar[]; days?: number } = $props()
  let shown = $derived(bars.slice(-days))
  let avg20 = $derived(
    bars.slice(-20).reduce((s, b) => s + b.volume, 0) / Math.max(Math.min(20, bars.length), 1),
  )
  let maxVol = $derived(Math.max(...shown.map((b) => b.volume), 1))
  const W = 460
  const H = 46
</script>

<svg width="100%" height={H} viewBox="0 0 {W} {H}" preserveAspectRatio="none">
  {#each shown as b, i}
    {@const h = (b.volume / maxVol) * H}
    <rect
      data-testid="vol-bar"
      x={(i / shown.length) * W}
      y={H - h}
      width={Math.max(W / shown.length - 1, 1)}
      height={h}
      fill={b.volume >= 1.5 * avg20 ? '#22c55e' : '#3a3a3a'}
    />
  {/each}
</svg>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/lib/components/TrendViz.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add web/src/lib/components/Gauge.svelte web/src/lib/components/StatCard.svelte web/src/lib/components/VolumeBars.svelte web/src/lib/components/TrendViz.test.ts
git commit -m "feat(web): 结论卡/指标卡/量价柱组件 Gauge/StatCard/VolumeBars"
```

---

## Task 8: CandleChart 支持 MA 叠加线

**Files:**
- Modify: `web/src/lib/charts/CandleChart.svelte`

**Interfaces:**
- Consumes: `toLineData()` 的输出格式 `{ time: string; value: number }[]`。
- Produces: `CandleChart` 新增可选 prop `overlays?: { color: string; data: { time: string; value: number }[] }[]`，默认 `[]`，不传时行为不变。

- [ ] **Step 1: 修改组件**

把 `web/src/lib/charts/CandleChart.svelte` 改为：

```svelte
<script lang="ts">
  import { createChart, type IChartApi, type ISeriesApi, type CandlestickData, type LineData } from 'lightweight-charts'
  import { onMount, onDestroy } from 'svelte'

  type Overlay = { color: string; data: { time: string; value: number }[] }
  let { data, overlays = [] }: { data: CandlestickData[]; overlays?: Overlay[] } = $props()
  let el: HTMLDivElement
  let chart: IChartApi | undefined
  let series: ISeriesApi<'Candlestick'> | undefined
  let lineSeries: ISeriesApi<'Line'>[] = []

  onMount(() => {
    const style = getComputedStyle(document.documentElement)
    const up = style.getPropertyValue('--up').trim() || '#16a34a'
    const down = style.getPropertyValue('--down').trim() || '#dc2626'
    chart = createChart(el, { width: el.clientWidth, height: 320, layout: { background: { color: 'transparent' } } })
    series = chart.addCandlestickSeries({ upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down })
    series.setData(data)
    syncOverlays()
    const ro = new ResizeObserver(() => chart?.applyOptions({ width: el.clientWidth }))
    ro.observe(el)
  })

  function syncOverlays() {
    if (!chart) return
    for (const s of lineSeries) chart.removeSeries(s)
    lineSeries = overlays.map((o) => {
      const s = chart!.addLineSeries({ color: o.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      s.setData(o.data as LineData[])
      return s
    })
  }

  $effect(() => { series?.setData(data) })
  $effect(() => { overlays; syncOverlays() })

  onDestroy(() => { chart?.remove() })
</script>

<div bind:this={el} style="width:100%;height:320px"></div>
```

- [ ] **Step 2: 类型检查 + 现有测试回归**

Run: `cd web && npx svelte-check --threshold error 2>&1 | tail -5 && npx vitest run src/lib/charts`
Expected: 无类型错误；现有 chart 相关测试仍 PASS（若 jsdom 无 canvas 导致既有 CandleChart 无测试，则仅需类型通过）。

- [ ] **Step 3: 提交**

```bash
git add web/src/lib/charts/CandleChart.svelte
git commit -m "feat(web): CandleChart 支持 overlays 叠加 MA 线"
```

---

## Task 9: 重写信号总览与趋势分析视图

**Files:**
- Modify: `web/src/routes/Data.svelte`
- Modify: `web/src/routes/Data.test.ts`

**Interfaces:**
- Consumes: `buildDayCells`/`countStatuses`（Task 4）、`StatusRibbon`/`DotMatrix`/`RatioBar`（Task 6）、`Gauge`（Task 7）、`getMarketSignals(30)`/`getMarketSignalsTrend(30)`。
- Produces: 无对外接口（视图内部装配）。注意：本任务仍保留 `tickers` Tab（在 Task 11 移除），以便独立测试。

- [ ] **Step 1: 写失败测试**（改 `web/src/routes/Data.test.ts`，追加一个用例）

```ts
it('signals tab shows dot matrix and ratio', async () => {
  vi.spyOn(api, 'getMarketSignals').mockResolvedValue({
    rows: [
      { signal_date: '2026-07-01', market_status: 'green', spy_close: 1, vix_close: 1, spy_above_200ma: true },
      { signal_date: '2026-07-02', market_status: 'red', spy_close: 1, vix_close: 22, spy_above_200ma: false },
    ],
  } as any)
  vi.spyOn(api, 'getMarketSignalsTrend').mockResolvedValue({
    window: 30, judgement: 'risk_on', summary: '偏积极', status_counts: { green: 1, yellow: 0, red: 1 },
  } as any)
  vi.spyOn(api, 'getTickerTrends').mockResolvedValue({ rows: [] } as any)
  vi.spyOn(api, 'getFilingRecords').mockResolvedValue({ records: [], tickers: [], degraded: false } as any)
  render(Data, { props: { sub: 'signals' } })
  const dots = await screen.findAllByTestId('dot')
  expect(dots.length).toBe(2)
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/routes/Data.test.ts`
Expected: FAIL（无 `dot` testid）

- [ ] **Step 3: 改 Data.svelte**

在 `Data.svelte` 的 `<script>` 顶部补 import：

```svelte
  import StatusRibbon from '../lib/components/StatusRibbon.svelte'
  import DotMatrix from '../lib/components/DotMatrix.svelte'
  import RatioBar from '../lib/components/RatioBar.svelte'
  import Gauge from '../lib/components/Gauge.svelte'
  import { buildDayCells, countStatuses } from '../lib/signals'
```

把 `load()` 里的 `getMarketSignals(60)` 改为 `getMarketSignals(30)`；新增派生：

```svelte
  let cells = $derived(buildDayCells(signals as any, 30))
  let counts = $derived(countStatuses(signals as any))
  const judgeLabel: Record<string, string> = { risk_on: '偏积极', neutral: '中性', risk_off: '偏空' }
  let vixHigh = $derived(((signals as any)[0]?.vix_close ?? 0) >= 20)
  let spyAbove200 = $derived(!!(signals as any)[0]?.spy_above_200ma)
  let recentYellowRed = $derived(
    (signals as any).slice(0, 5).filter((r: any) => ['yellow', 'red'].includes(String(r.market_status).toLowerCase())).length
  )
```

把 `tab === 'trend'` 分支替换为结论卡：

```svelte
  {:else if tab === 'trend'}
    {#if trend}
      <div class="bg-surface rounded-lg p-5 shadow-elev-1 space-y-4">
        <div class="flex items-center gap-5">
          <Gauge judgement={(trend as any).judgement ?? 'neutral'} />
          <div>
            <div class="text-2xl font-bold" style="color:#4ade80">{(trend as any).judgement ?? '—'}</div>
            <div class="mt-2"><RatioBar counts={(trend as any).status_counts ?? counts} /></div>
          </div>
        </div>
        <p class="text-sm text-muted">{(trend as any).summary ?? ''}</p>
        <div class="flex flex-wrap gap-2">
          <span class="text-xs px-2.5 py-1 rounded-full border {spyAbove200 ? 'border-green-500/40 text-green-400' : 'border-red-500/40 text-red-400'}">
            {spyAbove200 ? '✓ SPY 站上 200 日线' : '✗ SPY 跌破 200 日线'}
          </span>
          <span class="text-xs px-2.5 py-1 rounded-full border {vixHigh ? 'border-red-500/40 text-red-400' : 'border-green-500/40 text-green-400'}">
            VIX {(signals as any)[0]?.vix_close ?? '—'} {vixHigh ? '高波动' : '低波动'}
          </span>
          <span class="text-xs px-2.5 py-1 rounded-full border border-border text-muted">近 5 日 {recentYellowRed} 个 yellow/red</span>
        </div>
      </div>
    {:else}
      <p class="text-sm text-muted">暂无趋势数据</p>
    {/if}
```

把 `signals` 分支（`{:else}` 最后一段）替换为四层结构：

```svelte
  {:else}
    <div class="space-y-4">
      <div>
        <div class="text-xs text-muted mb-1">近 30 天状态演变</div>
        <StatusRibbon cells={cells} />
      </div>
      <div class="flex gap-4 text-sm">
        <span style="color:#22c55e"><b class="text-lg">{counts.green}</b> 天 green</span>
        <span style="color:#eab308"><b class="text-lg">{counts.yellow}</b> 天 yellow</span>
        <span style="color:#ef4444"><b class="text-lg">{counts.red}</b> 天 red</span>
      </div>
      <DotMatrix cells={cells} />
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <DataTable rows={signals} columns={cols} />
      </div>
    </div>
  {/if}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/routes/Data.test.ts`
Expected: PASS（含原财报用例 + 新 signals 用例）

- [ ] **Step 5: 提交**

```bash
git add web/src/routes/Data.svelte web/src/routes/Data.test.ts
git commit -m "feat(web): 信号总览四层可视化 + 趋势分析结论卡"
```

---

## Task 10: 路由抽取到 `lib/router.ts`（含 technicals zone）

**Files:**
- Create: `web/src/lib/router.ts`
- Create: `web/src/lib/router.test.ts`
- Modify: `web/src/app.svelte`

**Interfaces:**
- Produces:
  - `type Zone = 'tools'|'data'|'strategy'|'trade'|'settings'|'technicals'`
  - `zones: Zone[]`
  - `parseHash(hash: string): { zone: Zone; sub: string | undefined }`（未知 zone 回落 `'tools'`）。

- [ ] **Step 1: 写失败测试** (`web/src/lib/router.test.ts`)

```ts
import { describe, it, expect } from 'vitest'
import { parseHash } from './router'

describe('parseHash', () => {
  it('parses technicals zone with ticker sub', () => {
    expect(parseHash('#technicals/AAPL')).toEqual({ zone: 'technicals', sub: 'AAPL' })
  })
  it('parses data/signals', () => {
    expect(parseHash('#data/signals')).toEqual({ zone: 'data', sub: 'signals' })
  })
  it('falls back to tools for unknown zone', () => {
    expect(parseHash('#nope')).toEqual({ zone: 'tools', sub: undefined })
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/lib/router.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 router.ts 并接入 app.svelte**

`web/src/lib/router.ts`：

```ts
export type Zone = 'tools' | 'data' | 'strategy' | 'trade' | 'settings' | 'technicals'
export const zones: Zone[] = ['tools', 'data', 'strategy', 'trade', 'settings', 'technicals']

export function parseHash(hash: string): { zone: Zone; sub: string | undefined } {
  const [rawZone, rawSub] = hash.replace(/^#/, '').split('/')
  const zone = zones.includes(rawZone as Zone) ? (rawZone as Zone) : 'tools'
  return { zone, sub: rawSub || undefined }
}
```

改 `web/src/app.svelte`：删除本地 `Zone`/`zones`/`parseHash` 定义，改为 `import { parseHash, type Zone } from './lib/router'`；`import Technicals from './routes/Technicals.svelte'`（Task 11 会创建，此处先加 import 会因文件缺失报错——故本步骤先只加 router，Technicals import 与分支留到 Task 11）。本步骤仅替换路由解析，不新增 zone 分支：

```svelte
  import { parseHash, type Zone } from './lib/router'
  // 删除原 type Zone / const zones / function parseHash
```

- [ ] **Step 4: 跑测试 + 类型检查**

Run: `cd web && npx vitest run src/lib/router.test.ts && npx svelte-check --threshold error 2>&1 | tail -3`
Expected: router 测试 PASS；类型检查通过（app.svelte 仍能编译，因为 zone 联合类型多出的 `technicals` 尚无分支，会走 `{:else}` → Settings，暂时可接受，Task 11 补分支）。

- [ ] **Step 5: 提交**

```bash
git add web/src/lib/router.ts web/src/lib/router.test.ts web/src/app.svelte
git commit -m "refactor(web): 路由解析抽到 lib/router.ts，新增 technicals zone"
```

---

## Task 11: 技术面趋势独立页面 + 导航接入

**Files:**
- Create: `web/src/routes/Technicals.svelte`
- Create: `web/src/routes/Technicals.test.ts`
- Modify: `web/src/app.svelte`
- Modify: `web/src/lib/components/SideNav.svelte`
- Modify: `web/src/routes/Data.svelte`
- Modify: `web/src/routes/Data.test.ts`

**Interfaces:**
- Consumes: `getTickerTrends()`、`getTickerOhlcv()`（Task 3）、`deriveCards`/`toLineData`（Task 5）、`CandleChart`+overlays（Task 8）、`StatCard`/`VolumeBars`（Task 7）。
- Produces: `Technicals.svelte`（默认导出组件，props `{ sub?: string }`，sub=当前股票代码）。

- [ ] **Step 1: 写失败测试** (`web/src/routes/Technicals.test.ts`)

```ts
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Technicals from './Technicals.svelte'
import * as api from '../lib/api'

// CandleChart 依赖 canvas，jsdom 下 mock 掉
vi.mock('../lib/charts/CandleChart.svelte', async () => {
  const Stub = (await import('./__stub__.svelte')).default
  return { default: Stub }
})

describe('Technicals page', () => {
  it('renders ticker tabs and stat cards for the active ticker', async () => {
    vi.spyOn(api, 'getTickerTrends').mockResolvedValue({
      rows: [{ ticker: 'AAPL', relative_strength_spy: 0.03, trend_state: 'uptrend', attention_level: 'high' }],
    } as any)
    vi.spyOn(api, 'getTickerOhlcv').mockResolvedValue({
      ticker: 'AAPL',
      bars: [
        { date: '2026-06-01', open: 100, high: 101, low: 99, close: 100, volume: 1000 },
        { date: '2026-06-02', open: 100, high: 103, low: 100, close: 102, volume: 3000 },
      ],
      ma20: [null, 101], ma50: [null, 101], ma200: [null, 100],
    } as any)
    render(Technicals, { props: { sub: 'AAPL' } })
    expect(await screen.findByRole('tab', { name: /AAPL/ })).toBeTruthy()
    const cards = await screen.findAllByTestId('stat-card')
    expect(cards.length).toBe(6)
  })
})
```

创建极简 stub `web/src/routes/__stub__.svelte`：

```svelte
<div data-testid="chart-stub"></div>
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/routes/Technicals.test.ts`
Expected: FAIL（`Technicals.svelte` 不存在）

- [ ] **Step 3: 实现 Technicals.svelte**

`web/src/routes/Technicals.svelte`：

```svelte
<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import type { OhlcvResponse } from '../lib/api'
  import CandleChart from '../lib/charts/CandleChart.svelte'
  import StatCard from '../lib/components/StatCard.svelte'
  import VolumeBars from '../lib/components/VolumeBars.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import { deriveCards, toLineData } from '../lib/technicals'

  let { sub }: { sub?: string } = $props()

  let snapshots = $state<any[]>([])
  let ohlcv = $state<OhlcvResponse | null>(null)
  let loading = $state(true)
  let active = $derived(sub || snapshots[0]?.ticker || '')

  async function loadList() {
    const r: any = await api.getTickerTrends()
    snapshots = r.rows ?? []
  }

  async function loadOhlcv(ticker: string) {
    if (!ticker) return
    ohlcv = null
    try {
      ohlcv = await api.getTickerOhlcv(ticker, 250)
    } catch {
      ohlcv = null
    }
  }

  onMount(async () => {
    await loadList()
    loading = false
  })

  // active 变化时拉行情
  let lastLoaded = ''
  $effect(() => {
    if (active && active !== lastLoaded) {
      lastLoaded = active
      loadOhlcv(active)
    }
  })

  let snapshot = $derived(snapshots.find((s) => s.ticker === active))
  let cards = $derived(ohlcv ? deriveCards(ohlcv.bars, ohlcv.ma200, snapshot) : [])
  let candles = $derived(
    ohlcv
      ? ohlcv.bars.map((b) => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close }))
      : [],
  )
  let overlays = $derived(
    ohlcv
      ? [
          { color: '#22c55e', data: toLineData(ohlcv.bars, ohlcv.ma20) },
          { color: '#60a5fa', data: toLineData(ohlcv.bars, ohlcv.ma50) },
          { color: '#f59e0b', data: toLineData(ohlcv.bars, ohlcv.ma200) },
        ]
      : [],
  )
</script>

<div>
  <h2 class="text-lg font-semibold mb-4">技术面趋势</h2>

  {#if loading}
    <Skeleton rows={4} />
  {:else if snapshots.length === 0}
    <p class="text-sm text-muted">暂无个股快照（可在「工具 · 任务中心」运行 ticker-trends 任务）。</p>
  {:else}
    <div class="flex gap-1 flex-wrap mb-4" role="tablist">
      {#each snapshots as s}
        <a
          role="tab"
          href="#technicals/{s.ticker}"
          aria-selected={s.ticker === active}
          class="px-3 py-1 text-sm rounded {s.ticker === active ? 'bg-accent text-white' : 'bg-surface-2 text-muted hover:bg-surface'}"
        >{s.ticker}</a>
      {/each}
    </div>

    <div class="flex items-center gap-3 mb-3">
      <span class="text-xl font-bold">{active}</span>
      {#if snapshot}
        <span class="text-xs px-2 py-0.5 rounded-full border border-green-500/40 text-green-400">
          {snapshot.trend_state} · {snapshot.attention_level}
        </span>
      {/if}
    </div>

    {#if ohlcv}
      <div class="grid grid-cols-2 md:grid-cols-6 gap-2 mb-4">
        {#each cards as c}
          <StatCard label={c.label} value={c.value} tone={c.tone} />
        {/each}
      </div>
      <div class="bg-surface rounded-lg p-3 shadow-elev-1">
        <div class="flex gap-3 text-xs mb-2">
          <span style="color:#22c55e">— MA20</span>
          <span style="color:#60a5fa">— MA50</span>
          <span style="color:#f59e0b">— MA200</span>
        </div>
        <CandleChart data={candles} overlays={overlays} />
        <div class="text-xs text-muted mt-3 mb-1">量价（放量高亮）</div>
        <VolumeBars bars={ohlcv.bars} />
      </div>
    {:else}
      <Skeleton rows={3} />
    {/if}
  {/if}
</div>
```

- [ ] **Step 4: 接入 app.svelte + SideNav，并从 Data 移除 tickers**

改 `web/src/app.svelte`：加 `import Technicals from './routes/Technicals.svelte'`，在 `{#if zone === ...}` 链中新增分支（放在 `settings` 前）：

```svelte
  {:else if zone === 'technicals'}
    <Technicals {sub} />
```

改 `web/src/lib/components/SideNav.svelte`：从 `data` 的 children 删除 `{ id: 'tickers', label: '技术面趋势' }`；在 `nav` 数组 `data` 项之后插入新一级项：

```ts
    { id: 'technicals', label: '技术面趋势', icon: '📈' },
```

改 `web/src/routes/Data.svelte`：
- `type Tab` 去掉 `'tickers'`；`tab` 派生去掉 `sub === 'tickers'` 分支。
- 删除 `tickers` 状态、`tkCols`、`getTickerTrends` 调用（`load()` 里改为 `[signals, trend] = await Promise.all([...])`）。
- 删除 Tab 按钮里的 `tickers` 项与 `{:else if tab === 'tickers'}` 渲染分支。
- Tab 循环数组改为 `(['signals','trend','filings'] as const)`，标签 map 去掉 `tickers`。

改 `web/src/routes/Data.test.ts`：删除对 `getTickerTrends` 的 `vi.spyOn`（若某用例已不需要）——保留 mock 不会报错，但为准确性移除；确保财报与 signals 用例仍通过。

改 `web/src/app.test.ts`：给 `vi.mock('./lib/api', ...)` 的工厂对象补一行 `getTickerOhlcv: vi.fn(async () => ({ ticker: '', bars: [], ma20: [], ma50: [], ma200: [] })),`（app 顶层现会 import Technicals → api.getTickerOhlcv，整模块 mock 需覆盖到）。现有两个用例断言用 `greaterThan(0)`，新增第 6 个导航项不影响其通过。

- [ ] **Step 5: 跑全部前端测试 + 类型检查**

Run: `cd web && npx svelte-check --threshold error 2>&1 | tail -3 && npx vitest run`
Expected: 类型检查通过；所有测试 PASS。

- [ ] **Step 6: 提交**

```bash
git add web/src/routes/Technicals.svelte web/src/routes/Technicals.test.ts web/src/routes/__stub__.svelte web/src/app.svelte web/src/lib/components/SideNav.svelte web/src/routes/Data.svelte web/src/routes/Data.test.ts
git commit -m "feat(web): 技术面趋势独立页面 + 一级导航，Data 移除 tickers Tab"
```

---

## Task 12: 全量回归

**Files:** 无新增，跑全套。

- [ ] **Step 1: 后端全测**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部 PASS。

- [ ] **Step 2: 前端全测 + 类型 + 构建**

Run: `cd web && npx vitest run && npx svelte-check --threshold error 2>&1 | tail -3 && npm run build`
Expected: 测试全 PASS、类型检查零 error、构建成功。

- [ ] **Step 3: 提交（如有 lockfile/构建产物变更）**

```bash
git status
# 若有需要提交的变更：
git add -A && git commit -m "chore: 数据层展示优化回归修复"
```

---

## Self-Review 记录

- **Spec 覆盖**：新端点(Task 1/2/3)、信号总览四层(Task 4/6/9)、趋势结论卡+因子(Task 7/9)、技术面独立页+顶部 Tab+6 卡+K线MA+量价(Task 3/5/7/8/11)、导航升一级+移除旧 Tab(Task 10/11)、测试(各任务 + Task 12)。均有对应任务。
- **旧 `#data/tickers` 重定向**：spec 标为"实现时定"的低优先项——本计划采取"不做重定向"，`parseHash('#data/tickers')` 会落到 Data 的默认 signals Tab（因 `tickers` 分支已删），行为可接受；如需重定向可后续追加。
- **占位符**：无 TODO/TBD，每个代码步骤均含完整代码。
- **类型一致性**：`DayCell`/`Bar`/`OhlcvResponse`/`Card`/`Zone` 跨任务命名一致；`toLineData` 输出 `{time,value}` 与 `CandleChart` overlays 的 `data` 类型一致；`deriveCards` 卡序与 spec 指标卡表一致。
