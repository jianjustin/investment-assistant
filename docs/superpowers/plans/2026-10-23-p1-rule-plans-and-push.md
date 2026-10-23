---
title: P1 规则计划与推送实施计划
tags: [美股, 交易计划, 推送, 复盘, 实施计划]
created: 2026-10-23
---

# P1 规则计划与推送实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把美股工作台的买入决策单元升级为带价位与仓位的交易计划，按计划跟踪持仓止损、影子结果、纪律与月度收益，并每天推送到 Discord。

**Architecture:** 新纯函数模块（`plans`、`exits`、`plan_shadow`、`discipline`、`monthly`、`earnings`、`account`）承载计算，SQL 仍集中在 `workbench/repository.py`，事务边界仍在 `workbench/service.py`。迁移 017 只新增表和一列。推送复用 `notify` 的渠道配置，新增多消息发送。

**Tech Stack:** Python 3.11、FastAPI、psycopg 3、PostgreSQL、yfinance、pytest；Svelte 5、vitest。

**Spec:** [2026-10-23-p1-rule-plans-and-push-design.md](../specs/2026-10-23-p1-rule-plans-and-push-design.md)（`3bf5346`）。设计决定以 spec 为准，本文只定文件、接口、顺序与测试。

## Global Constraints

- 只追加不覆盖：新表不 UPDATE 业务字段；更正用 `supersedes_id`，出入金只能作废（`voided_at`/`void_reason`）。迁移 017 不含 `UPDATE`、`DELETE`、对旧行的回填。
- 公式常量（`plan-1`）：`ENTRY_ATR = 0.5`、`STOP_ATR = 2`、`TARGET_ATR = 4`、`TRAIL_ATR = 3`、`VALID_SESSIONS = 3`、`EARNINGS_WARN_SESSIONS = 10`、ATR 周期 14（Wilder），价位四舍五入到 0.01（`ROUND_HALF_UP`）。
- 账户参数默认：`risk_pct = 0.01`、`single_cap = 0.25`、`total_cap = 1.0`、`public_url = 'http://localhost:8787'`、`return_tiers = [0.20, 0.10, 0.0]`。
- 版本号：`PLAN_VERSION = 'plan-1'`、`SHADOW_VERSION = 'plan-shadow-1'`、周度 `CALC_VERSION = 'review-2'`、月度 `MONTHLY_VERSION = 'monthly-1'`、新规则 `rule_version = '1'`。
- 计算价格：ATR、计划价位、计划影子、持仓止损一律用 `price_bars` 的 `open/high/low/close`（拆股调整、未分红调整）；SPY 对照用 `adj_close`。
- 失败不冒充空：财报采集失败不写库；缺快照显示「缺资金快照，无法计算」；推送失败写入 `summary['push']`，不让批处理失败。
- 测试不访问网络、不发真实 Discord：yfinance、SEC、Codex、Discord 客户端全部注入替身。
- 每条 Discord 消息 ≤ 10 个 embed、≤ 6000 字符；字段值 ≤ 1024 字符。
- 证据状态文案固定为「证据：未验证」（Phase 0 Gate HOLD）。

## Review Focus

1. **ATR 为 0 或极小（停牌、合成平盘数据）**：价位会违反 `stop < entry_low <= entry_high < target1` 的 CHECK 而让整批写库失败；应跳过该计划并在运行报告记 `atr_unavailable`。测试放在 Task 3。
2. **补录的资金快照**：`as_of` 早于信号日但 `recorded_at` 晚于本次运行截止时间，不得用于这次计划的仓位；重跑同一交易日时应得到与原计划一致的结果。测试放在 Task 6。
3. **清仓后重新买入（无计划）**：持仓计划只能从当前未平仓批次推导，旧批次的计划不能沿用；此时应回到 `position_drawdown`。测试放在 Task 7。
4. **自定价位输入非法**（字符串、负数、`entry_low > entry_high`、止损高于入场）：接口返回 400，不写入计划也不写入决定。测试放在 Task 8。
5. **超长字段**（解读摘要很长、持仓很多）：单个字段截断到 1024 字符，整条消息不超过 6000 字符，末尾写「其余 N 条见系统」。测试放在 Task 12。

---

## 0. 执行边界

- 在 `main` 上串行实施，每个任务结束提交一次，只 `git add` 本任务列出的路径。
- 每个任务先写失败测试，再实现，再跑本任务测试与相关回归。
- 数据库测试只在显式的 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 下用一次性 schema（`tests/conftest.py` 的 `workbench_db`）运行；未提供时跳过，并在任务报告里如实记为「SQL 未验证」。不对真实库执行迁移 017。
- 不启动、重启或停止本地服务与调度器；前端不运行默认 `npm run build`，构建检查输出到 `.local/us-workbench/build-review/`。
- 不推送 git、不部署、不发真实 Discord。真实迁移、服务重载、开启推送另行授权。

后端测试命令：

```bash
env -u INVESTMENT_ASSISTANT_DATABASE_URL SCHEDULER_ENABLED=0 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest <测试文件> -q
```

前端测试命令（在 `web/` 目录）：

```bash
npx vitest run <测试文件>
```

## 1. 文件结构

```
migrations/017_trade_plans.sql                新表 trade_plans / earnings_dates / account_snapshots /
                                              cash_flows / monthly_reviews；signal_decisions.plan_id
investment_assistant/config.py                WorkbenchConfig；NotifyConfig 默认 workbench → signals
investment_assistant/workbench/
  plans.py        ATR、规则计划、自定计划、仓位、财报标记（纯函数）
  earnings.py     下次财报日期采集与规范化
  account.py      资金快照与出入金：校验、幂等、作废
  exits.py        持仓计划推导、当前止损（纯函数）
  rules.py        新增 plan_stop / plan_target；有计划时跳过 position_drawdown
  plan_shadow.py  计划影子模拟（纯函数）
  discipline.py   纪律指标（纯函数）
  monthly.py      月度收益、分档、流程复查、敏感性表、快照
  digest.py       推送内容汇总（纯函数，输入为 service 读出的数据）
  ledger.py       决定支持 plan_id / own_plan
  review.py       周度复盘 review-2 新视角
  repository.py   新增各表 SQL
  service.py      批处理接入计划与推送；新用例
investment_assistant/notify/templates.py      workbench_digest -> list[Notification]
investment_assistant/notify/notifier.py       send_notifications（多消息）
investment_assistant/tasks/workbench.py       定时运行推送
investment_assistant/api/routes/workbench.py  新接口
web/src/lib/workbench.ts, web/src/routes/Today.svelte, web/src/routes/Review.svelte
docs/us-workbench.md
tests/test_workbench_{plans,earnings,account,exits,plan_shadow,discipline,monthly,digest}.py
```

计划在代码中统一用 dict 表示，键与 `trade_plans` 列名一致；数值为 `Decimal`。

## 2. 任务

### Task 1：迁移 017 与 schema 测试

**Files:**
- Create: `migrations/017_trade_plans.sql`
- Modify: `tests/conftest.py`（`WORKBENCH_MIGRATIONS` 追加 `'017_trade_plans.sql'`）、`tests/test_workbench_schema.py`、`tests/test_workbench_postgres.py`、`investment_assistant/workbench/repository.py`（`missing_tables` 纳入新表）

**Interfaces:**
- Produces: spec §3 的五张表与 `signal_decisions.plan_id`；`repository.missing_tables(conn)` 在缺新表时返回其表名。

- [ ] **Step 1: 失败测试（离线）**：`test_017_is_additive` 读取 SQL，断言五张表、`ALTER TABLE signal_decisions ADD COLUMN IF NOT EXISTS plan_id`、`trade_plans` 的部分唯一索引 `WHERE kind = 'rule'`、`own` 计划 `request_id` 唯一存在；断言不含 `UPDATE `、`DELETE `。
- [ ] **Step 2: 失败测试（SQL）**：`test_rule_plan_unique_per_version`（同 ticker/signal_date/plan_version 第二条 `rule` 报 UniqueViolation，`own` 不受限）；`test_plan_levels_ordered`（`stop >= entry_low` 报 CheckViolation）；`test_cash_flow_nonzero_and_void_pair`；`test_snapshot_equity_positive`；`test_decision_plan_fk`。
- [ ] **Step 3: 运行，确认失败**：`... pytest tests/test_workbench_schema.py tests/test_workbench_postgres.py -q`。
- [ ] **Step 4: 写 SQL**：字段按 spec §3。`trade_plans.kind CHECK IN ('rule','own')`、`status CHECK IN ('ok','invalid')`、`CHECK (stop < entry_low AND entry_low <= entry_high AND entry_high < target1)`、`CHECK ((kind = 'own') = (request_id IS NOT NULL))`；`earnings_dates.status CHECK IN ('known','unknown')`、`CHECK ((status = 'known') = (earnings_date IS NOT NULL))`；`cash_flows` 约束仿照 `trades`；`monthly_reviews.month CHECK (EXTRACT(DAY FROM month) = 1)`。索引：`trade_plans (ticker, signal_date)`、`earnings_dates (ticker, fetched_at DESC)`、`account_snapshots (as_of DESC, recorded_at DESC)`、`cash_flows (flow_date)`。
- [ ] **Step 5: 更新 `missing_tables`**，运行 Step 3 命令确认通过（无测试库时 SQL 用例为 skipped，报告注明）。
- [ ] **Step 6: 提交** `feat: add trade plan schema`。

### Task 2：配置

**Files:**
- Modify: `investment_assistant/config.py`、`config/investment-assistant.example.json`
- Test: `tests/test_config.py`、`tests/test_config_notify.py`

**Interfaces:**
- Produces: `WorkbenchConfig(risk_pct: float = 0.01, single_cap: float = 0.25, total_cap: float = 1.0, public_url: str = 'http://localhost:8787', return_tiers: tuple[float, float, float] = (0.20, 0.10, 0.0))`；`AssistantConfig.workbench: WorkbenchConfig`；`NotifyConfig` 默认 `task_channels['workbench'] = 'signals'`、`task_enabled['workbench'] = True`。

- [ ] **Step 1: 失败测试**：`test_workbench_defaults`（断言上面五个默认值）；`test_workbench_section_overrides`（JSON `{"workbench": {"risk_pct": 0.015}}` 只覆盖该项）；`test_workbench_rejects_bad_values`（`risk_pct` ≤ 0 或 > 0.05、`single_cap`/`total_cap` 不在 (0, 1]、`return_tiers` 非降序 → `ValueError`）；`test_notify_defaults_include_workbench`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**：`load_config` 中 `if "workbench" in data` 用 `_dataclass_from_dict` 后调用 `_validate_workbench(cfg) -> WorkbenchConfig`；示例 JSON 增加 `workbench` 段。
- [ ] **Step 4: 运行确认通过**，并回归 `tests/test_config*.py tests/test_notifier.py`。
- [ ] **Step 5: 提交** `feat: add workbench account parameters`。

### Task 3：计划计算（纯函数）

**Files:**
- Create: `investment_assistant/workbench/plans.py`
- Test: `tests/test_workbench_plans.py`

**Interfaces:**
- Consumes: `WorkbenchConfig`（Task 2）；`data.calendar.add_trading_days`。
- Produces:
  - `atr14(bars: list[dict]) -> Decimal | None`：bars 旧到新，需 ≥ 15 根，否则 `None`。
  - `rule_levels(ref_price: Decimal, atr: Decimal) -> dict[str, Decimal]`：键 `entry_low, entry_high, stop, target1`。
  - `validity(signal_date: date) -> tuple[date, date]`。
  - `earnings_flags(row: dict | None, *, signal_date: date, valid_from: date, valid_until: date) -> tuple[list[str], list[str]]`：返回 (invalid_reasons, warnings)。
  - `size(*, snapshot: dict | None, ref_price, stop, entry_high, ticker_value: Decimal, total_value: Decimal, params: WorkbenchConfig) -> tuple[dict, list[str]]`：返回 (sizing, invalid_reasons)。
  - `validate_levels(raw: dict) -> dict[str, Decimal]`：非数字、非有限、≤ 0、顺序错误 → `ValueError`。
  - `build_rule_plan(*, ticker, signal_date, bars, earnings_row, snapshot, exposure: dict, params) -> dict`：成功返回计划 dict（`kind='rule'`、`plan_version='plan-1'`、`trail_atr_multiple=3`、`inputs` 含 `bar_ids`、`earnings_date_id`、`snapshot_id`、`exposure`）；无法生成时返回 `{'skip': 'atr_unavailable'}`。
  - `build_own_plan(*, rule_plan: dict | None, levels: dict, ticker, signal_date, bars, earnings_row, snapshot, exposure, params) -> dict`：`kind='own'`、`based_on_id=rule_plan['id']`（可空）、`status='ok'`，所有作废原因并入 `warnings`。

- [ ] **Step 1: 失败测试**（用手算数值）：
  - `test_atr14_wilder`：15 根 TR 均为 2 的 bars → `Decimal('2')`；14 根 → `None`。
  - `test_rule_levels`：ref 100、ATR 3 → `entry_low 98.50, entry_high 101.50, stop 94.00, target1 112.00`。
  - `test_rounding_half_up`：ref 10.005、ATR 0.01 → 价位按 0.01 四舍五入。
  - `test_validity_skips_holidays`：信号日为 2026-11-25（周三）→ `valid_from 2026-11-27`，`valid_until 2026-12-01`。
  - `test_earnings_in_validity_invalid`、`test_earnings_within_10_warns`、`test_earnings_unknown_or_past_warns`、`test_earnings_far_away_no_flag`。
  - `test_size_risk_bound`：equity 100000、ref 100、stop 94 → 166 股，`status 'sized'`。
  - `test_size_single_cap`：equity 10000、ATR 很小使风险股数大 → 被 25% 截到 floor(2500/entry_high)，`status 'capped'`，`applied_cap 'single'`。
  - `test_size_total_cap_no_room`：`total_value == equity` → invalid_reasons `['no_room']`。
  - `test_size_no_equity`：`snapshot None` → `status 'no_equity'`、`shares None`、`per_share_risk` 有值。
  - `test_zero_atr_skips`（Review Focus 1）：平盘 bars → `{'skip': 'atr_unavailable'}`。
  - `test_own_plan_demotes_invalid_reasons`：财报在有效期内 → own 计划 `status 'ok'`、`warnings` 含 `earnings_in_validity`。
  - `test_validate_levels_rejects`：`'abc'`、`-1`、`entry_low > entry_high`、`stop >= entry_low` 各一例。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**：Wilder：首个 ATR 为前 14 个 TR 的均值，之后 `ATR = (ATR_prev × 13 + TR) / 14`；TR 用 `max(high-low, |high-prev_close|, |low-prev_close|)`。股数用 `int(floor(...))`；`sizing` 键：`equity, snapshot_id, snapshot_as_of, risk_pct, single_cap, total_cap, per_share_risk, risk_amount, shares, applied_cap, status`。`atr` 为 0 或任一价位不满足顺序时返回 skip。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: compute rule and own trade plans`。

### Task 4：下次财报日期

**Files:**
- Create: `investment_assistant/workbench/earnings.py`
- Modify: `investment_assistant/workbench/repository.py`
- Test: `tests/test_workbench_earnings.py`、`tests/test_workbench_postgres.py`

**Interfaces:**
- Produces:
  - `fetch_next(ticker: str, *, fetcher=None, today: date) -> dict`：返回 `{'status': 'known', 'earnings_date': date}` 或 `{'status': 'unknown', 'earnings_date': None}`；网络或解析异常向上抛出（调用方记入报告，不写库）。默认 fetcher 读 `yf.Ticker(t).calendar` 的 `Earnings Date`，取 ≥ `today` 的最早日期。
  - `repository.store_earnings(conn, ticker, row: dict, *, now) -> dict`：与该股最新一行相同则返回 `{'status': 'unchanged', 'id': ...}`，否则插入返回 `{'status': 'inserted', 'id': ...}`。
  - `repository.latest_earnings(conn, ticker, *, cutoff_at) -> dict | None`。

- [ ] **Step 1: 失败测试**：`test_calendar_list_picks_next`（日期列表含过去与未来 → 取最早未来日）；`test_calendar_missing_is_unknown`；`test_fetch_error_raises`；SQL：`test_store_earnings_dedupes`、`test_latest_earnings_respects_cutoff`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: collect next earnings dates`。

### Task 5：资金快照与出入金

**Files:**
- Create: `investment_assistant/workbench/account.py`
- Modify: `repository.py`、`service.py`、`investment_assistant/api/routes/workbench.py`
- Test: `tests/test_workbench_account.py`、`tests/test_workbench_postgres.py`、`tests/test_workbench_api.py`

**Interfaces:**
- Consumes: `ledger.request_hash`、`ledger.LedgerError/Conflict/NotFound`、`repository.lock`。
- Produces:
  - `account.record_snapshot(conn, payload, *, now) -> dict`（字段 `request_id, as_of, equity, note, supersedes_id`；`supersedes_id` 必须是当前有效快照，否则 `Conflict`）。
  - `account.record_flow(conn, payload, *, now) -> dict`（`request_id, flow_date, amount, note`；`amount == 0` → `LedgerError`）。
  - `account.void_flow(conn, flow_id, reason, *, now) -> dict`。
  - `repository.snapshot_at(conn, as_of: date, *, cutoff_at) -> dict | None`：`as_of <= ?` 且 `recorded_at <= cutoff_at` 且未被取代的最新快照。
  - `repository.list_snapshots(conn) -> list[dict]`、`repository.list_flows(conn) -> list[dict]`。
  - `service.account_view() -> {'snapshots', 'flows', 'params'}`、`service.add_snapshot(payload, *, now)`、`service.add_flow(payload, *, now)`、`service.void_flow(flow_id, reason, *, now)`。
  - 路由：`GET/POST /api/workbench/account/snapshots`、`GET/POST /api/workbench/account/flows`、`POST /api/workbench/account/flows/{flow_id}/void`。

- [ ] **Step 1: 失败测试**：`test_snapshot_replay_same_request`、`test_snapshot_replay_conflict`、`test_snapshot_correction_must_target_head`、`test_flow_zero_rejected`、`test_flow_void_once`、`test_snapshot_at_ignores_recorded_after_cutoff`（SQL）、API：`test_account_routes_503_without_db`、`test_post_flow_400_on_zero`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**，复用 `ledger` 的 `_uuid/_decimal/_text` 校验（必要时提升为模块级公共函数，保持原名）。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_ledger.py tests/test_workbench_api.py`。
- [ ] **Step 5: 提交** `feat: record account snapshots and cash flows`。

### Task 6：批处理生成规则计划

**Files:**
- Modify: `repository.py`、`service.py`
- Test: `tests/test_workbench_service.py`、`tests/test_workbench_postgres.py`

**Interfaces:**
- Consumes: `plans.build_rule_plan`（Task 3）、`earnings.fetch_next` 与 `repository.store_earnings/latest_earnings`（Task 4）、`repository.snapshot_at`（Task 5）。
- Produces:
  - `repository.store_plan(conn, plan: dict) -> dict`：`rule` 计划已存在且价位、sizing、status 相同 → `{'status': 'existing', 'record'}`；不同 → `{'status': 'conflict', 'record': 已有}`，不写；否则插入。
  - `repository.rule_plan(conn, ticker, signal_date, plan_version='plan-1') -> dict | None`、`repository.plan_by_id(conn, plan_id) -> dict | None`、`repository.plans_since(conn, since: date) -> list[dict]`。
  - `service.Deps.earnings_fetcher`（可注入）。
  - `run_batch` 的 `summary` 新增 `earnings: {ticker: 'inserted'|'unchanged'|'error: ...'}`、`plans: {ticker: 'inserted'|'existing'|'conflict'|'skip: <reason>'}`；标的集合为 `_validate_tickers(watchlist)` ∪ 当前有持仓的股票（上限只检查观察名单）。
  - `today()` 的每个单元新增 `plan`（最新 `rule` 计划，可空）。
  - 暴露 `service.exposure(conn, session, *, cutoff_at, ticker) -> dict`：`{'ticker_value': Decimal, 'total_value': Decimal}`，按各持仓最近收盘计算。

- [ ] **Step 1: 失败测试**：
  - `test_batch_writes_rule_plan_for_buy_unit`（合成数据触发 `trend_reclaim`，断言计划价位等于 `rule_levels(close, atr14)`）。
  - `test_no_plan_for_conflict_or_sell_units`。
  - `test_rerun_returns_existing_plan`；`test_changed_inputs_record_conflict_without_overwrite`。
  - `test_backdated_snapshot_recorded_after_cutoff_ignored`（Review Focus 2）：先跑批生成 `no_equity` 计划；再录入 `as_of` 为信号日前的快照；用原 `now` 重跑 → 计划仍为 `existing`。
  - `test_earnings_fetch_failure_not_stored`：fetcher 抛错 → `summary['earnings'][t]` 以 `error:` 开头，`earnings_dates` 无行，计划 `warnings` 含 `earnings_unknown`。
  - `test_holding_outside_watchlist_is_collected`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**：在规则与合成之后、解读之前生成计划；单元已有决定时跳过；`store_plan` 冲突加入 `summary['conflicts']`。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_service.py tests/test_workbench_scenarios.py`。
- [ ] **Step 5: 提交** `feat: generate rule plans in the workbench batch`。

### Task 7：持仓止损与 `plan_stop` / `plan_target`

**Files:**
- Create: `investment_assistant/workbench/exits.py`
- Modify: `rules.py`、`repository.py`、`service.py`
- Test: `tests/test_workbench_exits.py`、`tests/test_workbench_rules.py`、`tests/test_workbench_service.py`

**Interfaces:**
- Consumes: `positions.build` 的 `open` 批次（含 `buy_trade_id`）；`repository.plan_by_id`。
- Produces:
  - `repository.plan_for_buy_trades(conn, trade_ids: list) -> dict[trade_id, plan]`（经 `trades.decision_id → signal_decisions.plan_id`）。
  - `exits.position_plan(open_lots: list[dict], trades: list[dict], plans_by_trade: dict) -> dict | None`：取当前未平仓批次中 `executed_at` 最新、且有计划的买入成交的计划。
  - `exits.active_stop(plan: dict, bars_since_open: list[dict], *, avg_cost: Decimal, splits: list[tuple[date, Decimal]]) -> dict`：返回 `{'stop': Decimal, 't1_reached': bool, 't1_reached_on': date | None, 'mode': 'initial' | 'trailing', 'target1': Decimal}`；计划价位按计划日之后的拆股换算。`t1_reached` 只看 T 日之前的 bars。
  - `rules.evaluate(..., plan_state: dict | None = None)`：`plan_state` 为 `active_stop` 的结果；非空时运行 `_plan_stop`、`_plan_target`，跳过 `_position_drawdown`。
  - 新规则：`plan_stop`（`sell`，条件 `T 日 low <= stop`，`inputs.values` 含 `low, stop, mode`）、`plan_target`（`sell`，条件 `not t1_reached and T 日 high >= target1`，`inputs.values` 含 `high, target1, sell_fraction: 0.5`）；`rule_version '1'`。
  - `today()` 新增 `holdings: [{ticker, quantity, avg_cost, plan_id, stop, mode, t1_reached, target1, last_close, to_stop_pct, to_target_pct, next_earnings}]`。

- [ ] **Step 1: 失败测试**：
  - `test_initial_stop_before_t1`；`test_trailing_after_t1`（最高收盘 120、ATR 3 → 111）；`test_trailing_floor_is_cost`；`test_split_rescales_levels`（2:1 拆股 → 价位减半）。
  - `test_plan_stop_fires_on_low`；`test_plan_target_fires_once`（`t1_reached` 已为真时不再触发）。
  - `test_drawdown_skipped_with_plan`、`test_drawdown_runs_without_plan`。
  - `test_rebuy_after_flat_uses_no_old_plan`（Review Focus 3）：有计划的仓位清仓后，无计划买入 → `position_plan` 为 `None`，`position_drawdown` 生效。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**，`service.run_batch` 对每只持仓股计算 `plan_state` 传入 `rules.evaluate`。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_rules.py tests/test_workbench_positions.py`。
- [ ] **Step 5: 提交** `feat: track plan stops for open positions`。

### Task 8：决定关联计划与自定价位

**Files:**
- Modify: `ledger.py`、`repository.py`、`service.py`、`api/routes/workbench.py`（沿用 `POST /api/workbench/decisions`）
- Test: `tests/test_workbench_ledger.py`、`tests/test_workbench_api.py`、`tests/test_workbench_postgres.py`

**Interfaces:**
- Consumes: `plans.build_own_plan`、`plans.validate_levels`（Task 3）；`repository.rule_plan/plan_by_id/store_plan`（Task 6）。
- Produces:
  - `validate_decision` 接受 `plan_id`（UUID，可空）与 `own_plan`（`{request_id, entry_low, entry_high, stop, target1}`，可空），二者互斥。
  - `record_decision` 规则（spec §5.3）：`accept` 且 `proposed_action == 'buy'` 时，存在 `ok` 的 `rule` 计划则必须带 `plan_id == 该计划` 或 `own_plan`；`rule` 计划 `invalid` 时只能带 `own_plan`；`reject`/`downgrade` 带计划 → `LedgerError`。带 `own_plan` 时在同一事务写计划再写决定，决定 `plan_id` 指向新计划。
  - `repository.insert_decision` 写入 `plan_id`；`request_hash` 计算包含 `plan_id` 与 `own_plan`。

- [ ] **Step 1: 失败测试**：`test_accept_buy_requires_plan`、`test_accept_with_wrong_plan_id_rejected`、`test_invalid_rule_plan_requires_own`、`test_own_plan_written_with_decision`（SQL：两行同事务）、`test_own_plan_replay_same_request`、`test_reject_with_plan_rejected`、`test_bad_own_levels_400_and_nothing_written`（Review Focus 4，API + SQL 断言两表均无新行）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_ledger.py tests/test_workbench_api.py`。
- [ ] **Step 5: 提交** `feat: link decisions to trade plans`。

### Task 9：计划影子模拟

**Files:**
- Create: `investment_assistant/workbench/plan_shadow.py`
- Modify: `service.py`、`api/routes/workbench.py`
- Test: `tests/test_workbench_plan_shadow.py`、`tests/test_workbench_api.py`

**Interfaces:**
- Produces:
  - `SHADOW_VERSION = 'plan-shadow-1'`。
  - `simulate(plan: dict, bars: list[dict], spy_bars: list[dict], *, splits: list[tuple[date, Decimal]]) -> dict`：`{'status': 'pending' | 'expired' | 'open' | 'closed', 'fill_date', 'fill_price', 'legs': [{'fraction', 'exit_date', 'exit_price', 'reason': 'stop'|'target1'|'trail'}], 'r': float | None, 'return': float | None, 'spy_return': float | None}`；`open` 时 `r` 为按最新收盘的浮动 R。
  - `service.plan_shadow(*, now, since: date | None = None) -> {'session', 'calc_version', 'plans': [...plan, 'outcome']}`（默认最近 90 天的 `rule` 与 `own` 计划）。
  - 路由 `GET /api/workbench/plans/shadow?since=YYYY-MM-DD`。

- [ ] **Step 1: 失败测试**（spec §6.1 每条一例）：`test_fill_at_open_inside_zone`、`test_fill_at_entry_high_when_gap_up_then_dip`、`test_fill_at_entry_low_when_gap_down_then_rise`、`test_expired_without_touch`、`test_stop_same_day_as_fill`、`test_gap_below_stop_exits_at_open`、`test_t1_half_then_trail`、`test_stop_and_t1_same_day_stop_first`、`test_trail_floor_is_fill_price`、`test_split_inside_window`、`test_open_reports_floating_r`、`test_pending_before_valid_from`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**：逐日循环；移动止损在当日收盘后更新、下一交易日生效；R 按两半平均（未触 T1 前止损则 fraction 1.0 一条 leg）。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: simulate trade plan outcomes`。

### Task 10：纪律指标

**Files:**
- Create: `investment_assistant/workbench/discipline.py`
- Modify: `service.py`、`api/routes/workbench.py`
- Test: `tests/test_workbench_discipline.py`、`tests/test_workbench_api.py`

**Interfaces:**
- Consumes: `positions.build`（已平仓段含 `buy_trade_id/sell_trade_id`）；`exits.active_stop`；`plan_stop` 候选（`repository.read_candidates`）。
- Produces:
  - `evaluate(*, trades: list[dict], decisions_by_id: dict, plans_by_id: dict, bars_by_ticker: dict, stop_events: list[dict], segments: list[dict], session: date) -> dict`：
    `{'trades': [{'trade_id', 'ticker', 'track': 'rule'|'own'|None, 'flags': [...], 'immature': [...], 'r': float | None}], 'counts': {'chase', 'early_take', 'held_loser', 'unplanned'}, 'immature': {...}, 'planned_buys': int, 'compliance_rate': float | None}`。
    标记名：`chase`、`early_take`、`held_loser`、`unplanned`；`EARLY_TAKE_SESSIONS = 20`。
  - `service.discipline(*, now, since: date | None = None) -> dict`；路由 `GET /api/workbench/discipline`。

- [ ] **Step 1: 失败测试**：`test_chase_above_entry_high`、`test_unplanned_without_decision`、`test_unplanned_decision_without_plan`、`test_early_take_matures_after_20_sessions`（19 个交易日时为 immature）、`test_sell_after_plan_stop_not_early_take`、`test_held_loser_when_no_sell_next_session`、`test_held_loser_cleared_by_next_day_sell`、`test_compliance_rate`、`test_actual_r_uses_plan_stop`、`test_track_from_plan_kind`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: measure execution discipline against plans`。

### Task 11：周度 review-2 与月度复盘

**Files:**
- Create: `investment_assistant/workbench/monthly.py`
- Modify: `review.py`、`repository.py`、`service.py`、`api/routes/workbench.py`
- Test: `tests/test_workbench_monthly.py`、`tests/test_workbench_review.py`、`tests/test_workbench_postgres.py`、`tests/test_workbench_api.py`

**Interfaces:**
- Consumes: `plan_shadow.simulate`、`discipline.evaluate`、`repository.list_snapshots/list_flows`、`WorkbenchConfig.return_tiers`。
- Produces:
  - `review.CALC_VERSION = 'review-2'`；`weekly_stats(...)` 新增参数 `plan_outcomes: list[dict]`、`discipline: dict`，`stats` 新增 `plans`（按 `kind` 分组的计数、过期数、R 的均值与中位数）与 `discipline`。
  - `monthly.MONTHLY_VERSION = 'monthly-1'`。
  - `monthly.month_return(month: date, snapshots: list[dict], flows: list[dict]) -> dict`：`{'status': 'ok' | 'missing_snapshot', 'start', 'end', 'net_flow', 'return'}`；只用未取代快照与未作废出入金；净出入金取 `start.as_of < flow_date <= end.as_of`。
  - `monthly.tier(r: float, tiers: tuple) -> str`：`'excellent_plus' | 'excellent' | 'viable' | 'attention'`（>20% / 10–20% / 0–10% / <0）。
  - `monthly.review_flag(last_three: list[dict]) -> str`：`'review' | 'ok' | 'insufficient'`。
  - `monthly.sensitivity(rs: list[float], pcts=(0.005, 0.01, 0.015, 0.02)) -> list[dict]`：`{'risk_pct', 'return', 'max_drawdown'}`。
  - `service.generate_monthly(month: date, *, notes='', supersedes_id=None, now) -> dict`、`service.list_monthly(limit=12)`；路由 `GET/POST /api/workbench/monthly-reviews`。

- [ ] **Step 1: 失败测试**：`test_month_return_with_flows`（start 100000、end 112000、入金 5000 → 0.07）、`test_month_missing_snapshot`、`test_voided_flow_ignored`、`test_tier_boundaries`（0.20 → `excellent`、0.2001 → `excellent_plus`、0 → `viable`、-0.0001 → `attention`）、`test_review_flag_requires_loss_and_underperform`、`test_review_flag_insufficient`、`test_sensitivity_drawdown`（R 序列 `[2, -1, -1, 3]`、1% → return 0.03、max_drawdown 0.02）、`test_weekly_review2_has_plans_and_discipline`、`test_old_weekly_snapshot_unchanged`（SQL）、`test_monthly_frozen_and_supersede`（SQL）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**；月度 `stats` 含 `return`、`tier`、`spy`（两快照日期间 SPY `adj_close` 收益与超额）、`review_flag`、`sensitivity`（标 `approximate: true`）、`discipline`、`plans`、`generated_at`。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_review.py`。
- [ ] **Step 5: 提交** `feat: add plan views to weekly review and monthly review`。

### Task 12：推送汇总与发送

**Files:**
- Create: `investment_assistant/workbench/digest.py`
- Modify: `notify/templates.py`、`notify/notifier.py`、`service.py`、`tasks/workbench.py`、`api/routes/workbench.py`、`repository.py`（读最近推送结果）
- Test: `tests/test_workbench_digest.py`、`tests/test_notifier.py`、`tests/test_workbench_service.py`、`tests/test_workbench_api.py`

**Interfaces:**
- Consumes: `today()` 的 `units`（含 `plan`）与 `holdings`（Task 6、7）；`run_batch` 的 `summary`。
- Produces:
  - `digest.build(*, session: date, units: list[dict], holdings: list[dict], summary: dict, last_push_failed: bool, public_url: str) -> dict`：`{'session', 'overview', 'plans', 'holdings', 'pending', 'errors'}`，纯数据。
  - `templates.workbench_digest(digest: dict) -> list[Notification]`：概览、新计划、持仓、待处理与异常各一条；无新计划时「新计划」段写「今日无新计划」；字段值截断到 1024 字符，单条消息总长 ≤ 6000，超出写「其余 N 条见系统」。
  - `templates.workbench_closed(ny_date: date) -> list[Notification]`：一行「纽约休市，未运行」。
  - `notifier.send_notifications(task: str, notifications: list[Notification], notify_cfg, *, client=None) -> dict`：沿用 `dispatch` 的开关、渠道与异常处理，逐条发送，返回 `{'sent': bool, 'messages': int, 'reason'?: str}`。
  - `repository.last_push(conn, *, session: date | None = None) -> dict | None`：从 `job_reports`（`task = 'workbench'`）读 `summary->'push'`。
  - `service.push(*, now, force: bool, summary: dict | None = None, notify_cfg, client=None) -> dict`：非 `force` 时同一交易日已有 `sent: true` 则返回 `{'sent': False, 'reason': 'already_pushed'}`。
  - `tasks/workbench.run`：定时运行在 `run_batch` 之后调用 `service.push(force=False, summary=...)`，结果写入 `summary['push'] = {'session', 'sent', 'reason'?, 'messages'}`；`run_batch` 返回 `skipped` 时推 `workbench_closed`。手动运行不推送。
  - 路由 `POST /api/workbench/push`（`force=True`）。

- [ ] **Step 1: 失败测试**：`test_digest_sections`、`test_digest_no_plans_still_sends`、`test_digest_marks_last_push_failed`、`test_plan_field_text`（断言包含「区间」「止损」「T1」「证据：未验证」与 `public_url` 链接）、`test_field_truncated_to_1024_and_message_under_6000`（Review Focus 5）、`test_overflow_says_rest_in_system`、`test_holding_earnings_eve_reminder`（持仓股下一交易日为财报日时持仓段出现提醒）、`test_expiring_plan_listed_in_pending`、`test_send_notifications_disabled_task`、`test_scheduled_run_pushes_once_per_session`、`test_manual_run_does_not_push`、`test_closed_day_message`、`test_push_failure_recorded_not_raised`、`test_push_route_forces`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**；`tasks/workbench.py` 文件头注释改为「Daily US workbench batch: collect, evaluate rules, plan, brief, push. Never trades.」。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_notifier.py tests/test_notify_discord.py tests/test_workbench_service.py`。
- [ ] **Step 5: 提交** `feat: push daily trade plans to Discord`。

### Task 13：前端

**Files:**
- Modify: `web/src/lib/workbench.ts`、`web/src/routes/Today.svelte`、`web/src/routes/Review.svelte`
- Test: `web/src/lib/workbench.test.ts`、`web/src/routes/Today.test.ts`、`web/src/routes/Review.test.ts`

**Interfaces:**
- Consumes: Task 5–12 的接口。
- Produces（`workbench.ts`）：类型 `Plan`、`Holding`、`Snapshot`、`CashFlow`、`MonthlyReview`、`PlanShadow`、`Discipline`；函数 `getAccount`、`postSnapshot`、`postFlow`、`voidFlow`、`getPlanShadow`、`getDiscipline`、`getMonthly`、`postMonthly`、`pushToday`；`Unit` 增加 `plan: Plan | null`，`TodayView` 增加 `holdings: Holding[]`。

- [ ] **Step 1: 失败测试**：
  - Today：`renders plan levels and shares`、`shows no_equity hint`、`invalid plan only allows own levels`、`own levels form blocks stop >= entry_low`、`accept sends plan_id`、`accept with own levels sends own_plan`、`holdings show stop and t1 state`、`repush button calls pushToday and shows result`。
  - Review：`monthly tab shows missing snapshot message`、`monthly tab shows tier and SPY`、`account tab records snapshot and flow`、`account tab voids flow with reason`、`weekly shows plan and discipline sections`。
- [ ] **Step 2: 运行确认失败**：`npx vitest run src/routes/Today.test.ts src/routes/Review.test.ts src/lib/workbench.test.ts`。
- [ ] **Step 3: 实现**，文案用中文，沿用现有组件与样式；风险参数只读显示。
- [ ] **Step 4: 运行确认通过**；构建检查：`npx vite build --outDir ../.local/us-workbench/build-review`。
- [ ] **Step 5: 提交** `feat: show trade plans, holdings and monthly review in the workbench UI`。

### Task 14：端到端场景、文档与回归

**Files:**
- Modify: `tests/test_workbench_scenarios.py`、`web/src/workbench-scenarios.test.ts`、`docs/us-workbench.md`、`docs/roadmap/v2-progress.md`

- [ ] **Step 1: 场景测试**：合成数据跑通「批处理生成计划 → 推送（替身客户端）→ 采纳自定价位 → 录入买入 → `plan_target` → 卖出一半 → 移动止损触发 `plan_stop` → 卖出 → 计划影子与纪律 → 录资金快照 → 生成月度复盘」，断言每一步的关键字段。
- [ ] **Step 2: 运行确认通过。**
- [ ] **Step 3: 文档（DoD）**：`us-workbench.md` 新增「交易计划」「持仓止损」「推送」「资金与月度复盘」四节，每节写功能说明、手动入口（页面路径、API、CLI）、验证入口（运行报告 `summary.plans/push`、页面）与一个验证示例；「上线前提」增加迁移 017 与 `workbench` 配置段。`v2-progress.md` 记录 P1 `engineering_done`、`runtime_unverified` 与提交号。
- [ ] **Step 4: 全量回归**：后端 `... pytest tests -q`、前端 `npx vitest run`；报告通过、跳过与失败数（无测试库时注明 SQL 用例跳过）。
- [ ] **Step 5: 提交** `test: verify P1 trade plans end to end`。

## 3. 依赖关系

按任务编号串行执行。各任务的直接依赖：

| 任务 | 依赖 |
| --- | --- |
| T2、T4、T5 | T1 |
| T3 | T2 |
| T6 | T3、T4、T5 |
| T7、T8 | T6 |
| T9 | T3、T8 |
| T10 | T7、T8 |
| T11 | T9、T10 |
| T12 | T7、T11 |
| T13 | T5–T12 |
| T14 | 全部 |

## 4. 完成标准

- 全部任务提交，后端与前端测试通过（SQL 用例在有测试库时通过，否则如实记为跳过）。
- `us-workbench.md` 满足 DoD 四项。
- 未对真实库执行迁移 017、未发送真实 Discord、未重启服务；这些在 P1 验收时另行授权，执行迁移前 `pg_dump` 备份。
