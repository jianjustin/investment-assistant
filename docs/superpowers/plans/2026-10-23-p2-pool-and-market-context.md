---
title: P2 观察池扩展与市场环境实施计划
tags: [美股, 观察池, 区制, FRED, 历史检查, 实施计划]
created: 2026-10-23
---

# P2 观察池扩展与市场环境实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 工作台标的从配置里的 ≤10 只扩到数据库观察名单的 ≤100 只并分为核心池与扩展池；每份计划带区制、行业强弱、利差背景与下次财报日；新增新规则上线前手动运行的历史检查。

**Architecture:** 新纯函数模块 `pool`（分层解析与变更）、`regime`（广度、区制、行业强弱、利差视图）、`backcheck`（历史重放与统计），采集模块 `macro`（FRED）。SQL 仍集中在 `workbench/repository.py`，事务边界仍在 `workbench/service.py`。迁移 018 只新增四张表；计划的环境信息写进已有的 `trade_plans.inputs`。

**Tech Stack:** Python 3.11、FastAPI、psycopg 3、PostgreSQL、yfinance、requests（FRED 官方 API）、pytest；Svelte 5、vitest。

**Spec:** [2026-10-23-p2-pool-and-market-context-design.md](../specs/2026-10-23-p2-pool-and-market-context-design.md)。设计决定以 spec 为准，本文只定文件、接口、顺序与测试。

## Global Constraints

- 只追加不覆盖：四张新表不 UPDATE 业务字段；迁移 018 不含 `UPDATE`、`DELETE`、对旧表的 `ALTER` 或回填。
- 池常量：`MAX_POOL = 100`、`MAX_CORE = 15`、`CORE_TAG = 'core'`、`SECTOR_PREFIX = 'sector:'`、`SECTOR_ETFS = ('SMH', 'XLK', 'QQQ')`；标签比较大小写不敏感，存储时 ETF 统一大写。
- 区制常量（`REGIME_VERSION = 'regime-1'`）：`MIN_ELIGIBLE_200 = 20`；进攻 `pct_200 >= 0.60 and pct_50 >= 0.50`；防守 `pct_200 < 0.40 and pct_50 < 0.30`；MA 合格样本 50 / 200 根，新高新低 252 根；`RS_WINDOWS = (20, 60)`。中文：进攻 / 中性 / 防守 / 样本不足。
- FRED：`MACRO_SERIES = ('BAMLH0A0HYM2', 'T10Y2Y')`、`MACRO_LOOKBACK_DAYS = 120`、`MACRO_CHANGE_OBS = 20`、接口 `https://api.stlouisfed.org/fred/series/observations`（`file_type=json`）；密钥只取环境变量 `FRED_API_KEY`，任何写入报告或日志的文本中出现密钥都替换为 `***`。
- 版本号：`CONTEXT_VERSION = 'context-1'`、周度 `CALC_VERSION = 'review-3'`、`BACKCHECK_VERSION = 'backcheck-1'`；`PLAN_VERSION` 仍为 `'plan-1'`，`SHADOW_VERSION` 仍为 `'plan-shadow-1'`。
- 新提示名：`regime_risk_off`、`regime_unavailable`、`sector_weak`；运行报告新错误名：`core_empty`、`batch_over_budget`。
- 批处理预算：`BATCH_BUDGET_S = 1800`。
- 历史检查常量：`WARMUP = rules.MIN_BARS`（200）、`MATURE_SESSIONS = 20`、`SWEEP_SESSIONS = 5`、`FREQ_LIMIT = 5.0`（每 100 个股票日）、`SWEEP_SHARE = 0.5`、`MIN_FILLED = 10`、`CLUSTER_MIN = 3`、`BUY_RULES = ('trend_reclaim', 'volume_breakout', 'earnings_gap_up')`。
- 价格口径：广度、行业强弱用 `adj_close`；计划、影子沿用 P1（`open/high/low/close`）。
- 测试不访问网络、不发真实 Discord：yfinance、SEC、FRED、Codex、Discord 全部注入替身。
- 每条 Discord 消息仍 ≤ 10 个 embed、≤ 6000 字符，字段值 ≤ 1024 字符；证据文案仍为「证据：未验证」。

## Review Focus

1. **FRED 异常文本带出密钥**（`requests` 的异常和 HTTP 错误会包含带 `api_key=` 的完整 URL）：运行报告、`errors`、推送异常段只能出现 `***`。测试放在 Task 3。
2. **一周之内改了分层**（周一扩展、周三标为核心）：周二的计划和触发在周度复盘里仍归扩展池；「今日」也按信号日分层判断。测试放在 Task 2（`pool_entry_at`）与 Task 8。
3. **持仓股同时在扩展池**：它的单元进主列表、生成 Codex 解读、计划会推送；只是不改它的分层记录。测试放在 Task 5 与 Task 7。
4. **上市不久或数据缺失的股票**（不足 50 / 200 / 252 根 K 线、当日无 K 线）：只从对应的合格样本中剔除，不报错；全部不合格时为「样本不足」。测试放在 Task 4。
5. **标签写法不规范**（`Core`、`CORE`、`sector:smh`、两个 `sector:` 标签、`sector:XLE`）：前三种按规则识别，后两种写入时返回 400 且不改观察名单。测试放在 Task 2。

---

## 0. 执行边界

- 在 `main` 上串行实施，每个任务结束提交一次，只 `git add` 本任务列出的路径。
- 每个任务先写失败测试，再实现，再跑本任务测试与相关回归。
- 数据库测试只在显式的 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 下用一次性 schema（`tests/conftest.py` 的 `workbench_db`）运行；未提供时跳过，并在任务报告里如实记为「SQL 未验证」。不对真实库执行迁移 018。
- 不启动、重启或停止本地服务与调度器；前端不运行默认 `npm run build`，构建检查输出到 `.local/us-workbench/build-review/`。
- 不推送 git、不部署、不发真实 Discord、不调用真实 FRED、不改真实观察名单。真实迁移、标记核心池、配置密钥另行授权。

后端测试命令：

```bash
env -u INVESTMENT_ASSISTANT_DATABASE_URL -u FRED_API_KEY SCHEDULER_ENABLED=0 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest <测试文件> -q
```

前端测试命令（在 `web/` 目录）：

```bash
npx vitest run <测试文件>
```

## 1. 文件结构

```
migrations/018_pool_and_market_context.sql   新表 pool_tiers / macro_observations / market_regimes / rule_backchecks
investment_assistant/workbench/
  pool.py         分层解析、上限校验、变更计算（纯函数）
  macro.py        FRED 采集与规范化、密钥脱敏
  regime.py       广度、区制标签、行业强弱、利差视图、快照（纯函数）
  backcheck.py    历史重放、统计与标记（纯函数）+ 命令行入口
  plans.py        环境信息与新提示
  review.py       review-3 分池视角
  digest.py       市场环境、扩展池计数、按数据源分组的异常
  repository.py   新表 SQL；missing_tables 纳入新表
  service.py      读池与同步分层、ETF 与 FRED 采集、区制快照、解读分流、运行报告、today 拆分、历史检查
investment_assistant/services/watchlist.py    写入时校验池上限与标签
investment_assistant/notify/templates.py      workbench_digest 新字段
investment_assistant/tasks/workbench.py       改为读数据库观察池
investment_assistant/api/routes/workbench.py  /backchecks
web/src/lib/pool-tags.ts                      标签与核心/行业的互转
web/src/lib/components/Watchlist.svelte, web/src/lib/workbench.ts,
web/src/routes/Today.svelte, web/src/routes/Review.svelte
docs/us-workbench.md, docs/roadmap/v2-progress.md
tests/test_workbench_{pool,macro,regime,backcheck}.py
```

市场环境快照、环境信息在代码中统一用 dict 表示，键与 spec §3.3、§6 一致；广度占比与 RS 为 `float`，FRED 数值为 `Decimal`。

## 2. 任务

### Task 1：迁移 018 与 schema 测试

**Files:**
- Create: `migrations/018_pool_and_market_context.sql`
- Modify: `tests/conftest.py`（`WORKBENCH_MIGRATIONS` 头部加 `'002_watchlist_items.sql'`，尾部加 `'018_pool_and_market_context.sql'`）、`tests/test_workbench_schema.py`、`tests/test_workbench_postgres.py`、`investment_assistant/workbench/repository.py`（`WORKBENCH_TABLES` 加四张新表与 `watchlist_items`）

**Interfaces:**
- Produces: spec §3 的四张表；`repository.missing_tables(conn)` 缺任一新表时返回其表名；`service._tx` 的提示文案改为「需执行迁移 016–018」。

- [ ] **Step 1: 失败测试（离线）**：`test_018_is_additive` 读取 SQL，断言四张表都有 `CREATE TABLE IF NOT EXISTS`、`market_regimes` 有 `UNIQUE (session, calc_version)`；断言不含 `UPDATE `、`DELETE `、`ALTER TABLE`。
- [ ] **Step 2: 失败测试（SQL）**：`test_pool_tier_check`（`tier = 'x'` 报 CheckViolation）；`test_regime_unique_per_session_version`；`test_regime_label_check`；`test_macro_value_required`；`test_missing_tables_lists_018`（删 `market_regimes` 后 `missing_tables` 含它）。
- [ ] **Step 3: 运行，确认失败**：`... pytest tests/test_workbench_schema.py tests/test_workbench_postgres.py -q`。
- [ ] **Step 4: 写 SQL**：`pool_tiers(id BIGSERIAL, ticker TEXT NOT NULL, tier TEXT NOT NULL CHECK IN ('core','extended','removed'), sector_etf TEXT, effective_session DATE NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT now())`，索引 `(ticker, effective_session DESC, recorded_at DESC)`；`macro_observations(id BIGSERIAL, series_id TEXT NOT NULL, obs_date DATE NOT NULL, value NUMERIC(18,6) NOT NULL, fetched_at TIMESTAMPTZ NOT NULL, created_at …)`，索引 `(series_id, obs_date DESC, fetched_at DESC)`；`market_regimes(id UUID DEFAULT gen_random_uuid(), session DATE, calc_version TEXT, label TEXT CHECK IN ('risk_on','neutral','risk_off','insufficient'), breadth/sectors/macro/inputs JSONB NOT NULL, created_at …, UNIQUE (session, calc_version))`；`rule_backchecks(id UUID …, calc_version TEXT NOT NULL, params JSONB NOT NULL, stats JSONB NOT NULL, created_at …)`。文件头注释写明「Additive only」与 spec 出处，风格同 017。
- [ ] **Step 5: 更新 `WORKBENCH_TABLES` 与 `_tx` 文案**，运行 Step 3 命令确认通过（无测试库时 SQL 用例为 skipped，报告注明）。
- [ ] **Step 6: 提交** `feat: add pool tier, macro and regime schema`。

### Task 2：观察池分层

**Files:**
- Create: `investment_assistant/workbench/pool.py`
- Modify: `repository.py`、`investment_assistant/services/watchlist.py`
- Test: `tests/test_workbench_pool.py`、`tests/test_workbench_postgres.py`、`tests/test_watchlist_api.py`

**Interfaces:**
- Consumes: `ashare.domain.us_only`；`db.list_watchlist_items(conn)` 的行（`ticker, status, tags`）。
- Produces:
  - 常量见 Global Constraints。
  - `@dataclass(frozen=True) class Pool`：`core: tuple[str, ...]`、`extended: tuple[str, ...]`、`sectors: dict[str, str]`；属性 `tickers -> tuple[str, ...]`（core 在前，各自按字母序）；方法 `tier(ticker) -> 'core' | 'extended' | None`；类方法 `Pool.all_core(tickers: list[str]) -> Pool`（去重、大写、空则 `ValueError('股票池为空')`、超 `MAX_POOL` 则 `ValueError`，不检查核心上限——测试与手动覆盖用）。
  - `parse_tags(tags: list[str] | None) -> tuple[bool, str | None]`：返回 (是否核心, 行业 ETF)；多个 `sector:` 或 ETF 不在 `SECTOR_ETFS` → `ValueError`。
  - `from_watchlist(rows: list[dict]) -> Pool`：只取 `status == 'active'` 的美股；空池、池超 100、核心超 15 → `ValueError`，文案写明数量与上限。
  - `tier_changes(pool: Pool, latest: dict[str, dict]) -> list[dict]`：`[{'ticker', 'tier', 'sector_etf'}]`，仅包含 `(tier, sector_etf)` 与 `latest` 不同的股票，以及 `latest` 中非 `removed`、但已不在池中的股票（写 `removed`、`sector_etf None`）。
  - `repository.pool_latest(conn) -> dict[str, dict]`：每只股票最新一行 `{'tier', 'sector_etf'}`。
  - `repository.insert_pool_tiers(conn, rows: list[dict], *, session: date, now: datetime) -> int`。
  - `repository.pool_entry_at(conn, ticker: str, day: date, *, cutoff_at: datetime) -> dict | None`：`effective_session <= day` 且 `recorded_at <= cutoff_at` 的最新一行，`removed` 也原样返回。
  - `services.watchlist.add_watchlist_item`：写入前把「当前全部行中替换/新增本条后的结果」交给 `pool.from_watchlist` 校验（只对写入后为 `active` 的美股生效），`ValueError` 冒泡为 400。

- [ ] **Step 1: 失败测试**：
  - `test_core_tag_case_insensitive`（`Core`、`CORE` → 核心；Review Focus 5）；`test_sector_tag_normalized`（`sector:smh` → `'SMH'`）；`test_two_sector_tags_rejected`；`test_unknown_sector_rejected`（`sector:XLE`）。
  - `test_from_watchlist_skips_paused_archived_and_cn`；`test_pool_limit_100`（100 只通过、101 只 `ValueError`）；`test_core_limit_15`；`test_empty_pool_raises`；`test_core_empty_is_allowed`。
  - `test_tier_changes_only_on_change`；`test_sector_change_is_a_change`；`test_removed_written_once`（`latest` 已是 `removed` 时不再写）。
  - SQL：`test_pool_entry_at_respects_effective_session_and_cutoff`（周一 extended、周三 core：周二查得 extended，周三查得 core；`recorded_at` 晚于 cutoff 的行不可见；Review Focus 2）。
  - API：`test_watchlist_rejects_16th_core`、`test_watchlist_rejects_bad_sector_tag`（均 400，随后 GET 列表不变）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_services_watchlist.py tests/test_watchlist_api.py tests/test_watchlist_postgres.py`。
- [ ] **Step 5: 提交** `feat: tier the workbench pool from the watchlist`。

### Task 3：FRED 采集

**Files:**
- Create: `investment_assistant/workbench/macro.py`
- Modify: `repository.py`
- Test: `tests/test_workbench_macro.py`、`tests/test_workbench_postgres.py`

**Interfaces:**
- Consumes: `data.http.get_json`。
- Produces:
  - 常量见 Global Constraints；`class NotConfigured(RuntimeError)`。
  - `redact(text: str, secret: str | None) -> str`：`secret` 非空时把所有出现替换为 `***`。
  - `fetch_series(series_id: str, *, start: date, end: date, api_key: str | None, fetcher=None) -> list[dict]`：`api_key` 为空 → `NotConfigured`，不调用 fetcher；默认 fetcher 调 `get_json(FRED_URL, params={'series_id', 'api_key', 'file_type': 'json', 'observation_start', 'observation_end'})`；返回 `[{'obs_date': date, 'value': Decimal}]`（旧到新，跳过值为 `'.'` 的观测）；请求失败或响应无 `observations` → `RuntimeError(redact(原因, api_key))`。
  - `repository.store_macro(conn, series_id: str, rows: list[dict], *, now: datetime) -> dict`：`{'inserted': int, 'unchanged': int}`；同日期数值不同即追加。
  - `repository.read_macro(conn, series_id: str, *, end_date: date, cutoff_at: datetime, limit: int = 60) -> list[dict]`：每个 `obs_date <= end_date` 取 `fetched_at <= cutoff_at` 的最新一行，旧到新，最多 `limit` 个日期。

- [ ] **Step 1: 失败测试**：`test_parse_skips_dot_values`；`test_not_configured_makes_no_request`；`test_request_params`（替身 fetcher 收到 `series_id`、`file_type='json'`、起止日期）；`test_error_text_redacts_key`（替身抛出含 `api_key=SECRET123` 的异常 → 异常文本含 `***` 不含 `SECRET123`；Review Focus 1）；`test_missing_observations_raises`；SQL：`test_store_macro_revision_appends`、`test_read_macro_as_of_cutoff`（修订前的 cutoff 读到旧值）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: collect FRED credit and curve spreads`。

### Task 4：广度、区制与行业强弱

**Files:**
- Create: `investment_assistant/workbench/regime.py`
- Modify: `repository.py`
- Test: `tests/test_workbench_regime.py`、`tests/test_workbench_postgres.py`

**Interfaces:**
- Consumes: `read_bars` 行（`price_date`、`adj_close`）；`read_macro` 行。
- Produces:
  - 常量见 Global Constraints；`LABEL_TEXT = {'risk_on': '进攻', 'neutral': '中性', 'risk_off': '防守', 'insufficient': '样本不足'}`。
  - `breadth(bars_by_ticker: dict[str, list[dict]], session: date) -> dict`：键 `tickers`（当日有 K 线的数量）、`eligible_50, above_50, pct_50, eligible_200, above_200, pct_200, eligible_52w, new_highs, new_lows`；合格样本为 0 时对应 `pct_*` 为 `None`。只用 `price_date <= session` 的 K 线，当日无 K 线的股票全部剔除。
  - `label(b: dict) -> str`：按 spec §5.2 的顺序判断。
  - `sector_strength(etf_bars: list[dict], spy_bars: list[dict], session: date) -> dict | None`：`{'rs20', 'rs60', 'state': 'strong'|'weak'|'mixed'}`；任一窗口的 K 线不足（ETF 或 SPY 少于 61 根到 session 为止）→ `None`。
  - `macro_view(rows: list[dict]) -> dict | None`：`{'value', 'obs_date', 'change', 'change_from'}`；空 → `None`；不足 21 个观测时 `change`、`change_from` 为 `None`。
  - `snapshot(*, session: date, pool_bars: dict[str, list[dict]], etf_bars: dict[str, list[dict]], spy_bars: list[dict], macro_rows: dict[str, list[dict]]) -> dict`：`{'session', 'calc_version', 'label', 'breadth', 'sectors': {etf: dict|None}, 'macro': {series: dict|None}, 'inputs': {'tickers': sorted, 'etfs', 'series'}}`。
  - `repository.store_regime(conn, snap: dict) -> dict`：`{'status': 'inserted'|'existing'|'conflict', 'record'}`，比较 `label/breadth/sectors/macro` 的规范化 JSON。
  - `repository.regime_for(conn, session: date, *, cutoff_at: datetime) -> dict | None`：该交易日 `regime-1` 的快照（`created_at <= cutoff_at`）。
  - `repository.latest_regime(conn, *, on_or_before: date, cutoff_at: datetime) -> dict | None`。

- [ ] **Step 1: 失败测试**：
  - `test_breadth_eligibility_by_history`（一只 120 根：计入 50 不计入 200、52w；Review Focus 4）；`test_missing_session_bar_excluded`；`test_new_high_and_low`；`test_all_ineligible_is_insufficient`（Review Focus 4）。
  - `test_label_boundaries`：`(pct_200, pct_50)` = `(0.60, 0.50)` → `risk_on`；`(0.5999, 0.50)` → `neutral`；`(0.39, 0.29)` → `risk_off`；`(0.40, 0.29)` → `neutral`；`eligible_200 = 19` → `insufficient`。
  - `test_sector_states`（两窗口均负 → `weak`，均正 → `strong`，一正一负 → `mixed`）；`test_sector_short_history_none`。
  - `test_macro_change_against_20_obs_back`；`test_macro_short_series_no_change`。
  - SQL：`test_store_regime_existing_then_conflict`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**：MA 用 `adj_close` 的简单平均；新高判定 `adj_close >= max(前 251 根)`，新低对称；RS 收益 = `adj_close[t] / adj_close[t-n] - 1`。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: compute pool breadth, regime and sector strength`。

### Task 5：批处理接入观察池与市场环境

**Files:**
- Modify: `service.py`、`investment_assistant/tasks/workbench.py`
- Test: `tests/test_workbench_service.py`、`tests/test_workbench_postgres.py`、`tests/test_tasks_runner.py`（或现有 workbench 任务测试所在文件）

**Interfaces:**
- Consumes: Task 2–4 全部接口；`db.list_watchlist_items`。
- Produces:
  - `run_batch(*, now: datetime, tickers: list[str] | None = None, pool: Pool | None = None, deps: Deps | None = None, skip_non_trading: bool = False, run_id: str | None = None) -> dict`：`pool` 优先；只给 `tickers` 时用 `Pool.all_core(tickers)`（保持现有测试与手动覆盖的行为）；都不给时在事务内读 `list_watchlist_items` 并 `from_watchlist`。删除 `MAX_TICKERS` 与 `_validate_tickers` 的 10 只上限。
  - `Deps` 新增 `macro_fetcher: Callable | None = None`、`clock: Callable[[], float] | None = None`（默认 `time.monotonic`）。
  - `ETF_TICKERS = pool.SECTOR_ETFS`；SPY 与 ETF 同一循环只采日线。
  - `_sync_pool(conn, pool: Pool, session: date, now: datetime) -> list[dict]`。
  - `_unit_is_extended(conn, ticker: str, signal_date: date, *, held: bool, now: datetime) -> bool`：`pool_entry_at` 为 `extended` 且 `held` 为假。
  - `summary` 新增键（spec §7.2）：`pool: {'core', 'extended', 'holdings', 'changes'}`、`etfs: {etf: 'inserted N'|'error: …'}`、`macro: {series: {'inserted', 'unchanged'}|'not_configured'|'error: …'}`、`regime: {'status', 'label'}|'error: …'`、`sources: {'bars', 'news', 'earnings', 'sec', 'etf_bars', 'fred', 'regime': list[str]}`（列出失败的标的或序列；`sec`、`regime` 失败时为 `['all']`）、`timings: {'collect', 'regime', 'rules', 'total'}`（秒，保留一位小数）。核心池为空时 `errors` 含 `core_empty`；`total > BATCH_BUDGET_S` 时 `errors` 含 `batch_over_budget: <秒>`。
  - 区制快照在采集之后、规则之前：`regime.snapshot` 的 `pool_bars` 只含池内股票（不含池外持仓），每只 `read_bars(limit=300)`；`store_regime` 冲突加入 `summary['conflicts']`（`rule_id: 'market_regime'`）。
  - 解读只对 `_unit_is_extended` 为假的单元生成。
  - `tasks/workbench.run` 改为 `service.run_batch(now=moment, deps=deps, skip_non_trading=…)`，不再读配置 `watchlist`。

- [ ] **Step 1: 失败测试**：
  - `test_batch_reads_pool_from_watchlist`（SQL：插入 2 只 `core`、3 只普通 → `summary['pool']` 计数正确，`pool_tiers` 5 行）。
  - `test_rerun_appends_no_tier_changes`；`test_pool_over_limit_fails_batch`（101 只 → `ValueError`，`tickers` 无采集记录）；`test_core_empty_runs_and_reports`。
  - `test_etf_bars_collected_and_isolated`（替身对 `XLK` 抛错 → `summary['etfs']['XLK']` 以 `error:` 开头、`sources['etf_bars'] == ['XLK']`，其余照常）。
  - `test_fred_not_configured`（无 `FRED_API_KEY` → `macro` 两个序列均为 `not_configured`，`sources['fred'] == []`，不调用 `macro_fetcher`）；`test_fred_error_in_sources`（设环境变量、替身抛错 → `sources['fred']` 列出序列，错误文本不含密钥）。
  - `test_regime_snapshot_written`（25 只合成池 → `market_regimes` 一行，`summary['regime']['label']` 非 `insufficient`）。
  - `test_extended_unit_has_plan_but_no_brief`（替身 brief_client 记录调用：扩展池触发买入 → 有 `rule` 计划、未调用解读）；`test_held_extended_ticker_gets_brief`（Review Focus 3）。
  - `test_sources_distinguish_failures`（日线、资讯、财报日期各坏一只不同股票 → 三个列表分别只含对应股票）。
  - `test_100_tickers_complete_with_timings`（100 只合成数据、全部替身 → `len(summary['tickers']) == 100`，`timings` 四个键均为数值）。
  - `test_over_budget_recorded`（替身 `clock` 每次调用前进 1000 秒 → `errors` 含 `batch_over_budget`）。
  - 现有 `test_too_many_tickers_is_an_error_not_a_truncation` 改为 101 只。
  - `test_scheduled_task_uses_db_pool`（替身 `service.run_batch` 断言未收到 `tickers`）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**：分层同步与读池在一个事务内完成；采集仍串行，每个数据源单独 `try`，`Unavailable` 照旧上抛。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_service.py tests/test_workbench_scenarios.py tests/test_scheduler.py`。
- [ ] **Step 5: 提交** `feat: run the workbench batch over the tiered pool with market context`。

### Task 6：计划的环境信息

**Files:**
- Modify: `plans.py`、`service.py`、`ledger.py`
- Test: `tests/test_workbench_plans.py`、`tests/test_workbench_service.py`、`tests/test_workbench_ledger.py`

**Interfaces:**
- Consumes: `repository.pool_entry_at`（Task 2）、`repository.regime_for`（Task 4）、`repository.latest_earnings`（P1）。
- Produces:
  - `plans.CONTEXT_VERSION = 'context-1'`。
  - `plans.context_flags(context: dict) -> list[str]`：`regime is None` → `regime_unavailable`；`regime.label == 'risk_off'` → `regime_risk_off`；`sector` 非空且 `state == 'weak'` → `sector_weak`。
  - `build_rule_plan(..., context: dict | None = None)`、`build_own_plan(..., context: dict | None = None)`：`context` 非空时写入 `inputs['context']` 并把 `context_flags` 追加到 `warnings`；为空时输出与 P1 完全相同。
  - `service.plan_context(conn, ticker: str, session: date, *, now: datetime) -> dict`：`{'context_version', 'pool_tier': 'core'|'extended'|'unknown', 'regime': {'id', 'label'}|None, 'sector': {'etf', 'rs20', 'rs60', 'state'}|None, 'next_earnings': date|None}`；`sector` 取 `pool_entry_at` 的 `sector_etf` 在当日快照 `sectors` 中的值，快照中为 `None` 时 `sector` 为 `{'etf', 'rs20': None, 'rs60': None, 'state': None}`；`removed` 或无记录的分层写 `unknown`。
  - `_generate_rule_plan` 与 `ledger` 的自定计划路径都传入 `plan_context(...)`。

- [ ] **Step 1: 失败测试**：`test_context_none_keeps_p1_output`（不传 context 时与现有快照逐键相等）；`test_context_frozen_in_inputs`；`test_risk_off_warns`；`test_regime_missing_warns_unavailable`；`test_weak_sector_warns`；`test_context_does_not_change_levels_or_sizing`；`test_own_plan_gets_context`（ledger，SQL）；`test_rerun_with_context_returns_existing_p1_plan`（SQL：先用无 context 的 P1 方式写入计划，再跑带 context 的批处理 → `existing`，不冲突）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_plans.py tests/test_workbench_ledger.py tests/test_workbench_service.py`。
- [ ] **Step 5: 提交** `feat: freeze market context into trade plans`。

### Task 7：今日与推送

**Files:**
- Modify: `service.py`、`digest.py`、`notify/templates.py`
- Test: `tests/test_workbench_service.py`、`tests/test_workbench_digest.py`、`tests/test_workbench_api.py`

**Interfaces:**
- Consumes: `_unit_is_extended`（Task 5）、`repository.latest_regime`（Task 4）、计划 `inputs.context`（Task 6）。
- Produces:
  - `today()` 返回 `{'session', 'units', 'extended_units', 'holdings', 'market'}`；`extended_units` 每项 `{'ticker', 'signal_date', 'proposed_action', 'rule_ids', 'plan'}`；`market` 为 `latest_regime(on_or_before=session)` 或 `None`。
  - `digest.build(..., extended_plans: int = 0, market: dict | None = None)`：每份计划新增 `regime_label`、`next_earnings`、`sector`（取自 `inputs.context`，没有时为 `None`）；`overview` 新增 `extended_plans`、`core_empty: bool`、`market`；新增 `errors_by_source: dict[str, list[str]]`（键与 `summary['sources']` 一致，另加 `budget`）。
  - `SOURCE_NAMES = {'bars': '日线', 'news': '资讯', 'earnings': '财报日期', 'sec': 'SEC', 'etf_bars': 'ETF 日线', 'fred': 'FRED', 'regime': '区制', 'budget': '耗时'}`（放在 `templates.py`）。
  - `templates.workbench_digest`：概览增加「市场环境」字段：`区制 {中文} · 站上 MA50 {pct}% · MA200 {pct}% · 新高 {n} / 新低 {n}`、`SMH {rs20:+.1%} {强/弱/分化/数据不足} …`、`HY OAS {value}（20 期 {change:+}）· 2s10s {value}（…）`，FRED 未配置时写「FRED 未配置」，`market` 为空写「市场环境未生成」；扩展池计数 > 0 时写「扩展池新计划 N 份（不推送）」；`core_empty` 时写「核心池为空，只推送持仓」。计划字段增加 `区制 {中文} · 下次财报 {日期|未知} · 行业 {ETF 强弱|未映射}`。异常段每个有失败的数据源一个字段。
  - `service.push` 传入 `extended_plans`（`extended_units` 中有计划的数量）与 `market`。

- [ ] **Step 1: 失败测试**：`test_today_splits_extended_units`（SQL）；`test_held_extended_stays_in_main_list`（Review Focus 3）；`test_today_market_block`；`test_digest_market_field_text`；`test_digest_fred_not_configured_text`；`test_plan_line_has_regime_earnings_sector`（断言含「区制 防守」「下次财报 2026-11-20」「行业 SMH 弱」，无数据时含「下次财报 未知」「行业 未映射」）；`test_extended_count_in_overview`；`test_core_empty_overview_text`；`test_errors_grouped_by_source`；`test_digest_limits_with_100_ticker_summary`（100 只的 `sources` 全部失败 → 每条消息 ≤ 6000 字符、字段 ≤ 1024）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**；待决定数只算 `units`。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_digest.py tests/test_notifier.py tests/test_workbench_api.py`。
- [ ] **Step 5: 提交** `feat: show market context and pool split in today and the daily push`。

### Task 8：周度复盘 review-3

**Files:**
- Modify: `review.py`、`service.py`
- Test: `tests/test_workbench_review.py`、`tests/test_workbench_postgres.py`

**Interfaces:**
- Consumes: `plan_shadow.simulate`、`repository.pool_entry_at`、`repository.unit_candidates`。
- Produces:
  - `review.CALC_VERSION = 'review-3'`。
  - `review.pool_of(context_tier: str | None, entry: dict | None) -> 'core' | 'extended'`：`context_tier` 优先；为空时看 `entry['tier']`；只有 `extended` 归扩展池。
  - `review.pool_summary(triggers: list[dict], plan_outcomes: list[dict]) -> dict`：`triggers` 为 `[{'pool', 'rule_id'}]`（当周买入候选），`plan_outcomes` 为 `[{'pool', 'rule_ids', 'outcome'}]`（当周 `rule` 计划）；返回 `{pool: {rule_id: {'triggers', 'plans', 'expired', 'filled', 'r_mean', 'r_median'}}}`，`filled` 为 `outcome.status in ('open', 'closed')`；一份计划对其每个买入规则各计一次。
  - `weekly_stats(..., by_pool: dict | None = None)`：`stats['by_pool'] = by_pool or {}`。
  - `generate_weekly` 计算 `by_pool`：触发取当周 `signal_candidates` 中 `action = 'buy'` 的候选。

- [ ] **Step 1: 失败测试**：`test_pool_summary_splits_by_pool_and_rule`；`test_pool_summary_counts_expired_and_filled`；`test_pool_of_prefers_context`；`test_legacy_plan_without_context_counts_core`；`test_weekly_review3_has_by_pool`（SQL）；`test_tier_change_midweek_uses_signal_date_tier`（SQL，Review Focus 2）；`test_old_review2_snapshot_unchanged`（SQL）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_review.py`。
- [ ] **Step 5: 提交** `feat: split weekly review by pool`。

### Task 9：历史检查

**Files:**
- Create: `investment_assistant/workbench/backcheck.py`
- Modify: `repository.py`、`service.py`、`api/routes/workbench.py`
- Test: `tests/test_workbench_backcheck.py`、`tests/test_workbench_api.py`、`tests/test_workbench_postgres.py`

**Interfaces:**
- Consumes: `rules.evaluate`、`rules.MIN_BARS`；`plans.atr14 / rule_levels / validity / levels_ordered`；`plan_shadow.simulate`；`data.calendar.add_trading_days`。
- Produces:
  - 常量见 Global Constraints。
  - `replay(ticker: str, bars: list[dict], filings: list[dict], spy_bars: list[dict], *, splits: list, evaluate=rules.evaluate) -> dict`：`{'ticker', 'warmup_end': date|None, 'eval_start': date|None, 'eval_end': date|None, 'eval_sessions': int, 'skipped_atr': int, 'signals': [{'rule_id', 'signal_date', 'mature': bool, 'outcome': dict|None}]}`。评估区为下标 `>= WARMUP` 的 K 线；每个评估日以 `bars[:i+1]` 调 `evaluate(ticker, d, bars[:i+1], filings, None)`，只收 `BUY_RULES` 中的候选；计划 dict 含 `simulate` 需要的键（`ticker, signal_date, entry_low, entry_high, stop, target1, atr, trail_atr_multiple, valid_from, valid_until`）；`mature = add_trading_days(valid_until, MATURE_SESSIONS) <= 最后一根 K 线日期`，未成熟时 `outcome` 为 `None`。
  - `summarize(replays: list[dict]) -> dict`：`{'rules': {rule_id: row}, 'all': row, 'tickers': [{'ticker', 'warmup_end', 'eval_start', 'eval_end', 'eval_sessions'}], 'note': '描述性检查，不调参，不代表规则有效。'}`；`row = {'triggers', 'ticker_sessions', 'per_100', 'max_per_ticker', 'cluster_days', 'filled', 'expired', 'stopped_within_5', 'stopped_within_5_share', 't1_share', 'r': {'count', 'mean', 'median', 'p25', 'p75'}, 'flags': [...]}`。「5 日内止损」= 第一条 leg 的 `reason == 'stop'` 且 `exit_date <= add_trading_days(fill_date, SWEEP_SESSIONS)`；`t1_share` 分母为成熟且成交的计划；`cluster_days` 为同一 `signal_date` 有 ≥ `CLUSTER_MIN` 只股票触发的日数。标记：`too_frequent`（`per_100 > FREQ_LIMIT`）、`stops_swept`（`filled >= MIN_FILLED` 且 share ≥ `SWEEP_SHARE`）、`insufficient`（`filled < MIN_FILLED`）。
  - `repository.insert_backcheck(conn, calc_version: str, params: dict, stats: dict) -> dict`、`repository.list_backchecks(conn, limit: int) -> list[dict]`。
  - `service.run_backcheck(*, now: datetime, tickers: list[str] | None = None) -> dict`：默认 `from_watchlist(list_watchlist_items).tickers`；每只读 `read_bars(limit=2000)`、`read_filings(since=第一根日期)`、`split_events`；`params = {'tickers', 'rule_version': rules.RULE_VERSION, 'plan_version', 'shadow_version', 'bars': 'stored current revisions'}`；写库并返回记录。不调用任何采集函数。
  - `service.list_backchecks(limit: int = 10) -> list[dict]`。
  - 路由：`GET /api/workbench/backchecks`、`POST /api/workbench/backchecks`（body 可含 `tickers`）。
  - 命令行：`python -m investment_assistant.workbench.backcheck [--tickers A,B]`，以 `datetime.now(UTC)` 调 `run_backcheck`，打印记录的 `id` 与 `stats['all']` 的 JSON。

- [ ] **Step 1: 失败测试**（`evaluate` 用替身控制触发日）：`test_no_signal_inside_warmup`（替身在第 150、210 根都触发 → 只有 210）；`test_eval_window_reported`；`test_immature_counted_not_scored`；`test_atr_unavailable_skipped`（平盘 K 线 → `skipped_atr` 计数，无信号）；`test_per_100_and_too_frequent`；`test_stops_swept_needs_min_filled`（9 笔全部 5 日内止损 → 只有 `insufficient`；10 笔 → `stops_swept`）；`test_cluster_days`；`test_r_quartiles`；SQL/API：`test_backcheck_route_runs_and_lists`、`test_backcheck_makes_no_network_calls`（monkeypatch `bars.fetch_history`、`news.fetch_yfinance`、`earnings.fetch_next`、`macro.fetch_series` 为抛错，运行仍成功）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**：分位数用 `statistics.quantiles(values, n=4, method='inclusive')`，少于 2 个值时 `p25`、`p75` 为 `None`。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: add pre-launch historical rule check`。

### Task 10：前端

**Files:**
- Create: `web/src/lib/pool-tags.ts`、`web/src/lib/pool-tags.test.ts`
- Modify: `web/src/lib/components/Watchlist.svelte`、`web/src/lib/workbench.ts`、`web/src/routes/Today.svelte`、`web/src/routes/Review.svelte`
- Test: `web/src/lib/components/Watchlist.test.ts`、`web/src/routes/Today.test.ts`、`web/src/routes/Review.test.ts`

**Interfaces:**
- Consumes: Task 2、5–9 的接口与返回结构。
- Produces:
  - `pool-tags.ts`：`SECTOR_ETFS = ['SMH', 'XLK', 'QQQ'] as const`；`isCore(tags: string[]): boolean`；`sectorOf(tags: string[]): string | null`；`withPoolTags(tags: string[], core: boolean, sector: string | null): string[]`（去掉旧的 `core` 与 `sector:*`，按需追加 `core`、`sector:<ETF>`，其余标签原样保留）。
  - `workbench.ts`：类型 `MarketContext`、`PlanContext`、`ExtendedUnit`、`Backcheck`；`TodayView` 增加 `extended_units: ExtendedUnit[]`、`market: MarketContext | null`；`Plan.inputs.context?: PlanContext`；函数 `getBackchecks()`、`runBackcheck(tickers?: string[])`。

- [ ] **Step 1: 失败测试**：
  - pool-tags：`withPoolTags keeps other tags`、`withPoolTags replaces sector`、`isCore is case-insensitive`。
  - Watchlist：`core checkbox writes core tag`、`sector select writes sector tag`、`header shows pool and core counts`（「美股池 3/100 · 核心 1/15」）、`server 400 detail is shown and row unchanged`、`A-share rows have no core or sector controls`。
  - Today：`market card shows label and breadth`、`market card shows FRED not configured`、`plan card shows regime, next earnings and sector`、`extended units are collapsed and have no decision controls`。
  - Review：`weekly shows by-pool table`、`backcheck tab lists runs with flags`、`backcheck run posts and shows the descriptive note`。
- [ ] **Step 2: 运行确认失败**：`npx vitest run src/lib/pool-tags.test.ts src/lib/components/Watchlist.test.ts src/routes/Today.test.ts src/routes/Review.test.ts`。
- [ ] **Step 3: 实现**，文案用中文，沿用现有组件与样式。
- [ ] **Step 4: 运行确认通过**；构建检查：`npx vite build --outDir ../.local/us-workbench/build-review`。
- [ ] **Step 5: 提交** `feat: manage pool tiers and show market context in the workbench UI`。

### Task 11：端到端场景、文档与回归

**Files:**
- Modify: `tests/test_workbench_scenarios.py`、`web/src/workbench-scenarios.test.ts`、`docs/us-workbench.md`、`docs/roadmap/v2-progress.md`

- [ ] **Step 1: 场景测试** `test_pool_and_context_end_to_end`：合成数据跑通「观察名单 2 只核心（带 `sector:SMH`）+ 25 只扩展 → 批处理（FRED 替身、密钥由 monkeypatch 设置）→ 区制快照非 `insufficient` → 核心与扩展各有买入计划且带 `context` → 推送替身只收到核心计划、概览含市场环境与扩展池计数 → 周中把一只扩展股改为核心 → 生成周度 review-3，`by_pool` 按信号日归池 → 运行历史检查并列出」，断言每一步的关键字段。
- [ ] **Step 2: 运行确认通过。**
- [ ] **Step 3: 文档（DoD）**：`us-workbench.md` 把「观察名单 ≤ 10 只」改为数据库观察池；新增「观察池与分层」「市场环境」「上线前检查」三节，每节写功能说明、手动入口（页面路径、API、命令行）、验证入口（运行报告 `summary.pool/etfs/macro/regime/sources/timings`、页面）与一个验证示例；「上线前提」增加迁移 018、`FRED_API_KEY`、在观察名单中标记核心池。`v2-progress.md` 记录 P2 `engineering_done`、`runtime_unverified` 与提交号。
- [ ] **Step 4: 全量回归**：后端 `... pytest tests -q`、前端 `npx vitest run`；报告通过、跳过与失败数（无测试库时注明 SQL 用例跳过）。
- [ ] **Step 5: 提交** `test: verify P2 pool and market context end to end`。

## 3. 依赖关系

按任务编号串行执行。各任务的直接依赖：

| 任务 | 依赖 |
| --- | --- |
| T2、T3、T4 | T1 |
| T5 | T2、T3、T4 |
| T6 | T5 |
| T7、T8 | T6 |
| T9 | T2 |
| T10 | T2、T5–T9 |
| T11 | 全部 |

## 4. 完成标准

- 全部任务提交，后端与前端测试通过（SQL 用例在有测试库时通过，否则如实记为跳过）。
- `us-workbench.md` 满足 DoD 四项。
- 未对真实库执行迁移 018、未改真实观察名单、未配置或调用真实 FRED、未发送真实 Discord、未重启服务；这些在 P2 验收时另行授权，执行迁移前 `pg_dump` 备份。
- P2 退出条件（roadmap §5）在验收时核对：100 只规模下 07:00 前完成并推送（看 `summary.timings` 与推送时间）；每份计划显示区制与下次财报日；各数据源失败可在 `summary.sources` 中区分。
