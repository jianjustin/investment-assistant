---
title: 系统每天怎么跑
version: 1
---

## 系统做什么、不做什么

系统每个交易日收盘后（定时任务在北京时间周二至周六 06:30）对你的观察池和持仓跑一遍固定流程：采集数据、筛选、判断市场环境、按规则找出候选、生成价位计划、让 Agent 提议并每天复查，检测已结束的交易并起草复盘卡，最后把摘要推送给你。下面按这个顺序一步一步讲。

**做什么**：出研究候选和计划，每个价位都能追溯到规则、数据和它的输入。**你决定、你下单、你录入成交**：系统不接券商，不会替你买卖，也不会自动调整你的持仓。

**不做什么**：它不预测行情，也不保证任何结果。更要紧的是，所有规则和 Agent 都**未经验证**——Phase 0 的正式结论是暂不放行（Gate HOLD），所以每份计划都带着"证据：未验证"。推导一致、数据完整、Agent 默认展示在前，都不等于有效，详见 [证据状态「未验证」](concepts/system.gate_hold.md)。

三条贯穿全系统的口径：规则、计划和 Agent 的数据类工具只读[截止时间](concepts/system.cutoff.md)之前已入库的数据，所以能还原"当时知道什么"（不是严格的历史回测；`get_trigger`、`get_position` 读当日候选与持仓记录，不按截止时间过滤）；业务记录[只追加](concepts/system.append_only.md)，更正是新记录指向旧记录，错误不会被悄悄抹掉；每套口径都有版本号，旧记录保留它当时的版本。

读这一页时，每一步都有「当天这一步」的链接，点开会回到「今日」顶部的运行一览，看当天这一步实际做了什么、跳过了什么。

## ① 数据采集

**做什么**：给后面所有阶段打底。逐只采集观察池和持仓的数据，包括六个数据族：[日线](concepts/family.bars.md)（开高低收按拆股调整、不按分红调整，另存全复权收盘价）、[SEC 申报](concepts/family.sec_filings.md)列表、[资讯](concepts/family.news.md)标题、由日线现算的 [ATR](concepts/family.atr.md)、[FRED 利差](concepts/family.fred.md)，以及手动维护的[纳指 100 范围](concepts/family.universe.md)。此外还采财报日。仍有有效 Agent 计划链的标的，即使已不在观察池和持仓里，也会单独采集日线、资讯和财报日，但不跑规则。

**读什么、写什么**：读数据源（日线、资讯、财报日、SEC、FRED），写进数据库；数据源改了数值就追加一个修订版本，不覆盖旧值。每个数据族各记一行拉取结果。

**怎么失败与降级**：单只标的采集失败记为该阶段的逐目标失败，其余照常，阶段状态是"部分成功"而不是"成功"；某个数据源没配置（例如没有 FRED 密钥）会如实记录，不会假装有数据。休市日整个阶段跳过。

[当天这一步](#stage-collect)

## ② 筛选（screen-1）

**做什么**：在纳指 100 范围里按固定阈值挑出值得多看一眼的股票，让它们并入扩展观察池，之后规则照常运行。过滤条件是 20 日平均成交额达到 5000 万美元（见 [20 日平均成交额](concepts/indicator.dollar_volume_20.md)）、避开今天至其后第 5 个交易日内的已知财报（财报日未知的不排除）；触发了买入规则的股票排在前面，形态合格的再按[相对强弱](concepts/indicator.screen_rs.md)补齐，每天新入选不超过 20 只。成员有保留期和上限，细节见[每日筛选](concepts/system.screen.md)；它们属于扩展池，见[观察池分层](concepts/system.pool_tiers.md)。

**读什么、写什么**：读范围文件和范围内股票的日线与财报日，写筛选运行记录与结果；成员写入观察池分层。

**怎么失败与降级**：范围文件加载失败，或基准 QQQ 缺当日数据时，筛选记为出错，成员只保留已锁定和保留期内的、当天不新增，批处理继续。只对指定标的运行时整阶段跳过。

[当天这一步](#stage-screen)

## ③ 市场环境（regime-2）

**做什么**：给当天的市场打一个粗略的标签，并看行业强弱和利率背景，帮你判断一份买入计划是顺风还是逆风。四个部分：[广度](concepts/indicator.breadth.md)（范围与手动池里站上 MA50 和 MA200 的占比、新高新低数）；[区制](concepts/indicator.regime.md)（据广度判成进攻、中性、防守，样本不足 20 只时为样本不足）；[行业强弱](concepts/indicator.sector_strength.md)（SMH、XLK、QQQ 相对 SPY 的 20 与 60 日强弱）；利差背景，[HY 信用利差](concepts/indicator.hy_oas.md)与 [2s10s 利差](concepts/indicator.t10y2y.md)。

**读什么、写什么**：读日线和 FRED 序列，写一份当日市场环境快照。

**怎么失败与降级**：区制和利差**只给计划加提示，不改价位、仓位和有效期**。范围文件缺失时广度退回只用手动观察池；快照失败时计划上会加"环境不可用"的提示。

[当天这一步](#stage-regime)

## ④ 信号与候选

**做什么**：规则 v1 在观察池和持仓上逐只评估，阈值事先固定、不用历史数据调参。下面是八条规则，每条的条件原文：

- [趋势回踩修复](concepts/rule.trend_reclaim.md)（买入）：收盘 > MA50 > MA200，且收盘重新站上 MA20，此前至少连续 3 天在 MA20 下方。
- [放量突破](concepts/rule.volume_breakout.md)（买入）：收盘创前 20 日收盘新高，成交量 ≥ 前 50 日均量 × 1.5，收盘 > MA50。
- [财报跳空向上](concepts/rule.earnings_gap_up.md)（买入）：8-K Item 2.02 后第一个交易日，开盘较前收盘跳空 ≥ +3%，收盘 ≥ 开盘。
- [跌破 MA50](concepts/rule.trend_break.md)（卖出）：此前至少连续 10 天收在 MA50 上方，当日跌破。
- [财报跳空向下](concepts/rule.earnings_gap_down.md)（卖出）：财报后第一个交易日跳空 ≤ −3%，收盘 ≤ 开盘。
- [持仓回撤](concepts/rule.position_drawdown.md)（卖出）：仅限没有计划的持仓，收盘较成本跌 ≥ 8%，或较持仓以来最高收盘回撤 ≥ 12%。
- [新财报](concepts/rule.new_filing.md)（观察）：当日出现新的 10-Q / 10-K / 8-K。
- [异常波动](concepts/rule.abnormal_move.md)（观察）：日收益绝对值 ≥ 近 20 日波动率 × 2.5，且当日无新财报。

另有两条只对**有计划的持仓**生效的卖出规则，它们同样产生候选：[计划止损](concepts/rule.plan_stop.md)（当日最低价触及当前止损）和[计划目标](concepts/rule.plan_target.md)（开仓以来首次触及 T1，卖出一半，只触发一次）。有计划的持仓用这两条，没有计划的持仓用持仓回撤。

财报时点按 SEC 受理时间判断：盘后发布算下一个交易日，盘前算当天，盘中发布不触发跳空规则。同一只股票当天的全部候选被合成一个[决策单元](concepts/system.decision_unit.md)；买入和卖出同日并存标记"冲突"、默认观察，没有持仓的卖出候选标记"回避"，见[冲突与回避](concepts/system.conflict.md)。

**读什么、写什么**：读日线、SEC 申报和你的持仓，写候选与决策单元，候选里冻结了当时的输入值。

**怎么失败与降级**：日线不足 200 根、缺当日日线或复权因子异常时，价格规则不产出候选，并记下跳过原因——这和"今天没有信号"是两回事，不会被写成无信号。

[当天这一步](#stage-signals)

## ⑤ 规则计划（plan-1）

**做什么**：只为"建议买入、无冲突、未决定"的单元生成规则计划。公式固定，价位四舍五入到 0.01：

- 参考价：信号日 T 的收盘价，见[参考价](concepts/plan.ref_price.md)。
- ATR：ATR14（Wilder 方法，拆股调整口径；系统只取最近 15 根日线，实际等于最近 14 个真实波幅的简单平均），见 [ATR14](concepts/indicator.atr14.md)。
- 入场区间：参考价 ± 0.5 ATR，见[入场区间](concepts/plan.entry_zone.md)。
- 止损：参考价 − 2 ATR，见[止损](concepts/plan.stop.md)。
- 目标 T1：参考价 + 4 ATR（2R），触及后卖出一半，见[目标 T1](concepts/plan.target1.md)；之后用[移动止损](concepts/plan.trailing_stop.md)。
- 有效期：T+1 至 T+3 个交易日，见[有效期](concepts/plan.validity.md)。
- 建议仓位：取 资金 × `risk_pct` ÷ 每股风险、单票上限、总持仓剩余空间三者中最小的；`risk_pct` 默认 1%，单票上限默认 25%，总持仓上限默认 100%（均为配置项）。缺资金快照时只给每股风险并标 `no_equity`，没有剩余空间则计划作废（`no_room`），见[建议仓位](concepts/plan.sizing.md)。
- 财报：有效期内有财报则计划作废；之后 10 个交易日内有财报，或日期未知、已过，则加提示，见[财报规则](concepts/plan.earnings.md)。
- 市场环境：冻结进计划的输入；防守区制、快照失败、行业弱势分别加提示，价位不变，见[市场环境提示](concepts/plan.context_flags.md)。

计划有[状态与作废原因](concepts/plan.status.md)。每份计划的价位都能只用它的输入所指向的已存行重算，批处理会做一次核对，结果是一致、不一致或不完整，见[推导与一致性](concepts/plan.derivation.md)；"推导一致"只说明算术正确。你采纳时也可以提交[自定计划](concepts/plan.own.md)。

**读什么、写什么**：读日线、财报日、区制和你的资金快照与敞口，写计划。同一单元重跑，结果相同就返回原计划，不同则记冲突、不覆盖。

**怎么失败与降级**：ATR 算不出（日线太少）则这份计划不生成并记原因；推导核对发现不一致或不完整时，这一阶段记为降级。

[当天这一步](#stage-plan)

## ⑥ Agent 建议

**做什么**：Agent 是"挑战者"：对每个买入候选独立给出一份计划，并行展示在规则计划旁，不改主计划。整个流程：

- **取数**：Agent 只能调用九个只读工具：`get_trigger`、`get_price_bars`、`get_indicators`、`get_filings`、`get_news`、`get_earnings`、`get_market_context`、`get_position`，以及 `get_concept`。工具不接受日期参数，读价格、申报、资讯、财报日和市场环境时只读截止时间之前入库的数据（`get_trigger`、`get_position` 读当日候选与持仓记录，不按截止时间过滤），只允许查本单元标的和 SPY、SMH、XLK、QQQ，每次调用的参数、返回值和 SHA-256 都留痕。见[工具调用](concepts/agent.tool_calls.md)。
- **`get_concept` 的例外**：它读的是概念卡（也就是你正在读的这类解释），随代码版本走，**不按截止时间回读**，结果标 `point_in_time: false`，记录里照样留痕。卡里只有定义，没有行情；见[概念卡](concepts/system.concept_card.md)。
- **提议**：给出买或不买，买时给入场区间、止损、T1，加 1 到 3 条[论点](concepts/agent.thesis.md)、1 到 5 条[失效条件](concepts/agent.invalidation.md)和 0 到 3 条[下次复查条件](concepts/agent.review_when.md)。每个价位和论点都必须[引用](concepts/agent.citation.md)本次真实发生的工具调用，价位还必须引用价格类工具；见[动作与价位](concepts/agent.action_levels.md)。
- **反方**：另一轮调用逐条对论点找[关键反证](concepts/agent.counter.md)，不能改价位和动作。
- **校验**：引用、价位顺序与 ±50% 区间、论点条数、条件合法性逐项检查，任一项不过整版作废，只显示原因，见[作废与跳过原因](concepts/agent.reject_reasons.md)。
- **第 0 版**：通过校验的建议成为[版本链](concepts/agent.version_chain.md)的第 0 版，之后每天复查。
- **解读**：卖出、观察、冲突的单元不给买卖建议，只写一份[解读](concepts/agent.brief.md)；失败时退回规则版摘要。

**读什么、写什么**：读上述工具能读到的数据，写 Agent 运行、全部工具调用、计划行、版本行和简报，同一事务里写入，任一步失败整体回滚。Agent 在全部规则计划写完之后才开始，失败只影响 Agent 轨道。

**怎么失败与降级**：每个单元最多尝试 3 次；批处理开始 1500 秒后不再启动新单元；额度用尽或达到每日 token 上限时其余单元记为跳过；缺密钥或被关闭时整阶段跳过。价位来自模型，不是投资建议，也未经验证。

[当天这一步](#stage-agent)

## ⑦ 每日复查

**做什么**：对每条处于入场期或持仓期的 Agent 计划链（见[版本链状态](concepts/review.chain_state.md)）复查一次，结论是维持、修订或作废。复查先由系统自己看七项[系统信号](concepts/agent.signals.md)：新 8-K、异常波动、触及止损、触及 T1、临近到期、区制变化、新的用户输入；并判断最新版的失效条件和复查条件。然后按固定顺序得出[复查结论](concepts/agent.review_outcome.md)：

1. 任一失效条件成立：系统规则直接作废，不调用模型。
2. 没有信号、没有新用户输入、复查条件都没满足：系统规则直接维持，不调用模型。
3. 预算闸门（超出时限、Agent 不可用、额度或 token 上限）：写一条跳过记录。
4. 否则调用一次单阶段复查，让 Agent 判定维持、修订或作废。
5. 结论为修订时，再走一遍完整的提议、反方、校验；通过才成为[版本链](concepts/agent.version_chain.md)的新一版，并写明[相对上版变化](concepts/agent.changes.md)。

你贴入的研报、新闻和判断是[用户输入](concepts/agent.user_input.md)：它们只是证据，不是指令，会触发 `user_input` 信号，让当天的复查认真看一次。你也可以在「今日」点"重新复查"，立即对一条链复查一次；除非失效条件已经成立（那仍由系统规则作废），否则一定会调用模型。

**读什么、写什么**：读截止时间之前的数据和你的输入，写复查记录；修订时写新计划行与新版本行。每条链每个交易日至多一条有效的批处理复查，当天刚生成的版本不复查。

**怎么失败与降级**：修订没通过校验，或新版按规则作废时，只记一条没有新版的修订记录，最新版不变，该阶段记为降级；Agent 不可用时，系统能自己判定的照常写，其余写跳过。

[当天这一步](#stage-review)

## ⑧ 复盘卡

**做什么**：检测最近 5 个交易日内结束的交易：持仓全部平掉，或你做过决定的计划止损、到 T1、过期未成交、作废（有持仓的计划不因过期或作废而结束，只看平仓），见[结束事件](concepts/review.retro_end.md)。每个结束事件只建一张[复盘卡](concepts/review.retro_card.md)：程序把当时各版本的价位、之后的日线、三条轨道的 R、你的决定和纪律判定冻结成十个事实，Agent 只负责把这些事实讲成一段话并起草 0–3 条教训，数字它不能改。每次批处理最多起草 5 张，起草不出来的卡之后再试，最多三次。

**读什么、写什么**：读决定、成交、计划、日线和复查记录；写复盘卡和起草记录。教训草稿要你在卡页审定后才进入「我的知识」，审定之前任何 Agent 都读不到。

**怎么失败与降级**：Agent 不可用、超出时限、额度或 token 上限时，卡照常建好，起草留到下一次；某个标的读数出错只影响它自己，下次批处理再试。

[当天这一步](#stage-retro)

## ⑨ 复核与推送

**做什么**：组装今日视图，把摘要推送到 Discord。消息按顺序是：概览、新计划、计划更新（有更新时才发）、持仓、待处理与异常、筛选报告，平常五条，有计划更新时六条，细节见[每日推送](concepts/system.push.md)。推送范围是核心池、持仓和可决定的筛选单元，扩展池不推送，见[观察池分层](concepts/system.pool_tiers.md)。

**读什么、写什么**：读当天所有结果，写发送记录进运行报告。

**怎么失败与降级**：手动运行不推送；同一交易日已推送过就不重复；休市日只发一行"纽约休市，未运行"；推送失败只写进运行报告，下一次推送附"上次推送失败"。

[当天这一步](#stage-push)

## 你做什么：决定与成交

早上打开「今日」，对每个决策单元做一次[决定](concepts/system.decision.md)：采纳、否决，或降级为观察，并写一句理由。采纳买入时选执行依据：Agent 计划（第 n 版）、规则计划或自定价位；Agent 在复查后改到更新的一版时，系统会提示你刷新再决定，避免基于过期版本。你自己在券商下单，然后到「复盘 → 交易与持仓」录入成交，并关联当时的决定，见[持仓与成交](concepts/review.position.md)。

有计划的持仓会按[计划止损](concepts/rule.plan_stop.md)和[计划目标](concepts/rule.plan_target.md)每天判断：触及 T1 之后，止损变为 开仓以来最高收盘 − 3 ATR 与持仓成本中较高者，收盘后更新、次日生效，见[移动止损](concepts/plan.trailing_stop.md)。如果你自己调整价位，会另存一份[自定计划](concepts/plan.own.md)。

## 复盘口径

复盘不评价你"对不对"，只把"计划怎么说、系统怎么算、你怎么做"并排放好：

- **计划影子**：按计划的价位逐日独立模拟，结果用 [R](concepts/review.r_multiple.md) 计，详见[计划影子](concepts/review.plan_shadow.md)；
- **对照组**：所有已决定的单元假设下一交易日开盘入场，看 5、10、20 个交易日的超额，见[对照组](concepts/review.control_group.md)；
- **纪律四项**：[追高进场](concepts/review.discipline_chase.md)、[过早止盈](concepts/review.discipline_early_take.md)、[死扛亏损](concepts/review.discipline_held_loser.md)、[计划外交易](concepts/review.discipline_unplanned.md)；
- **三方对比**：规则、Agent、实际三条轨道并列，见[三方对比](concepts/review.tracks.md)与[状态含义](concepts/review.track_status.md)；Agent 轨道取你[决定时看到的那一版](concepts/review.version_basis.md)，不拿事后修订美化；
- **首版与最新版**：每条 Agent 链分别只算首版和只算最新版，避免样本被修订次数放大，见[首版与最新版汇总](concepts/review.first_latest.md)；
- **周度与月度复盘**：[周度复盘](concepts/review.weekly.md)冻结当期快照，其中"[你学到了什么](concepts/review.weekly_learning.md)"汇总本周的复盘卡和被检验的知识；[月度收益与分档](concepts/review.monthly_return.md)、[流程复查触发](concepts/review.process_check.md)和[风险敏感性表](concepts/review.sensitivity.md)看账户层面；
- **复盘卡与我的知识**：每笔结束的交易有一张[复盘卡](concepts/review.retro_card.md)，你审定的教训进入[我的知识](concepts/system.my_knowledge.md)，被引用后可以按计划影子回看[表现](concepts/review.knowledge_performance.md)；
- **上线前检查**：新规则上线前用库内已有数据回看，见[上线前检查](concepts/review.backcheck.md)。

这些都是描述性统计：样本小、信号同日重叠，只给计数、均值、中位数和分布，不宣称任何规则或 Agent 有效。

## 怎么在系统里核对

不用读仓库文档，下面几个页面各回答一类问题：

- **今天批处理跑了什么**：「今日」顶部的运行一览，九个阶段各一句话，附计数、状态和跳过原因，可以选日期看往日。状态含义见[阶段状态](concepts/system.stage_status.md)，阶段定义见[批处理九个阶段](concepts/system.stages.md)。
- **一份计划的价位怎么来的**：计划卡上的"展开推导"，顺着触发条件、输入快照、逐项计算和校验看一遍，并告诉你推导是否一致。
- **一份 Agent 计划的每个字段和数字从哪来**：计划卡展开后的推理阅读视图，按时间顺序看提议者读了什么、论点与价位、反方提了什么反证、之后的复查与修订，以及校验结果。
- **采集到了什么数据**：「数据」菜单，看六个数据族的覆盖、拉取记录和原始值。
- **某个词是什么意思**：「知识」菜单的"概念"，或者在各页面上点带虚线下划线的概念名，就地展开摘要，再一跳到完整的概念卡。
- **某只股票今天为什么值得关注**：「标的」页，首屏列出信号与计划，K 线上标出候选、各版本计划价位和你的成交。
