# 数据层展示优化设计

日期：2026-07-06
状态：已通过 brainstorming 评审，待实现计划

## 背景与目标

「数据」区当前三个视图展示粗糙：

- **信号总览**：一张 4 列表格（日期/状态/SPY/VIX）+ 顶部状态药丸，看不出"过去 30 天哪种状态居多"。
- **趋势分析**：直接把 `/api/market/signals/trend` 的返回 `JSON.stringify` 糊在 `<pre>` 里。
- **技术面趋势**：一张 3 列表格（Ticker/趋势/关注度）。底层 `ticker_signal_snapshots` 表**已存**了 `close/ma20/ma50/ma200/volume/volume_ratio/relative_strength_spy/relative_strength_qqq` 等字段，但前端一个都没展示。

目标：用更贴合语义的可视化重构这三个视图，并把技术面趋势升级为按股票分 Tab 的独立个股页面，补齐美股基础指标（量价强弱、开收盘、200 日均线）。

**关键判断**：本次以前端为主，后端**只新增 1 个端点**。大部分指标后端早已算好入库，之前只是没在前端露出。

## 非目标（YAGNI）

- **不做真实盘口/逐笔"订单流"**。数据源 yfinance 只有日频 OHLCV，拿不到 Level 2。"订单流"落地为**量价强弱**（成交量 + 量比 + 相对强弱 + 放量高亮），不引入付费数据源。
- **不做 OHLCV 落库**。个股 K 线走后端实时代拉（roadmap Phase 1 的 OHLCV 落库另行推进，本次不碰 migration）。
- 不改动信号/快照的计算逻辑，只改展示与新增读取端点。

## 架构与数据流

```
前端 (Svelte 5)                         后端 (FastAPI)
─────────────────                       ─────────────────
信号总览  ── /api/market/signals ────────► services.market.market_signal_rows
          └ /api/market/signals/trend ──► services.market.market_signal_trend
趋势分析  ── /api/market/signals/trend ──► （同上；因子取 signals 最新行）
技术面趋势 ┌ /api/tickers/trends ─────────► services.tickers.ticker_trend_rows（快照）
          └ /api/tickers/{t}/ohlcv 【新】► services.tickers.ohlcv_series ─► data.price
```

### 复用的现有端点（无改动）

- `GET /api/market/signals?limit=` → 每日市场信号行（`signal_date/market_status/spy_close/spy_ma200/spy_above_200ma/vix_close/...`）。
- `GET /api/market/signals/trend?window=` → `{window, sample_size, latest_status, status_counts{green,yellow,red}, green_ratio, red_ratio, judgement, summary, rows}`。
- `GET /api/tickers/trends` → 每票最新快照行（含 `close/ma200/volume_ratio/relative_strength_spy/trend_state/attention_level`）。

### 新增端点

`GET /api/tickers/{ticker}/ohlcv?days=250`

- 路由：`investment_assistant/api/routes/tickers.py` 新增。
- 服务：`investment_assistant/services/tickers.py` 新增 `ohlcv_series(ticker: str, days: int = 250) -> dict`。
- 实现：调 `data.price.get_price_history(ticker, days)` 取日频 OHLCV，服务端计算 `MA20/MA50/MA200`（`Close.rolling(n).mean()`）。
- 返回：
  ```json
  {
    "ticker": "AAPL",
    "bars": [{"date":"2026-01-02","open":..,"high":..,"low":..,"close":..,"volume":..}, ...],
    "ma20": [null,.., 227.1, ...],
    "ma50": [...],
    "ma200": [...]
  }
  ```
  MA 数组与 `bars` 等长，前 n-1 个为 `null`。
- **缓存**：进程内 `dict` + 5 分钟 TTL（key=`(ticker, days)`），软化 yfinance 限流。缓存实现放在 service 层。
- 错误：`price.get_price_history` 抛 `ValueError`（无数据）时返回 4xx（沿用现有路由错误约定）。

### 前端复用组件

- `CandleChart.svelte`：**扩展**，新增可选 `overlays` prop 承载 MA 线序列（用 lightweight-charts `addLineSeries`）。默认不传时行为不变。
- `DataTable.svelte`、`StatusPill.svelte`：信号总览明细表继续复用。

### 前端新增小组件（各自单一职责，`web/src/lib/components/`）

- `StatusRibbon.svelte`：输入按日期排序的 `{date, status}[]`，渲染一条连续色带（每段宽度=连续同状态天数）。
- `DotMatrix.svelte`：输入 `{date, status}[]`，渲染每日方块点阵（green/yellow/red，缺失日灰色）。
- `RatioBar.svelte`：输入 `{green,yellow,red}` 计数，渲染占比条。
- `Gauge.svelte`：输入 `judgement`（risk_off/neutral/risk_on），渲染半圆仪表。
- `StatCard.svelte`：输入 `{label, value, tone?}`，渲染单个指标卡。

## 视图设计

### 视图 1 · 信号总览（`#data/signals`）

自上而下四层：

1. **状态时间带**（`StatusRibbon`）：连续色带，看状态演变（连涨/连跌一目了然）。
2. **占比大数字**（`RatioBar` + 文案）：green/yellow/red 各多少天 + 百分比，直接回答"哪种居多"。
3. **点阵图**（`DotMatrix`）：近 30 天每日方块。
4. **明细表**（现有 `DataTable`）：保留，列不变。

数据：`getMarketSignals(30)` 提供每日行；`getMarketSignalsTrend(30)` 提供计数/判断。窗口统一 30 天。

### 视图 2 · 趋势分析（`#data/trend`）

替换现有裸 JSON，改为**结论卡 + 驱动因子**：

- **半圆仪表**（`Gauge`）：risk_off ↔ neutral ↔ risk_on，指向 `judgement`。
- **占比条**（`RatioBar`）：green/yellow/red 近 30 天占比。
- **一句话总结**：`trend.summary`。
- **驱动因子 chip**：
  - `SPY 站上 / 跌破 200 日线` ← `signals` 最新行 `spy_above_200ma`。
  - `VIX {值} {低/高}波动` ← `signals` 最新行 `vix_close`（阈值：<20 低，≥20 高）。
  - `近 5 日 {n} 个 yellow/red` ← 由 `signals` 前 5 行统计。

无需后端改动：因子全部从已有的 `signals` 行派生。

### 视图 3 · 技术面趋势 → 独立一级页面（新 zone `technicals`）

**导航与路由改动**：

- `SideNav.svelte`：新增一级项 `{ id: 'technicals', label: '技术面趋势', icon: '📈' }`（无 children，或 children 为空）；从 `data` 的 children 中**移除** `{ id: 'tickers' }`。
- `app.svelte`：`Zone` 类型与 `zones` 数组新增 `'technicals'`；`{#if}` 分支新增 `technicals` → 渲染新组件 `Technicals.svelte`。
- `Data.svelte`：移除 `tickers` Tab 及其相关状态/渲染（`getTickerTrends` 调用迁至新页面）；保留 `signals/trend/filings`。旧 `#data/tickers` 可选做 hash 兼容重定向到 `#technicals`（低优先，实现时定）。
- hash 形如 `#technicals/AAPL`，`sub` = 股票代码。

**页面布局**（`Technicals.svelte`）：

1. **顶部横排股票 Tab**：Tab 列表 = `/api/tickers/trends` 返回的股票（有快照的票）。点击切换 `#technicals/{ticker}`。
2. **6 个指标卡**（`StatCard` × 6）：
   | 卡 | 来源 |
   |---|---|
   | 收盘 | OHLCV 端点最新 bar `close` |
   | 开盘 | OHLCV 端点最新 bar `open` |
   | 涨跌 | OHLCV 端点：`close/前一 close - 1` |
   | 量比 | OHLCV 端点：`volume / 近20日均量` |
   | RS·SPY | `/api/tickers/trends` 快照 `relative_strength_spy` |
   | 距200线 | OHLCV 端点：`close/ma200 - 1` |
3. **K线 + 均线**（`CandleChart` + `overlays`）：蜡烛 + MA20/50/200 三条线。
4. **量价柱**：成交量柱状图，放量（量比高）高亮。

**数据拼装**：
- 进入页面：`getTickerTrends()` 拿快照（提供 Tab 列表 + RS·SPY/趋势/关注度）。
- 切换/进入某票：`getTickerOhlcv(ticker, 250)` 拿 K 线序列 + 开收盘/涨跌/量比/距200线。

**为何必须要新端点**：`ticker_signal_snapshots` 表**无 `open` 字段**，"开盘/涨跌"必须来自 OHLCV；且快照只有每票最新一条，画不了 K 线。

## API 客户端

`web/src/lib/api.ts` 新增：

```ts
export const getTickerOhlcv = (ticker: string, days = 250) =>
  get<{ ticker: string; bars: Bar[]; ma20: (number|null)[]; ma50: (number|null)[]; ma200: (number|null)[] }>(
    `/api/tickers/${ticker}/ohlcv?days=${days}`)
```

## 测试

**后端**（pytest，`tests/`）：

- `ohlcv_series`：注入假 fetcher（沿用 `data.price` 已有的 `AsofFetcher` 注入模式或直接 monkeypatch `get_price_history`），断言 MA20/50/200 计算正确、bars/MA 数组等长、前 n-1 为 null。
- 缓存：同参二次调用命中缓存（fetcher 只被调一次）；TTL 过期后重新拉取。
- 路由：无数据时返回 4xx。

**前端**（vitest，`web/src/`）：

- 各新组件渲染测（`StatusRibbon/DotMatrix/RatioBar/Gauge/StatCard`）：给定输入渲染出预期结构与颜色类。
- `app.svelte` 路由解析测：`#technicals/AAPL` → `{zone:'technicals', sub:'AAPL'}`。
- `Technicals.svelte`：mock api，断言 Tab 列表渲染、切票触发 OHLCV 拉取、指标卡取值正确。
- `Data.test.ts`：更新，确认 `tickers` Tab 已移除、`signals/trend/filings` 仍在。

## 交付顺序（供实现计划参考）

1. 后端 OHLCV 端点 + service + 缓存 + 测试。
2. `api.ts` 客户端方法。
3. 前端小组件（`StatusRibbon/DotMatrix/RatioBar/Gauge/StatCard`）+ `CandleChart` overlays 扩展 + 各自测试。
4. 信号总览、趋势分析视图重构。
5. 新 `Technicals.svelte` 页面 + 导航/路由改动 + `Data.svelte` 移除 tickers Tab。
6. 回归：`Data.test.ts` 更新、路由测。

## 部署影响

无 migration、无新环境变量。仅前端构建 + 后端代码更新，滚动重启即可。
