# Backlog — 下一版候选

> v2.0.0 发布后的待议事项，还没有排期。真正开工前，先和你讨论定下一版的 roadmap，再按阶段写 spec 和 plan。

## 1. v1 遗留功能：合并或删除

v2.0.0 原样保留了这些功能（清单见 [features/legacy](../features/legacy/README.md)），下一版逐项决定合并进工作台还是删除。

| 功能 | 代码 / 表 / 任务 | 可能的去向 |
| --- | --- | --- |
| Hermes 宏观分析、决策证据（DeepSeek） | `hermes/`、`services/hermes.py`；无表 | 与 Agent 轨道的解读重叠，候选删除；或把宏观判断并入市场环境 |
| SPY/VIX 市场信号、趋势分析 | `market/`；`market_signals`；任务 `metrics` | 工作台已改用池内广度做区制，候选删除 |
| 个股趋势快照、技术面趋势页 | `tickers/`；`ticker_signal_snapshots` | 「标的」页已经展示日线和候选，候选删除 |
| 策略评分 | `strategies/`；`strategy_scores`；任务 `scores` | 已被规则 v1 取代，候选删除 |
| 事件研究 | `research/event_study.py` 等；`event_studies`；任务 `event_study` | 与上线前检查（`backcheck-1`）重叠，候选合并 |
| 美股财季数据、指引、研究观察卡 | `us_research/`、`research/cards.py`；`us_research_*`、`research_observation_cards*` | 候选作为「标的」页的基本面一栏并入，或删除 |
| 「更多」下的旧六个入口 | `web/src/routes/` 中的 Data、Technicals、Strategy、Trade | 跟随上面各项的决定 |

删除时要一并考虑：对应表的去留（新增迁移，执行前备份）、`config.watchlist` 是否还有读者、`DEEPSEEK_API_KEY` 等环境变量。

## 2. v2 暂缓项

来自 [v2 路线 §6](v2-decision-loop.md#6-暂缓与不做)：

| 项 | 何时再议 |
| --- | --- |
| 晋升机制（挑战者替换冠军） | Agent 轨道积累 2–3 个月影子结果后 |
| 期权隐含波动、EPS 超预期 | 有稳定数据源或明确需求时 |
| 盘中价位提醒 | 需要盘中行情源 |
| 邮件推送工作台计划 | 需要时 |

## 3. 未完成的使用验收

v2 各阶段都是 `engineering_done`、`user_acceptance_pending`（详见 [v2 进度](v2-progress.md)）。还需要的真实证据：

- 第一个无冲突的买入单元出现后，核对规则计划的价位、Agent 计划、推送中的计划行与 Agent 行，以及三方对比。
- P3 退出条件：连续两周 `GET /api/workbench/agent-runs` 的 `coverage.missing` 为空；额度类错误码（1113/1308/1310）真实出现时，对照 `detail` 核对。
- 10 月末录入月末资金快照后，核对 11 月的月度推送（没录入的话，11-07 起会提醒一次）。
- 观察池扩大到 ≥ 20 只有 200 根 K 线的股票后，区制才会脱离「样本不足」。
- 从 v1 转入：确认 SEC 只有一个调度器在跑（OpenClaw 侧未核对）；美股工作台四周使用观察。
