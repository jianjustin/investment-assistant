# 复盘

按计划和结果复盘：规则与 Agent 各自按自己的价位做影子跟踪，再和你的实际执行并列比较；另外统计纪律指标、周度和月度收益，按周、按月推送摘要。样本小、信号同日重叠，所以只给计数、均值、中位数和分布，不宣称任何规则或 Agent 有效。

设计：[P1](../specs/2026-10-23-p1-rule-plans-and-push-design.md)（影子、纪律、月度收益）、[P4 复盘扩展](../specs/2026-10-25-p4-review-expansion-design.md)（三方对比、推送）、[v2.5 计划时间线 §9](../specs/2026-10-28-v2.5-plan-timeline-design.md#9-影子跟踪与三方对比)（每版影子、三方对比取决定时看到的版本）。

## 口径

### 实际交易

先进先出配对。买入费用计入成本，卖出费用按数量分摊；跨拆股时按拆股比例换算。每笔交易显示持有交易日数、盈亏、同期 SPY、最大浮盈和最大浮亏。

### 对照组

所有已决定的单元（包括被否决的和观察的）都假设在下一交易日开盘入场，统计 5、10、20 个交易日相对 SPY 的超额收益。卖出单元取反（避开的跌幅），观察单元只记录走势。窗口没走完的显示「未成熟」，不拿部分窗口代替。

### 计划影子 `plan-shadow-1`

按价位逐日独立模拟规则计划、Agent 计划和自定计划，结果以 R 计：有三种入场方式；止损和 T1 在同一天都触及时，按先触止损算；移动止损有保本下限；跳空穿过止损时按开盘价成交。影子结果不受你实际选择的影响。

`agent-2` 计划链的每一版都是一份计划、各自模拟（修订版的有效期从复查日次一交易日开始，所以只可能在生成之后成交）。`GET /api/workbench/plans/shadow` 每行带 `chain`：`{version_no, origin, is_head, supersedes_plan_id}`（`agent-1`、规则与自定计划为 `null`）；响应另有 `agent_summary: {first, latest}`——`first` 每条链只算首版（`agent-1` 计划算自己的首版），`latest` 每条链只算当前最新版（`agent-1` 计划同样算自己）；每项给 `count`、`determined`（有 R 的份数）、`expired`、`r_mean`、`r_median`，有 R 的不足 5 份时均值与中位数为空。

### 纪律

| 坏习惯 | 判定 |
| --- | --- |
| 追高进场 | 成交价高于计划入场区间上限 |
| 过早止盈 | 持有期内未到 T1 就卖出，之后价格到达 T1 |
| 死扛亏损 | 收盘跌破止损后，下一交易日仍未卖出 |
| 计划外交易 | 成交没有关联任何计划 |

### 三方对比 `tracks-1`

对同一批买入单元，把规则、Agent、实际三条轨道的结果并列，R 都按各自计划的止损计算。单元集合 = 窗口内有规则计划或有 propose 运行的单元。每条轨道的状态分为：`missing`、`not_executable`（0R）、`pending`（不计入均值）、`expired`（0R）、`open`（浮动 R）、`closed`、`pass`（0R）、`not_executed`（0R）、`no_plan`。实际轨道另外记录 `plan_kind`（照规则 / 照 Agent / 自定）。汇总时把「没算出来」和「0R」分开统计，均值只用已确定的值。每一行的计划、运行、决定、成交 id 都能追溯到对应接口。

Agent 轨道取「你决定时看到的那一版」（v2.5，口径版本仍是 `tracks-1`）：决定记了 `agent_plan_id` → 就是这一版（`version_basis = decision`）；v2.5 之前的决定没有记 → 该单元的 `agent-1` 计划，没有则首版（`first`）；未决定 → 首版（`first`），不拿事后修订的版本美化结果。`run_id` 是生成这一版的运行。行上新增 `version_no`（`agent-1` 为空）与 `version_basis`（没有 Agent 计划时为空）；`agent-1` 单元其余字段与 v2.5 之前完全相同。

### 周度复盘 `review-6`

从按规则、按决定、执行偏差、无信号交易、计划影子、纪律、分池几个视角统计，并冻结一份当期三方对比。计划影子按种类汇总：`agent` 每条链只算首版（`agent-1` 计划算自己的首版），`agent_latest` 是快照生成时每条链的最新版，避免样本被修订次数放大（`review-5` 及更早的快照里 `agent` 是每一版都算，已冻结的快照不重算）。分池按三分类：`core`（核心）、`screen`（筛选，`source = screen` 的计划不论是否进了主列表）、`extended`（扩展）；旧计划的 context 没有来源时按分层归池。快照生成后就冻结；要更正，就对同一周重新生成，新快照指向旧快照。

### 月度复盘 `monthly-3`

- 月度收益 =（本月末资金快照 − 上月末资金快照 − 区间净出入金）÷ 上月末资金快照。任一端缺快照时，显示「缺资金快照，无法计算」。
- 分档：> 20% 非常优秀，10%–20% 优秀，0%–10% 可行，< 0 需关注；同时列出同期 SPY 和超额收益。
- 流程复查：连续 3 个月的复合收益 < 0，**且**跑输 SPY 复合收益，才标记，并附逐月明细。
- 敏感性表：用当月已平仓交易的实际 R，按单笔风险 0.5% / 1% / 1.5% / 2% 重算收益，按平仓时间排序并注明笔数。
- 另外冻结一份当期三方对比、纪律和计划影子；计划影子的 `agent` / `agent_latest` 口径同周度（`monthly-2` 及更早的快照不重算）。

资金快照按券商月末总资金录入，更正时必须指向当前有效的那份快照；出入金按笔录入（入金为正），录错只能作废。

## 复盘推送

任务 `workbench_review`（北京时间每天 08:00，默认 `signals` 频道）每天检查一次：

- **周度**：每周最后一个交易日收盘后的首次运行，冻结并推送该周快照。
- **月度**：上月有月末资金快照、且还没推送过时，生成并推送。缺快照时，从次月第一个周六起提醒一次；工作台启用之前的月份不提醒（`monthly.action` 记为 `before_start`）。
- 推送成功后不再重复；`send_failed` 或 `task_disabled` 时下一次运行重试；每次尝试都写一行 `review_pushes`。手动推送会强制重发。

## 入口与验证

- 页面「复盘」：交易与持仓、对照组、周度复盘、月度复盘、资金、轨道对比、上线前检查（见 [观察池与市场环境](pool-and-context.md)）；周度和月度卡片上都有「推送到 Discord」按钮。
- API：`GET /api/workbench/review/tracks?since=&until=`（默认最近 90 天，不冻结）；`GET/POST /api/workbench/monthly-reviews`；`GET /api/workbench/plans/shadow`；`GET /api/workbench/discipline`；`GET/POST /api/workbench/account/snapshots`、`GET/POST /api/workbench/account/flows`、`POST /api/workbench/account/flows/{id}/void`；`GET/POST /api/workbench/review-pushes`（POST body 为 `kind` 与 `period`；该周期没有快照返回 404，period 不是周一或每月 1 日返回 400）；`POST /api/jobs/workbench_review/run`。
- 验证一次：周六 08:00 之后手动运行 `workbench_review`，运行报告里 `weekly.action == "generated"` 且 `push.sent == true`；同一天再跑一次，`weekly.action == "already_sent"`。录入 8-31 和 9-30 两份资金快照后生成 9 月月度复盘，页面显示「月度收益 +x.xx% · 档位 · SPY …」。
