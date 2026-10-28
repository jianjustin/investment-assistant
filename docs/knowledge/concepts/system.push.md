---
id: system.push
title: "每日推送"
group: system
version: 1
applies_to: []
summary: "定时批处理之后把当日简报推到 Discord：概览、新计划、计划更新、持仓、待处理与异常、筛选报告；手动运行不推送，同一交易日不重复。"
related: [system.stages, system.pool_tiers, agent.review_outcome, system.gate_hold]
sources: [investment_assistant/workbench/digest.py, investment_assistant/tasks/workbench.py, investment_assistant/tasks/workbench_review.py]
---

## 是什么
推送是批处理最后一个阶段 `push`：把当天的结果压缩成几条 Discord 消息，让你早上不用打开页面也知道有什么要处理。

## 怎么算 / 从哪来
- **顺序**：概览（含市场环境、扩展池新计划数、计划更新数）、新计划、计划更新（有更新时才发）、持仓、待处理与异常、筛选报告。平常五条，有计划更新时六条。
- **范围**：核心池、持仓股和可决定的筛选单元；扩展池不推送（见[观察池分层](system.pool_tiers.md)）。
- **新计划**：有 Agent 结果的单元 Agent 行在前，规则计划作为"规则基线"在后；每条都带"证据：未验证"。
- **计划更新**：只推作废和产生新版的修订；维持、修订失败、跳过、出错都不推；扩展池入场期的链不推，持仓期的链总是推。
- **规则**：手动运行不推送；同一交易日已成功推送就不重复；休市日只发一行"休市，未运行"；没有新计划也推送。
- **失败**：只写进运行报告，下一次推送附"上次推送失败"。字段与单条消息有长度上限，超出的整字段丢弃并注明"其余 n 条见系统"。
- 周度和月度复盘由另一个任务 `workbench_review` 在北京时间每天 08:00 检查并推送。

## 在系统里哪里看到
Discord 的 signals 频道；「今日」的"重新推送今日计划"；运行一览里 `push` 阶段的产出计数（实际发送的消息数）。

## 注意
推送是便利，不是依据：它与页面是同一份数据的摘要，价位和判断仍然未经验证。
