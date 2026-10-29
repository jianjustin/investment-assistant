---
id: review.weekly
title: "周度复盘"
group: review
version: 2
applies_to: [review-6, review-7]
summary: "每周冻结一份快照：按规则、按决定、执行偏差、无信号交易、计划影子、纪律、分池多个视角统计，并冻结当期三方对比；更正要重新生成。"
related: [review.control_group, review.tracks, review.first_latest, review.monthly_return, system.push, review.weekly_learning]
sources: [investment_assistant/workbench/review.py, investment_assistant/workbench/review_digest.py, investment_assistant/tasks/daily.py]
---

## 是什么
周度复盘把一周内信号日落在该周的决定与结果汇总成一份不可变的快照，让你每周对照自己的纪律与系统的表现。

## 怎么算 / 从哪来
快照包含这些视角：

- **按规则 / 按决定**：对照组的超额收益，按规则、按你的决定（采纳、否决、降级）分组，见[对照组](review.control_group.md)。
- **执行偏差**：成交价相对信号后下一交易日开盘价的偏离，以及从决定到成交的延迟小时数。
- **无信号交易**：本周没有关联决定的成交。
- **已平仓交易**：持有交易日数、盈亏、同期 SPY、最大浮盈与浮亏。
- **计划影子**：按计划种类汇总，Agent 分首版与最新版两个口径，见[首版与最新版汇总](review.first_latest.md)。
- **纪律**：追高进场、过早止盈、死扛亏损、计划外交易四项与遵守率。
- **分池**：核心（`core`）、筛选（`screen`）、扩展（`extended`）三类。
- **三方对比**：当期冻结一份。
- **你学到了什么**（`review-7` 起）：本周结束的交易的纪律四项、本周的复盘卡摘要、本周被检验的知识，见[你学到了什么](review.weekly_learning.md)；`review-6` 及更早的快照没有这一段，不重算。

**冻结与更正**：快照生成后不再改动；要更正就对同一周重新生成，新快照指向旧快照。**推送**：每日工作流的 `retro` 节点在北京时间周二至周六 11:30 检查一次，每周最后一个交易日收盘后的首次运行会冻结并推送该周快照（手动运行只生成不推送）。

## 在系统里哪里看到
「复盘 → 周度复盘」，卡片上有"推送到 Discord"按钮；推送里多一个"你学到了什么"字段。

## 注意
所有数字是描述性统计，样本小且互相重叠，快照里也写明"不代表规则有效"。
