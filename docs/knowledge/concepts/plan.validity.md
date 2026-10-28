---
id: plan.validity
title: 有效期
group: plan
version: 1
applies_to: [plan-1]
summary: "规则计划在信号日后第 1 至第 3 个交易日内有效；过了有效期还没成交，计划到期作废。"
related: [plan.earnings, plan.status, agent.version_chain, review.plan_shadow]
sources: [investment_assistant/workbench/plans.py, docs/features/daily-plan.md]
---

## 是什么

计划是在信号日收盘后生成的，行情每天都在变，所以不能无限期有效。有效期规定了你可以在哪几个交易日里按这份计划入场。

## 怎么算 / 从哪来

- 有效期从信号日 T 之后第 1 个交易日（T+1）到第 3 个交易日（T+3），按美股交易日历数，周末和休市日不算。
- 计划里记录 `valid_from` 和 `valid_until`，过了 `valid_until` 还没成交就到期。
- 有效期内有财报，计划整份作废，见[财报规则](plan.earnings.md)。

## 在系统里哪里看到

- 「今日」计划块的有效期；「标的」页 K 线上的计划线段只画在有效期内。
- 计划影子里没成交的计划记为到期，见[计划影子](review.plan_shadow.md)。

## 注意

- 这是规则计划（`plan-1`）的有效期。Agent 计划是一条随复查更新的版本链，每一版的有效期规则不同，见[版本链](agent.version_chain.md)。
- 规则**未经验证**（Phase 0 Gate HOLD）。
