---
id: system.daily_workflow
title: "每日工作流"
group: system
version: 1
applies_to: [daily-1, stages-4]
summary: "一个任务 daily 把十个节点串成一条链：每个节点结束落检查点，出错 60 秒后自动重试一次，再失败就停在该节点，可从那里续跑。"
related: [system.stages, system.stage_status, system.push, system.fetch_policy, system.cutoff, system.append_only]
sources: [investment_assistant/workbench/workflow.py, investment_assistant/tasks/daily.py]
---

## 是什么
原来的三个定时任务（SEC 监控、每日批处理、复盘）合成了一个任务 `daily`：北京时间周二至周六 11:30 跑一次，按固定顺序走十个节点（[每日十个节点](system.stages.md)）：`sec_monitor`、`collect`、`screen`、`regime`、`signals`、`plan`、`agent`、`review`、`push`、`retro`。每次运行恰好有十个节点，每个节点写一行运行证据。

## 怎么算 / 从哪来
- **检查点**：每个节点结束时，整条链的状态（池、持仓、各节点的产出引用、运行摘要）同步存进数据库。运行编号 `daily-…` 就是检查点的线程号。
- **两层重试**：每个外部请求按目标重试（见[外部请求策略](system.fetch_policy.md)）；节点本身抛出没人接住的异常时，等 60 秒自动重试一次，第一次的错误记在这一行的 `detail.retry`。数据库连不上（`Unavailable`）不等、直接按失败处理。
- **停在失败的节点**：重试后仍失败，该节点记 `failed`，它后面的节点各记一行 `skipped`、原因 `upstream_failed`，运行状态是失败，并发一条「每日工作流失败」通知（每次执行至多一条）。其中市场环境 `regime` 出错也会停链，因为信号依赖当天的区制。
- **续跑**：在运行详情点「从此节点继续」，从检查点接着跑。已完成的节点不重跑；沿用原运行的交易日（session）和[截止时间](system.cutoff.md)，采集类节点丢掉来源时间晚于截止时间的资讯和申报；下一个交易日纽约 17:00 之后不再允许续跑，只能整次重新运行。
- **`attempt`**：续跑只给重新执行的节点（失败节点和它后面记了 `upstream_failed` 的节点）追加一行 `attempt = n+1`；失败行与跳过行是真实发生过的，不会被改写（[只追加](system.append_only.md)）。「十行」读作每个节点的有效行（最大 `attempt`）共十条；已完成的节点只有 `attempt 1`，这就是它没有重跑的证明。
- **运行状态**：由有效行推出：有 `failed` 为失败，否则有 `partial` 或 `degraded` 为降级，否则成功；跳过（休市、`manual_run`、`not_due`）不影响。降级不发通知。
- **并发**：同一时刻只允许一次执行（定时、手动、续跑、SEC 回补共用一把数据库锁）；后到的手动运行得到「正在运行」，定时运行记一行 `daily_running`。
- **预算**：Agent 与每日复查共用一个 1500 秒窗口，从 `agent` 节点开始起算；复盘卡起草在 `retro` 节点里有自己的 1500 秒。采集的重试和等待不会挤占它们。

## 在系统里哪里看到
「工具 → 运行记录」每一行的「详情」打开运行详情页：节点状态图、每个节点做了什么、拉取详情和结果详情；失败的节点上有「从此节点继续」。命令行：`python -m investment_assistant.tasks.daily show --run-id …`。

## 注意
迁移 028 未执行时 `daily` 拒绝运行（记一行 `migration_028_missing`）。手动运行（「立即运行批处理」）不推送，周 / 月复盘只生成不推送。
