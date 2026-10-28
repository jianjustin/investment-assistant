---
id: agent.invalidation
title: "失效条件"
group: agent
version: 1
applies_to: [agent-2, condition-1]
summary: "Agent 计划必须给出 1 到 5 条失效条件，取自 condition-1 登记表，每条带引用；任一条成立，系统规则直接作废这份计划。"
related: [agent.review_when, agent.review_outcome, agent.version_chain, agent.signals, agent.citation]
sources: [investment_assistant/workbench/agent/conditions.py, investment_assistant/workbench/agent/plan_check.py, investment_assistant/workbench/timeline.py]
---

## 是什么
失效条件是 Agent 在给出计划时就写明的"什么情况下这份计划不再成立"。它们不是自由文字，而是从 `condition-1` 登记表里挑的、系统能自己判断的条件，所以每天复查时不需要模型参与就能知道是否成立。

可用于失效条件的 `kind` 共九种，文案由系统按模板生成（不是模型的原话）：

| `kind` | 参数 | 文案模板 |
| --- | --- | --- |
| `close_below` | `price` | 收盘跌破 {price} |
| `close_above` | `price` | 收盘突破 {price} |
| `no_entry_by` | `date` | {date} 收盘前未进入入场区 |
| `no_entry_before_earnings` | 无 | 财报前未进入入场区 |
| `earnings_within` | `sessions` | 距财报不足 {sessions} 个交易日 |
| `regime_is` | `label` | 区制变为 {label} |
| `sector_weak` | 无 | 所属行业转弱 |
| `rs_below` | `window`、`value` | 相对 SPY {window} 日强弱低于 {value} |
| `new_filing` | `form` | 出现新的 {form} |

## 怎么算 / 从哪来
**提出时的校验**：条数 1 到 5；`kind` 必须登记且允许用在失效条件上；参数必须合法，否则整版作废（`invalid_condition`）。参数范围：价格在生成时最近收盘价的 ±50% 以内；日期晚于本版生成的交易日且不超过其后 60 个自然日；`sessions` 为 1 到 10；`window` 为 20 或 60；`value` 在 −1 到 1 之间；`label` 为 `risk_on`、`neutral`、`risk_off` 之一；`form` 为 `8-K`、`10-Q`、`10-K` 之一。每条还要带[引用](agent.citation.md)。

**每天的判定**：宿主只读截止时间之前的数据，对每条给出三种结果之一：成立（`met`）、未成立（`not_met`）、无法判定（`unknown`）。数据缺失一律是"无法判定"，绝不当作成立。判定窗口是本版生成交易日的次日到复查日。持仓期时，`no_entry_by` 和 `no_entry_before_earnings` 不适用，判为未成立。

任一失效条件成立，当天复查由系统规则作废这份计划，理由写"失效条件成立：条件文案"，不再调用模型（见[每日复查结论](agent.review_outcome.md)）。

## 在系统里哪里看到
计划块的"失效条件"列表，每条旁标最近一次复查的判定（成立 / 未成立 / 无法判定，还没复查写"尚未复查"）。

## 注意
条件由模型挑选，系统只保证它们能被机械判定，不保证选得恰当。`unknown` 不等于安全，只是数据不够判断。

这条口径同样**未经验证**（Phase 0 Gate HOLD，见[证据状态「未验证」](system.gate_hold.md)）：它只说明系统怎么运作，不说明这些条件有效。
