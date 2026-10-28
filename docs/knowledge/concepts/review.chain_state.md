---
id: review.chain_state
title: "版本链状态"
group: review
version: 1
applies_to: [timeline-1]
summary: "链状态共七种，取第一条成立的：legacy、invalidated、closed_by_decision、holding、position_closed、expired、entry；仅 entry 与 holding 会被复查。"
related: [agent.version_chain, agent.review_outcome, agent.legacy, system.decision]
sources: [investment_assistant/workbench/timeline.py]
---

## 是什么
链状态说明一条 Agent 计划链现在处于什么阶段，决定它还要不要被每日复查。

## 怎么算 / 从哪来
按下面的顺序检查，**取第一条成立的**：

| 顺序 | 状态 | 条件 | 会被复查 |
| --- | --- | --- | --- |
| 1 | `legacy` | 是 [agent-1 旧版](agent.legacy.md)，不在链里 | 否 |
| 2 | `invalidated` | 最新版已被复查作废 | 否 |
| 3 | `closed_by_decision` | 你最新的决定不是买（否决、降级、观察等） | 否 |
| 4 | `holding` | 决定链上的买入成交还有未平批次 | 是（持仓期） |
| 5 | `position_closed` | 决定链上的买入已全部平仓 | 否 |
| 6 | `expired` | 已到最新版截止日，仍没成交 | 否 |
| 7 | `entry` | 其余情况：未决定，或已决定买入但尚未成交，且最新版还有效 | 是（入场期） |

只有 `entry`（入场期）和 `holding`（持仓期）两种会进入[每日复查](agent.review_outcome.md)；其余状态的链保留记录但不再复查。每个状态都附一句依据，如"第 n 版已被复查作废"。

## 在系统里哪里看到
计划页的链头部、「标的」页"Agent 计划"列表里的状态、「今日」"进行中的 Agent 计划"（只列入场期和持仓期）。

## 注意
状态按当前记录的决定与成交判定，每次读取时现算，不是写死在链上的；链状态变化不会改动已写入的版本。
