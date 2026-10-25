# v1 遗留功能

这些功能来自 roadmap v1，在 v2.0.0 中**保留、可用，但不再演进**，以后会逐项合并进工作台或删除，排期见 [backlog](../../roadmap/backlog.md)。前端入口都收在侧栏「更多」下面。

| 功能 | 文档 | 代码 | 定时任务 |
| --- | --- | --- | --- |
| Hermes 宏观分析与决策证据（DeepSeek） | [hermes.md](hermes.md) | `hermes/`、`services/hermes.py` | 无 |
| SPY/VIX 市场信号、个股趋势、策略评分 | [strategy-and-signals.md](strategy-and-signals.md) | `market/`、`tickers/`、`strategies/`、`facts/` | `metrics`、`scores` |
| 事件研究 | [event-study.md](event-study.md) | `research/event_study.py`、`research/event_sources.py` | `event_study`（无默认调度行） |
| 美股财季数据、指引与研究观察卡 | [us-research.md](us-research.md) | `us_research/`、`research/cards.py` | 无（手动采集） |

与主线的关系：工作台不读这些模块写的表（`market_signals`、`ticker_signal_snapshots`、`strategy_scores`、`event_studies`），也不回填它们。v1 的 SPY/VIX 门控、评分和事件研究都没有通过 Phase 0 正式 Gate（全部 HOLD），不要把它们的输出当作交易指令。
