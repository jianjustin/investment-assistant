# Roadmap v2 进度

> 活文档，接替 v1 的 [08 活路线](../archive/roadmap-v1/08-living-collaboration.md)。路线本身见 [v2-decision-loop.md](v2-decision-loop.md)。
> 本文不授权补采、真实库迁移、通知、部署或交易；这些动作单独点名。

## 当前阶段

| 阶段 | 状态 | 下一步 |
| --- | --- | --- |
| P1 规则计划与推送 | `engineering_done`；真实库已迁移 017、服务已重载，页面与接口已检查；推送暂关（待你确认后开启）；`user_acceptance_pending` | 确认后开启 `workbench` 推送；出现第一个买入单元时核对计划价位与推送内容 |
| P2 观察池扩展与市场环境 | `engineering_done`；验收复核修复已提交；真实库已迁移 018，8 只美股全部标为核心，服务已重载，手动批处理与页面已检查；`FRED_API_KEY` 已配置并采集成功；`user_acceptance_pending` | 10-27（周二）06:30 定时运行后核对推送中的市场环境字段（含 HY OAS、2s10s）与计划行；扩大观察池（≥ 20 只有 200 根 K 线）后区制才会脱离「样本不足」 |
| P3 Agent 轨道 | 工程完成并经验收复核修复（`engineering_done`，`runtime_unverified`） | 运行时验收另行授权：迁移 019、检查点建表、配置 `ZHIPU_API_KEY`、核对真实端点与额度错误码 |
| P4 复盘扩展 | 未开工 | 依赖 P1，三方对比依赖 P3 |

## 起点（2026-10-23）

- 美股投研工作台（采集 → 信号 → 复盘）已在 `main` 落地并在本机运行：`engineering_done`，真实运行已验证，`user_acceptance_pending`。见 [使用文档](../us-workbench.md)。
- 真实库已执行迁移 `015`、`016`（执行前 `pg_dump` 备份）；`workbench` 每日任务已启用（北京时间周二至周六 06:30）。
- Phase 0 正式信号 Gate 全部 HOLD（[v1 评审](../archive/roadmap-v1/reports/2026-10-17-phase0-review.md)）。
- `main` 上的工作台与文档提交尚未推送到远端。

## 近期待办

从 v1 转入的未完成项：

1. 确认 SEC 只有一个调度器在跑：对照本机 LaunchAgent 的 `filings` 任务和 OpenClaw 的 dry_run 任务，避免双跑或都不跑。（10-23：OpenClaw 侧未核对。）
2. 用已有页面做一次跨市场只读验收，不新开调度器、不补采、不发通知。（10-23：未做。）
3. 美股工作台四周使用观察：在「今日」处理决策单元，每周生成一次周度复盘。（10-23 开始。）

v2 新增：

4. 写 P1「规则计划与推送」spec。（10-23：已批准。）
5. 审阅 P1 实施计划并开始实施。（10-23：已完成实施。）
6. P1 验收：对真实库执行迁移 017（先 `pg_dump`）、开启推送并页面验收。（10-23：迁移与页面检查完成；推送待确认。）
7. 开启工作台推送：在「设置」把任务 `workbench` 打开（10-23 为避免重载后自动推送而关闭）。（10-24：已打开，频道 `signals`。）
8. 配置 Discord `signals` webhook：当前没有任何 webhook（库内设置与环境变量均为空），工作台推送会以 `send_failed` 记入运行报告。需在「设置 → 通知」填写后，用「测试」或「重新推送今日计划」验证。（10-24：已填写；强制推送成功，见阶段证据。）
7. 审阅 P2 spec 与实施计划（11 个任务）。（10-23：已写，待审阅。）
9. P2 工程完成：迁移 018、观察池分层、FRED 采集、区制快照、计划 context、今日/推送/周度分池、上线前检查、前端（提交 `9d67da2` 起见 P2 计划各任务提交）。`engineering_done`；`runtime_unverified`——未对真实库执行迁移 018、未配置真实 `FRED_API_KEY`、未扩大真实观察名单、未发真实推送，待 P2 验收时另行授权（执行迁移前 `pg_dump` 备份）。（10-24：验收复核修复 `69715a5`；迁移 018 已执行、观察名单 8 只美股标为核心、服务已重载，见阶段证据。）

10. 审阅 P3 spec 与实施计划（11 个任务）。（10-24：已写，待审阅。）
11. P3 工程完成（Task 1–11：迁移 019、Agent 工具层、建议校验与 Agent 计划、智谱模型接入、LangGraph 图、批处理 Agent 阶段与手动运行、决定与纪律、今日与接口、推送、前端、端到端场景与文档）。`engineering_done`；`runtime_unverified`——未对真实库执行迁移 019、未建真实检查点表、未配置真实 `ZHIPU_API_KEY`、未调用真实智谱接口、未发真实推送，待 P3 验收时另行授权（执行迁移前 `pg_dump` 备份）。（10-24：提交 `2a75616` 起见 P3 计划各任务提交；10-25：验收复核修复 `8390c1b`。）

## 阶段证据

每完成一项，在这里记日期、提交和验证方式。

| 日期 | 事项 | 证据 |
| --- | --- | --- |
| 2026-10-23 | roadmap v2 确认，v1 归档 | 本目录 |
| 2026-10-23 | P1 设计逐项确认 | [P1 spec](../superpowers/specs/2026-10-23-p1-rule-plans-and-push-design.md) |
| 2026-10-23 | P1 实施计划写成（14 个任务） | [P1 实施计划](../superpowers/plans/2026-10-23-p1-rule-plans-and-push.md) |
| 2026-10-23 | P1 工程完成（Task 1–14，提交 `0caf127`…见该计划各任务提交；前端完成于 `c2adc45`；终审修复 `a923e6c`） | 端到端场景测试 `tests/test_workbench_scenarios.py::test_plan_to_monthly_review_end_to_end`；[使用文档](../us-workbench.md) P1 四节 |
| 2026-10-23 | P1 复核修复：月度收益只用上月与本月的快照、自定计划按自定入场区间计仓位、过早止盈只看持有期内的 T1 | 新增 4 个回归测试；全量后端 1129 通过（含一次性库 SQL），前端 201 通过（Node 26 需 `NODE_OPTIONS=--no-experimental-webstorage`） |
| 2026-10-23 | P2 四项设计确认（分层存数据库观察名单、区制只看广度且仅提示、扩展池只影子跟踪、FRED 官方 API + 密钥），spec 与实施计划写成（11 个任务），待审阅 | [P2 spec](../superpowers/specs/2026-10-23-p2-pool-and-market-context-design.md)、[P2 实施计划](../superpowers/plans/2026-10-23-p2-pool-and-market-context.md) |
| 2026-10-23 | P1 运行验收（部分） | 备份 `.local/us-workbench/backups/investment_assistant-before-017-20261023-202915.dump`（sha256 `8542b9d5…`）；迁移 017 已执行，5 张新表为空、`signal_decisions.plan_id` 已加，旧行未动；`web/dist` 先备份到 `.local/us-workbench/dist-backup-20261023-203002` 再构建；服务重载后手动批处理成功（9 只财报日期入库、无报错、未推送）；「今日」「复盘 → 资金 / 月度复盘」页面与新接口均正常。未覆盖：当日无买入单元，真实数据上的计划价位与持仓止损尚未出现；推送未开启 |
| 2026-10-24 | 开启 `workbench` 推送（频道 `signals`） | 10-24 06:30 的定时运行仍为 `task_disabled`；下一次定时运行为 10-27（周二）06:30。`signals` webhook 未配置，推送尚不能送达 |
| 2026-10-24 | `signals` webhook 已配置，强制推送验证送达 | `POST /api/workbench/push` 返回 `sent: true`、4 条消息、频道 `signals`（交易日 2026-10-23，当日无买入计划）；Discord 接口已接受，频道内显示待你确认 |
| 2026-10-24 | P2 工程完成（Task 1–11：迁移 018 四张新表、pool/macro/regime/backcheck 模块、批处理接池与环境、计划 context 冻结、今日与推送扩展、review-3 分池、上线前检查、前端与文档） | 端到端场景 `tests/test_workbench_scenarios.py::test_pool_and_context_end_to_end`；[使用文档](../us-workbench.md) P2 三节；各任务提交见 [P2 实施计划](../superpowers/plans/2026-10-23-p2-pool-and-market-context.md) ledger |
| 2026-10-24 | P2 运行验收（部分） | 复核修复 `69715a5`（分池只计规则计划、FRED 状态文案、扩展池计划状态、历史检查同日多规则）；备份 `.local/us-workbench/backups/investment_assistant-before-018-20261024-104613.dump`（sha256 `99c110dd…`）；迁移 018 已执行，四张新表建好且为空、旧表未动；观察名单 8 只 active 美股经写入接口加 `core` 标签（原标签保留）；`web/dist` 先备份到 `.local/us-workbench/dist-backup-20261024-104707` 再构建；服务重载后手动批处理成功（`pool` 核心 8 / 扩展 0、`pool_tiers` 8 行、SMH/XLK/QQQ 日线各 290 根、FRED `not_configured`、区制快照 `inserted` 标签「样本不足」（MA200 合格样本 8 < 20）、`sources` 全空、总耗时 19.7 秒、未推送）；「今日」市场环境卡片与「设置 → 关注列表」（美股池 8/100 · 核心 8/15）正常。未覆盖：P2 推送内容（下次定时运行 10-27）、真实 FRED、扩展池、100 只规模耗时 |
| 2026-10-24 | 配置 `FRED_API_KEY`（写入 `.env`），服务重载后手动批处理 | FRED 直连验证可用；批处理 `macro`：BAMLH0A0HYM2 写入 86 条（至 10-22）、T10Y2Y 写入 84 条（至 10-23），`sources.fred` 为空、无错误；运行报告与服务日志均不含密钥。10-23 区制快照已在 FRED 未配置时写入，本次按设计记为 `conflict`（`market_regime`）不覆盖，所以「今日」卡片在下一个交易日快照前仍显示「FRED 未配置」 |
| 2026-10-24 | P3 四项设计确认（智谱 `glm-5.3`、不设每日 token 上限但额度用尽即停 Agent 轨道、Agent 看不到规则价位、扩展池跑但排在后面），spec 与实施计划写成（11 个任务），待审阅 | [P3 spec](../superpowers/specs/2026-10-24-p3-agent-track-design.md)、[P3 实施计划](../superpowers/plans/2026-10-24-p3-agent-track.md) |
| 2026-10-24 | P3 工程完成（Task 1–11 与终审修复，提交 `2a75616`…`2067af2`；全量后端 1332 在一次性库上通过、前端 234 与 svelte-check 通过） | 端到端场景 `tests/test_workbench_scenarios.py::test_agent_track_end_to_end` 与 `web/src/workbench-scenarios.test.ts`；[使用文档](../us-workbench.md)「Agent 轨道」一节与上线前提 2d/已知限制；未做：真实库迁移 019、检查点建表、`ZHIPU_API_KEY` 配置与真实接口核对（P3 验收时另行授权） |
| 2026-10-25 | P3 验收复核修复（提交 `8390c1b`）：「今日」规则计划缺失或作废时执行依据可选 Agent 或自定价位，Agent 价位旁显示可展开的引用；推送概览 Agent 计数只算本交易日无冲突买入单元；`agent_runs` 新增 `detail` 列（迁移 019 内，尚未在真实库执行）保存 `error` 运行脱敏后的异常文本。全量后端 1336 在一次性库上通过、前端 237 与 svelte-check 通过 | 离线验收：本地桩接口 + 真实 `ChatOpenAI` + `PostgresSaver` 跑通建议/反方/额度 429 识别；未做：运行时验收（同上）。前端在 Node 26 下需 `NODE_OPTIONS=--no-experimental-webstorage` |
