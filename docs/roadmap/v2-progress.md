# Roadmap v2 进度

> 已冻结（v2.0.0，2026-10-25）。之后只在「阶段证据」末尾追加验收记录；下一版的待办见 [backlog.md](backlog.md)。

> 活文档，接替 v1 的 [08 活路线](../archive/roadmap-v1/08-living-collaboration.md)。路线本身见 [v2-decision-loop.md](v2-decision-loop.md)。
> 本文不授权补采、真实库迁移、通知、部署或交易；这些动作单独点名。

## 当前阶段

| 阶段 | 状态 | 下一步 |
| --- | --- | --- |
| P1 规则计划与推送 | `engineering_done`；真实库已迁移 017、服务已重载，页面与接口已检查；推送暂关（待你确认后开启）；`user_acceptance_pending` | 确认后开启 `workbench` 推送；出现第一个买入单元时核对计划价位与推送内容 |
| P2 观察池扩展与市场环境 | `engineering_done`；验收复核修复已提交；真实库已迁移 018，8 只美股全部标为核心，服务已重载，手动批处理与页面已检查；`FRED_API_KEY` 已配置并采集成功；`user_acceptance_pending` | 10-27（周二）06:30 定时运行后核对推送中的市场环境字段（含 HY OAS、2s10s）与计划行；扩大观察池（≥ 20 只有 200 根 K 线）后区制才会脱离「样本不足」 |
| P3 Agent 轨道 | `engineering_done`；验收复核修复已提交；真实库已迁移 019、检查点表已建，`ZHIPU_API_KEY` 已配置并用真实端点跑通一次只读试跑，服务已重载，手动批处理成功；`user_acceptance_pending` | 观察池出现无冲突买入单元后核对第一条真实 `agent_runs`、Agent 计划与推送 Agent 行；额度类错误码（1113/1308/1310）待真实遇到时按 `detail` 核对；退出条件需连续两周 `coverage.missing` 为空 |
| P4 复盘扩展 | `engineering_done`；验收复核修复与「启用前月份不提醒」已提交；已并入 `main`；真实库已迁移 020、前端已构建、服务已重载，接口与页面已检查，真实周度推送一次成功；`workbench_review` 已开启（北京 08:00），手动运行一次结果符合预期；`user_acceptance_pending` | 10-31（周六）08:00 定时运行后核对 10-26 周的周度推送；出现第一个买入单元后核对三方对比与推送中的轨道行；10 月末录入月末资金快照后核对月度推送（未录入则 11-07 起提醒一次） |

## 起点（2026-10-23）

- 美股投研工作台（采集 → 信号 → 复盘）已在 `main` 落地并在本机运行：`engineering_done`，真实运行已验证，`user_acceptance_pending`。见 [使用文档](../features/daily-plan.md)。
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
11. P3 工程完成（Task 1–11：迁移 019、Agent 工具层、建议校验与 Agent 计划、智谱模型接入、LangGraph 图、批处理 Agent 阶段与手动运行、决定与纪律、今日与接口、推送、前端、端到端场景与文档）。`engineering_done`；`runtime_unverified`——未对真实库执行迁移 019、未建真实检查点表、未配置真实 `ZHIPU_API_KEY`、未调用真实智谱接口、未发真实推送，待 P3 验收时另行授权（执行迁移前 `pg_dump` 备份）。（10-24：提交 `2a75616` 起见 P3 计划各任务提交；10-25：验收复核修复 `8390c1b`；迁移 019 已执行、检查点表已建、服务已重载，见阶段证据。）

12. 审阅 P4 spec 与实施计划（11 个任务）。（10-25：已写，待审阅。）
13. P4 工程完成（Task 1–11：迁移 020（`agent_runs.mode`、`signal_briefs.agent_run_id`、`review_pushes`、`workbench_review` 任务行默认关闭）、解读校验与单阶段解读图、解读行由 Agent 运行构造并按 mode 过滤查询、Agent 阶段三组统一产出解读且 Codex 退役、三方对比纯函数、周度 `review-4` 与实时接口、月度 `monthly-2`（复查明细、按平仓时间排序的敏感性、tracks）、推送数据与模板、复盘推送编排与定时任务、前端轨道对比与推送按钮、端到端场景与文档）。`engineering_done`；`runtime_unverified`——未对真实库执行迁移 020、未开启 `workbench_review`、未发真实推送、未重启服务，待 P4 验收时另行授权（执行迁移前 `pg_dump` 备份，用 `psql --single-transaction` 执行，不走 `migrate` 入口）。（10-25：提交 `0d36add`…`d25c363` 与终审修复 `e4abfd0`；验收复核修复 `8850e69`；快进并入 `main`，P4 工作区与分支已删除；迁移 020 已执行、服务已重载，见阶段证据。）

## 阶段证据

每完成一项，在这里记日期、提交和验证方式。

| 日期 | 事项 | 证据 |
| --- | --- | --- |
| 2026-10-23 | roadmap v2 确认，v1 归档 | 本目录 |
| 2026-10-23 | P1 设计逐项确认 | [P1 spec](../specs/2026-10-23-p1-rule-plans-and-push-design.md) |
| 2026-10-23 | P1 实施计划写成（14 个任务） | [P1 实施计划](../plans/2026-10-23-p1-rule-plans-and-push.md) |
| 2026-10-23 | P1 工程完成（Task 1–14，提交 `0caf127`…见该计划各任务提交；前端完成于 `c2adc45`；终审修复 `a923e6c`） | 端到端场景测试 `tests/test_workbench_scenarios.py::test_plan_to_monthly_review_end_to_end`；[使用文档](../features/daily-plan.md) P1 四节 |
| 2026-10-23 | P1 复核修复：月度收益只用上月与本月的快照、自定计划按自定入场区间计仓位、过早止盈只看持有期内的 T1 | 新增 4 个回归测试；全量后端 1129 通过（含一次性库 SQL），前端 201 通过（Node 26 需 `NODE_OPTIONS=--no-experimental-webstorage`） |
| 2026-10-23 | P2 四项设计确认（分层存数据库观察名单、区制只看广度且仅提示、扩展池只影子跟踪、FRED 官方 API + 密钥），spec 与实施计划写成（11 个任务），待审阅 | [P2 spec](../specs/2026-10-23-p2-pool-and-market-context-design.md)、[P2 实施计划](../plans/2026-10-23-p2-pool-and-market-context.md) |
| 2026-10-23 | P1 运行验收（部分） | 备份 `.local/us-workbench/backups/investment_assistant-before-017-20261023-202915.dump`（sha256 `8542b9d5…`）；迁移 017 已执行，5 张新表为空、`signal_decisions.plan_id` 已加，旧行未动；`web/dist` 先备份到 `.local/us-workbench/dist-backup-20261023-203002` 再构建；服务重载后手动批处理成功（9 只财报日期入库、无报错、未推送）；「今日」「复盘 → 资金 / 月度复盘」页面与新接口均正常。未覆盖：当日无买入单元，真实数据上的计划价位与持仓止损尚未出现；推送未开启 |
| 2026-10-24 | 开启 `workbench` 推送（频道 `signals`） | 10-24 06:30 的定时运行仍为 `task_disabled`；下一次定时运行为 10-27（周二）06:30。`signals` webhook 未配置，推送尚不能送达 |
| 2026-10-24 | `signals` webhook 已配置，强制推送验证送达 | `POST /api/workbench/push` 返回 `sent: true`、4 条消息、频道 `signals`（交易日 2026-10-23，当日无买入计划）；Discord 接口已接受，频道内显示待你确认 |
| 2026-10-24 | P2 工程完成（Task 1–11：迁移 018 四张新表、pool/macro/regime/backcheck 模块、批处理接池与环境、计划 context 冻结、今日与推送扩展、review-3 分池、上线前检查、前端与文档） | 端到端场景 `tests/test_workbench_scenarios.py::test_pool_and_context_end_to_end`；[使用文档](../features/pool-and-context.md) P2 三节；各任务提交见 [P2 实施计划](../plans/2026-10-23-p2-pool-and-market-context.md) ledger |
| 2026-10-24 | P2 运行验收（部分） | 复核修复 `69715a5`（分池只计规则计划、FRED 状态文案、扩展池计划状态、历史检查同日多规则）；备份 `.local/us-workbench/backups/investment_assistant-before-018-20261024-104613.dump`（sha256 `99c110dd…`）；迁移 018 已执行，四张新表建好且为空、旧表未动；观察名单 8 只 active 美股经写入接口加 `core` 标签（原标签保留）；`web/dist` 先备份到 `.local/us-workbench/dist-backup-20261024-104707` 再构建；服务重载后手动批处理成功（`pool` 核心 8 / 扩展 0、`pool_tiers` 8 行、SMH/XLK/QQQ 日线各 290 根、FRED `not_configured`、区制快照 `inserted` 标签「样本不足」（MA200 合格样本 8 < 20）、`sources` 全空、总耗时 19.7 秒、未推送）；「今日」市场环境卡片与「设置 → 关注列表」（美股池 8/100 · 核心 8/15）正常。未覆盖：P2 推送内容（下次定时运行 10-27）、真实 FRED、扩展池、100 只规模耗时 |
| 2026-10-24 | 配置 `FRED_API_KEY`（写入 `.env`），服务重载后手动批处理 | FRED 直连验证可用；批处理 `macro`：BAMLH0A0HYM2 写入 86 条（至 10-22）、T10Y2Y 写入 84 条（至 10-23），`sources.fred` 为空、无错误；运行报告与服务日志均不含密钥。10-23 区制快照已在 FRED 未配置时写入，本次按设计记为 `conflict`（`market_regime`）不覆盖，所以「今日」卡片在下一个交易日快照前仍显示「FRED 未配置」 |
| 2026-10-24 | P3 四项设计确认（智谱 `glm-5.3`、不设每日 token 上限但额度用尽即停 Agent 轨道、Agent 看不到规则价位、扩展池跑但排在后面），spec 与实施计划写成（11 个任务），待审阅 | [P3 spec](../specs/2026-10-24-p3-agent-track-design.md)、[P3 实施计划](../plans/2026-10-24-p3-agent-track.md) |
| 2026-10-24 | P3 工程完成（Task 1–11 与终审修复，提交 `2a75616`…`2067af2`；全量后端 1332 在一次性库上通过、前端 234 与 svelte-check 通过） | 端到端场景 `tests/test_workbench_scenarios.py::test_agent_track_end_to_end` 与 `web/src/workbench-scenarios.test.ts`；[使用文档](../features/agent-track.md)「Agent 轨道」一节与上线前提 2d/已知限制；未做：真实库迁移 019、检查点建表、`ZHIPU_API_KEY` 配置与真实接口核对（P3 验收时另行授权） |
| 2026-10-25 | P3 验收复核修复（提交 `8390c1b`）：「今日」规则计划缺失或作废时执行依据可选 Agent 或自定价位，Agent 价位旁显示可展开的引用；推送概览 Agent 计数只算本交易日无冲突买入单元；`agent_runs` 新增 `detail` 列（迁移 019 内，尚未在真实库执行）保存 `error` 运行脱敏后的异常文本。全量后端 1336 在一次性库上通过、前端 237 与 svelte-check 通过 | 离线验收：本地桩接口 + 真实 `ChatOpenAI` + `PostgresSaver` 跑通建议/反方/额度 429 识别；未做：运行时验收（同上）。前端在 Node 26 下需 `NODE_OPTIONS=--no-experimental-webstorage` |
| 2026-10-25 | P3 运行验收（部分） | 备份 `.local/us-workbench/backups/investment_assistant-before-019-20261025-095614.dump`（sha256 `e10804a4…`）；`psql --single-transaction` 执行迁移 019（未经 `migrate` 入口：`schema_migrations` 无 018/019 记录，入口会重跑 018），`agent_runs`/`agent_tool_calls` 建好且为空、`trade_plans_kind_check` 含 `agent`、部分唯一索引与 `detail` 列在，旧表行数不变；`agent setup` 建 `checkpoints` 等 4 张表；端点 `open.bigmodel.cn/api/coding/paas/v4` 与 `glm-5.3` 可用，错误密钥返回 401 且错误体为 `{error: {code, message}}`（与解析一致）；真实密钥只读试跑 NVDA 10-22（不写库、内存检查点）：`pass`，15 次工具调用无报错、引用均有效、约 100 秒、输入 20586 / 输出 6903 token、结果不含密钥；`web/dist` 先备份到 `.local/us-workbench/dist-backup-20261025-100647` 再构建；服务重载后 `/api/workbench/agent-runs` 200，手动批处理 `workbench-20261025020759-43abf8cb` 成功（session 10-23，核心 8、无买入单元，`summary.agent.runs` 为空、`sources` 全空、`timings.agent` 0.0、总耗时 28.6 秒、未推送）；手动运行接口对非买入单元返回 400。未覆盖：真实买入单元的 Agent 运行与写库、Agent 计划、推送 Agent 行、额度用尽 |
| 2026-10-25 | P4 四项设计确认（Agent 统一解读、Codex 退役；周度自动生成并推送；月度每日检查、缺月末快照提醒一次；三方对比用同一批单元，未执行记 0R），spec 与实施计划写成（11 个任务），待审阅 | [P4 spec](../specs/2026-10-25-p4-review-expansion-design.md)、[P4 实施计划](../plans/2026-10-25-p4-review-expansion.md) |
| 2026-10-25 | P4 工程完成（Task 1–11 与终审修复，提交 `0d36add`…`d25c363`、终审修复 `e4abfd0`；全量后端 1430 在一次性库上通过（SQL 用例全部执行）、前端 247 与 svelte-check 通过） | 端到端场景 `tests/test_workbench_scenarios.py::test_review_expansion_end_to_end`；[使用文档](../features/review.md)「轨道对比」「复盘推送」两节、上线前提 2e 与第 3 条改写；未做：真实库迁移 020、开启 `workbench_review`、真实 Discord 推送、服务重载（P4 验收时另行授权，迁移前 `pg_dump` 备份） |
| 2026-10-25 | P4 验收复核修复（提交 `8850e69`）：实际轨道按单元整条决定链匹配买入成交，更正决定后不再丢成交；`monthly-1` 旧快照带复查标记时手动推送不再报 `TypeError`，改为不带复合数字的复查文案；周度推送规则行均值格式化为 `+0.53R`；周度与月度卡片显示该周期最近一次推送记录（定时或手动）。全量后端 1433 在一次性库上通过（0 跳过）、前端 248 与 svelte-check 通过 | 新增用例 `test_track_rows_keep_buys_after_decision_correction`、`test_monthly_v1_review_flag_without_compounds`、`test_weekly_rule_mean_is_formatted`、`Review.test.ts`「shows the latest recorded push beside each card」；未做：运行时验收（同上） |
| 2026-10-25 | P4 运行验收（部分） | 备份 `.local/us-workbench/backups/investment_assistant-before-020-20261025-131236.dump`（sha256 `39947d4d…`）；`psql --single-transaction` 执行迁移 020（未经 `migrate` 入口）：旧匿名约束 `agent_runs_check` 已替换为 `agent_runs_mode_plan_check`，新增 `agent_runs_interpret_no_pass_check`，`agent_runs.mode` 默认 `propose`、`signal_briefs.agent_run_id`、`review_pushes` 与两条索引都在，`workbench_review` 任务行为关闭；旧表行数不变（`signal_briefs` 4、`agent_runs` 0、`signal_decisions` 4）；`web/dist` 先备份到 `.local/us-workbench/dist-backup-20261025-131309` 再构建；服务重载后 `review-pushes`、`review/tracks`、`agent-runs`、`today`、周度与月度列表均 200，`review-pushes` 对 `limit=0` 与非周一 period 返回 400、对无快照周期返回 404；生成 10-19 周快照（`review-4`，已决定 4，tracks 为空：窗口内还没有规则计划或 propose 运行），手动推送到 Discord `signals` 成功（1 条消息，`review_pushes` 一行 `sent`）；页面「复盘 → 周度复盘」卡片显示「最近推送 … · 已推送 · 手动」，「轨道对比」标签正常加载、控制台无报错。未覆盖：`workbench_review` 定时运行与 `POST /api/jobs/workbench_review/run`（真实库无任何资金快照，首次运行会对 9 月推月度提醒）、月度推送、真实 interpret 运行与三方对比非空数据 | 同左 |
| 2026-10-25 | P4 启用前月份不提醒（提交 `fc6be8d`）：月度到期月缺月末快照时，若该月末之前既无决定也无资金快照，记 `before_start`、不提醒（真实库最早决定为 10-23，否则首次运行会对 9 月推提醒）。全量后端 1436 在一次性库上通过（0 跳过）；服务重载后开启 `workbench_review`，手动运行 `workbench_review-20261025052032-bddc3908`：`success`，`weekly.action = already_sent`（10-19）、`monthly.action = before_start`（09-01）、`errors` 为空，未发新消息（`review_pushes` 仍 1 行） | 新增用例 `test_monthly_no_reminder_before_workbench_started`、`test_monthly_no_reminder_on_empty_database`、`test_monthly_reminds_when_a_decision_precedes_month_end`；[使用文档](../features/review.md)「复盘推送」一节已补 `before_start`；未覆盖：定时运行本身、月度推送与提醒的真实发送 |

| 2026-10-25 | v2.0.0 发布整理：删除 A 股、只保留本机部署、文档重构（[spec](../specs/2026-10-25-v2-release-cleanup-design.md)、[plan](../plans/2026-10-25-v2-release-cleanup.md)，提交 `87ed4fb`…`fb950b4`） | 全量后端 1407 在一次性库上通过（0 跳过）、前端 239 与构建通过；备份 `.local/us-workbench/backups/investment_assistant-before-021-20261025-145848.dump`（sha256 `566236e4…`）；迁移 021 用 `psql --single-transaction` 执行：`cn_observations`（1735 行）与 `cn_collection_state`（11 行）已删除，CN 研究卡 1 张及版本 2 行、观察名单 `688008.SH`、`ashares` 任务行已删除，`job_reports` 中 12 行 `ashares` 历史保留，观察名单为 8 只美股；`web/dist` 先备份到 `.local/us-workbench/dist-backup-20261025-145924` 再构建；服务重载后调度线程正常，5 个任务；手动批处理 `workbench-20261025070104-00ce9a84` 成功（交易日 10-23，错误 0，未推送；区制与 10-23 既有快照不同记 `conflict`，按只追加不覆盖，「今日」仍显示该快照生成时的「FRED 未配置」）；`POST /api/watchlist` 提交 `688008.SH` 返回 400，`/api/ashares/*` 返回 404；页面「今日」「标的」「复盘 → 周度」「设置 → 关注列表」「策略 → 研究观察卡」正常，旧 CN 链接落到美股卡 CRDO，页面无 A 股文字、控制台无报错 |
