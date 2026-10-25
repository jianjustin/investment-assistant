# Backlog — 下一版候选

> v2.0.0 发布后的待议事项，还没有排期。真正开工前，先和你讨论定下一版的 roadmap，再按阶段写 spec 和 plan。

## 1. v1 遗留功能：合并或删除

已于 `v2.1.0` 落地（2026-10-25）：下表全部执行完毕，设计见 [spec](../specs/2026-10-25-v2.1-legacy-consolidation-design.md)，去向逐项见墓碑页 [features/legacy](../features/legacy/README.md)。

| 功能 | 代码 / 表 / 任务 | 决定 |
| --- | --- | --- |
| Hermes 宏观分析、决策证据（DeepSeek） | `hermes/`、`services/hermes.py`；无表 | 删除；`run_log` 移到共享底座；去掉 `DEEPSEEK_API_KEY` |
| SPY/VIX 市场信号、趋势分析 | `market/`；`market_signals`；任务 `metrics` | 删除；决策单元去掉 `market_status` |
| 个股趋势快照、技术面趋势页 | `tickers/`；`ticker_signal_snapshots` | 删除；K 线 + MA20/50/200 + 成交量图并入「标的」页，改读 `price_bars` |
| 策略评分 | `strategies/`；`strategy_scores`；任务 `scores` | 删除 |
| 事件研究 | `research/event_study.py` 等；`event_studies`；任务 `event_study` | 删除；上线前检查升级为 `backcheck-2`，加触发后 5/10/20 日相对 SPY 的超额 |
| 美股财季数据、指引、研究观察卡 | `us_research/`、`research/cards.py`；`us_research_*`、`research_observation_cards*` | 财季数据与指引并入「标的」页基本面一栏；观察卡删除 |
| 「更多」下的旧入口 | `web/src/routes/` 中的 Data、Technicals、Strategy、Trade | 四个入口删除；SEC 文件记录移到「工具」；旧地址回落到「今日」 |

表的删除走迁移 022，真实库执行前 `pg_dump` 备份、单独授权；`config.watchlist` 仍有 SEC 下载器和关注列表兜底两个读者，保留。

v2.1.0 之后的新候选（讨论中提出，暂不做）：

| 项 | 说明 |
| --- | --- |
| Agent 工具 `get_fundamentals` | 让 Agent 读「标的」页同一份财季数据 |
| K 线图标注候选与计划价位 | 在「标的」页图上画出规则候选、入场区间、止损、目标 |

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
