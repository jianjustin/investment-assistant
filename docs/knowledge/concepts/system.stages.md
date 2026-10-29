---
id: system.stages
title: "批处理九个阶段"
group: system
version: 2
applies_to: [stages-3, stages-2, stages-1]
summary: "每个交易日的批处理依次跑九个阶段：collect、screen、regime、signals、plan、agent、review、retro、push，每个阶段各写一行运行证据。"
related: [system.stage_status, system.screen, agent.review_outcome, system.push, review.retro_card]
sources: [investment_assistant/workbench/stages.py, investment_assistant/tasks/workbench.py, docs/operations/scheduling-and-notifications.md]
---

## 是什么
定时任务 `workbench`（北京时间周二至周六 06:30）对最近收盘的交易日跑一遍完整流程。流程被拆成九个固定顺序的阶段，每个阶段结束时各写一行运行证据，你在「运行一览」里看到的就是这九行。

## 怎么算 / 从哪来
| 顺序 | 阶段 id | 名称 | 做什么 |
| --- | --- | --- | --- |
| 1 | `collect` | 数据采集 | 逐只采集日线、资讯标题、财报日、SEC 列表与 FRED 宏观，是后面各阶段的数据底座 |
| 2 | `screen` | 筛选 `screen-1` | 在纳指 100 范围内按 `screen-1` 过滤排序，入选成员自动并入扩展观察池 |
| 3 | `regime` | 市场环境 `regime-2` | 用范围加手动池的广度与宏观序列判定区制，并计算行业强弱 |
| 4 | `signals` | 信号与候选 | 规则 v1 在观察池与持仓上逐只评估，产生候选并合成每股每日一个决策单元 |
| 5 | `plan` | 规则计划 `plan-1` | 为无冲突、未决定的买入单元生成计划：ATR 止损、2R 目标、按风险定仓、超限作废 |
| 6 | `agent` | Agent 建议 | Agent 对候选做提议与反方论证并给出解读；缺 key 等不可用时整阶段跳过 |
| 7 | `review` | 每日复查 | 对每份有效 Agent 计划复查一次：维持、修订或作废 |
| 8 | `retro` | 复盘卡 | 检测已结束的计划与平仓，冻结复盘事实并起草[复盘卡](review.retro_card.md) |
| 9 | `push` | 复核与推送 | 组装今日视图并把摘要推送 Discord；手动运行不推送 |

每次运行向 `stage_runs` 追加恰好 9 行（`stages-3`）。每行记状态（见[阶段状态](system.stage_status.md)）、输入与产出计数、按原因分组的跳过、逐目标失败、降级、产出引用和耗时。

**`stages-2`**：v2.5 到 v2.6 的版本有八个阶段，没有 `retro`。任务开始时如果库里还没有迁移 027，本次就按 `stages-2` 记 8 行，运行报告的 `errors` 里有一条 `growth: migration_027_missing`。

**`stages-1`**：迁移 026 之前的版本只有七个阶段，没有 `review`。任务开始时如果库里还没有迁移 026，本次就按 `stages-1` 记 7 行。

纽约休市日，`push` 之前的全部阶段整体跳过，原因 `not_trading_day`，`push` 只发一行休市提示。手动运行针对最近一个已收盘的交易日，总是不推送。

## 在系统里哪里看到
「今日」顶部的运行一览（每个阶段一句话加计数和跳过原因，可选日期看往日）；「原理」页每一步的"当天这一步"。

## 注意
证据写入失败只记在运行报告里，不影响批处理本身；某个阶段中途出错时，已写的阶段保留，出错阶段及其后未写的阶段记为失败（`aborted`），仍是完整的 9 行。
