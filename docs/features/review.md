# 复盘

按计划和结果复盘：规则与 Agent 各自按自己的价位做影子跟踪，再和你的实际执行并列比较；另外统计纪律指标、周度和月度收益，按周、按月推送摘要。样本小、信号同日重叠，所以只给计数、均值、中位数和分布，不宣称任何规则或 Agent 有效。

设计：[P1](../specs/2026-10-23-p1-rule-plans-and-push-design.md)（影子、纪律、月度收益）、[P4 复盘扩展](../specs/2026-10-25-p4-review-expansion-design.md)（三方对比、推送）、[v2.5 计划时间线 §9](../specs/2026-10-28-v2.5-plan-timeline-design.md#9-影子跟踪与三方对比)（每版影子、三方对比取决定时看到的版本）、[v2.7 我的成长闭环](../specs/2026-10-28-v2.7-growth-loop-design.md)（复盘卡、周度「你学到了什么」）。

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

### 周度复盘 `review-7`

从按规则、按决定、执行偏差、无信号交易、计划影子、纪律、分池几个视角统计，并冻结一份当期三方对比。计划影子按种类汇总：`agent` 每条链只算首版（`agent-1` 计划算自己的首版，页面标「Agent（首版）」），`agent_latest` 是快照生成时每条链的最新版（页面标「Agent（最新版）」），避免样本被修订次数放大（`review-5` 及更早的快照里 `agent` 是每一版都算，页面仍标「Agent」，已冻结的快照不重算）。分池按三分类：`core`（核心）、`screen`（筛选，`source = screen` 的计划不论是否进了主列表）、`extended`（扩展）；旧计划的 context 没有来源时按分层归池。快照生成后就冻结；要更正，就对同一周重新生成，新快照指向旧快照。

`review-7`（v2.7）起快照的 `stats` 多一个 `learning` 键，见下面「周度「你学到了什么」」；`review-6` 及更早的快照没有这个键，页面明说，不重算。

### 月度复盘 `monthly-3`

- 月度收益 =（本月末资金快照 − 上月末资金快照 − 区间净出入金）÷ 上月末资金快照。任一端缺快照时，显示「缺资金快照，无法计算」。
- 分档：> 20% 非常优秀，10%–20% 优秀，0%–10% 可行，< 0 需关注；同时列出同期 SPY 和超额收益。
- 流程复查：连续 3 个月的复合收益 < 0，**且**跑输 SPY 复合收益，才标记，并附逐月明细。
- 敏感性表：用当月已平仓交易的实际 R，按单笔风险 0.5% / 1% / 1.5% / 2% 重算收益，按平仓时间排序并注明笔数。
- 另外冻结一份当期三方对比、纪律和计划影子；计划影子的 `agent` / `agent_latest` 口径同周度（`monthly-2` 及更早的快照不重算，页面仍标「Agent」）。

资金快照按券商月末总资金录入，更正时必须指向当前有效的那份快照；出入金按笔录入（入金为正），录错只能作废。

## 复盘卡

一笔交易平仓、或你决定过的一份计划结束（止损、到 T1、过期未成交、作废）之后，批处理的第 8 个阶段 `retro`（见 [每日计划](daily-plan.md#每日流程)）检测到这个结束事件，把当时的事实**冻结**进一张卡，Agent 只把这些事实讲成一段话并起草 0–3 条教训，你审定后教训才进入「我的知识」（[知识层 · 我的知识](knowledge.md#我的知识)）。设计：[v2.7 §4](../specs/2026-10-28-v2.7-growth-loop-design.md#4-复盘卡)，版本 `retro-1`（事实与判定）、`agent-retro-1`（起草）。

- **对象**（两类）：决策单元——买入单元，且你做过决定、或决定链上有未作废的买入成交；计划外成交——没有关联决定的未作废买入成交，每笔一张。没有决定、也没有成交的单元不出卡。
- **结束事件**（纯函数 `retro.end_event`）：有买入成交时只看平仓——这些买入的 FIFO 批次全部平掉才结束（`position_closed`，结束日是平掉最后一批的那笔卖出的纽约日期），持仓期间链被作废或计划过期**不**算结束；没有买入成交时，取参考计划上最早的一个：链被复查作废或参考计划按规则作废（`invalidated`）、影子第一条腿是止损 / 移动止损（`stop`）、是 T1（`target`）、影子 `expired`（`expired`，结束日为计划有效期止），同一天按 作废 → 止损 → 到 T1 → 过期 排序。参考计划按「决定执行的计划 → 决定时看到的 Agent 版本 → 规则计划 → `agent-1` 计划」取第一个存在的，有持仓时只认决定执行的那一份，没有就不出卡（阶段 `detail.no_plan` 计数）。只认结束日在最近 5 个交易日内（含当日）的事件；更早的用 `retro_cards detect --since D` 手动补。平仓方式 `exit_basis` 只描述（按止损 / 到 T1 后 / 自行卖出），不是纪律判定。
- **同一事件一张卡**：`review_cards.event_key` 唯一（单元无持仓结束 `unit:<标的>:<信号日>:ended`；单元平仓 `unit:<标的>:<信号日>:closed:<最后一笔卖出 id>`；计划外成交 `trade:<买入成交 id>`），插入 `ON CONFLICT DO NOTHING`，同一 session 重跑不重复建卡。
- **冻结的十个事实**（`retro.FACT_KEYS`，建卡时一次算好、之后不重算）：`subject`、`plans`（各份计划当时的价位、有效期、截止时间与角色）、`bars_after`（之后的日线摘要与每份计划的首次触及日期，拆股基准同 `plan_shadow`）、`shadow`、`tracks`（与「轨道对比」同一个函数 `service._track_rows` 的同一单元行，原样取 `rule` / `agent` / `actual`）、`decision`、`trades`、`discipline`（直接用 `discipline.evaluate`，未到判定期的记「待定」）、`reviews`、`knowledge`。卡页另显示「现在的判定」：按当前日期对同一批成交只读重算一次，与冻结结果不同时并列。
- **起草**（`agent-retro-1`，单阶段）：每次批处理对没有成功草稿的卡按结束日升序起草，**至多 5 张**（`RETRO_MAX_DRAFTS`），失败 3 次（`rejected` / `error`）后不再自动起草；闸门与 Agent 阶段相同（超时限、Agent 不可用、本次已遇额度用尽、当日 token 达上限）。教训必须写适用范围与反例。起草结果通过校验才写草稿；每次尝试写一行 `review_card_drafts`（跳过也写一行原因，原因没变就不重复写）。叙述的每一句都要引用 `fact:<键>`、本次工具调用、本次读到的概念卡或我的知识。
- **审定**（一次，`POST /api/workbench/review-cards/{id}/verdict`）：每条教训草稿「采纳（可改）/ 不采纳」且必须全部出现，可另写新教训，可写 0–2000 字「我的复盘」；同一事务写审定记录、每稿一行决定、采纳的教训（含另写的）成为新条目的第 1 版；二次审定 409 `card_reviewed`；没有成功草稿的卡也可以只写复盘或另写教训。卡状态由记录推出：`reviewed` / `to_review` / `draft_failed` / `drafting`。
- **重新起草**（`POST …/redraft`）：前置检查同步执行（卡不存在 404、已有成功草稿 409 `draft_exists`、已审定 409 `card_reviewed`、Agent 不可用 409 `agent_unavailable: <原因>`、当日 token 达上限 409 `token_budget`，迁移 027 未执行 503），通过后后台起草，返回 `{run_id, status: pending}`，用 `GET /api/runs/{run_id}` 查结果；不受 3 次上限。
- **页面**：「复盘」的第二个页签「复盘卡」（`#review/cards`，页签带待审定数；可按状态、标的筛选），卡页 `#review/cards/<id>` 依次是页头、预期与实际（表格来自冻结事实，叙述的引用可点开）、三条轨道、你的决定与纪律（检测时 / 现在）、教训草稿与审定、起草过程、重新起草。
- **接口**：`GET /api/workbench/review-cards?status=&ticker=&since=`（卡列表，带按状态的 `counts`）、`GET /api/workbench/review-cards/{id}`（`card`、`facts`、`status`、`drafts`、`lesson_drafts`、`verdict`、`discipline_now`、`discussions`）、上面的 `verdict` 与 `redraft`。迁移 027 未执行时这些接口 503「迁移 027 未执行」，页面显示同一句。
- **命令行** `python -m investment_assistant.workbench.retro_cards`：`detect [--since D]`（检测并建卡，不起草）、`draft --card ID`（同步起草一次）、`show --card ID`（只读）、`check --since D [--until D]`（只读）：窗口内每个按 §4.1 现算出的结束事件恰有一张卡，每张卡十个事实齐全，`facts.tracks` 与现在的 `tracks-1` 行相同（成交作废等后来的变化列为「事实已变化」，不算失败）；缺卡或事实不全退出码 1，参数错误、数据库不可用或迁移 027 未执行退出码 2。
- **怎么验证一次**：手动运行批处理后，`stage_runs` 该 `run_id` 有 9 行，`retro` 行的 `output_count` 等于本次新成功的 `review_card_drafts` 数；`retro_cards check --since <上线前第 5 个交易日>` 通过；任选一张卡，`facts.tracks` 与「复盘 → 轨道对比」同一单元逐项一致，纪律与 `GET /api/workbench/discipline` 一致。
- **已知限制**：冻结事实不随后来的更正变化（建卡后成交被作废时，卡页与 `check` 标「事实已变化」，不重建；同单元若因此变成另一种结束，可能出第二张卡）；未决定的单元没有卡，上线前的旧交易默认没有卡；纪律的「待定」可能很久，以「现在的判定」为准。证据状态仍是「未验证」。

## 周度「你学到了什么」

`review-7` 的周度快照新增 `stats.learning`（`review.learning_stats`，在 `generate_weekly` 的同一个只读快照里算）：`discipline`（本周结束的卡的冻结纪律合计：`cards`、`chase`、`early_take`、`held_loser`、`unplanned`、`pending`）、`cards`（本周结束的卡按结束日排列的摘要）连同 `counts`（`total`、`reviewed`、`to_review`、`drafting`、`draft_failed`）、`knowledge`（本周至少有一个样本结果落在这一周的我的知识条目：`ref`、`title`、`new_outcomes`、`sample`，`sample` 与表现回看同口径，有结果的不足 5 个不给均值）。迁移 027 未执行时生成的快照带全零的 `learning`。页面「复盘 → 周度复盘」卡片多一段「你学到了什么」。

推送（`review_digest.weekly` 新增 `learning` 键，`notify.templates.workbench_weekly` 在「纪律」之后、「说明」之前多一个字段「你学到了什么」）：第一行 `纪律（本周结束的 n 笔）：追高 … · 过早止盈 … · 死扛亏损 … · 计划外 … · 待定 …`，第二行 `复盘卡 n 张（已审定 … · 待审定 …）`，再是至多 5 张卡各一行（`标的 结束类型 · 实际 … · 决定文案`，超出写 `…另有 n 张`），然后 `被检验的知识 k 条` 与至多 3 行（`know:<id>@<版本> 标题 · 样本 n（均值 … / 少于 5 个不给均值）`）；三项都为空时只写一行「本周没有结束的交易，也没有被检验的知识」；字段超过 1024 字从后面截断并加 `…`。

## 复盘推送

任务 `workbench_review`（北京时间每天 08:00，默认 `signals` 频道）每天检查一次：

- **周度**：每周最后一个交易日收盘后的首次运行，冻结并推送该周快照。
- **月度**：上月有月末资金快照、且还没推送过时，生成并推送。缺快照时，从次月第一个周六起提醒一次；工作台启用之前的月份不提醒（`monthly.action` 记为 `before_start`）。
- 推送成功后不再重复；`send_failed` 或 `task_disabled` 时下一次运行重试；每次尝试都写一行 `review_pushes`。手动推送会强制重发。

## 入口与验证

- 页面「复盘」：交易与持仓、复盘卡、对照组、周度复盘、月度复盘、资金、轨道对比、上线前检查（见 [观察池与市场环境](pool-and-context.md)）；周度和月度卡片上都有「推送到 Discord」按钮。
- API：`GET /api/workbench/review/tracks?since=&until=`（默认最近 90 天，不冻结）；`GET/POST /api/workbench/monthly-reviews`；`GET /api/workbench/plans/shadow`；`GET /api/workbench/discipline`；`GET/POST /api/workbench/account/snapshots`、`GET/POST /api/workbench/account/flows`、`POST /api/workbench/account/flows/{id}/void`；`GET/POST /api/workbench/review-pushes`（POST body 为 `kind` 与 `period`；该周期没有快照返回 404，period 不是周一或每月 1 日返回 400）；`POST /api/jobs/workbench_review/run`。
- 验证一次：周六 08:00 之后手动运行 `workbench_review`，运行报告里 `weekly.action == "generated"` 且 `push.sent == true`（消息里有「你学到了什么」字段）；同一天再跑一次，`weekly.action == "already_sent"`。录入 8-31 和 9-30 两份资金快照后生成 9 月月度复盘，页面显示「月度收益 +x.xx% · 档位 · SPY …」。
