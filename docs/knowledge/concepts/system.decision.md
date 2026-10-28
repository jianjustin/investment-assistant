---
id: system.decision
title: "决定与执行依据"
group: system
version: 1
applies_to: []
summary: "你对每个决策单元做一次决定：采纳、否决或降级为观察，写一句理由；采纳买入时选执行依据（Agent 计划、规则计划或自定价位）。"
related: [system.decision_unit, review.position, review.version_basis, review.tracks, plan.own]
sources: [investment_assistant/workbench/ledger.py, investment_assistant/workbench/service.py]
---

## 是什么
系统给出候选和计划，决定权在你。决定是你对一个[决策单元](system.decision_unit.md)的回应，也是后面复盘把"系统怎么建议"和"你怎么做"对上号的凭据。

## 怎么算 / 从哪来
- **三种决定**：采纳（最终动作等于建议动作）、否决（最终动作为忽略）、降级为观察（最终动作为观察，建议动作本身是观察时不能再降级）。必须写一句理由。
- **执行依据**：采纳买入时从三者中选一个——Agent 计划（第 n 版）、规则计划、自定价位。Agent 计划可用时默认选 Agent，否则规则计划，再否则自定。选自定价位时，会另存一份自定计划，与决定在同一事务里写入，建议股数按新价位重算（见[自定计划](plan.own.md)）。否决和降级不带计划。
- **记录你看到的 Agent 版本**：提交时附带页面显示的 Agent 版本；如果后台已经修订到更新的一版，决定会被拒绝（"Agent 计划已更新到第 n 版，请刷新后再决定"），避免你基于过期的版本做决定。这条记录就是[决定时看到的版本](review.version_basis.md)。
- **更正**：再提交一条新的决定，指向旧决定；同一请求编号重复提交返回原决定。

## 在系统里哪里看到
「今日」每个单元的决定区；录入成交时可关联决定；「复盘」按决定分组统计。

## 注意
决定只是记录，不会替你下单。成交要你在券商自己下，再到「复盘 → 交易与持仓」录入（见[持仓与成交](review.position.md)）。
