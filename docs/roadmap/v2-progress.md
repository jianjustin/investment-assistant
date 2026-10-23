# Roadmap v2 进度

> 活文档，接替 v1 的 [08 活路线](../archive/roadmap-v1/08-living-collaboration.md)。路线本身见 [v2-decision-loop.md](v2-decision-loop.md)。
> 本文不授权补采、真实库迁移、通知、部署或交易；这些动作单独点名。

## 当前阶段

| 阶段 | 状态 | 下一步 |
| --- | --- | --- |
| P1 规则计划与推送 | `engineering_done`，`runtime_unverified`（离线测试与一次性测试库全绿；未迁移真实库、未发真实推送） | P1 验收：授权后对真实库 `pg_dump` 并执行迁移 017、开启推送、页面验收 |
| P2 观察池扩展与市场环境 | 未开工 | 依赖 P1 |
| P3 Agent 轨道 | 未开工 | 依赖 P1、P2 |
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
6. P1 验收：对真实库执行迁移 017（先 `pg_dump`）、开启推送并页面验收。（待授权。）

## 阶段证据

每完成一项，在这里记日期、提交和验证方式。

| 日期 | 事项 | 证据 |
| --- | --- | --- |
| 2026-10-23 | roadmap v2 确认，v1 归档 | 本目录 |
| 2026-10-23 | P1 设计逐项确认 | [P1 spec](../superpowers/specs/2026-10-23-p1-rule-plans-and-push-design.md) |
| 2026-10-23 | P1 实施计划写成（14 个任务） | [P1 实施计划](../superpowers/plans/2026-10-23-p1-rule-plans-and-push.md) |
| 2026-10-23 | P1 工程完成（Task 1–14，提交 `0caf127`…见该计划各任务提交；前端完成于 `c2adc45`；终审修复 `a923e6c`） | 端到端场景测试 `tests/test_workbench_scenarios.py::test_plan_to_monthly_review_end_to_end`；[使用文档](../us-workbench.md) P1 四节 |
