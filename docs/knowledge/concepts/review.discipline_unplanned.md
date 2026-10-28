---
id: review.discipline_unplanned
title: "计划外交易"
group: review
version: 1
applies_to: [review-6]
summary: "买入成交没有关联任何决定的计划（没有决定，或决定没选计划），记为计划外交易；它不进入遵守率的分母。"
related: [review.discipline_chase, review.position, system.decision]
sources: [investment_assistant/workbench/discipline.py, investment_assistant/workbench/ledger.py]
---

## 是什么
系统的闭环是"信号、计划、决定、成交"。计划外交易指你的买入没有走完这条链：要么没有关联决定，要么关联的决定没有选任何计划。

## 怎么算 / 从哪来
对每笔未作废的买入成交，查它的 `decision_id` 对应的[决定](system.decision.md)是否带了计划（规则计划、Agent 计划或自定计划都算）。查不到决定或决定没有计划，就标记 `unplanned`。

这类成交无法计算追高、过早止盈、死扛亏损，所以遵守率只对**有计划的买入**计算：没有被任何项标记的有计划买入数 ÷ 有计划买入数，计划外交易不进分母。

## 在系统里哪里看到
「复盘」纪律明细的"计划外交易"计数；周度复盘里单独列出"无信号交易"。录入成交时选择关联的决定，可以避免被记为计划外。

## 注意
计划外并不一定是坏事（也许是你自己的研究），只是系统无法用计划对它复盘。
