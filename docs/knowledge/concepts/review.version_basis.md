---
id: review.version_basis
title: "决定时看到的版本"
group: review
version: 1
applies_to: [tracks-1]
summary: "三方对比的 Agent 轨道取你做决定时看到的那一版（依据 decision），没有记录或未决定则取首版（依据 first），不拿事后修订美化结果。"
related: [review.tracks, agent.version_chain, system.decision, review.first_latest]
sources: [investment_assistant/workbench/tracks.py, investment_assistant/workbench/service.py]
---

## 是什么
一个 Agent 计划链可能有好几个版本。比较"Agent 的表现"时必须说清楚取哪一版，否则事后被修订得更好的版本会让结果看起来比当时的真实判断更漂亮。三方对比的做法是：取你**决定时页面上看到的那一版**。

## 怎么算 / 从哪来
`version_basis` 有两个取值：

- `decision`：决定里记了 `agent_plan_id`（决定时页面显示的 Agent 版本），就取这一版。
- `first`：决定里没有这条记录（v2.5 之前的决定）时，取该单元的 `agent-1` 计划，没有 `agent-1` 计划就取首版；还没有决定的单元也取首版。

行上还带 `version_no`（`agent-1` 计划没有版本号，为空）和 `version_basis`（没有 Agent 计划时为空）。口径版本仍是 `tracks-1`，`agent-1` 单元的其余字段与 v2.5 之前完全相同。

## 在系统里哪里看到
「复盘 → 轨道对比」每行的 Agent 轨道标明取的是第几版、依据是什么；提交决定时系统会把页面上显示的版本记进决定（见[决定与执行依据](system.decision.md)）。

## 注意
这样取意味着：决定之后才出现的修订版，不会计入这次决定对应的 Agent 轨道结果；它们在"最新版"汇总里另算（见[首版与最新版汇总](review.first_latest.md)）。
