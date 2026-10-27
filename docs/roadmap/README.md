# Roadmap

> v2 已完成，发布为 `v2.0.0`（2026-10-25）。v2 的收尾版 `v2.1.0` 收拢 v1 遗留功能，设计见 [spec](../specs/2026-10-25-v2.1-legacy-consolidation-design.md)。其余候选项见 [backlog.md](backlog.md)。v1（2026-06-30 – 2026-10-23）已归档到 [archive/roadmap-v1](../archive/roadmap-v1/README.md)，仅作历史参考。
> 从 v2 起，roadmap 版本即发布的大版本号。

## 文档

| 文档 | 内容 | 更新方式 |
| --- | --- | --- |
| [v2-decision-loop.md](v2-decision-loop.md) | 长期路线：目标与成功标准、各环节设计、P1–P4 阶段、暂缓与不做、决策记录 | 方向变化时改，并在决策记录追加 |
| [v2-progress.md](v2-progress.md) | v2 各阶段状态与阶段证据 | 已冻结（v2.0.0），只追加验收证据 |
| [v2.2-acceptance.md](v2.2-acceptance.md) | v2.2 手动触发验收（§11.2）与定时验收（§11.3）的证据 | 每完成一项验收追加 |
| [v2.3-acceptance.md](v2.3-acceptance.md) | v2.3 手动触发验收（§11.2）与定时验收（§11.3）的证据 | 每完成一项验收追加 |
| [v2-visibility.md](v2-visibility.md) | v2.3–v2.5 路线：数据、计划推导、运行全景的透明 | 方向变化时改，并在决策记录追加 |
| [v2-agent-collab.md](v2-agent-collab.md) | v2.6–v2.9 路线：知识层、运行时切换、Agent 一级入口、多 agent 对抗 | 方向变化时改，并在决策记录追加 |
| [backlog.md](backlog.md) | 下一版候选：v1 遗留的合并或删除、v2 暂缓项、未完成的使用验收 | 排期变化时改 |

## 版本

| 版本 | 时间 | 主线 | 状态 |
| --- | --- | --- | --- |
| v1 | 2026-06-30 – 2026-10-23 | Phase 0 事件研究 → 数据地基 → 计划—执行—复盘 → 区制与校准 | 已归档；FastAPI 迁移、事件研究框架、美股工作台已落地，Phase 0 正式 Gate HOLD |
| v2 | 2026-10-23 – 2026-10-25 | 数据 → 交易计划（规则主计划 + Agent 建议）→ Discord 投递 → 复盘 | 已完成，发布 `v2.0.0`；P1–P4 `engineering_done`，`user_acceptance_pending`；删除 A 股 |
| v2.1 | 2026-10-25 | v1 遗留收拢：删除 Hermes、SPY/VIX 信号、趋势快照、策略评分、事件研究、研究观察卡；K 线图、基本面并入「标的」页，信号后超额并入 `backcheck-2`（[spec](../specs/2026-10-25-v2.1-legacy-consolidation-design.md)） | `engineering_done`、`user_acceptance_pending`；迁移 022 已于 10-25 在真实库执行，发布 `v2.1.0`；v2 路线收尾，不开 v3 |
| v2.2 | 2026-10-25 – | 纳指 100 每日筛选自动进扩展池、`plan-1` 复核与筛选报告；`regime-2`；任务中心统一北京时间、任务自描述（[spec](../specs/2026-10-25-v2.2-screener-and-task-center-design.md)） | `engineering_done`、`user_acceptance_pending`（迁移 023 已于 2026-10-26 在真实库执行、服务已重启跑 v2.2 代码，见[迁移记录](../operations/migrations-and-backup.md)；手动验收 §11.2 四条均已核对（真实批处理、只读回放、推送、任务中心），见[验收记录](v2.2-acceptance.md)；定时验收 §11.3 自 10-27 首次定时运行起积累） |
| v2.3 | 2026-10-26 – | 数据底座与「数据」菜单：数据族状态层、单族手动拉取、原始数据浏览（[v2-visibility.md](v2-visibility.md)；[spec](../specs/2026-10-26-v2.3-data-foundation-design.md)、[plan](../plans/2026-10-26-v2.3-data-foundation.md)） | `engineering_done`、`user_acceptance_pending`（版本号 `v2.3.0`；迁移 024 已于 2026-10-27 在真实库执行、服务已重启跑 v2.3 代码，见[迁移记录](../operations/migrations-and-backup.md)；手动验收 §11.2 五条已核对、用户已于 10-27 确认浏览可用，见[验收记录](v2.3-acceptance.md)；定时验收 §11.3 自 10-28 起积累；全范围 final review 已完成并修复，保留偏差见[下文](#v23-工程自查与验收边界)） |
| v2.4 | 2026-10-27 – | 计划推导链与批处理 workflow 底座：7 阶段证据 `stage_runs`、run_id 接通、单份计划推导视图与「推导 = 重算」自动校验（[v2-visibility.md](v2-visibility.md)；[spec](../specs/2026-10-27-v2.4-derivation-and-workflow-design.md)、[plan](../plans/2026-10-27-v2.4-derivation-and-workflow.md)） | spec 已审阅通过；plan 已写，待用户审阅；未开工（版本号 `v2.4.0`；迁移 025 待授权） |
| v2.5 | — | 当日运行全景、「标的」页认知重排（[v2-visibility.md](v2-visibility.md)） | 已确认，未开工 |
| v2.6 | — | 知识层：概念卡 + 我的知识，在系统内展示（「知识」菜单 + 就地展开），Agent 可引用、受截止时间约束（[v2-agent-collab.md](v2-agent-collab.md)） | 草案，待审阅 |
| v2.7 | — | Agent 运行时可切换、本地 CLI 为主：工具层 MCP + 适配器（Claude Code / codex / pi，API 模型挂在 pi），删除智谱，LangGraph 保留为编排层（[v2-agent-collab.md](v2-agent-collab.md)） | 草案，待审阅 |
| v2.8 | — | Agent 一级入口：计划对话、补充信息生成新版 Agent 计划、结束的计划沉淀经验（[v2-agent-collab.md](v2-agent-collab.md)） | 草案，待审阅 |
| v2.9 | — | 多 agent 对抗 `agent-2`：2 提议者 + 反方 + 回应 + 裁决（[v2-agent-collab.md](v2-agent-collab.md)） | 草案，待审阅 |
| 下一版 | — | 见 [v2-visibility.md](v2-visibility.md)、[v2-agent-collab.md](v2-agent-collab.md) 与 [backlog.md](backlog.md) | v2.4 已排期 |

## v2.3 工程自查与验收边界

以 [spec §4–§13](../specs/2026-10-26-v2.3-data-foundation-design.md#4-数据族清单) 对照代码；[实施 plan](../plans/2026-10-26-v2.3-data-foundation.md) 保持冻结。全范围 final review 已于 2026-10-26 完成，意见集中修复在 `068debd`（记账事实：锁、目标、哨兵、墙钟）、`a14c1c0`（读取契约、浏览窗口、覆盖口径）、`ed4682c`（前端展示）、`03ccf6f`（文档）。2026-10-27 按 plan 复核工程部分：离线 pytest 921 passed / 323 skipped，一次性 PostgreSQL 1244 passed，前端 Vitest 233 passed，构建成功。

**自查曾列出、已修复的缺口**：

- **状态与原因展示**：卡片与最近记录表显示 `skipped` 原因、最近成功时间、单只 / 全族范围与实际 `job`；记录表有「任务」列（`job` + `detail.targets_source`），区分两路 SEC 目标；各族覆盖口径一句话内联并悬浮显示。
- **读取契约与降级**：每张卡片（含独立详情）带 `fetch_runs_ready`；范围文件不可读时卡片与浏览以 `current_error` 显示文件错误原文，不伪造拉取行。
- **覆盖与窗口**：FRED 覆盖为「有观测值的序列数」，滞后独立列出；资讯与 SEC 浏览先按来源过滤、窗口内完整读取，去掉 200 条上限；无接收时间的 `sec_8k` 标「申报日未知」，不计入最近申报日。
- **记账与锁**：`*` 整族失败哨兵不进分母，空目标的整次失败记 `failed`；批处理锁部分获取异常后逐把释放，无法证明干净的会话物理丢弃、不还池（`tests/test_workbench_lock_pool.py` 用真实 `psycopg_pool` 验证）；拉取行时间戳用真实墙钟。
- **测试与文档**：批处理特征测试补上 §6.1 要求的 SPY 失败；[backlog](backlog.md) 已补「与 Team B 衔接」「验证 / 回测专项」两条不做项。

**保留的偏差与限制**（已在 [CHANGELOG](../../CHANGELOG.md) 与[功能文档](../features/data-menu.md#已知限制)披露，不阻断 `engineering_done`）：

- 卡片「最近拉取」主行只取最新全族记录（spec §8 为最新一行），比它更新的单只拉取另列 `last_ticker_run`，`last_success_at` 只算全族记录（2026-10-27 用户决定）。
- 批处理记录 `run_id` 为空；单族手动拉取带 runner `run_id`、不写 `job_reports`。
- 范围加载失败记录的目标是 `nasdaq100`（照 plan Task 5），不是 spec §5.1 整族失败约定的 `*`；目标就是范围文件本身（分母 1），失败时状态同样是 `failed`。
- `filings` 任务的目标按模式取实际采集清单：监控模式是 `sec_monitor.watchlist_path`，下载器模式是 `config.watchlist`，均与批处理的「当前池 + 持仓」不同。
- 手动全族目标不含已清仓的历史持仓，旧批处理循环仍为其采集，批处理 `target_count` 可能更大。
- `tests/test_api_contract.py` 只钉住总览无库 503；四接口的字段与错误码由 `tests/test_api_data.py` 覆盖（委托、错误映射，以及真实路由 + 一次性 schema 的 POST 四类错误码）。

**后续使用验收**：2026-10-27 已执行迁移 024、重启服务，并完成 §11.2 手动验收与原始值核对（[验收记录](v2.3-acceptance.md)），因此不再标 `runtime_unverified`；用户已于 10-27 确认浏览可用。仍缺：迁移后连续 5 个交易日的 `workbench` 五族 / `filings` 记录与日线推进证据（自 10-28 起）。打 tag、推送各自另行授权；这些完成前保持 `user_acceptance_pending`，不宣称发布 / 验收完成。

## 沿用原则

以下来自 v1 [00](../archive/roadmap-v1/00-principles-and-direction.md)，v2 继续有效：

- **闭环优先于回测**：价值在「计划、执行、结果」的归因，不在小样本上的组合回测。
- **证伪优先于建设**：规则和 Agent 都要有影子跟踪证据，没有证据不宣称有效。
- **诚实优先于漂亮**：统计带样本量；区分「没算」和「无信号」；不用历史反推参数。
- **人在环路**：系统出计划，人决定是否下单；不接券商、不自动下单。

## 交付标准（DoD）

每个阶段的每项交付同时满足四条：

1. **手动入口**：自动任务有手动触发路径（API、CLI 或前端按钮至少其一）。
2. **验证入口**：结果可查（`job_reports`、前端状态或 CLI 输出至少其一）。
3. **功能说明 + 如何验证**：文档或页面写清做什么、怎么手动验证一次。
4. **离线测试**：pytest 离线可跑，数据库、网络、LLM 全部 mock 或注入。

工程纪律沿用：路由层薄封装（`api/routes` → `services` → `db` / `tasks`）；外部失败结构化返回，不吞成成功；凭据不进报告；业务数据只追加，更正用新记录指向旧记录。

## 状态用语

| 用语 | 含义 |
| --- | --- |
| `engineering_done` | 代码和入口在仓库里 |
| `runtime_unverified` | 尚未经真实库、HTTP 或页面验收 |
| `gate_hold` | 证据不够，不能当作有效规则 |
| `user_acceptance_pending` | 工程结果不能代替使用验收 |

没有新证据时，不把状态改成完成。
