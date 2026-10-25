# Agent 轨道

每个买入单元在规则主计划旁并列一条 Agent 建议；卖出、观察和有冲突的单元，由 Agent 生成只读解读。Agent 是**挑战者**：只做影子跟踪、并列展示，不改主计划。

设计：[P3 Agent 轨道](../specs/2026-10-24-p3-agent-track-design.md)、[P4 复盘扩展](../specs/2026-10-25-p4-review-expansion-design.md)（解读并入 Agent 轨道）。

## 怎么工作

- **运行时**：LangGraph，默认模型智谱 `glm-5.3`（OpenAI 兼容接口），检查点存在本库（PostgresSaver）。
- **工具层**（`workbench/agent/tools.py`）：八个普通 Python 函数，只能读运行截止时间之前的数据，只允许查单元自身的标的和 SPY/SMH/XLK/QQQ，不接受日期参数。截止时间由批处理传入，模型无法修改。每次调用的参数、返回值和 SHA-256 都写入 `agent_tool_calls`。
- **提议（`propose`）**：独立给出动作、入场区间、止损、T1，以及带引用的理由。每个价位和理由都要引用一次已写库的工具调用（`call:N`）；引用不存在，或价位找不到价格类工具支撑，整条作废（`rejected / invalid_citation`），只显示原因、不显示内容。还要通过基本校验，比如买入的止损必须低于入场。
- **反方**：专门找反证、核对引用和数字，结果写进风险提示，不改价位和动作。
- **Agent 计划**：结果为 `ok` 的建议生成 `agent` 计划（`agent-1`），有效期和移动止损与 `plan-1` 相同，仓位按入场区间中点计算，并进入影子跟踪。采纳时可以把执行依据选为「Agent 建议」。
- **解读（`interpret`，`agent-brief-1`）**：无冲突买入单元的解读，直接取提议的摘要和反方；其余单元单独跑一次单阶段解读。模型不可用或校验失败时，退回规则版摘要。
- **隔离**：Agent 在规则计划全部写入之后才开始，失败只影响 Agent 轨道。每个单元最多尝试 3 次（超过记 `skipped / max_attempts`）；批处理开始 1500 秒后不再启动新单元；智谱额度用尽时其余单元记 `skipped / quota_exhausted`；达到每日 token 上限时记 `skipped / token_budget`。扩展池单元也跑，但排在后面，结果不推送。

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
- API：`GET /api/workbench/agent-runs?since=`（运行列表与覆盖率 `coverage`）、`GET /api/workbench/agent-runs/{id}`（详情和全部工具调用）、`POST /api/workbench/agent-runs`（body `{ticker, signal_date}`；已有 `ok`/`pass` 返回 409，不是买入单元返回 400）。
- 命令行：`python -m investment_assistant.workbench.agent run --ticker X --date YYYY-MM-DD`。
- 运行报告：`summary.agent`（`{runs, tokens, quota_exhausted}`）、`summary.sources.agent`、`summary.timings.agent`；`error` 状态的运行带脱敏后的 `detail`。
- 验证一次：跑完批处理后 `GET /api/workbench/agent-runs`，`coverage.missing` 应为空；任选一个买入单元，Agent 卡片上每个价位旁都有引用编号，点开能看到工具调用和哈希。

## 已知限制

- 额度错误码（`1113`、`1308`、`1310`）和端点是按文档初值写的，需要拿真实响应核对（看 `error` 运行的 `detail`）。
- 模型输出格式不保证稳定：带围栏的 JSON 和数字字符串已做兼容；JSON 里夹带说明文字的，作废为 `malformed`。
- Agent 价位来自模型输出，不构成投资建议；证据状态仍是「未验证」。目前不设晋升机制，只观察，不安排用 Agent 替换主计划。
