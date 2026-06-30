# Phase 1：数据地基（OHLCV 落库 + 市场广度 + 精简宏观 + EPS surprise）设计

> 日期：2026-06-30 ｜ 范围：roadmap `docs/roadmap/02-phase1-data-foundation.md` 的可执行落地设计
> 上游（已批准方向）：`docs/roadmap/00-principles-and-direction.md`（宏观被砍、广度优先、回测降级）、`docs/roadmap/README.md`（迁移编号约定、落地纪律）
> 关联代码现状：`data/price.py`、`market/service.py`、`tickers/trend.py`、`filings/sec_downloader.py`、`config.py`（已预留 `PriceConfig/MacroConfig/FundamentalsConfig`）、`db.py`、`tasks/_harness.py`、`services/jobs.py`
> 本文是 subagent 在**自主模式**下产出：roadmap 即已批准方向，本文对关键设计点列出备选并自行选定，决策与假设记录在 §10。

---

## 1. 目标与背景

Phase 0 把事件研究骨架（`eps_beat/miss`、point-in-time 取价、前瞻收益分布）搭起来了，但喂给它的是**占位数据**：价格每次全量重下、不可复现；`eps_beat` 没有真实 EPS surprise；市场状态只有「VIX + SPY 单均线」两因子。Phase 1 只补**被事件研究证明有用**的数据，做四件事：

1. **OHLCV 落库**：价格成为可复现、可回测、可回放的稳定基底（迁移 009）。
2. **市场广度指标**：用已落库价格几乎零成本地算出比滞后宏观更灵敏的市场健康度（迁移 010）。
3. **精简宏观**：只采 HY 信用利差 + 2s10s 两个有 risk-off 价值的 FRED series（迁移 011，与 fundamentals 同批）。
4. **EPS surprise 结构化**：抽 EPS 实际/预期/surprise + 营收，把 Phase 0 的 `eps_beat/miss` 从占位升级为真实数据（迁移 011/012）。

**非目标（明确排除，来自 00 方向篇）：**
- 不采全部 6 个 FRED series（CPI/就业/FedFunds 滞后，推迟）。
- 不做全 XBRL companyfacts 大工程（只抽事件研究够用的三项）。
- 不引入付费价格源（Tiingo/Polygon）；单源 yfinance + 落库 + 重试。
- 不在本期对市场状态阈值「寻优」（避免过拟合，先用经验值）。
- 不做前端页面（仅产出 API + 手动 CLI；前端消费留给后续 dashboard 计划）。

**成功标准：**
1. `ohlcv_bars` 有数据，价格读库优先、可复现；`market/service.py` 的 `signal_date` 新鲜度 bug 修复（取实际最新 bar 日期）。
2. `market_breadth` 可按任意历史日期计算；市场状态升级为「VIX + 广度 + HY 利差」多因子门控。
3. HY 利差 + 2s10s 入库；缺 `FRED_API_KEY` 时降级跳过不崩。
4. `fundamentals` 有真实 EPS surprise，Phase 0 PEAD 事件研究可重跑。
5. 四类采集任务**都有定时入口 + 手动回补 CLI**（共享核心函数），且**全部经 `_harness` 审计**（`job_reports` + run_log + 结构化 summary）。
6. 新增逻辑均有单测，外部依赖（DB/yfinance/FRED/SEC）全 mock 或注入，离线可跑。

---

## 2. 总体架构与分层

严格沿用仓库现有分层：`api/routes/* → services/* → db.py / tasks/* / data/*`，路由层薄封装。

```
                      ┌─────────────────────── 定时入口 (tasks/*.py:run) ───────────────────────┐
                      │  metrics(扩展) · breadth(新) · macro(新) · fundamentals(新)             │
                      │  每个 run() = run_task(task, lambda: _core(...), config=config)         │
                      └───────────────┬──────────────────────────────────┬────────────────────┘
                                      │ 共享 _core / 核心纯函数            │
   手动回补 CLI (同文件 main()) ──────┤                                  │
   --from/--to/--date 历史区间        ▼                                  ▼
                          services/{breadth,macro,fundamentals}.py   data/{price,fred}.py
                          (业务编排 + 降级 + 组装 summary)            (取数 + 重试 + 解析，注入式)
                                      │                                  │
                                      ▼                                  ▼
                                    db.py  (ohlcv/breadth/macro/fundamentals 仓储)
                                      │
                                      ▼
                              Postgres (009–012)

   审计/日志：所有 run() 经 tasks/_harness.run_task → job_reports(DB) + run_log(jsonl) + dispatch(notify)
   API：api/routes/data.py 暴露只读查询 + 手动触发 (POST .../backfill)，复用 services/jobs.runner.submit
```

核心 DRY 原则：**定时入口与手动 CLI 调用同一个核心函数**。定时入口传「截至今天」的隐式区间，手动 CLI 传显式历史日期/区间。核心函数对外部依赖（价格 fetcher、FRED getter、DB 连接）一律**参数注入**，保证离线可测。

---

## 3. 数据模型（迁移 009–012）

迁移编号承接 on-disk 008（`notify_settings`）。Phase 1 从 **009** 起。**与并行 Phase 0 agent 可能争用 012**：本设计按 README §4 占用 009/010/011/012，落地时若 012 被先占，则**按落地顺序顺延**（同步改所有 SQL 文件名与测试中的路径断言）。

| 迁移 | 表 | 用途 |
|------|----|------|
| 009 | `ohlcv_bars` | 复权价格落库（回测/事件研究基底） |
| 010 | `market_breadth` | 每日市场广度指标 |
| 011 | `macro_indicators` | HY 利差 + 2s10s（精简宏观，单建以备扩展） |
| 012 | `fundamentals` | EPS 实际/预期/surprise + 营收 |

### 3.1 `009_ohlcv_bars.sql`

```sql
CREATE TABLE IF NOT EXISTS ohlcv_bars (
  ticker      TEXT NOT NULL,
  bar_date    DATE NOT NULL,
  open        NUMERIC(18,6),
  high        NUMERIC(18,6),
  low         NUMERIC(18,6),
  close       NUMERIC(18,6),
  adj_close   NUMERIC(18,6),             -- 复权收盘，事件研究/回测用这列
  volume      BIGINT,
  source      TEXT NOT NULL DEFAULT 'yfinance',
  fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, bar_date)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv_bars (ticker, bar_date DESC);
```

### 3.2 `010_market_breadth.sql`

```sql
CREATE TABLE IF NOT EXISTS market_breadth (
  breadth_date         DATE PRIMARY KEY,
  pct_above_200ma      NUMERIC(6,2),     -- 0..100
  pct_above_50ma       NUMERIC(6,2),
  new_highs_minus_lows INT,
  advance_decline      INT,              -- 当日涨家数 - 跌家数
  universe_size        INT NOT NULL,     -- 计算基数，用于解释百分比
  details              JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 成分池/缺口/run_id
  computed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_market_breadth_date ON market_breadth (breadth_date DESC);
```

> 注：A/D Line（累积涨跌线）= `advance_decline` 的累积和，是**派生量**，不落库原始累积值（避免回补时累积口径漂移）；查询层按区间累加即可。`advance_decline` 落「当日净涨跌家数」。

### 3.3 `011_macro_indicators.sql`

```sql
CREATE TABLE IF NOT EXISTS macro_indicators (
  obs_date     DATE NOT NULL,
  series_id    TEXT NOT NULL,            -- 'BAMLH0A0HYM2' | 'T10Y2Y_DERIVED'
  value        NUMERIC(18,6),
  source       TEXT NOT NULL DEFAULT 'fred',
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (series_id, obs_date)
);
CREATE INDEX IF NOT EXISTS idx_macro_indicators_series_date ON macro_indicators (series_id, obs_date DESC);
```

> 2s10s 既可直接采 FRED 已发布的 `T10Y2Y`，也可由 `DGS10 - DGS2` 派生。**决策见 §10-D3**：采 `T10Y2Y`（FRED 已算好、省一次拼接、避免两序列日期错位），series_id 存 `'T10Y2Y'`。HY 用 `BAMLH0A0HYM2`。

### 3.4 `012_fundamentals.sql`

```sql
CREATE TABLE IF NOT EXISTS fundamentals (
  ticker           TEXT NOT NULL,
  period_end       DATE NOT NULL,        -- 财报对应季度末
  report_date      DATE,                 -- 实际公布日（事件研究锚点）
  eps_actual       NUMERIC(18,6),
  eps_estimate     NUMERIC(18,6),
  eps_surprise     NUMERIC(18,6),        -- (actual-estimate)/NULLIF(abs(estimate),0)
  revenue_actual   NUMERIC(20,2),
  revenue_estimate NUMERIC(20,2),
  source           TEXT NOT NULL DEFAULT 'yfinance',
  fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, period_end)
);
CREATE INDEX IF NOT EXISTS idx_fundamentals_report ON fundamentals (ticker, report_date DESC);
```

> `report_date` 允许 NULL（部分历史季度 yfinance 无公布日）；事件研究只取 `report_date IS NOT NULL` 的行作为锚点。`eps_surprise` 在写入前于 Python 侧计算（含 estimate=0 除零保护），不依赖 generated column（保持迁移可移植）。

---

## 4. 任务清单（Task 1.1–1.4）

每个 Task 都遵循同一形态：**纯核心函数（可测）→ services 编排（降级/组装 summary）→ tasks 定时 run() + 手动 main() → db 仓储 → migration → API 只读/触发**。

### Task 1.1 — OHLCV 落库 + 可靠性（迁移 009）

**为什么**：现在每次重算全量重下、不可复现、yfinance 偶发空值直接报错。

**改动：**
- `data/price.py`：
  - 新增 `fetch_ohlcv(ticker, *, start, end, max_retries, backoff_seconds, ticker_factory=yf.Ticker) -> pd.DataFrame`：按日期区间取**含 `Adj Close`** 的 OHLCV（`auto_adjust=False` 以同时拿到 `Close` 与 `Adj Close`），带**指数退避重试**（复用 `data/http.py` 的退避风格，但这里是 yfinance，单独实现一个 `_with_retry`）。`ticker_factory` 注入用于测试。
  - 保留旧 `get_price_history(ticker, days)` 向后兼容（内部可改为走 DB-first，见下）。
- `db.py` 新增仓储：
  - `upsert_ohlcv_bars(conn, ticker, rows) -> int`：增量 upsert（`ON CONFLICT (ticker,bar_date) DO UPDATE`），返回写入行数。
  - `get_ohlcv_bars(conn, ticker, *, start=None, end=None) -> list[dict]`：读库。
  - `latest_bar_date(conn, ticker) -> date|None`：新鲜度/缺口检测用。
  - `missing_bar_ranges(...)`：用「库里已有最大日期」判断缺口，只回源缺失段（一期简化：取 `max(bar_date)+1 .. end`；区间中间空洞由手动全量回补覆盖，见 §10-D2）。
- `services/prices.py`（新）：
  - `ingest_ohlcv(tickers, *, start, end, fetcher, conn_factory, run_id) -> dict`：对每个 ticker 取数→upsert→记录 `{ticker, rows_written, range, gaps, error}`，组装结构化 summary。缺 DB 时降级（不写库，summary 标 `degraded`）。
  - `get_price_history_db_first(ticker, days, *, asof=None) -> pd.DataFrame`：优先读库，缺口才回源并补库；供 `market/service` 与 `tickers/trend` 调用。
- `market/service.py` **新鲜度守卫**：`compute_market_signal` 的 `signal_date` 不再默认 `date.today()`，改为取 SPY 最新 bar 的实际日期（从 `spy_df.index[-1].date()`），避免周末/假日写陈旧收盘价。

**审计**：OHLCV 采集走 `tasks/prices.py:run`（新定时任务名 `prices`）经 `_harness`；summary 含每 ticker 写入行数、日期区间、缺口、错误。

### Task 1.2 — 市场广度指标（迁移 010）

**为什么**：广度比滞后宏观更灵敏，用已落库 OHLCV 几乎零成本。

**改动：**
- `market/breadth.py`（新，纯函数，输入是「成分池 → 各自价格序列」）：
  - `compute_breadth(price_frames: dict[str, pd.DataFrame], *, breadth_date) -> dict`：算 `pct_above_200ma / pct_above_50ma / new_highs_minus_lows / advance_decline / universe_size`。空成分池或全缺 → 优雅降级返回 `universe_size=0` + 各指标 None。
  - 52 周新高/新低：用 252 个交易日窗口；advance/decline：当日 close vs 前一日 close。
- `services/breadth.py`（新）：
  - 成分池来源（§10-D4）：watchlist（`config.watchlist`）∪ 主要宽基 ETF 代表篮子（常量 `BREADTH_UNIVERSE`，如 SPY/QQQ/IWM + 若干大盘股）。一期用固定篮子近似，不抓指数全成分。
  - `compute_breadth_for_date(target_date, *, conn_factory, price_loader, run_id) -> dict`：从 `ohlcv_bars` 读各成分截至 `target_date` 的序列 → `compute_breadth` → upsert `market_breadth`。
  - `compute_breadth_range(start, end, ...)`：循环交易日回放，用于历史回补/重算。
- `db.py`：`upsert_market_breadth(conn, row)`、`get_market_breadth(conn, *, start, end, limit)`、`latest_market_breadth(conn)`。
- 接入市场状态：见 Task 1.3 汇合。

### Task 1.3 — 精简宏观：HY 利差 + 2s10s（迁移 011）+ 多因子门控

**为什么砍**：宏观择时战绩差、CPI/就业滞后。只留两个有 risk-off 价值的。

**改动：**
- `config.py`：`MacroConfig.fred_series` 默认从 6 个**精简为** `["BAMLH0A0HYM2", "T10Y2Y"]`（改默认值，保留可配置）。
- `data/fred.py`（新）：
  - `fetch_fred_series(series_id, *, start, end, api_key, getter=http.get_json) -> list[dict]`：调 FRED `observations` 端点，解析 `{date, value}`（`"."` 缺测值→None）。缺 `api_key`（`FRED_API_KEY` env）→ 返回结构化「skipped/degraded」，**不崩、不回显 key**。
- `services/macro.py`（新）：
  - `ingest_macro(series_ids, *, start, end, getter, conn_factory, api_key, run_id) -> dict`：逐 series 取数→upsert `macro_indicators`，组装 summary（每 series 行数/缺口/是否降级）。
- `db.py`：`upsert_macro_observations(conn, series_id, rows)`、`get_macro_series(conn, series_id, *, start, end)`、`latest_macro_value(conn, series_id)`。
- **多因子市场状态门控**（`market/service.py` 扩展）：在已有 VIX+SPY 基础上叠加广度与 HY，新增可注入的 `breadth`/`hy_spread` 入参（默认 None 时退回旧两因子，保证向后兼容与离线可测）：

```
red    : VIX>30  OR  pct_above_200ma<20   OR  HY利差快速走阔(较 N 日前 +Δ)
yellow : VIX>20  OR  SPY<200MA            OR  pct_above_200ma<40
green  : 其余
```

阈值经验值放入 `MarketConfig`（新增 `breadth_red_pct=20.0`、`breadth_yellow_pct=40.0`、`hy_widen_delta`、`hy_lookback_days`），**本期不寻优**。门控结果写入 `market_signals.details`（多因子各分量留痕，可审计）。

### Task 1.4 — EPS surprise 结构化（迁移 012）

**为什么**：Phase 0 PEAD 事件研究需要真实「EPS 实际 vs 预期」。

**改动：**
- `data/fundamentals.py`（新）：
  - `fetch_earnings(ticker, *, ticker_factory=yf.Ticker) -> list[dict]`：用 yfinance `earnings_dates`/`get_earnings_dates` 拿每季 `{period_end, report_date, eps_actual, eps_estimate, revenue_actual, revenue_estimate}`（字段缺失→None）。注入式可测。
  - `compute_eps_surprise(actual, estimate) -> float|None`：`(actual-estimate)/abs(estimate)`，`estimate in (None,0)` → None（除零保护）。
- `services/fundamentals.py`（新）：
  - `ingest_fundamentals(tickers, *, fetcher, conn_factory, run_id, since=None, until=None) -> dict`：取数→算 surprise→upsert `fundamentals`，可按 `report_date` 区间过滤（季度回填）。组装 summary（每 ticker 季度数/最新 surprise/缺口）。
- `db.py`：`upsert_fundamentals(conn, ticker, rows)`、`get_fundamentals(conn, ticker, *, start, end)`、`list_eps_events(conn, *, start, end)`（供 Phase 0 事件研究取锚点）。
- 二期（可选，**不在本期实现**）：SEC XBRL `companyconcept` 补营收/毛利，`FundamentalsConfig.concepts` 已预留。

---

## 5. 硬约束一：Dashboard 可审计 + 日志化

每个数据采集任务**复用现有 `_harness` 机制**，绝不另造一套：

- **定时/触发统一经 `tasks/_harness.run_task(task, fn, config=config)`**，它已经做了三件事：写 `job_reports`（DB，含 task/run_id/status/started_at/finished_at/summary）、`run_log` jsonl 追加、`dispatch` 通知。Phase 1 四个新任务名：`prices`、`breadth`、`macro`、`fundamentals`，全部注册进 `tasks/scheduler.py:REGISTRY`，从而：
  - 自动获得 `job_reports` 审计行（谁触发由 run_id 前缀区分：定时 `prices-…`、手动 `manual-prices-…`、UI 触发经 `runner.submit` 也带 task 名）。
  - 自动出现在 `services/jobs.py` 的 `scheduled_jobs()/job_reports()/job_metrics()` 聚合里，dashboard 工具层已有的「运行记录/运维指标」页**无需改动即可展示**这四个新任务。
  - 可经已有 `POST /api/jobs/{name}/run` 手动触发（`trigger_job` 读 `REGISTRY`）。
- **结构化 summary（审计内容）**：每个 `_core` 返回的 summary 必须包含「触发参数 + 抓取范围 + 结果 + 缺口」：
  - `prices`：`{tickers:[…], range:{from,to}, written:{ticker:rows}, gaps:[…], failures:[…], degraded:bool}`
  - `breadth`：`{breadth_date(s), universe_size, metrics:{…}, missing_constituents:[…], degraded}`
  - `macro`：`{series:[…], range, written:{series:rows}, skipped:[{series,reason}], degraded}`（缺 key 时 `reason:"FRED_API_KEY missing"`，**不含 key 值**）
  - `fundamentals`：`{tickers, quarters:{ticker:count}, latest_surprise:{ticker:val}, failures, degraded}`
- **谁/何时/参数**：`run_id` 含时间戳；定时由 scheduler 写 `last_run_at`；手动 CLI 与 UI 触发用不同 run_id 前缀 → `job_reports` 可回溯触发来源。
- **新增 scheduled_jobs 默认行**：在 011/012 之外用一个轻量 data 迁移补 `prices/breadth/macro/fundamentals` 的默认排程行（`INSERT … ON CONFLICT DO NOTHING`），让它们出现在定时任务管理里（默认可 `enabled=false`，避免未配置 key 时空跑）。

**敏感值**：`FRED_API_KEY` 只从 env 读，**绝不写入 summary / job_reports / 日志 / API 响应**；缺失只记 `reason` 文案。

---

## 6. 硬约束二：自动/定时脚本 必须配套手动回补脚本

DRY 原则：**定时入口与手动 CLI 共享同一核心函数**，仅入口不同（隐式「截至今天」区间 vs 显式历史区间）。每个 `tasks/*.py` 文件已有 `run(config)`（定时）+ `main()`（CLI）双入口的先例（见 `tasks/metrics.py`/`filings.py`），Phase 1 沿用并强化 `main()` 的历史回放能力：

| 任务 | 定时入口 | 手动 CLI（历史回放/回补） |
|------|----------|---------------------------|
| OHLCV | `tasks/prices.py:run` 取「max(bar_date)+1 .. today」增量 | `python -m investment_assistant.tasks.prices --tickers NVDA,MU --from 2020-01-01 --to 2024-12-31`（全量回补区间，含中间空洞） |
| 广度 | `tasks/breadth.py:run` 算 today | `… breadth --from 2023-01-01 --to 2023-12-31` 重算某段历史广度（回测基底） |
| 宏观 | `tasks/macro.py:run` 取近 N 天 | `… macro --from 2018-01-01 --to 2024-12-31 [--series BAMLH0A0HYM2]` 回填历史宏观 |
| 财报 | `tasks/fundamentals.py:run` 取最新季 | `… fundamentals --tickers NVDA --from 2019-01-01 --to 2024-12-31` 回填某段所有季度 |

- 手动 CLI 都接受 `--date`（单日）或 `--from/--to`（区间）；区间上限做合理保护（如 OHLCV 单次 ≤ 某年数，宏观/财报按需），超限给清晰报错。
- 手动入口**同样经 `_harness.run_task`**（run_id 前缀 `manual-`），所以历史回补也产生审计记录 + 结构化 summary，可在 dashboard 看到「这次回补了哪些 ticker / 日期区间 / 写了多少行 / 哪些缺口」。
- 手动脚本用途明确：离线验证、数据回补、**回测/事件研究基底准备**（先把历史 OHLCV/广度/财报灌满，Phase 0 事件研究即可在真实历史上重跑）。

---

## 7. API 层（薄路由，只读 + 触发）

新增 `api/routes/data.py`（注册进 `api/routes/__init__.py`），全部薄封装 `services/*`，复用 `@register` + `ApiResponse` + `first/parse_int/parse_optional_date`：

- `GET /api/data/ohlcv?ticker=NVDA&from=&to=&limit=` → `services.prices.query_ohlcv`
- `GET /api/data/breadth?from=&to=&limit=` → `services.breadth.query_breadth`
- `GET /api/data/macro?series=BAMLH0A0HYM2&from=&to=` → `services.macro.query_macro`
- `GET /api/data/fundamentals?ticker=NVDA` → `services.fundamentals.query_fundamentals`
- `POST /api/data/{kind}/backfill`（kind ∈ prices/breadth/macro/fundamentals）→ 经 `runner.submit` 异步触发手动回补，body 传 `{tickers?, from, to, date?, series?}`，返回 `{run_id, status:"pending"}`，结果经 `/api/runs/{run_id}` 查询 + `job_reports` 落库。

只读端点缺 DB 一律返回 `{rows:[], degraded:true}`，不崩（沿用 `services/jobs.py` 的 `_has_db()` 模式）。手动触发与既有 `POST /api/jobs/{name}/run` 等价，保留 `/api/data/.../backfill` 是为了能传历史区间参数（jobs 触发不带参数）。

---

## 8. 错误处理与优雅降级

- **缺 DB**（无 `INVESTMENT_ASSISTANT_DATABASE_URL`）：采集核心仍能取数并返回 summary（标 `degraded:true, reason:"no database"`），只是不落库；只读 API 返回空 + `degraded`。
- **缺 `FRED_API_KEY`**：`macro` 任务跳过、summary 记 `skipped`，不崩、不回显 key。
- **yfinance 空值/网络抖动**：`fetch_ohlcv`/`fetch_earnings` 重试 + 指数退避；最终失败记入 `failures`，不中断其他 ticker（沿用 `tickers/trend.py:scan_ticker_trends` 的逐 ticker 容错风格）。
- **不静默吞错**：所有 `except` 都结构化记录到 summary/日志，不裸 `except: pass`。
- **空成分池广度**：返回 `universe_size=0` + 指标 None，不抛。

---

## 9. 测试策略（TDD，全离线）

外部依赖全部 mock/注入，离线可跑。每个 Task 至少覆盖：

- **迁移 SQL 断言**（`tests/test_db_sql.py` 追加）：表名、主键、关键列、索引存在（沿用现有断言风格）。
- **data 层**：
  - `fetch_ohlcv`：注入 fake `ticker_factory`，断言含 `Adj Close`、重试在连续失败时被调用（mock sleep）、空 frame 处理。
  - `fetch_fred_series`：注入 fake getter，断言解析、`"."`→None、缺 key 降级、key 不出现在返回里。
  - `fetch_earnings` + `compute_eps_surprise`：估计=0/None 除零保护、字段缺失。
- **db 仓储**：用 `FakeConn/FakeCursor`（见 `tests/test_job_reports_repository.py` 风格）断言 SQL 含 `ON CONFLICT`、具名参数、`dict(zip(keys,row))` 映射。
- **services**：注入 fake fetcher + fake conn_factory，断言 summary 结构、降级分支、逐 ticker 容错。
- **market/service 新鲜度**：构造 mock SPY frame（index 末日 ≠ today），断言 `signal_date` 取 bar 实际日期；多因子门控在给定 breadth/hy 入参时的 red/yellow/green 判定。
- **tasks 入口**：mock `run_task` 或注入，断言定时 `run()` 与手动 `main()` 调同一核心、手动入口正确解析 `--from/--to/--date` 并传区间；run_id 前缀区分。
- **API**：经 router dispatch 断言只读端点降级返回、backfill 返回 `run_id`（沿用 `tests/test_api_contract.py` 风格）。

---

## 10. 关键设计决策与假设（自主模式记录）

> 本节是 brainstorming 在无人逐一确认时，对关键设计点列备选并选定的记录。

**D1 — 价格源是否保留旧 `get_price_history(ticker, days)`？**
- 备选：(a) 直接替换为 DB-first；(b) 新增 `fetch_ohlcv` + DB-first 包装，旧函数内部转调；(c) 全部调用方改签名。
- **选 (b)**：旧函数签名保留（`market/service`、`tickers/trend` 现有调用不破），内部走 DB-first；新增 `fetch_ohlcv` 负责区间+复权+重试。最小破坏面。

**D2 — 缺口检测粒度？**
- 备选：(a) 精确找区间内所有空洞逐段回源；(b) 只补 `max(bar_date)+1..end`，中间空洞靠手动全量回补。
- **选 (b)**：定时增量只追最新；历史空洞用手动 CLI 全量区间回补（upsert 幂等，安全）。一期不实现复杂空洞探测，避免过度工程；缺口在 summary 里如实报告。

**D3 — 2s10s 采原始两序列相减还是 FRED 已发布 `T10Y2Y`？**
- 备选：(a) `DGS10 - DGS2` 自行相减；(b) 直接采 `T10Y2Y`。
- **选 (b) `T10Y2Y`**：FRED 已算好、单序列、无两序列交易日错位问题。`MacroConfig.fred_series = ["BAMLH0A0HYM2", "T10Y2Y"]`。（roadmap 文字写 `DGS10-DGS2`，此处作为实现细化选等价且更稳的 `T10Y2Y`，记为偏离并说明。）

**D4 — 广度成分池？**
- 备选：(a) 抓某指数全成分（S&P500）；(b) watchlist ∪ 固定代表性 ETF/大盘股篮子；(c) 仅 watchlist。
- **选 (b)**：一期用固定常量篮子 `BREADTH_UNIVERSE`（宽基 ETF + 若干流动性大盘股）∪ watchlist，零额外数据成本、可解释（`universe_size` 落库）。抓全成分留待后续，避免本期工程膨胀。

**D5 — 宏观/财报表是否单建？**
- roadmap 建议宏观「可并入 breadth 或单建」。**选单建 `macro_indicators`**（窄长表，series_id 维度，易扩展）；fundamentals 单建 012。

**D6 — 多因子门控向后兼容？**
- `compute_market_signal` 新增 `breadth`/`hy_spread` 可选入参，**默认 None 时退回旧 VIX+SPY 两因子**，保证现有 `tasks/metrics.py` 与测试不破；定时 metrics 任务后续可注入广度/HY（读库最新值）。

**假设：**
- yfinance `earnings_dates` 能提供 EPS 实际/预期（一期足够 PEAD）；营收预期可能缺失 → 允许 None，不阻塞。
- 迁移 012 可能与并行 Phase 0 agent 争用 → 落地时按实际顺延编号，同步改测试路径断言。
- 前端消费（图表）不在本期；本期只到 API + CLI。

---

## 11. 文件清单（新增/修改）

```
migrations/
  009_ohlcv_bars.sql                 # 新
  010_market_breadth.sql             # 新
  011_macro_indicators.sql           # 新
  012_fundamentals.sql               # 新
  013_phase1_scheduled_jobs.sql      # 新（补 prices/breadth/macro/fundamentals 排程行；编号顺延）
investment_assistant/
  config.py                          # 改：MacroConfig.fred_series 精简为 2；MarketConfig +广度/HY 阈值
  data/price.py                      # 改：+fetch_ohlcv（区间+复权+重试）
  data/fred.py                       # 新
  data/fundamentals.py               # 新
  market/service.py                  # 改：signal_date 新鲜度修复 + 多因子门控
  market/breadth.py                  # 新（纯函数）
  services/prices.py                 # 新
  services/breadth.py                # 新
  services/macro.py                  # 新
  services/fundamentals.py           # 新
  db.py                              # 改：+ohlcv/breadth/macro/fundamentals 仓储
  tasks/prices.py                    # 新（run + main 回补）
  tasks/breadth.py                   # 新
  tasks/macro.py                     # 新
  tasks/fundamentals.py              # 新
  tasks/scheduler.py                 # 改：REGISTRY +4 任务
  api/routes/data.py                 # 新
  api/routes/__init__.py             # 改：import data
tests/
  test_data_price_ohlcv.py  test_data_fred.py  test_data_fundamentals.py
  test_market_breadth.py    test_market_signal_freshness.py
  test_services_prices.py   test_services_breadth.py  test_services_macro.py  test_services_fundamentals.py
  test_ohlcv_repository.py  test_breadth_repository.py  test_macro_repository.py  test_fundamentals_repository.py
  test_tasks_prices.py … (各 task 入口)   test_db_sql.py（追加 009–013 断言）
  test_api_contract.py（追加 /api/data/* 断言）
```

---

## 12. 完成标志（验收）

- 四张表迁移幂等可重跑；`signal_date` 新鲜度 bug 修复且有回归测试。
- 四类采集任务定时 + 手动 CLI 双入口，共享核心函数，全部经 `_harness` 审计（job_reports + run_log + 结构化 summary）。
- 缺 DB / 缺 FRED key 优雅降级、不崩、不回显敏感值。
- `fundamentals` 有真实 EPS surprise，Phase 0 `eps_beat/miss` 可从占位升级、PEAD 事件研究可在历史回补数据上重跑。
- 全部新增逻辑离线单测通过。
