---
title: P4 复盘扩展实施计划
tags: [美股, 复盘, 三方对比, Discord, Agent, 实施计划]
created: 2026-10-25
---

# P4 复盘扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** P4 补齐复盘环节，做四件事：

1. 对同一批买入单元，并列规则计划、Agent 计划、实际执行三条轨道的结果（以 R 计），每行可追溯；
2. 月度复盘补上复查明细，敏感性表按平仓时间排序；
3. 新增定时任务，推送周度和月度摘要，缺月末资金快照时提醒；
4. Codex 解读退役，由 Agent 轨道统一产出解读。

**Architecture:**

- 新增纯函数模块：
  - `workbench/tracks.py`：三方对比；
  - `workbench/review_digest.py`：推送内容的数据与到期周期计算。
- 新增 `tasks/workbench_review.py`，注册进调度器。
- Agent 包新增：
  - 解读校验 `check_interpretation`；
  - 单阶段解读图 `run_interpret`。
- `briefs.py` 不再调用模型，只负责从 Agent 运行构造解读行。
- 代码分层不变：SQL 集中在 `workbench/repository.py`，事务、批处理、推送编排在 `workbench/service.py`。

**Tech Stack:** Python 3.11、FastAPI、psycopg 3、PostgreSQL、LangGraph 1.2（沿用 P3）、pytest；Svelte 5、vitest。

**Spec:** [2026-10-25-p4-review-expansion-design.md](../specs/2026-10-25-p4-review-expansion-design.md)。设计决定以 spec 为准，本文只定文件、接口、顺序与测试。

## Global Constraints

- **只追加。** `review_pushes`、`agent_runs`、`signal_briefs` 不 UPDATE、不 DELETE。迁移 020 对旧表只做以下几件事：
  - `agent_runs`：加 `mode` 列，替换 ok/plan 约束，新增 interpret 不得 pass 约束，加索引；
  - `signal_briefs`：加 `agent_run_id` 列；
  - `scheduled_jobs`：插入一行 `workbench_review`。
  - 迁移中不含 `UPDATE `、`DELETE `，不回填。
- **版本号：**
  - `review.CALC_VERSION = 'review-4'`；`monthly.MONTHLY_VERSION = 'monthly-2'`；`tracks.TRACKS_VERSION = 'tracks-1'`；
  - `graph.INTERPRET_VERSION = 'agent-brief-1'`；
  - `AGENT_VERSION` 仍为 `'agent-1'`，`PLAN_VERSION` 仍为 `'plan-1'`，`SHADOW_VERSION` 仍为 `'plan-shadow-1'`。
- **定时任务：** 名称 `workbench_review`，`'08:00'`、`'1-7'`、`'Asia/Shanghai'`，迁移时插入为 `enabled = FALSE`。通知默认 `task_channels['workbench_review'] = 'signals'`、`task_enabled['workbench_review'] = True`。
- **推送：**
  - 一律经 `notifier.send_notifications('workbench_review', …)`；
  - 每条消息 ≤ 10 个 embed、≤ 6000 字符，字段值 ≤ 1024 字符；
  - 证据文案「证据：未验证」，说明文案「描述性统计，样本小且重叠，不代表规则或 Agent 有效。」；
  - 链接用 hash 路由：`{public_url}/#review/weekly`、`#review/monthly`、`#review/account`。
- **状态取值：** 轨道结果的 `status` 只用 spec §4.2 的取值。中文对照 `TRACK_STATUS_TEXT` 定义一次（后端 `tracks.py`、前端 `web/src/lib/workbench.ts`，二者逐项一致）：
  - `missing` 缺失、`not_executable` 计划作废、`pending` 待定、`expired` 到期未成交；
  - `open` 未平仓、`closed` 已平仓、`pass` 不建议、`not_executed` 未执行、`no_plan` 无计划成交。
- **按 `mode` 过滤：** 凡是按单元查 Agent 运行的地方，都按 `mode` 过滤，默认 `'propose'`。只有 `agent_tokens_on` 不过滤。
- **提示词：** `INTERPRET_PROMPT` 逐字取 spec §7.2。
- **测试不访问网络：** 模型用 `scripted_model` 夹具，检查点用 `InMemorySaver`，Discord 用替身客户端。
- **日期与时区：** 周以纽约周一为起点；「北京日期」用 `Asia/Shanghai`；交易日用 `investment_assistant.data.calendar`。

## Review Focus

1. **解读运行混进 `propose` 的查询。** 场景：同一单元先有 `interpret / ok`，再成为无冲突买入单元，或在同一天重跑。预期：
   - 批处理照常跑 `propose`；
   - 「今日」的 `agent`、覆盖率、手动运行冲突、三方对比都只看 `propose`；
   - 两种 `mode` 的重试次数分开算。
   - 测试放在 Task 3 与 Task 4。
2. **把还没决定、计划仍在有效期内的单元算成 0R。** 预期：实际一列为 `pending`，不进均值；有效期过后才记 `not_executed / 0R`。规则计划 `pending`（有效期内未成交）同理。测试放在 Task 5。
3. **同一周期重复推送或漏推送。** 预期：
   - 推送失败（`send_failed`）或任务开关关闭（`task_disabled`）时，下一次定时运行重试；
   - 推送成功后不再推送；
   - 手动推送不受这条限制。
   - 测试放在 Task 9。
4. **把收盘前生成的快照当成周度或月度结果推送。** 场景：周三手动生成了本周快照，或录入月末资金快照之前就生成了月度快照。预期：定时任务生成新快照，指向旧快照，推送新快照。测试放在 Task 9。
5. **月末资金快照缺失或晚到。** 预期：
   - 新月第一个周六之前，不推、不提醒；
   - 之后只提醒一次，之后每天的运行都不再提醒；
   - 补录快照后的下一次运行，生成并推送月度快照；
   - 只缺上月初快照时，推送里写「缺资金快照，无法计算」，不写 0%。
   - 测试放在 Task 7 与 Task 9。

---

## 0. 执行边界

- 在 `main` 上串行实施。每个任务结束提交一次，只 `git add` 本任务列出的路径；删除的文件用 `git rm`。
- 每个任务先写失败测试，再实现，再跑本任务测试与相关回归。
- 数据库测试只在显式设置了 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 时，用一次性 schema（`tests/conftest.py` 的 `workbench_db`）运行；未设置时跳过，并在任务报告里如实记为「SQL 未验证」。不对真实库执行迁移 020。
- 不启动、重启或停止本地服务与调度器。前端不运行默认 `npm run build`，构建检查输出到 `.local/us-workbench/build-review/`。
- 不推送 git、不部署、不发真实 Discord、不调用真实智谱接口、不写 `.env`、不开启 `workbench_review`。真实迁移、开启任务、真实推送另行授权。

后端测试命令：

```bash
env -u INVESTMENT_ASSISTANT_DATABASE_URL -u FRED_API_KEY -u ZHIPU_API_KEY -u WORKBENCH_AGENT_PROVIDER SCHEDULER_ENABLED=0 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest <测试文件> -q
```

前端测试命令（在 `web/` 目录；Node 26 下加 `NODE_OPTIONS=--no-experimental-webstorage`）：

```bash
npx vitest run <测试文件>
```

## 1. 文件结构

```
migrations/020_review_expansion.sql            agent_runs.mode / signal_briefs.agent_run_id / review_pushes / 定时任务行
investment_assistant/config.py                 workbench_review 的通知默认值
investment_assistant/workbench/
  tracks.py          （新）三方对比：plan_track / agent_track / actual_track / summarize（纯）
  review_digest.py   （新）周度、月度、提醒推送数据；due_week / due_month / reminder_due（纯）
  briefs.py          （重写）rule_summary / for_run：由 Agent 运行构造解读行，不调用模型
  codex_client.py    （删除）
  agent/citations.py check_interpretation
  agent/graph.py     INTERPRET_VERSION / INTERPRET_PROMPT / run_interpret
  monthly.py         review_detail / month_end_snapshot；MONTHLY_VERSION = 'monthly-2'
  review.py          weekly_stats 接 tracks；CALC_VERSION = 'review-4'
  repository.py      mode 过滤、解读 agent_run_id、对比取数、review_pushes SQL
  service.py         Agent 阶段三组、解读同事务写入、tracks、monthly-2、复盘推送
  digest.py          日推送跳过 agent-1 解读
investment_assistant/notify/templates.py       workbench_weekly / workbench_monthly / workbench_review_reminder
investment_assistant/tasks/workbench_review.py （新）定时任务入口
investment_assistant/tasks/scheduler.py        REGISTRY 加 workbench_review
investment_assistant/api/routes/workbench.py   /review/tracks、/review-pushes
web/src/lib/workbench.ts, web/src/routes/Review.svelte, web/src/routes/Today.svelte
docs/us-workbench.md, docs/roadmap/v2-progress.md
tests/conftest.py（020、删 WORKBENCH_LLM_PROVIDER）
tests/test_workbench_tracks.py、tests/test_workbench_review_digest.py、tests/test_workbench_review_push.py（新）
tests/test_workbench_codex_client.py（删除）
```

约定：

- 轨道结果、单元行、推送数据在代码里一律用 dict 表示，键与 spec §4.4、§6.2 一致。
- R 值为 `float`，价位为 `Decimal`。
- 写入 JSONB 前沿用 `repository._plan_json`。

## 2. 任务

### Task 1：迁移 020 与通知默认值

**Files:**
- Create: `migrations/020_review_expansion.sql`
- Modify:
  - `tests/conftest.py`（`WORKBENCH_MIGRATIONS` 尾部加 `'020_review_expansion.sql'`）；
  - `investment_assistant/workbench/repository.py`（`WORKBENCH_TABLES` 加 `review_pushes`）；
  - `investment_assistant/workbench/service.py`（`_tx` 文案改为「需执行迁移 016–020」）；
  - `investment_assistant/config.py`（`NotifyConfig` 默认值）。
- Test: `tests/test_workbench_schema.py`、`tests/test_workbench_postgres.py`、`tests/test_config_notify.py`

**Interfaces:**
- Produces:
  - spec §3 的列、约束、表与定时任务行；
  - `missing_tables` 缺 `review_pushes` 时返回该表名；
  - `NotifyConfig().task_channels['workbench_review'] == 'signals'`、`task_enabled['workbench_review'] is True`。

- [ ] **Step 1: 写失败测试（离线）**
  - `test_020_is_additive`：SQL 文本里，`ALTER TABLE` 只作用于 `agent_runs`、`signal_briefs`；`INSERT INTO` 只有 `scheduled_jobs`，且带 `ON CONFLICT (name) DO NOTHING` 与 `FALSE`；不含 `UPDATE `、`DELETE `。
  - `test_review_task_notify_defaults`。
- [ ] **Step 2: 写失败测试（SQL）**
  - `test_agent_run_mode_defaults_propose`：按 019 的字段插入一行，`mode == 'propose'`。
  - `test_interpret_ok_without_plan_allowed`。
  - `test_propose_ok_without_plan_rejected`：CheckViolation。
  - `test_interpret_pass_rejected`。
  - `test_old_ok_plan_constraint_dropped`：`pg_constraint` 中不再有定义含 `(status = 'ok'::text) = (plan_id IS NOT NULL)` 且不含 `mode` 的约束。
  - `test_brief_agent_run_fk`：指向不存在的运行时报 ForeignKeyViolation。
  - `test_review_push_reason_required`：`sent = false` 且无 `reason` 时报 CheckViolation。
  - `test_review_job_inserted_disabled`。
  - `test_missing_tables_lists_review_pushes`。
- [ ] **Step 3: 运行确认失败**：`... pytest tests/test_workbench_schema.py tests/test_workbench_postgres.py tests/test_config_notify.py -q`。
- [ ] **Step 4: 写 SQL**（文件头注释写明「Additive except replacing agent_runs' ok/plan CHECK」与 spec 出处，风格同 019）：
  - 旧约束用 `DO $$ … $$` 块删除：遍历 `pg_constraint WHERE conrelid = 'agent_runs'::regclass AND contype = 'c'`，删除 `pg_get_constraintdef(oid)` 同时含 `plan_id IS NOT NULL` 且不含 `mode` 的那一条。
  - 再 `ADD CONSTRAINT agent_runs_mode_plan_check CHECK ((mode = 'propose' AND status = 'ok') = (plan_id IS NOT NULL))`。
  - 再 `ADD CONSTRAINT agent_runs_interpret_no_pass_check CHECK (mode = 'propose' OR status <> 'pass')`。
  - 两个 `ADD CONSTRAINT` 前各加 `DROP CONSTRAINT IF EXISTS`，保证可重复执行。
  - `review_pushes` 按 spec §3.3 建表。
- [ ] **Step 5: 更新 `WORKBENCH_TABLES`、`_tx` 文案与配置默认值**，运行 Step 3 命令确认通过（无测试库时 SQL 用例跳过，报告注明）。
- [ ] **Step 6: 提交** `feat: add review expansion schema and review task defaults`。

### Task 2：解读校验与解读图

**Files:**
- Modify: `investment_assistant/workbench/agent/citations.py`、`investment_assistant/workbench/agent/graph.py`
- Test: `tests/test_workbench_agent_citations.py`、`tests/test_workbench_agent_graph.py`

**Interfaces:**
- Consumes：P3 中已有的 `Rejected`、`_loads`（只剥一层围栏）、`Recorder`、`ToolContext`、`_wrapped_tools`、`MAX_TOOL_ROUNDS`。
- Produces:
  - `check_interpretation(text: str, *, refs: set[str]) -> dict`：返回 `{'summary': str, 'support': [{'text', 'refs'}], 'contra': [...], 'conflicts': [...]}`。按 spec §7.2 三步校验，失败抛 `Rejected('malformed' | 'invalid_citation')`；其他键丢弃。
  - `graph.INTERPRET_VERSION = 'agent-brief-1'`；`graph.INTERPRET_PROMPT`。
  - `run_interpret(*, unit: dict, ctx: ToolContext, model: BaseChatModel, checkpointer, run_id: str, now: Callable[[], datetime]) -> dict`：
    - `unit` 含 `ticker`、`signal_date`、`pool_tier`；
    - 返回 `{'status': 'ok' | 'rejected', 'reason': str | None, 'output': dict | None, 'calls': list[dict], 'input_tokens': int, 'output_tokens': int}`；
    - 模型异常原样抛出，由批处理分类；
    - `recursion_limit = 2 * MAX_TOOL_ROUNDS + 6`。

- [ ] **Step 1: 写失败测试**
  - citations：
    - `test_interpretation_fenced_ok`；
    - `test_interpretation_empty_lists_ok`：三个列表都为空也通过；
    - `test_interpretation_missing_summary_malformed`；
    - `test_interpretation_item_without_refs_malformed`；
    - `test_interpretation_unknown_ref_invalid`：`call:42` 不在 `refs` 中；
    - `test_interpretation_drops_action_and_levels`：输出含 `action`、`entry_low` 时被丢弃。
  - graph：
    - `test_interpret_ok`：脚本：先调用 `get_trigger`，再输出合法 JSON。断言 `status == 'ok'`、`calls[0]['tool'] == 'get_trigger'`、`calls[0]['phase'] == 'propose'`；
    - `test_interpret_invalid_citation`；
    - `test_interpret_malformed`；
    - `test_interpret_tool_rounds_exceeded`：连续 9 轮工具调用 → `rejected / tool_rounds_exceeded`；
    - `test_interpret_prompt_verbatim`：首条系统消息等于 `INTERPRET_PROMPT`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。** 图为 `interpret ⇄ interpret_tools → check → END`，节点写法同 `_build_graph` 的 propose 部分。首条用户消息与 `run_unit` 相同。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_agent_graph.py` 全部用例。
- [ ] **Step 5: 提交** `feat: add the agent interpretation step`。

### Task 3：解读行构造与按 mode 查询

**Files:**
- Modify: `investment_assistant/workbench/briefs.py`（重写）、`investment_assistant/workbench/repository.py`
- Test: `tests/test_workbench_briefs.py`（重写）、`tests/test_workbench_postgres.py`

**Interfaces:**
- Consumes：`agent.REASON_TEXT`、`plans.AGENT_VERSION`、Task 2 的 `INTERPRET_VERSION`。
- Produces:
  - `briefs.rule_summary(unit: dict, candidates: list[dict]) -> dict`：沿用旧 `_fallback_summary` 的输出与文案。
  - `briefs.for_run(run: dict, calls: list[dict], *, unit: dict, candidates: list[dict]) -> dict`：返回可直接交给 `store_brief` 的解读行，键为 `ticker, signal_date, model, prompt_version, cutoff_at, input_refs, output, status, error, agent_run_id`，取值按 spec §7.1 的表：
    - `propose` 且 `ok`/`pass`：`status='ok'`；`output` 为 `{'summary', 'support': thesis, 'contra': counter.risks 或 [], 'conflicts': []}`；
    - `interpret` 且 `ok`：`status='ok'`，`output` 为运行的 `output`；
    - `interpret` 且 `rejected`：`status='error'`，`output={}`，`error=REASON_TEXT[reason]`；
    - 其余：`status='fallback'`，`output=rule_summary(...)`，`error=REASON_TEXT[reason]`。
    - `prompt_version` 取 `run['agent_version']`；`input_refs` 为 `sorted(f"call:{c['seq']}" …)`，按 seq 的数值排序。
  - repository：
    - `_AGENT_RUN_COLUMNS` 加 `mode`；`insert_agent_run` 写入 `run.get('mode', 'propose')`；
    - `agent_runs_for(conn, ticker, signal_date, mode: str = 'propose')`、`latest_agent_run(conn, ticker, signal_date, mode: str = 'propose')` 按 `mode` 过滤；
    - `list_agent_runs` 返回 `mode`；
    - `store_brief` 写入 `brief.get('agent_run_id')`；`latest_brief` 返回 `agent_run_id`。
  - 旧的 `briefs.generate / provider_client / build_payload / _validate / SYSTEM_PROMPT / PROMPT_VERSION` 和对应的旧测试，本任务先保留，由 Task 4 删除，这样每个任务结束时测试都是绿的。

- [ ] **Step 1: 写失败测试**
  - briefs：
    - `test_proposal_ok_brief_from_thesis_and_counter`；
    - `test_proposal_pass_brief`：`contra` 来自反方；反方 `malformed` 时为 `[]`；
    - `test_interpret_ok_brief`；
    - `test_interpret_rejected_is_error_and_hidden`：`output == {}`，`error == '引用无效已作废'`；
    - `test_skipped_run_falls_back_to_rule_summary`：`status='fallback'`、`error='已关闭'`，`summary` 以「规则候选：」开头；
    - `test_input_refs_sorted_by_seq`：`call:10` 排在 `call:9` 之后。
  - SQL：
    - `test_latest_agent_run_filters_mode`：同一单元先写 `propose / skipped`、后写 `interpret / ok`，默认查询返回 `propose` 那一行（Review Focus 1）；
    - `test_agent_runs_for_counts_per_mode`；
    - `test_brief_round_trips_agent_run_id`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_postgres.py tests/test_workbench_service.py`。
- [ ] **Step 5: 提交** `refactor: build briefs from agent runs and filter runs by mode`。

### Task 4：Agent 阶段统一产出解读，Codex 退役

**Files:**
- Modify：`investment_assistant/workbench/service.py`、`investment_assistant/workbench/digest.py`、`tests/conftest.py`（删除 `WORKBENCH_LLM_PROVIDER` 一行）、`tests/test_workbench_service.py`、`tests/test_workbench_scenarios.py`（只删除 `brief_client` 用法）、`tests/test_workbench_digest.py`
- Delete：`investment_assistant/workbench/codex_client.py`、`tests/test_workbench_codex_client.py`

**Interfaces:**
- Consumes：Task 2 的 `run_interpret`、Task 3 的 `briefs.for_run` 与按 `mode` 查询的函数。
- Produces:
  - 删除 `Deps.brief_client`；`run_batch` 的规则循环不再生成解读。
  - `_interpret_units(conn, session: date, *, now: datetime) -> list[dict]`：本交易日、尚未决定、属于主列表、不是无冲突买入的单元，按标的字母序。返回项的键与 `_agent_units` 相同，`pool='main'`，另加 `candidates`。`_agent_units` 返回的每项同样加 `candidates`。
  - `_run_agent_unit(...)`：主列表单元在写入运行的同一事务中，`store_brief(briefs.for_run(run, calls, unit=…, candidates=…))`。`ok` 时的写入顺序为计划 → 运行 → 工具调用 → 解读。扩展池不写解读。
  - `_run_interpret_unit(unit: dict, *, now: datetime, deps: Deps, settings, attempt: int) -> dict`：错误分类同 `_run_agent_unit`。写入运行行（`mode='interpret'`、`agent_version=INTERPRET_VERSION`），并在同一事务写解读行。
  - `_skip(unit, reason, *, now, settings, attempt, mode: str = 'propose')`：主列表单元同时写规则版解读。
  - `_agent_stage`：依次处理三组，即主列表 propose、主列表 interpret、扩展池 propose。共用时限、额度用尽、每日 token 上限三条判断；跳过与重试按 `agent_runs_for(..., mode=...)` 计数。`summary['agent']` 新增 `briefs`；`summary['briefs'][ticker]` 记解读行的 `status`。
  - `digest.build`：单元的 `brief.prompt_version == 'agent-1'` 时，计划项的 `brief_summary` 和 `contra` 记为 `None`。

- [ ] **Step 1: 写失败测试**（`scripted_model`，SQL 用一次性库）
  - `test_rules_loop_writes_no_brief`：Agent 阶段打桩成空操作后跑批处理，`signal_briefs` 为空。
  - `test_buy_unit_brief_derived_from_proposal`：`ok` 运行后，最新解读的 `prompt_version == 'agent-1'`、`agent_run_id` 等于该运行，模型回复次数等于 propose 加 counter，没有额外调用。
  - `test_sell_and_watch_units_get_interpretations`：一只持仓触发 `plan_stop`（卖出），一只只有观察候选，各有一行 `interpret` 运行和 `ok` 解读。
  - `test_conflict_buy_unit_is_interpreted_not_proposed`。
  - `test_agent_off_writes_rule_only_briefs`：`provider='off'` 时，每个主列表单元都有 `fallback` 解读，`error == '已关闭'`；扩展池单元没有解读。
  - `test_stage_order_main_propose_interpret_extended`：记录模型被调用的顺序。
  - `test_quota_exhausted_skips_interpret_and_extended`。
  - `test_interpret_ok_does_not_skip_propose`：预置 `interpret / ok` 行后，同一单元成为买入单元，批处理仍运行 `propose`，`today()` 的 `agent` 为新运行（Review Focus 1）。
  - `test_attempts_counted_per_mode`：`propose` 已失败 3 次时，`interpret` 照常运行。
  - `test_agent_runs_coverage_ignores_interpret`。
  - digest：`test_agent_brief_not_repeated_in_plan_line`；`test_legacy_brief_still_attached`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现，并删除 Codex 文件**，同时删除 `briefs.py` 中 Task 3 保留的旧函数和 `test_workbench_briefs.py` 中对应的旧用例。用 `grep -rn "codex_client\|brief_client\|WORKBENCH_LLM_PROVIDER\|WORKBENCH_CODEX" investment_assistant tests` 确认已无引用（`docs/` 留到 Task 11）。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_service.py tests/test_workbench_digest.py tests/test_workbench_scenarios.py tests/test_workbench_api.py`。
- [ ] **Step 5: 提交** `feat: produce all briefs from the agent track and retire codex`。

### Task 5：三方对比纯函数

**Files:**
- Create: `investment_assistant/workbench/tracks.py`
- Test: `tests/test_workbench_tracks.py`

**Interfaces:**
- Consumes：`plan_shadow.simulate` 的输出形状，`discipline._at_basis`、`discipline._current_basis`。
- Produces:
  - `TRACKS_VERSION = 'tracks-1'`；`TRACK_STATUS_TEXT`（见 Global Constraints）。
  - `plan_track(plan: dict | None, outcome: dict | None) -> dict`：返回 `{'plan_id': str | None, 'status', 'r': float | None}`，规则见 spec §4.2 的规则表。
  - `agent_track(run: dict | None, plan: dict | None, outcome: dict | None) -> dict`：返回 `{'run_id', 'run_status', 'run_reason', 'plan_id', 'status', 'r'}`。
  - `actual_track(*, decision: dict | None, plan: dict | None, buys: list[dict], segments: list[dict], open_lots: list[dict], last_close: Decimal | None, splits: list[tuple[date, Decimal]], session: date, unit_valid_until: date | None) -> dict`：返回 `{'decision_id', 'final_action', 'plan_id', 'plan_kind', 'buy_trade_ids', 'status', 'r', 'open': bool}`。
    - `buys`：该决定关联的有效买入成交；
    - `segments`：`positions.build` 的 `closed` 中属于这些买入的分段；
    - `open_lots`：`positions.build` 的 `open` 中属于这些买入的批次，已在当前拆股口径；
    - `unit_valid_until`：单元所有计划中最晚的 `valid_until`；
    - 已平仓部分的 R 用买入日口径的止损；未平仓部分的 R 用 `_current_basis` 换算后的止损和 `last_close`；两部分按股数加权。
  - `summarize(rows: list[dict]) -> dict`：返回 `{'all' | 'core' | 'extended': {'rule' | 'agent' | 'actual': stats}}`。
    - `stats` 为 `{'units', 'determined', 'pending', 'missing', 'mean', 'median', 'sum', 'wins', 'by_status'}`；
    - `actual` 另加 `by_plan_kind`；
    - `missing` 计 `missing`、`no_plan` 两种状态。

- [ ] **Step 1: 写失败测试**
  - 规则：
    - `test_rule_missing_without_plan`；
    - `test_rule_invalid_plan_is_zero`；
    - `test_rule_pending_has_no_r`（Review Focus 2）；
    - `test_rule_expired_is_zero`；
    - `test_rule_open_and_closed_take_simulated_r`。
  - Agent：
    - `test_agent_pass_is_zero`；
    - `test_agent_rejected_is_missing_with_reason`；
    - `test_agent_ok_uses_agent_plan_outcome`。
  - 实际：
    - `test_ignored_unit_is_not_executed_zero`；
    - `test_buy_decision_without_fill_pending_until_validity_ends`：有效期内为 `pending`，过期后为 `not_executed / 0`；
    - `test_undecided_unit_pending_then_not_executed`（Review Focus 2）；
    - `test_closed_r_priced_at_chosen_plan_stop`：选 Agent 计划，止损 95，成本 100，卖出 110，期望 R = 2.0，`plan_kind == 'agent'`；
    - `test_partial_close_weights_open_lot`：100 股卖出 50 股记 2R，剩余 50 股浮动 1R，期望 1.5R，`status == 'open'`；
    - `test_split_between_buy_and_now`：2:1 拆股后，浮动 R 不变；
    - `test_trade_without_plan_is_no_plan`。
  - 汇总：
    - `test_summarize_excludes_none_from_mean`；
    - `test_summarize_by_pool_and_plan_kind`；
    - `test_status_text_covers_every_status`。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** `feat: compare rule, agent and actual tracks per unit`。

### Task 6：对比取数、周度 `review-4` 与对比接口

**Files:**
- Modify：`investment_assistant/workbench/repository.py`、`investment_assistant/workbench/service.py`、`investment_assistant/workbench/review.py`、`investment_assistant/api/routes/workbench.py`
- Test：`tests/test_workbench_service.py`、`tests/test_workbench_review.py`、`tests/test_workbench_api.py`

**Interfaces:**
- Consumes：Task 5 的全部函数；已有的 `rule_plan`、`agent_plan`、`latest_agent_run`、`decision_head`、`plan_by_id`、`list_trades`、`split_events`、`read_bars`、`pool_entry_at`、`_book`、`review.pool_of`。
- Produces:
  - `repository.track_units(conn, since: date, until: date) -> list[dict]`：返回 `[{'ticker', 'signal_date'}]`，是窗口内有 `rule` 计划或有 `mode='propose'` 运行的单元的并集，按 `(signal_date, ticker)` 排序。
  - `service._track_rows(conn, since: date, until: date, *, session: date, now: datetime) -> list[dict]`：每个单元一行，键见 spec §4.4（`pool` 由 `review.pool_of` 判定）。同一事务内按标的缓存 K 线和账本。
  - `service.tracks(*, now: datetime, since: date | None = None, until: date | None = None) -> dict`：返回 `{'session', 'since', 'until', 'calc_version': 'tracks-1', 'units': rows, 'summary': tracks.summarize(rows)}`。默认 `since = session − 90 天`、`until = session`。
  - `review.weekly_stats(..., tracks: dict | None = None)`：新键 `tracks`（`{'units', 'summary'}`）；`CALC_VERSION = 'review-4'`。`generate_weekly` 传入该周的 `_track_rows`。
  - 路由 `GET /api/workbench/review/tracks?since=&until=`：日期用 `_date` 解析，非法时 400，`since > until` 时 400。

- [ ] **Step 1: 写失败测试**
  - SQL：`test_track_rows_trace_ids`：一个单元有规则计划和 Agent `ok` 计划，你照 Agent 计划成交；另一个单元被忽略。断言两行的 `rule.plan_id`、`agent.run_id`、`agent.plan_id`、`actual.decision_id`、`actual.buy_trade_ids`，以及 `actual.plan_kind == 'agent'`、被忽略单元的实际 R 为 0。
  - SQL：`test_track_units_include_agent_only_unit`：规则因 ATR 跳过、只有 `propose` 运行的单元也在集合里。
  - SQL：`test_track_units_ignore_interpret_runs`。
  - SQL：`test_weekly_snapshot_has_tracks`：`calc_version == 'review-4'`，`stats['tracks']['summary']['all']['actual']['units'] == 2`。
  - review：`test_weekly_stats_without_tracks_keeps_shape`。
  - API：`test_tracks_route_bad_date_400`、`test_tracks_route_since_after_until_400`、`test_tracks_route_passes_dates`（monkeypatch `service.tracks`）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_review.py tests/test_workbench_api.py`。
- [ ] **Step 5: 提交** `feat: add track comparison to weekly reviews and the API`。

### Task 7：月度 `monthly-2`

**Files:**
- Modify：`investment_assistant/workbench/monthly.py`、`investment_assistant/workbench/service.py`
- Test：`tests/test_workbench_monthly.py`、`tests/test_workbench_service.py`

**Interfaces:**
- Consumes：Task 6 的 `_track_rows`、`tracks.summarize`。
- Produces:
  - `MONTHLY_VERSION = 'monthly-2'`。
  - `monthly.month_end_snapshot(snapshots: list[dict], month: date) -> dict | None`：`_usable` 的公开名，供 Task 9 使用。
  - `monthly.review_detail(last_three: list[dict]) -> dict`：返回 `{'flag': review_flag(...), 'months': [{'month', 'return', 'spy_return'}], 'compound': float | None, 'spy_compound': float | None}`。每项输入带 `month`（ISO 字符串）。
  - `generate_monthly`：
    - `per_month` 每项加 `month`；
    - `rs` 改为 `(closed_at, r)` 列表，排序后取 r；
    - `stats` 保留 `review_flag`，新增 `review`；
    - `sensitivity = {'approximate': True, 'count': len(rs), 'rows': …}`；
    - 新增 `tracks`（该月信号日窗口）。

- [ ] **Step 1: 写失败测试**
  - `test_review_detail_compounds`：+2%、−5%、+1% 对 SPY +1%、+1%、+1%，断言 `compound`、`spy_compound` 与 `flag == 'review'`。
  - `test_review_detail_missing_month_nulls`。
  - SQL：`test_monthly_sensitivity_ordered_by_close_time`：两只标的，按平仓时间先后为 A(+2R)、B(−3R)、A(+1R)。期望回撤 3R × 比例；`monthly-1` 的拼接顺序（A、A、B）会得到不同结果。
  - SQL：`test_monthly_snapshot_has_tracks_and_detail`：`calc_version == 'monthly-2'`。
  - SQL：`test_monthly_missing_start_snapshot_stays_missing`：只有月末快照时，`return.status == 'missing_snapshot'`，`tier` 为空（Review Focus 5）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_workbench_monthly.py`。
- [ ] **Step 5: 提交** `feat: add review detail, ordered sensitivity and tracks to monthly reviews`。

### Task 8：推送数据、到期周期与模板

**Files:**
- Create：`investment_assistant/workbench/review_digest.py`
- Modify：`investment_assistant/notify/templates.py`
- Test：`tests/test_workbench_review_digest.py`

**Interfaces:**
- Consumes：快照行（`weekly_reviews` / `monthly_reviews` 的列，`stats` 为 `review-3`/`review-4` 或 `monthly-1`/`monthly-2`）；`bars.latest_closed_session`；`calendar.add_trading_days`、`trading_days_between`；`templates._clip_field`、`_fit_message`、`_footer`。
- Produces（`review_digest.py`，纯函数）:
  - `due_week(now: datetime) -> date`、`due_month(now: datetime) -> date`：算法见 spec §6.1。
  - `last_session(start: date, end: date) -> date`：区间内最后一个交易日。
  - `reminder_due(month: date, now: datetime) -> bool`：北京日期 ≥ 次月第一个周六。
  - `weekly(review: dict, *, public_url: str) -> dict`：返回 `{'kind': 'weekly', 'period', 'start', 'end', 'overview': {'decided', 'undecided', 'unsignaled', 'closed'}, 'tracks': {'rule', 'agent', 'actual'} | None, 'rules': [{'pool', 'rule_id', 'triggers', 'plans', 'filled', 'r_mean'}], 'discipline': {'chase', 'early_take', 'held_loser', 'unplanned', 'compliance_rate'} | None, 'note', 'evidence', 'url'}`。`tracks` 取 `stats.tracks.summary.all`，快照没有 `tracks` 时为 `None`。
  - `monthly(review: dict, *, public_url: str) -> dict`：返回 `{'kind': 'monthly', 'period', 'month': 'YYYY-MM', 'return', 'tier', 'spy', 'review': {'flag', 'compound', 'spy_compound'}, 'sensitivity': {'count', 'rows'}, 'tracks', 'discipline', 'note', 'evidence', 'url'}`。`monthly-1` 快照没有 `review` 时，只填 `flag`。
  - `reminder(month: date, *, public_url: str) -> dict`：返回 `{'kind': 'monthly_reminder', 'period', 'month', 'url'}`。
- Produces（`templates.py`）：`workbench_weekly(payload) -> list[Notification]`、`workbench_monthly(payload) -> list[Notification]`、`workbench_review_reminder(payload) -> list[Notification]`。标题、字段名与每行写法逐字取 spec §6.2。`tracks` 为 `None` 时，「轨道对比」字段写「该快照无轨道对比」。

- [ ] **Step 1: 写失败测试**
  - 到期周：
    - `test_due_week_after_friday_close`：北京时间周六 08:00，返回本周一；
    - `test_due_week_midweek_is_previous_week`；
    - `test_due_week_good_friday`：周五休市时，周四收盘后到期。
  - 到期月：
    - `test_due_month_after_last_session`；
    - `test_due_month_month_ends_on_weekend`。
  - 提醒：`test_reminder_due_first_saturday`：2026-11 的第一个周六是 11-07，11-06 不到期，11-07 到期。
  - 文案：
    - `test_weekly_lines`：断言「已决定 2 · 未处理 1」、「实际 2 单元 · 已定 2 · 均值 +1.00R」、「实际：未执行 1（记 0R）」、「描述性统计」与 `#review/weekly`；
    - `test_weekly_without_tracks_says_so`；
    - `test_monthly_missing_snapshot_line`：「缺资金快照，无法计算」（Review Focus 5）；
    - `test_monthly_review_flag_lines`：三种写法；
    - `test_monthly_v1_snapshot_renders`；
    - `test_reminder_text`。
  - 限制：`test_review_messages_within_discord_limits`：40 条规则行、每行 200 字时，每条消息 ≤ 6000 字符，每个字段 ≤ 1024 字符。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_notifier.py`。
- [ ] **Step 5: 提交** `feat: render weekly and monthly review pushes`。

### Task 9：复盘推送编排、定时任务与推送接口

**Files:**
- Create：`investment_assistant/tasks/workbench_review.py`
- Modify：`investment_assistant/tasks/scheduler.py`、`investment_assistant/workbench/repository.py`、`investment_assistant/workbench/service.py`、`investment_assistant/api/routes/workbench.py`
- Test：`tests/test_workbench_review_push.py`、`tests/test_scheduler.py`、`tests/test_workbench_api.py`

**Interfaces:**
- Consumes：Task 8 的全部函数；Task 7 的 `monthly.month_end_snapshot`；已有的 `generate_weekly`、`generate_monthly`、`weekly_head`、`monthly_head`、`list_snapshots`、`list_flows`、`notifier.send_notifications`、`load_config().workbench.public_url`、`macro.redact`。
- Produces:
  - repository：
    - `insert_review_push(conn, row: dict) -> dict`；
    - `review_push_sent(conn, kind: str, period: date) -> bool`：只看 `sent = true` 的行；
    - `list_review_pushes(conn, limit: int) -> list[dict]`；
    - `latest_account_record_at(conn) -> datetime | None`：资金快照 `recorded_at` 与出入金 `recorded_at`、`voided_at` 中的最大值。
  - service：
    - `push_review(kind: str, period: date, *, now: datetime, notify_cfg, trigger_source: str = 'manual', client=None) -> dict`：推送该周期快照链的最新一份，写一行 `review_pushes`，返回 `{'kind', 'period', 'review_id', 'sent', 'messages', 'reason'?}`。`kind` 不合法或 `period` 格式不对时抛 `ledger.LedgerError`；没有快照时抛 `ledger.NotFound`。`reason` 用 `redact` 脱敏。
    - `review_tick(*, now: datetime, notify_cfg, trigger_source: str, client=None) -> dict`：spec §6.1 的周度与月度流程，返回 `{'weekly': {...}, 'monthly': {...}, 'errors': [...]}`。每个部分含 `period`，以及 `action ∈ {'already_sent', 'reused', 'generated', 'reminded', 'waiting', 'error'}` 和推送结果。
    - `list_review_pushes(limit: int = 20) -> list[dict]`。
  - `tasks/workbench_review.run(config=None, *, trigger_source='scheduled', now=None, client=None)`：通过 `run_task('workbench_review', …, notify=False)` 调用 `review_tick`。`REGISTRY['workbench_review'] = workbench_review.run`。
  - 路由：
    - `GET /api/workbench/review-pushes?limit=`：`limit` 取 1–100，默认 20；
    - `POST /api/workbench/review-pushes`：请求体 `{kind, period}`，`LedgerError` → 400，`NotFound` → 404。

- [ ] **Step 1: 写失败测试**（SQL，Discord 用替身客户端记录发送内容）
  - 周度：
    - `test_tick_generates_and_pushes_weekly`：周六 08:00 时无快照，自动生成（备注「自动生成」）并推送一条，`review_pushes` 一行 `sent = true`；
    - `test_tick_reuses_snapshot_generated_after_close`；
    - `test_tick_supersedes_snapshot_generated_before_close`：周三生成的快照被新快照更替，推送的是新快照（Review Focus 4）；
    - `test_tick_does_not_repeat_after_success`：第二次运行 `action == 'already_sent'`，没有发送（Review Focus 3）；
    - `test_tick_retries_after_send_failure`：替身第一次抛异常，第二次成功（Review Focus 3）；
    - `test_tick_task_disabled_retries_later`：`task_enabled` 为关时写入 `reason = 'task_disabled'`，开启后的下一次运行推送成功。
  - 月度：
    - `test_monthly_waits_then_reminds_once`：
      - 11-03 时缺快照，`action == 'waiting'`，不发送；
      - 11-07 时推送一条提醒；
      - 11-08 时不再提醒（Review Focus 5）。
    - `test_monthly_generated_after_snapshot_recorded`：录入 10 月末快照后的下一次运行，生成并推送月度快照。
    - `test_monthly_head_older_than_snapshot_is_superseded`。
  - 其他：
    - `test_manual_push_forces_resend`；
    - `test_manual_push_unknown_period_404`；
    - `test_push_reason_redacted`：替身异常文本含 webhook 地址，`reason` 中被替换。
    - `test_generation_conflict_recorded_and_retried`：`generate_weekly` 抛 `ledger.Conflict` 时，写入 `errors`、不推送，周度出错不影响同次运行的月度部分，下一次运行重试成功。
  - 调度器：`test_registry_has_workbench_review`。
  - API：`test_review_push_route_validation`（400 / 404）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现。** 周度和月度各在自己的事务里生成快照，生成和推送互不阻塞：周度出错不影响月度。
- [ ] **Step 4: 运行确认通过**，回归 `tests/test_scheduler.py tests/test_workbench_api.py tests/test_notifier.py`。
- [ ] **Step 5: 提交** `feat: schedule and push weekly and monthly review digests`。

### Task 10：前端

**Files:**
- Modify：`web/src/lib/workbench.ts`、`web/src/routes/Review.svelte`、`web/src/routes/Today.svelte`
- Test：`web/src/lib/workbench.test.ts`、`web/src/routes/Review.test.ts`、`web/src/routes/Today.test.ts`

**Interfaces:**
- Consumes：Task 6 与 Task 9 的接口；P3 的 `getAgentRun`。
- Produces（`workbench.ts`）:
  - 类型：
    - `TrackStatus`（联合类型）、`TrackResult { status: TrackStatus; r: number | null }`；
    - `TrackRow`（键同 spec §4.4）、`TrackStats`、`TrackSummary { all; core; extended }`；
    - `TracksView { session; since; until; calc_version; units: TrackRow[]; summary: TrackSummary }`；
    - `ReviewPush { id; kind; period; review_id; trigger_source; sent; messages; reason; created_at }`。
  - 常量 `TRACK_STATUS_TEXT`，与后端一致。
  - 函数：`getTracks(since?: string, until?: string)`、`getReviewPushes()`、`postReviewPush(kind: 'weekly' | 'monthly', period: string)`、`rText(r: number | null): string`（`+1.50R` 或 `—`）。
  - `Brief` 加 `prompt_version`、`model`。

- [ ] **Step 1: 写失败测试**
  - workbench：
    - `TRACK_STATUS_TEXT covers every status`；
    - `rText formats sign and null`。
  - Review：
    - `tracks tab shows summary by pool and unit rows`；
    - `track row agent run expands tool calls`：替身 `getAgentRun`；
    - `weekly card renders tracks when present and hides when absent`；
    - `monthly card shows review detail compound`；
    - `push button posts and shows latest push result`：显示「已推送」或失败原因。
  - Today：
    - `agent-1 brief collapses to pointer line`：只显示「解读见 Agent 建议」；
    - `interpret brief shows model name`。
- [ ] **Step 2: 运行确认失败**：`npx vitest run src/lib/workbench.test.ts src/routes/Review.test.ts src/routes/Today.test.ts`。
- [ ] **Step 3: 实现。** `TABS` 在「对照组」之后插入 `['tracks', '轨道对比']`；计划 id 链接到 `#instrument/{ticker}`；文案用中文；沿用现有表格与 `Drawer` 样式。
- [ ] **Step 4: 运行确认通过**；构建检查：`npx vite build --outDir ../.local/us-workbench/build-review`。
- [ ] **Step 5: 提交** `feat: show track comparison and review pushes in the workbench UI`。

### Task 11：端到端场景、文档与回归

**Files:**
- Modify：`tests/test_workbench_scenarios.py`、`docs/us-workbench.md`、`docs/roadmap/v2-progress.md`

- [ ] **Step 1: 写场景测试** `test_review_expansion_end_to_end`，用合成数据与 `scripted_model` 跑通以下流程，断言每一步的关键字段：
  1. 两只核心标的同一周触发买入，另一只持仓触发卖出；
  2. 批处理：A 的 Agent 建议为 `ok`，B 为 `pass`，持仓得到 `interpret` 解读，不调用 Codex；
  3. 采纳 A，执行依据选 Agent 计划，录入买入并在 T1 卖出；B 选忽略；
  4. 推进 K 线，让规则与 Agent 计划都有结果；
  5. 周六 08:00 运行 `review_tick`：生成 `review-4` 快照，`tracks` 中 A 的实际 R 等于成交算出的值、B 的实际 R 为 0、两行 id 都可追溯；推送替身收到一条周度消息；
  6. 同一天再次运行，不重复推送；
  7. 录入月初与月末资金快照后，下一次运行生成 `monthly-2` 并推送；
  8. `GET /api/workbench/review/tracks` 与快照中的单元行一致。
- [ ] **Step 2: 运行确认通过。**
- [ ] **Step 3: 更新文档（DoD）**
  - `us-workbench.md`：
    - 删掉 `WORKBENCH_LLM_PROVIDER` / Codex 那一段，改写为「解读由 Agent 轨道产出」；
    - 新增「轨道对比」一节：口径（spec §4.2 表）、接口、页面、验证示例；
    - 新增「复盘推送」一节：定时任务与默认关闭、到期规则、手动入口（`POST /api/jobs/workbench_review/run`、`POST /api/workbench/review-pushes`、页面按钮）、验证入口（`job_reports` 中 `workbench_review` 的 `summary`、`GET /api/workbench/review-pushes`）、验证示例；
    - 「上线前提」增加迁移 020，以及开启 `workbench_review`。
  - `v2-progress.md`：记录 P4 `engineering_done`、`runtime_unverified` 与提交号。
- [ ] **Step 4: 全量回归**：后端 `... pytest tests -q`、前端 `npx vitest run` 与 `npx svelte-check`。报告通过、跳过与失败数；无测试库时注明 SQL 用例跳过。
- [ ] **Step 5: 提交** `test: verify P4 review expansion end to end`。

## 3. 依赖关系

按任务编号串行执行。各任务的直接依赖：

| 任务 | 依赖 |
| --- | --- |
| T2、T3 | T1 |
| T4 | T2、T3 |
| T5 | T1 |
| T6 | T3、T5 |
| T7 | T6 |
| T8 | T6、T7 |
| T9 | T8 |
| T10 | T4、T6、T9 |
| T11 | 全部 |

## 4. 完成标准

- 全部任务提交，后端与前端测试通过（有测试库时 SQL 用例通过，否则如实记为跳过）。
- `us-workbench.md` 满足 DoD 四项；仓库中已没有 Codex 解读的代码与环境变量说明（归档文档除外）。
- 以下事项都没有做，留到 P4 验收时另行授权：对真实库执行迁移 020、开启 `workbench_review`、发送真实 Discord、重启服务。执行迁移前先 `pg_dump` 备份；与 019 一样，用 `psql --single-transaction` 执行，不走 `migrate` 入口。
- P4 退出条件（roadmap §5）在验收时核对：
  - 完成一次完整的月度复盘并推送：`review_pushes` 中有一行 `monthly` 且 `sent = true`，Discord 内容与 `monthly-2` 快照一致；
  - 三方对比可追溯到每份计划：快照 `tracks.units` 中每一行的计划、运行、决定、成交 id 都能在对应接口查到。
