# Agent 轨道

每个买入单元在规则主计划旁并列一条 Agent 建议；卖出、观察和有冲突的单元，由 Agent 生成只读解读。Agent 是**挑战者**：只做影子跟踪、并列展示，不改主计划。

设计：[P3 Agent 轨道](../specs/2026-10-24-p3-agent-track-design.md)、[P4 复盘扩展](../specs/2026-10-25-p4-review-expansion-design.md)（解读并入 Agent 轨道）、[v2.5 计划时间线](../specs/2026-10-28-v2.5-plan-timeline-design.md)（`agent-2` 结构与版本链）。

## 怎么工作

- **运行时**：LangGraph，默认模型智谱 `glm-5.3`（OpenAI 兼容接口），检查点存在本库（PostgresSaver）。
- **工具层**（`workbench/agent/tools.py`）：八个普通 Python 函数，只能读运行截止时间之前的数据，只允许查单元自身的标的和 SPY/SMH/XLK/QQQ，不接受日期参数。截止时间由批处理传入，模型无法修改。每次调用的参数、返回值和 SHA-256 都写入 `agent_tool_calls`。
- **提议（`propose`，`agent-2`）**：独立给出动作、入场区间、止损、T1，以及下面几项结构化字段。每个价位和论点都要引用一次已写库的工具调用（`call:N`）；引用不存在，或价位找不到价格类工具支撑，整条作废（`rejected / invalid_citation`），只显示原因、不显示内容。还要通过基本校验，比如买入的止损必须低于入场。任一字段校验不过，整版作废：
  - **论点** `thesis`：1–3 条，每条带引用，宿主按顺序编号 `T1…T3`；条数不对 → `thesis_count`。
  - **失效条件** `invalidation`：1–5 条，取自条件集合（见下），每条带引用；**下次复查条件** `review_when`：0–3 条，留空等于「下一交易日」。`kind` 未登记、不能用在这一栏、参数不合法或缺引用 → `invalid_condition`。
  - **相对上版变化** `changes`：首版不填（填了 → `malformed`）；修订版必填，字段集合必须等于宿主算出的差异（`changes_mismatch`），没有差异 → `no_change`。修订只由每日复查生成。
- **条件集合 `condition-1`**（`agent/conditions.py`，失效与复查共用）：`close_below` / `close_above`（`price`）、`no_entry_by`（`date`，仅失效）、`no_entry_before_earnings`（仅失效）、`earnings_within`（`sessions` 1–10）、`regime_is`（`label`）、`sector_weak`、`rs_below`（`window` 20/60、`value`）、`new_filing`（`form` 8-K/10-Q/10-K）、`date_reached`（`date`，仅复查）、`next_session`（仅复查）。价格须在生成时最近收盘的 ±50% 内，日期须晚于本版生成交易日且不超过其后 60 天。每条判定为成立 / 未成立 / 无法判定，数据缺失一律「无法判定」，不当作成立。
- **反方**：逐条对论点给出反证（`counter: [{thesis, text, refs}]`），其余风险进 `risks`；引用不存在或论点编号不存在的条目丢弃并计数，没有反证的论点列入 `uncountered`。反方不改价位和动作。
- **Agent 计划与版本链**：结果为 `ok` 的首版生成 `agent` 计划（`plan_version = agent-2`），同一个事务里依次写计划行、运行行与工具调用、版本行 `agent_plan_versions`（`version_no = 0`、`origin = signal`、`cutoff_at` 等于运行的截止时间）和简报，任何一步失败都整体回滚，单元记 `error`。有效期 T+1…T+3、移动止损与 `plan-1` 相同，仓位按入场区间中点计算，`inputs` 另记 `as_of_session`、`version_no`、`supersedes_plan_id`、`chain_entry_cap`（入场期链上限：信号日后第 10 个交易日）。手动「重新运行 Agent」同样只生成首版；已有 `ok` / `pass` 时返回 409。首版计划进入影子跟踪和推导核对（`('agent-2', 'agent')`：价位核对 `agent_runs.output`，有效期按 `as_of_session` 与链上限推导，缺版本行 → `incomplete`）。采纳时可以把执行依据选为「Agent 建议」。
- **`agent-1` 旧版**：v2.5 之前生成的 `agent-1` 计划原样保留、只读，照常展示与影子跟踪，标「agent-1（旧版，不参与复查）」；不迁移、不回填、不进每日复查。
- **解读（`interpret`，`agent-brief-1`）**：无冲突买入单元的解读，直接取提议的摘要和第一条反证（`agent-1` 运行取反方风险）；其余单元单独跑一次单阶段解读。模型不可用或校验失败时，退回规则版摘要。
- **隔离**：Agent 在规则计划全部写入之后才开始，失败只影响 Agent 轨道。每个单元最多尝试 3 次（超过记 `skipped / max_attempts`）；批处理开始 1500 秒后不再启动新单元；智谱额度用尽时其余单元记 `skipped / quota_exhausted`；达到每日 token 上限时记 `skipped / token_budget`。扩展池单元也跑，但排在后面，结果不推送。
- **迁移 026 未执行**：写不了版本行，所以需要提议的单元逐个记 `skipped / migration_026_missing`（主列表单元照旧得到规则版简报），解读照常运行；`agent` 阶段记 `degraded`（`migration_026_missing`），`summary.errors` 加一条 `timeline: migration_026_missing`；规则计划照常。「今日」照旧按最新运行显示，不带链。

## 配置

| 环境变量 | 说明 |
| --- | --- |
| `WORKBENCH_AGENT_PROVIDER` | `zhipu`（默认）或 `off` |
| `ZHIPU_API_KEY` | 智谱密钥；只从环境变量读取，出现在错误文本里时一律替换为 `***` |
| `WORKBENCH_AGENT_MODEL` | 默认 `glm-5.3` |
| `WORKBENCH_AGENT_BASE_URL` | 默认 GLM Coding Plan 端点 `https://open.bigmodel.cn/api/coding/paas/v4` |
| `WORKBENCH_AGENT_DAILY_TOKENS` | 可选，每日 token 上限 |

首次使用前建检查点表：`python -m investment_assistant.workbench.agent setup`。

## 入口与验证

- 页面：「今日」的 Agent 建议卡片（引用编号可以展开，看到工具调用的参数、返回值和哈希前 8 位；失败时有「重新运行 Agent」）；「复盘 → 轨道对比」里点 Agent 运行 id。
- 「今日」接口（`GET /api/workbench/today`）：`agent-2` 单元的 `agent` 取**链的最新版**的运行与计划（不是最新一次运行），并带 `chain`（`version_no`、`head_plan_id`、`state`、`mode`、`basis`、`latest_review`）；`agent-1` 单元带 `legacy: true`。另有 `chains`（已决定买入、等待成交的入场期链与持仓期链：第几版、最近复查的结论 / 判定方 / 时间 / 理由前 40 字、当日触发的信号）、持仓行的 `has_chain`，以及 `timeline_ready`（迁移 026 是否就绪）。
- API：`GET /api/workbench/agent-runs?since=`（运行列表与覆盖率 `coverage`）、`GET /api/workbench/agent-runs/{id}`（详情和全部工具调用）、`POST /api/workbench/agent-runs`（body `{ticker, signal_date}`；已有 `ok`/`pass` 返回 409，不是买入单元返回 400）。
- 命令行：`python -m investment_assistant.workbench.agent run --ticker X --date YYYY-MM-DD`。
- 运行报告：`summary.agent`（`{runs, tokens, quota_exhausted}`）、`summary.sources.agent`、`summary.timings.agent`；`error` 状态的运行带脱敏后的 `detail`。
- 验证一次：跑完批处理后 `GET /api/workbench/agent-runs`，`coverage.missing` 应为空；任选一个买入单元，Agent 卡片上每个价位旁都有引用编号，点开能看到工具调用和哈希。

## 已知限制

- 额度错误码（`1113`、`1308`、`1310`）和端点是按文档初值写的，需要拿真实响应核对（看 `error` 运行的 `detail`）。
- 模型输出格式不保证稳定：带围栏的 JSON 和数字字符串已做兼容；JSON 里夹带说明文字的，作废为 `malformed`。
- Agent 价位来自模型输出，不构成投资建议；证据状态仍是「未验证」。目前不设晋升机制，只观察，不安排用 Agent 替换主计划。
