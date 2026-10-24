---
title: P3 Agent 轨道实施计划
tags: [美股, Agent, LangGraph, 智谱, 引用校验, 实施计划]
created: 2026-10-24
---

# P3 Agent 轨道实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每个买入单元在规则主计划旁多一条 Agent 建议（LangGraph + 智谱 `glm-5.3`）：工具层按截止时间取数，价位与理由引用写库的工具调用，反方步骤写风险，`ok` 的建议生成 `agent` 计划并影子跟踪，在「今日」与推送中并列展示、可被选为执行依据。

**Architecture:** 新包 `investment_assistant/workbench/agent/`：`tools.py`（纯 Python 工具与调用记录，不依赖 LangGraph）、`citations.py`（建议与反方的纯函数校验）、`model.py`（环境配置、`ChatOpenAI`、额度错误识别、检查点）、`graph.py`（LangGraph 图与单元运行）、`__main__.py`（命令行）。`plans.build_agent_plan` 复用 P1 仓位与财报逻辑。SQL 仍集中在 `workbench/repository.py`，事务与批处理阶段仍在 `workbench/service.py`；Agent 阶段排在规则循环之后、推送之前。

**Tech Stack:** Python 3.11、FastAPI、psycopg 3、PostgreSQL、LangGraph 1.2（`StateGraph`、`ToolNode`、`PostgresSaver` / `InMemorySaver`）、`langchain-openai`（`ChatOpenAI` 指向智谱 OpenAI 兼容端点）、pytest；Svelte 5、vitest。

**Spec:** [2026-10-24-p3-agent-track-design.md](../specs/2026-10-24-p3-agent-track-design.md)。设计决定以 spec 为准，本文只定文件、接口、顺序与测试。

## Global Constraints

- 只追加：`agent_runs`、`agent_tool_calls` 不 UPDATE / DELETE；迁移 019 对旧表只允许「放宽 `trade_plans_kind_check` 为 `('rule','own','agent')`」与「新增 agent 部分唯一索引」，不含 `UPDATE`、`DELETE` 或回填。
- 版本号：`AGENT_VERSION = 'agent-1'`（同时作 `agent` 计划的 `plan_version`）；`PLAN_VERSION` 仍为 `'plan-1'`，`SHADOW_VERSION` 仍为 `'plan-shadow-1'`，周度 `CALC_VERSION` 仍为 `'review-3'`。
- 模型常量：`DEFAULT_MODEL = 'glm-5.3'`、`DEFAULT_BASE_URL = 'https://open.bigmodel.cn/api/coding/paas/v4'`、`TEMPERATURE = 0.2`、`REQUEST_TIMEOUT_S = 90`、`CLIENT_RETRIES = 2`、`QUOTA_CODES = frozenset({'1113', '1308', '1310'})`。
- 环境变量：`WORKBENCH_AGENT_PROVIDER`（`zhipu` 默认 / `off`）、`ZHIPU_API_KEY`、`WORKBENCH_AGENT_MODEL`、`WORKBENCH_AGENT_BASE_URL`、`WORKBENCH_AGENT_DAILY_TOKENS`（可选正整数）。密钥出现在任何报告、`reason`、日志文本中都替换为 `***`（复用 `macro.redact`）。
- 流程常量：`MAX_TOOL_ROUNDS = 8`（每阶段）、`LEVEL_BAND = Decimal('0.5')`、`MAX_LOOKBACK = 120`、`AGENT_DEADLINE_S = 1500`（自批处理开始计）、`AGENT_MAX_ATTEMPTS = 3`。
- 允许的标的：单元标的与 `('SPY', 'SMH', 'XLK', 'QQQ')`；价格类工具 `PRICE_TOOLS = frozenset({'get_price_bars', 'get_indicators'})`；引用格式 `call:<seq>`，`seq` 运行内从 1 递增、两阶段共用。
- 状态与原因只用 spec §6.4 的取值；中文对照 `REASON_TEXT` 定义一次（后端在 `workbench/agent/__init__.py`，前端在 `web/src/lib/workbench.ts`），二者逐项一致。
- 提示词 `PROPOSE_PROMPT`、`COUNTER_PROMPT` 逐字取 spec §6.5。
- Agent 看不到规则计划价位：任何工具返回值、发给模型的消息都不含 `trade_plans` 的价位字段。
- 测试不访问网络：模型用脚本化假模型，检查点用 `InMemorySaver`，Discord、yfinance、SEC、FRED 照旧注入替身。
- 每条 Discord 消息仍 ≤ 10 个 embed、≤ 6000 字符，字段值 ≤ 1024 字符；证据文案仍为「证据：未验证」。

## Review Focus

1. **编造或写错引用**（`call:99`、`call3`、引用了别的标的上下文里的编号）：整条建议 `rejected / invalid_citation`，内容不在「今日」与推送中出现，只显示原因。测试放在 Task 3（`check_proposal`）与 Task 5（图）。
2. **越过截止时间或越权取数**（传入别的标的、`lookback=1000`、截止时间之后才写入的 K 线修订或资讯）：工具返回错误或看不到，调用照样记录。测试放在 Task 2。
3. **智谱 5 小时窗口额度在批处理中途用尽**：首个单元 `error / quota_exhausted`，其余 `skipped / quota_exhausted`；规则计划全部在库、推送照常并带「Agent 额度用尽」提示。测试放在 Task 6 与 Task 9。
4. **模型输出不规范**（JSON 包在 ```` ```json ```` 围栏、数字写成 `"123.40"`、JSON 前后夹带说明文字）：前两种接受，第三种 `rejected / malformed`。测试放在 Task 3。
5. **同一交易日重跑批处理或手动重跑**：已有 `ok` / `pass` 的单元不重复运行、不新增计划；失败的单元最多运行 3 次，第 4 次只写一行 `skipped / max_attempts`。测试放在 Task 6 与 Task 8。

---

## 0. 执行边界

- 在 `main` 上串行实施，每个任务结束提交一次，只 `git add` 本任务列出的路径。
- 每个任务先写失败测试，再实现，再跑本任务测试与相关回归。
- 数据库测试只在显式的 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 下用一次性 schema（`tests/conftest.py` 的 `workbench_db`）运行；未提供时跳过，并在任务报告里如实记为「SQL 未验证」。不对真实库执行迁移 019，不在真实库执行 `PostgresSaver.setup()`。
- 不启动、重启或停止本地服务与调度器；前端不运行默认 `npm run build`，构建检查输出到 `.local/us-workbench/build-review/`。
- 不推送 git、不部署、不发真实 Discord、不调用真实智谱接口、不写 `.env`。真实迁移、建检查点表、配置 `ZHIPU_API_KEY` 另行授权。
- 允许的本地变更：Task 1 在 `.venv` 中安装 `langchain-openai`（`langgraph`、`langgraph-checkpoint-postgres` 已安装）。

后端测试命令：

```bash
env -u INVESTMENT_ASSISTANT_DATABASE_URL -u FRED_API_KEY -u ZHIPU_API_KEY -u WORKBENCH_AGENT_PROVIDER SCHEDULER_ENABLED=0 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest <测试文件> -q
```

前端测试命令（在 `web/` 目录）：

```bash
npx vitest run <测试文件>
```

## 1. 文件结构

```
requirements.txt                               + langgraph / langgraph-checkpoint-postgres / langchain-openai
migrations/019_agent_track.sql                 agent_runs / agent_tool_calls；trade_plans kind 放宽 + agent 唯一索引
investment_assistant/workbench/agent/
  __init__.py     REASON_TEXT、STATUSES、REASONS
  tools.py        ToolContext、Recorder、八个工具、indicators（纯）、call 分发
  citations.py    check_proposal、filter_counter（纯）
  model.py        AgentSettings、settings_from_env、chat_model、classify_error、checkpointer、setup_checkpoints
  graph.py        AGENT_VERSION、MAX_TOOL_ROUNDS、提示词、run_unit
  __main__.py     命令行 setup / run
investment_assistant/workbench/plans.py        build_agent_plan
investment_assistant/workbench/repository.py   agent 表 SQL、agent_plan、candidate_groups_since
investment_assistant/workbench/service.py      Agent 阶段、手动运行、today 的 agent 视图、运行列表与详情
investment_assistant/workbench/ledger.py       采纳可指向 agent 计划
investment_assistant/workbench/digest.py       Agent 行与概览计数
investment_assistant/notify/templates.py       workbench_digest 的 Agent 文案、SOURCE_NAMES['agent']
investment_assistant/api/routes/workbench.py   /agent-runs
web/src/lib/workbench.ts, web/src/routes/Today.svelte, web/src/routes/Review.svelte
docs/us-workbench.md, docs/roadmap/v2-progress.md
tests/conftest.py（scripted_model 夹具、019）
tests/test_workbench_agent_{tools,citations,model,graph}.py
```

运行记录在代码中统一用 dict 表示，键与 spec §3.2 一致；价位为 `Decimal`；工具返回值为可 JSON 序列化的 dict（日期转 ISO 字符串、`Decimal` 转 `float`）。

## 2. 任务

### Task 1：依赖与迁移 019

**Files:**
- Create: `migrations/019_agent_track.sql`
- Modify: `requirements.txt`、`tests/conftest.py`（`WORKBENCH_MIGRATIONS` 尾部加 `'019_agent_track.sql'`）、`investment_assistant/workbench/repository.py`（`WORKBENCH_TABLES` 加 `agent_runs`、`agent_tool_calls`）、`investment_assistant/workbench/service.py`（`_tx` 文案「需执行迁移 016–019」）
- Test: `tests/test_workbench_schema.py`、`tests/test_workbench_postgres.py`

**Interfaces:**
- Produces: spec §3.1–3.3 的表与约束；`missing_tables` 缺任一新表时返回其表名。

- [ ] **Step 1: 安装依赖**：`requirements.txt` 追加 `langgraph>=1.2`、`langgraph-checkpoint-postgres>=3.1`、`langchain-openai>=1.0`；运行 `.venv/bin/pip install 'langchain-openai>=1.0'`。
- [ ] **Step 2: 失败测试（离线）**：`test_019_only_widens_trade_plans`（SQL 文本含两张表的 `CREATE TABLE IF NOT EXISTS`；所有 `ALTER TABLE` 都作用于 `trade_plans` 且只涉及 `trade_plans_kind_check`；不含 `UPDATE `、`DELETE `）；`test_agent_dependencies_importable`（导入 `langgraph.graph.StateGraph`、`langgraph.checkpoint.postgres.PostgresSaver`、`langchain_openai.ChatOpenAI`）。
- [ ] **Step 3: 失败测试（SQL）**：`test_agent_plan_kind_allowed`；`test_agent_plan_unique_per_unit`（同 `(ticker, signal_date, 'agent-1')` 第二个 agent 计划报 UniqueViolation，`rule` 计划不受影响）；`test_agent_run_ok_requires_plan`；`test_agent_run_reason_required`（`rejected` 无 `reason` 报 CheckViolation）；`test_tool_call_seq_unique`；`test_missing_tables_lists_019`。
- [ ] **Step 4: 运行确认失败**：`... pytest tests/test_workbench_schema.py tests/test_workbench_postgres.py -q`。
- [ ] **Step 5: 写 SQL**：`ALTER TABLE trade_plans DROP CONSTRAINT IF EXISTS trade_plans_kind_check`，再 `ADD CONSTRAINT trade_plans_kind_check CHECK (kind IN ('rule','own','agent'))`；`CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_plans_agent_unique ON trade_plans (ticker, signal_date, plan_version) WHERE kind = 'agent'`。`agent_runs(id UUID PRIMARY KEY, ticker TEXT NOT NULL, signal_date DATE NOT NULL, pool TEXT NOT NULL CHECK IN ('main','extended'), attempt INT NOT NULL CHECK (attempt >= 1), agent_version TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, cutoff_at TIMESTAMPTZ NOT NULL, status TEXT NOT NULL CHECK IN ('ok','pass','rejected','error','skipped'), reason TEXT, output JSONB, counter JSONB, plan_id UUID REFERENCES trade_plans(id), input_tokens INT NOT NULL DEFAULT 0, output_tokens INT NOT NULL DEFAULT 0, started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), CHECK ((status = 'ok') = (plan_id IS NOT NULL)), CHECK (status IN ('ok','pass') OR reason IS NOT NULL))`，索引 `(ticker, signal_date, created_at DESC)`、`(started_at)`；`agent_tool_calls(id BIGSERIAL, run_id UUID NOT NULL REFERENCES agent_runs(id), seq INT NOT NULL CHECK (seq >= 1), phase TEXT NOT NULL CHECK IN ('propose','counter'), tool TEXT NOT NULL, args JSONB NOT NULL, result JSONB NOT NULL, result_sha256 TEXT NOT NULL CHECK (length(result_sha256) = 64), called_at TIMESTAMPTZ NOT NULL, UNIQUE (run_id, seq))`。文件头注释写明「Additive except widening trade_plans.kind」与 spec 出处，风格同 018。
- [ ] **Step 6: 更新 `WORKBENCH_TABLES` 与 `_tx` 文案**，运行 Step 4 命令确认通过（无测试库时 SQL 用例 skipped，报告注明）。
- [ ] **Step 7: 提交** `feat: add agent track schema and dependencies`。

### Task 2：工具层

**Files:**
- Create: `investment_assistant/workbench/agent/__init__.py`、`investment_assistant/workbench/agent/tools.py`
- Test: `tests/test_workbench_agent_tools.py`

**Interfaces:**
- Consumes: `repository.read_bars / unit_candidates / read_filings / read_news / latest_earnings / regime_for / list_trades / split_events`；`positions.build`；`plans.atr14`。
- Produces:
  - `agent/__init__.py`：`STATUSES = ('ok','pass','rejected','error','skipped')`；`REASON_TEXT = {'disabled': '已关闭', 'not_configured': '未配置', 'quota_exhausted': '额度用尽', 'token_budget': '超出 token 上限', 'stage_budget': '超出时限', 'max_attempts': '已达重试上限', 'malformed': '输出格式无效', 'invalid_citation': '引用无效已作废', 'level_check': '价位校验未通过', 'tool_rounds_exceeded': '工具调用超限', 'model_error': '模型调用失败', 'checkpoint_unavailable': '状态库未就绪'}`。
  - `ALLOWED_EXTRA`、`MAX_LOOKBACK`、`PRICE_TOOLS`（Global Constraints）；`class ToolError(ValueError)`。
  - `@dataclass class ToolContext`：`ticker: str`、`session: date`、`cutoff_at: datetime`、`read: Callable[[Callable[[Any], Any]], Any]`（给一个接收连接的函数，在只读事务中执行并返回结果）。
  - `@dataclass class Recorder`：`phase: str = 'propose'`、`calls: list[dict]`（每项 `{'seq', 'phase', 'tool', 'args', 'result', 'result_sha256', 'called_at'}`）；`record(tool: str, args: dict, *, data=None, error: str | None = None, now: datetime) -> dict` 返回 `{'ref': 'call:<seq>', 'data': data}` 或 `{'ref': ..., 'error': error}`，`result` 存的就是这个信封；`refs(phase: str | None = None) -> set[str]`；`price_refs() -> set[str]`（`tool in PRICE_TOOLS` 且无 `error`）。
  - `result_hash(result: dict) -> str`：`json.dumps(result, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)` 的 SHA-256 十六进制。
  - `indicators(bars: list[dict], spy_bars: list[dict]) -> dict`：键见 spec §5；不足 20 / 50 / 200 / 252 / 61 根时对应项为 `None`。
  - 八个工具 `get_trigger(ctx)`、`get_price_bars(ctx, ticker: str, lookback: int = 60)`、`get_indicators(ctx, ticker: str)`、`get_filings(ctx, days: int = 30)`、`get_news(ctx, days: int = 7)`、`get_earnings(ctx)`、`get_market_context(ctx)`、`get_position(ctx)`，返回可序列化 dict，非法参数抛 `ToolError`；`get_trigger` 只返回 `[{'rule_id', 'action', 'inputs'}]`。
  - `TOOLS: dict[str, Callable]`；`TOOL_DESCRIPTIONS: dict[str, str]`（中文一句话，供 Task 5 包装）。
  - `call(ctx: ToolContext, recorder: Recorder, name: str, args: dict, *, now: datetime) -> dict`：未知工具、`ToolError`、其他异常都记录为 error 信封（异常文本截到 300 字符），不抛出。

- [ ] **Step 1: 失败测试**（`read` 用内存替身直接返回构造的行；截止时间用例走 SQL）：
  - `test_ticker_outside_allowed_is_error_and_recorded`（`NVDA` 对 `AMD` 单元 → 信封含 `error`，`recorder.calls` 一行；Review Focus 2）；`test_lookback_out_of_range_is_error`（`0`、`1000`）。
  - `test_trigger_has_no_plan_levels`（候选行里混入 `entry_low` 等键也不出现在结果中）。
  - `test_seq_increments_across_phases`（propose 两次、counter 一次 → `call:1..3`，`refs('propose') == {'call:1','call:2'}`）；`test_price_refs_exclude_errors`；`test_hash_is_canonical`（键顺序不同哈希相同）。
  - `test_indicators_short_history_nulls`（120 根 → `ma200`、`high_252` 为 `None`，`ma50` 有值）；`test_indicators_values`（构造序列断言 `ma20`、`volume_ratio`、`rs20`）。
  - SQL：`test_bars_after_cutoff_invisible`（cutoff 后写入的修订与新 K 线、cutoff 后抓取的资讯都不出现；Review Focus 2）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**；`get_position` 用 `positions.build(list_trades, splits=split_events)` 的 `position`。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: add agent tool layer with recorded calls`。

### Task 3：建议校验与 Agent 计划

**Files:**
- Create: `investment_assistant/workbench/agent/citations.py`
- Modify: `investment_assistant/workbench/plans.py`
- Test: `tests/test_workbench_agent_citations.py`、`tests/test_workbench_plans.py`

**Interfaces:**
- Consumes: `plans.levels_ordered / atr14 / validity / earnings_flags / size / context_flags`。
- Produces:
  - `LEVEL_BAND`；`class Rejected(Exception)`，属性 `reason: str`。
  - `check_proposal(text: str, *, refs: set[str], price_refs: set[str], last_close: Decimal) -> dict`：按 spec §6.2 六步，返回 `{'action', 'summary', 'thesis': [{'text', 'refs'}], 'levels': {key: {'value': Decimal, 'refs'}} | None}`（价位已取整到美分）；失败抛 `Rejected(reason)`。
  - `filter_counter(text: str, *, refs: set[str]) -> dict`：`{'status': 'ok' | 'malformed', 'risks': [{'text', 'refs'}], 'dropped': int}`；只读 `risks`，其余键忽略。
  - `plans.build_agent_plan(*, levels: dict[str, Decimal], agent_run_id: str, model: str, ticker: str, signal_date: date, bars: list[dict], earnings_row: dict | None, snapshot: dict | None, exposure: dict, params: WorkbenchConfig, context: dict | None = None) -> dict`：spec §7；`kind='agent'`、`plan_version='agent-1'`、`based_on_id=None`；`inputs` 在 `_inputs` 与 `context` 之外加 `agent_run_id`、`model`。

- [ ] **Step 1: 失败测试**：
  - `test_fenced_json_accepted`、`test_numeric_strings_accepted`（`"123.40"` → `Decimal('123.40')`）、`test_prose_around_json_is_malformed`（Review Focus 4）。
  - `test_missing_thesis_malformed`、`test_bad_action_malformed`、`test_buy_without_levels_malformed`、`test_pass_without_levels_ok`。
  - `test_unknown_ref_rejects_whole_proposal`（`call:99`、`call3` 分别 → `invalid_citation`；Review Focus 1）；`test_level_without_price_ref_rejected`（只引用 `get_news` → `invalid_citation`）。
  - `test_level_order_and_band`（`stop >= entry_low` → `level_check`；`target1 = last_close × 1.6` → `level_check`；`last_close × 1.5` 边界通过）。
  - `test_counter_drops_unknown_refs`（3 条中 1 条无效 → `dropped == 1`）；`test_counter_ignores_levels_and_action`；`test_counter_malformed`。
  - plans：`test_agent_plan_fields`（`kind`、`plan_version`、`inputs.agent_run_id`、有效期同 `validity`）；`test_agent_plan_sizes_from_entry_midpoint`；`test_agent_plan_earnings_in_validity_invalid`；`test_agent_plan_no_atr_uses_zero`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**；围栏只剥一层，正则 ``^```(?:json)?\s*(.*?)\s*```$``（DOTALL）。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_plans.py`。
- [ ] **Step 5: 提交** `feat: validate agent proposals and build agent plans`。

### Task 4：模型接入

**Files:**
- Create: `investment_assistant/workbench/agent/model.py`
- Test: `tests/test_workbench_agent_model.py`

**Interfaces:**
- Consumes: `macro.redact`。
- Produces:
  - 模型常量见 Global Constraints。
  - `@dataclass(frozen=True) class AgentSettings`：`provider: str`、`model: str`、`base_url: str`、`api_key: str | None`、`daily_tokens: int | None`、`config_error: str | None`。
  - `settings_from_env(env: Mapping[str, str] = os.environ) -> AgentSettings`：`WORKBENCH_AGENT_DAILY_TOKENS` 非正整数时 `config_error = 'WORKBENCH_AGENT_DAILY_TOKENS 必须是正整数'`、`daily_tokens = None`。
  - `unavailable_reason(s: AgentSettings) -> str | None`：`provider == 'off'` → `'disabled'`；无密钥或 `config_error` → `'not_configured'`；否则 `None`。
  - `chat_model(s: AgentSettings) -> BaseChatModel`：`ChatOpenAI(model=s.model, base_url=s.base_url, api_key=s.api_key, temperature=TEMPERATURE, timeout=REQUEST_TIMEOUT_S, max_retries=CLIENT_RETRIES)`。
  - `classify_error(exc: BaseException, api_key: str | None) -> tuple[str, str]`：`getattr(exc, 'status_code', None) == 429` 且 `exc.body`（dict）中 `error.code` 或 `code` 的字符串在 `QUOTA_CODES` → `('quota_exhausted', 详情)`；其余 `('model_error', 详情)`；详情为 `redact(f'{type(exc).__name__}: {exc}', api_key)[:300]`。
  - `checkpointer(url: str) -> ContextManager[PostgresSaver]`（`PostgresSaver.from_conn_string(url)`）；`setup_checkpoints(url: str) -> None`（进入后调用 `.setup()`）。

- [ ] **Step 1: 失败测试**：`test_defaults`（空环境 → `provider='zhipu'`、`model='glm-5.3'`、`base_url` 为默认、`unavailable_reason == 'not_configured'`）；`test_off_is_disabled`；`test_daily_tokens_parse`（`'500000'` → 500000；`'0'`、`'abc'` → `config_error` 且 `not_configured`）；`test_quota_429_classified`（假异常 `status_code=429`、`body={'error': {'code': '1308', 'message': '已达到 5 小时的使用上限'}}`）；`test_other_429_is_model_error`（`code='1302'`）；`test_error_detail_redacts_key`（异常文本含密钥 → 详情含 `***` 不含密钥）；`test_chat_model_points_at_base_url`（只构造不调用，断言 `model_name` 与 `openai_api_base`）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: configure the zhipu agent model and quota detection`。

### Task 5：LangGraph 图

**Files:**
- Create: `investment_assistant/workbench/agent/graph.py`
- Modify: `tests/conftest.py`（新增 `scripted_model` 夹具）
- Test: `tests/test_workbench_agent_graph.py`

**Interfaces:**
- Consumes: Task 2 `ToolContext / Recorder / call / TOOLS / TOOL_DESCRIPTIONS`；Task 3 `check_proposal / filter_counter / Rejected`。
- Produces:
  - `AGENT_VERSION`、`MAX_TOOL_ROUNDS`、`PROPOSE_PROMPT`、`COUNTER_PROMPT`。
  - `run_unit(*, unit: dict, ctx: ToolContext, model: BaseChatModel, checkpointer, run_id: str, last_close: Decimal, now: Callable[[], datetime]) -> dict`：`unit` 含 `ticker, signal_date, pool_tier`；返回 `{'status': 'ok'|'pass'|'rejected', 'reason': str | None, 'output': dict | None, 'counter': dict | None, 'calls': recorder.calls, 'input_tokens': int, 'output_tokens': int}`；`output` 中价位转为字符串以便写 JSONB。模型调用抛出的异常原样上抛（Task 6 分类）。
  - 图：`StateGraph` 节点 `propose`、`propose_tools`、`check`、`counter`、`counter_tools`、`finish`；工具节点用 `ToolNode`，工具为每次运行用 `StructuredTool.from_function` 包装的 `call(ctx, recorder, name, args)`（进入 counter 前把 `recorder.phase` 设为 `'counter'`）；`config = {'configurable': {'thread_id': run_id}, 'recursion_limit': 4 * MAX_TOOL_ROUNDS + 10}`。
  - 首条用户消息：`标的 {ticker} · 信号日 {signal_date} · 分层 {pool_tier} · 数据截至信号日收盘`；counter 的用户消息为建议 JSON。
- `scripted_model` 夹具：返回工厂 `make(responses: list[AIMessage]) -> BaseChatModel`；假模型 `bind_tools` 返回自身，按序返回 `responses`，记录每次收到的消息到 `.seen`，每条回复带 `usage_metadata`；回复用尽时抛 `AssertionError`。

- [ ] **Step 1: 失败测试**（工具上下文用内存替身，检查点用 `InMemorySaver()`）：
  - `test_ok_run_records_calls_and_tokens`（脚本：调 `get_indicators` → 输出引用 `call:1` 的买入 JSON → 反方调 `get_news` → 输出风险 → `status='ok'`，`calls` 两行 `phase` 分别为 propose / counter，token 为四条回复之和）。
  - `test_pass_run`；`test_unknown_ref_rejected_and_counter_not_called`（Review Focus 1）；`test_tool_rounds_exceeded`（连续 9 轮工具调用 → `rejected / tool_rounds_exceeded`）。
  - `test_counter_rounds_exceeded_keeps_proposal`；`test_counter_malformed_keeps_proposal`；`test_counter_cites_propose_call`。
  - `test_model_messages_have_no_rule_levels`（替身库中该单元的规则计划 `entry_low=123.45`；断言 `.seen` 全部消息文本不含 `123.45`）。
  - `test_thread_id_is_run_id`（运行后 `checkpointer.get({'configurable': {'thread_id': run_id}})` 非空）。
  - `test_model_exception_propagates`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**：轮数记在状态里，每次模型回复含工具调用即加一；超限直接路由到结束并标记原因。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: run the agent proposal and counter graph`。

### Task 6：批处理 Agent 阶段、手动运行与命令行

**Files:**
- Create: `investment_assistant/workbench/agent/__main__.py`
- Modify: `repository.py`、`service.py`
- Test: `tests/test_workbench_service.py`、`tests/test_workbench_postgres.py`、`tests/test_workbench_agent_model.py`

**Interfaces:**
- Consumes: Task 2–5 全部接口；`_unit_is_extended`、`plan_context`、`exposure`、`synthesis.synthesize`。
- Produces:
  - `repository.insert_agent_run(conn, run: dict, calls: list[dict]) -> dict`（插入运行行与全部调用，返回运行行）；`agent_runs_for(conn, ticker: str, signal_date: date) -> list[dict]`（旧到新）；`latest_agent_run(conn, ticker, signal_date) -> dict | None`；`agent_run_by_id(conn, run_id) -> dict | None`；`agent_tool_calls(conn, run_id) -> list[dict]`（按 `seq`）；`list_agent_runs(conn, since: date) -> list[dict]`（含 `tool_calls` 计数，不含 `result`）；`agent_tokens_on(conn, ny_date: date) -> int`（`started_at` 落在该纽约日期的 `input_tokens + output_tokens` 之和）；`agent_plan(conn, ticker, signal_date) -> dict | None`；`candidate_groups_since(conn, since: date) -> list[dict]`（同 `open_candidate_groups` 的形状，含已决定的组）。
  - `service.AGENT_DEADLINE_S`、`service.AGENT_MAX_ATTEMPTS`；`Deps` 新增 `agent_model: Any = None`（替身模型；为空时用 `model.chat_model(settings)`）、`agent_checkpointer: Callable[[], ContextManager] | None = None`（为空时用 `model.checkpointer(INVESTMENT_ASSISTANT_DATABASE_URL)`）、`agent_settings: AgentSettings | None = None`（为空时 `settings_from_env()`）。
  - `_agent_units(conn, session: date, *, now: datetime) -> list[dict]`：spec §8.1 第 1–2 条，每项 `{'ticker', 'signal_date', 'pool': 'main'|'extended', 'pool_tier'}`。
  - `_run_agent_unit(unit: dict, *, now: datetime, deps: Deps, settings: AgentSettings, attempt: int) -> dict`：读 K 线与 `last_close`、构造 `ToolContext`（`read` 用 `_tx()`）、进入检查点（失败 → `error / checkpoint_unavailable`）、`graph.run_unit`（异常 → `classify_error`）；`ok` 时 `build_agent_plan` → `store_plan` → `insert_agent_run`，三者一个 `_tx()`；返回已写入的运行行。
  - `_skip(unit, reason, *, now, settings, attempt) -> dict`：写 `skipped` 行。
  - `run_batch` 在 `timings['rules']` 之后调用 `_agent_stage(session, now=now, deps=deps, summary=summary, started=started, clock=clock)`，按 spec §8.1 第 3–5 条与 §4 每日上限处理；写 `summary['agent']`、`summary['sources']['agent']`、`summary['timings']['agent']`；`settings.config_error` 时 `summary['errors']` 加 `agent_config: …`。`summary['sources']` 初始化加 `'agent': []`。
  - `class AgentConflict(RuntimeError)`；`run_agent(ticker: str, signal_date: date, *, now: datetime, deps: Deps | None = None) -> dict`：单元不存在或不是无冲突的买入 → `ValueError`；已有 `ok`/`pass` → `AgentConflict`；否则以 `now` 为截止时间运行一次（不受 `AGENT_MAX_ATTEMPTS` 限制），返回运行行。
  - 命令行：`python -m investment_assistant.workbench.agent setup` → `model.setup_checkpoints(url)`，打印 `checkpoint tables ready`；`run --ticker X --date YYYY-MM-DD` → `service.run_agent(..., now=datetime.now(UTC))`，打印 `{'id', 'status', 'reason'}` JSON。

- [ ] **Step 1: 失败测试**（SQL；`deps.agent_model` 用 `scripted_model`，`deps.agent_checkpointer = lambda: nullcontext(InMemorySaver())`，`deps.agent_settings` 显式给出带假密钥的设置）：
  - `test_agent_stage_after_rule_plans`（替身模型首条回复即抛错 → 规则计划已在库，`agent_runs` 一行 `error / model_error`）。
  - `test_agent_order_main_before_extended`（2 只核心、1 只扩展、1 只持仓扩展股同日买入 → 运行顺序为核心与持仓按字母序，再扩展）。
  - `test_agent_ok_writes_plan_run_calls`（`agent` 计划、运行 `plan_id`、调用 `seq` 连续）。
  - `test_existing_ok_or_pass_not_rerun`、`test_rerun_same_session_no_duplicate_plans`（Review Focus 5）。
  - `test_failed_unit_retried_until_max_attempts`（三次批处理均失败 → 第四次写一行 `skipped / max_attempts`，第五次不再写；Review Focus 5）。
  - `test_stage_budget_skips_remaining`（替身 `clock` 使开始后已过 1500 秒 → 全部 `skipped / stage_budget`）。
  - `test_quota_exhausted_skips_rest`（首个单元抛 429 + `1308` → 其余 `skipped / quota_exhausted`，`summary['agent']['quota_exhausted'] is True`，规则计划数不变；Review Focus 3）。
  - `test_not_configured_makes_no_model_call`、`test_disabled_provider`、`test_config_error_reported`、`test_token_budget_skips`（`daily_tokens=10`，首个运行耗 50 → 后续 `skipped / token_budget`）。
  - `test_atr_skipped_unit_still_gets_agent`。
  - `test_checkpoint_unavailable`（`agent_checkpointer` 进入时抛 `OperationalError` → `error / checkpoint_unavailable`）。
  - `test_summary_agent_keys`（`agent.runs`、`agent.tokens`、`sources.agent`、`timings.agent`）。
  - `test_manual_run_conflict_and_not_buy`。
  - `test_postgres_saver_setup_in_disposable_schema`（以测试库 URL 加 `options=-csearch_path=<schema>` 调 `setup_checkpoints`，随后 `checkpoints` 表可见）。
  - `test_cli_dispatch`（monkeypatch `setup_checkpoints` 与 `service.run_agent`，断言参数与输出）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**；Agent 阶段内每个单元单独 `try`，`Unavailable` 照旧上抛，其余异常只影响该单元。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_service.py tests/test_workbench_scenarios.py tests/test_scheduler.py`。
- [ ] **Step 5: 提交** `feat: run the agent track in the workbench batch`。

### Task 7：决定与纪律

**Files:**
- Modify: `ledger.py`
- Test: `tests/test_workbench_ledger.py`、`tests/test_workbench_discipline.py`、`tests/test_workbench_review.py`

**Interfaces:**
- Consumes: `repository.agent_plan`（Task 6）。
- Produces: `ledger._checked_plan_id`：允许的 `plan_id` = 该单元 `status = 'ok'` 的规则计划与 `status = 'ok'` 的 agent 计划；采纳买入且存在允许的计划时必须带其一或 `own_plan`；都不存在时只能带 `own_plan`；错误文案「plan_id 必须指向该单元可用的规则计划或 Agent 计划，或改用自定价位」。

- [ ] **Step 1: 失败测试**：`test_accept_with_agent_plan`（SQL）；`test_rule_invalid_agent_ok_allows_agent_plan`；`test_agent_plan_of_other_unit_rejected`；`test_agent_invalid_and_rule_invalid_only_own`；`test_discipline_track_agent`（计划 `kind='agent'` → `track == 'agent'`）；`test_weekly_plan_summary_has_agent_kind`；`test_pool_summary_ignores_agent_plans`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_ledger.py tests/test_workbench_discipline.py tests/test_workbench_review.py`。
- [ ] **Step 5: 提交** `feat: accept agent plans as an execution track`。

### Task 8：今日与接口

**Files:**
- Modify: `service.py`、`api/routes/workbench.py`
- Test: `tests/test_workbench_service.py`、`tests/test_workbench_api.py`

**Interfaces:**
- Consumes: Task 6 repository 函数与 `run_agent`、`AgentConflict`。
- Produces:
  - `_agent_view(run: dict | None, plan: dict | None) -> dict | None`：`ok`/`pass` → `{'id', 'status', 'model', 'agent_version', 'output', 'counter', 'plan', 'input_tokens', 'output_tokens', 'created_at'}`；其余 → `{'id', 'status', 'reason', 'created_at'}`。
  - `today()`：每个单元加 `agent`；`extended_units` 每项加 `agent_status`（`status` 或 `status: reason`，无运行为 `None`）。
  - `agent_runs(*, now: datetime, since: date | None = None) -> dict`：`{'since', 'runs', 'coverage': {'units': int, 'covered': int, 'missing': [{'ticker', 'signal_date'}]}}`；默认 `since` = 交易日前 14 天；买入单元取 `candidate_groups_since` 经 `synthesize` 后 `proposed_action == 'buy'` 且无 `conflict` 的组。
  - `agent_run_detail(run_id: str) -> dict`：运行行加 `tool_calls`；不存在 → `LookupError`。
  - 路由：`GET /api/workbench/agent-runs`（query `since`）、`GET /api/workbench/agent-runs/{run_id}`（404）、`POST /api/workbench/agent-runs`（body `ticker`、`signal_date`；`ValueError` → 400，`AgentConflict` → 409）。

- [ ] **Step 1: 失败测试**：`test_today_unit_has_agent_ok_view`（SQL）；`test_today_hides_rejected_output`（只含 `status`、`reason`；Review Focus 1）；`test_extended_unit_agent_status`；`test_agent_runs_coverage_lists_missing`；`test_agent_run_detail_has_calls_and_hashes`；`test_agent_run_routes`（GET 列表、GET 404、POST 409 与 400、数据库未就绪 503；Review Focus 5）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_api.py`。
- [ ] **Step 5: 提交** `feat: show agent suggestions in today and the API`。

### Task 9：推送

**Files:**
- Modify: `digest.py`、`notify/templates.py`、`service.py`（`push` 传入 `summary['agent']`）
- Test: `tests/test_workbench_digest.py`、`tests/test_notifier.py`

**Interfaces:**
- Consumes: 单元的 `agent` 视图（Task 8）、`summary['agent']`（Task 6）、`agent.REASON_TEXT`。
- Produces:
  - `digest.build(..., agent_summary: dict | None = None)`：每份计划加 `agent`（`{'status', 'model', 'reason', 'entry_low', 'entry_high', 'stop', 'target1', 'shares', 'plan_status', 'invalid_reasons', 'summary', 'first_risk'}`，无运行为 `None`）；规则计划为空但 Agent 为 `ok` 的单元也生成一项（`kind='agent'`，规则价位字段为 `None`）；`overview` 加 `agent: {'ok', 'pass', 'missing'}`（按主列表单元计）与 `agent_quota_exhausted: bool`。
  - `templates.SOURCE_NAMES['agent'] = 'Agent'`；计划字段在原有行之后加 Agent 行，三种写法逐字取 spec §10.2；作废原因写法同规则计划；仅 Agent 计划的单元不写规则区间行；概览加 `Agent 建议 {ok} · 不建议 {pass} · 未给出 {missing}`，额度用尽时加 `⚠️ Agent 额度用尽，其余单元未运行`。

- [ ] **Step 1: 失败测试**：`test_agent_line_ok`（断言含「Agent（glm-5.3）买入 · 区间」「反方：」）；`test_agent_line_pass`；`test_agent_line_missing_reason`（`skipped / quota_exhausted` → 「Agent 未给出建议（额度用尽）」）；`test_agent_only_unit_listed`；`test_overview_agent_counts_and_quota_warning`（Review Focus 3）；`test_agent_errors_source_field`；`test_digest_limits_with_agent_lines`（15 个单元、每条 Agent 理由 900 字 → 每条消息 ≤ 6000 字符、字段 ≤ 1024）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_digest.py tests/test_notifier.py`。
- [ ] **Step 5: 提交** `feat: push agent suggestions beside rule plans`。

### Task 10：前端

**Files:**
- Modify: `web/src/lib/workbench.ts`、`web/src/routes/Today.svelte`、`web/src/routes/Review.svelte`
- Test: `web/src/lib/workbench.test.ts`、`web/src/routes/Today.test.ts`、`web/src/routes/Review.test.ts`

**Interfaces:**
- Consumes: Task 8 接口与返回结构。
- Produces（`workbench.ts`）：`Plan.kind`、`PlanShadow.kind` 加 `'agent'`，`DisciplineTrade.track` 加 `'agent'`；类型 `AgentItem { text: string; refs: string[] }`、`AgentRun`（spec §10.1 两种形状，`status` 联合类型）、`AgentToolCall { seq; phase; tool; args; result; result_sha256; called_at }`、`AgentRunDetail`；`Unit.agent: AgentRun | null`、`ExtendedUnit.agent_status: string | null`；`AGENT_REASON_TEXT`（与后端 `REASON_TEXT` 一致）；`KIND_TEXT = { rule: '规则', own: '自定', agent: 'Agent' }`；函数 `getAgentRun(id: string)`、`rerunAgent(ticker: string, signalDate: string)`；`Basis` 加 `'agent'`，提交时 `basis === 'agent'` 发 `plan_id = u.agent.plan.id`。

- [ ] **Step 1: 失败测试**：
  - workbench：`AGENT_REASON_TEXT covers every reason`（键集合与固定数组相等）；`agent basis submits agent plan id`。
  - Today：`agent block shows action, levels, thesis refs and counter`；`clicking a ref opens the tool call`（替身 `getAgentRun` 返回调用 → 显示工具名、参数与哈希前 8 位）；`rejected agent shows reason and rerun button`；`rerun posts and refreshes`；`agent basis enabled only when agent plan ok`；`rule invalid and agent ok defaults basis to agent`；`extended list shows agent status`。
  - Review：`plan shadow and discipline label agent track`。
- [ ] **Step 2: 运行确认失败**：`npx vitest run src/lib/workbench.test.ts src/routes/Today.test.ts src/routes/Review.test.ts`。
- [ ] **Step 3: 实现**，文案用中文，沿用现有组件（`Drawer` 展示工具调用）与样式。
- [ ] **Step 4: 运行确认通过**；构建检查：`npx vite build --outDir ../.local/us-workbench/build-review`。
- [ ] **Step 5: 提交** `feat: show agent suggestions and tool calls in the workbench UI`。

### Task 11：端到端场景、文档与回归

**Files:**
- Modify: `tests/test_workbench_scenarios.py`、`web/src/workbench-scenarios.test.ts`、`docs/us-workbench.md`、`docs/roadmap/v2-progress.md`

- [ ] **Step 1: 场景测试** `test_agent_track_end_to_end`：合成数据跑通「2 只核心 + 1 只扩展同日触发买入 → 批处理（脚本化模型：核心 A `ok`、核心 B 引用 `call:99` 被作废、扩展 C `pass`）→ `agent_runs` 三行、A 有 `agent` 计划 → 推送替身只含 A、B 的 Agent 行（B 写「引用无效已作废」），概览计数正确 → `today` 中 B 不含建议内容 → 采纳 A 并以 Agent 计划为执行依据 → 录入买入成交 → 纪律轨道为 `agent` → 计划影子含 A 的 `agent` 计划 → `GET /agent-runs` 覆盖率 3/3 → 同日重跑批处理不新增运行与计划」，断言每一步的关键字段。
- [ ] **Step 2: 运行确认通过。**
- [ ] **Step 3: 文档（DoD）**：`us-workbench.md` 新增「Agent 轨道」一节：功能说明、环境变量、手动入口（「今日」重新运行、`POST /api/workbench/agent-runs`、命令行 `run` 与 `setup`）、验证入口（运行报告 `summary.agent / sources.agent / timings.agent`、`GET /api/workbench/agent-runs` 覆盖率、运行详情的工具调用与哈希）与一个验证示例；「上线前提」增加迁移 019、检查点建表、`ZHIPU_API_KEY` 与端点核对；「已知限制」写明额度错误码与端点需按真实响应核对。`v2-progress.md` 记录 P3 `engineering_done`、`runtime_unverified` 与提交号。
- [ ] **Step 4: 全量回归**：后端 `... pytest tests -q`、前端 `npx vitest run`；报告通过、跳过与失败数（无测试库时注明 SQL 用例跳过）。
- [ ] **Step 5: 提交** `test: verify P3 agent track end to end`。

## 3. 依赖关系

按任务编号串行执行。各任务的直接依赖：

| 任务 | 依赖 |
| --- | --- |
| T2、T4 | T1 |
| T3 | T1 |
| T5 | T2、T3 |
| T6 | T3、T4、T5 |
| T7、T8 | T6 |
| T9 | T8 |
| T10 | T7、T8 |
| T11 | 全部 |

## 4. 完成标准

- 全部任务提交，后端与前端测试通过（SQL 用例在有测试库时通过，否则如实记为跳过）。
- `us-workbench.md` 满足 DoD 四项。
- 未对真实库执行迁移 019、未建真实检查点表、未配置或调用真实智谱接口、未发送真实 Discord、未重启服务；这些在 P3 验收时另行授权，执行迁移前 `pg_dump` 备份。
- P3 退出条件（roadmap §5）在验收时核对：连续两周每个买入单元都有 Agent 建议或明确原因（`GET /agent-runs` 覆盖率 `missing` 为空）；无效引用被拦截（`rejected / invalid_citation` 不出现在「今日」与推送内容中）；额度用尽或 Agent 失败时规则计划照常推送（看运行报告与推送时间）。
