# Changelog

版本号与 roadmap 版本对应：`v2.x` 对应 [roadmap v2](docs/roadmap/v2-decision-loop.md)。

## v2.1.0 — 2026-10-25

v2 路线的收尾版：收拢 v1 遗留功能（[spec](docs/specs/2026-10-25-v2.1-legacy-consolidation-design.md)）。状态：`engineering_done`、`user_acceptance_pending`；迁移 022 已于 2026-10-25 在真实库手动执行（见 [operations/migrations-and-backup.md](docs/operations/migrations-and-backup.md)）。

### 删除

- **Hermes 宏观分析与决策证据（DeepSeek）**：`hermes/`、`services/hermes.py`、`/api/hermes/*`、「交易」页；`run_log` 先移到共享底座 `tasks/run_log.py`。
- **SPY/VIX 市场信号**：`market/`、`market_signals` 表、任务 `metrics` 的信号部分、`/api/market/*`、「数据 → 信号总览」；决策单元不再带 `market_status` 字段。
- **个股趋势快照**：`tickers/`、`ticker_signal_snapshots` 表、`/api/tickers/*`、「技术面趋势」页。
- **策略评分**：`strategies/`、`strategy_scores` 表、任务 `scores`、`/api/strategies/*`、「策略」页。
- **事件研究与研究观察卡**：`research/`、`services/research.py`、任务 `event_study`、`/api/research/*`（含 `us-references`）、`event_studies` 与 `research_observation_cards*` 表；关注列表「下一次事件」改读财报日。
- **推送路由与 `daily` 频道**：`NotifyConfig` 默认路由与已存设置只保留 `filings`、`workbench`、`workbench_review`；`DiscordChannel.DAILY`、`DISCORD_WEBHOOK_DAILY` 删除；已存路由失效时返回结构化错误，不抛异常。

### 并入

- **「标的」页 K 线图**：MA20/50/200 与成交量（最多 250 根日线，MA 用满 450 根历史），图下注明「拆股调整、未分红调整」。
- **「标的」页基本面一栏**：美股财季数据、来源展开、指引录入与手动刷新（原「数据 → 美股研究数据」）；读取失败只影响本栏。
- **上线前检查 `backcheck-2`**：信号后 5/10/20 个交易日相对 SPY 的超额统计（n、均值、中位数、正超额占比）；`backcheck-1` 旧记录超额列显示「—」。
- **SEC 文件记录**：移到「更多 → 工具 → SEC 文件」。

### 迁移

- **`022_drop_v1_legacy.sql`**：删除 `strategy_scores`、`ticker_signal_snapshots`、`market_signals`、`event_studies`、`research_observation_card_versions`、`research_observation_cards` 六张表与 `metrics`、`scores`、`event_study` 调度行；`job_reports` 历史与已冻结的 `backcheck-1` 记录保留；无 `CASCADE`。真实库手动 psql 执行（见 [operations/migrations-and-backup.md](docs/operations/migrations-and-backup.md)）。

### 不兼容变更

- API：删除 `/api/hermes/*`、`/api/market/*`、`/api/tickers/*`、`/api/strategies/*`、`/api/research/*`；`/api/us-research/*` 不变。
- 决策单元（`synthesize` 输出、`/api/workbench/*`）不再有 `market_status` 字段。
- 配置：`config.py` 删除 `market`、`strategy`、`backtest`、`llm` 段与 `model_default`（旧配置文件不改也能加载）；`DEEPSEEK_API_KEY`、`DISCORD_WEBHOOK_DAILY` 不再使用。
- 前端：`#data/...`、`#technicals/...`、`#strategy/...`、`#trade/...` 回落到「今日」。

## v2.0.0 — 2026-10-25

第一个正式版本。完成 roadmap v2 的「数据 → 交易计划 → 复盘」闭环，只做美股。各阶段都是 `engineering_done`，使用验收（`user_acceptance_pending`）仍在进行中。

### 新增

- **美股投研工作台**（[spec](docs/specs/2026-10-23-us-research-workbench-design.md)）：每日批处理采集日线、资讯、SEC 列表，运行规则 v1，按股票、按日合成决策单元；「今日」「标的」「复盘」页面；决定与成交只追加；对照组和周度复盘。
- **P1 规则计划与推送**（[spec](docs/specs/2026-10-23-p1-rule-plans-and-push-design.md)）：ATR、下次财报日；`plan-1` 计划（入场区间、止损、T1、有效期、按风险定仓、超限作废）；持仓止损与移动止损；计划影子跟踪；四个纪律指标；资金快照与出入金；月度收益与分档；北京时间 06:30 Discord 推送。
- **P2 观察池与市场环境**（[spec](docs/specs/2026-10-23-p2-pool-and-market-context-design.md)）：观察池上限 100 只，分核心池（≤ 15 只）与扩展池；行业 ETF 强弱；池内广度与区制标签；FRED HY 利差与 2s10s；上线前检查 `backcheck-1`。
- **P3 Agent 轨道**（[spec](docs/specs/2026-10-24-p3-agent-track-design.md)）：LangGraph + 智谱；工具调用写库并做引用校验；反方步骤；每日 token 预算与额度识别；Agent 计划进入影子跟踪，可选作执行依据。
- **P4 复盘扩展**（[spec](docs/specs/2026-10-25-p4-review-expansion-design.md)）：规则 / Agent / 实际三方对比；滚动 3 个月复查、敏感性表；周度与月度复盘推送（任务 `workbench_review`）；解读统一由 Agent 轨道产出，退役 Codex 解读。
- **文档重构**（[spec](docs/specs/2026-10-25-v2-release-cleanup-design.md)）：架构、功能（按业务能力拆分）、运维、roadmap、spec、plan 各自归位；`tests/test_docs_links.py` 检查相对链接。

### 不兼容变更

- **删除 A 股**：删除 `investment_assistant/ashare/`（含 CNEquity vendor）、`/api/ashares/*`、任务 `ashares`、「数据 → A 股研究数据」页、研究观察卡的 A 股 / 美股切换。
- **观察名单只认美股代码**：`POST /api/watchlist` 提交 A 股代码时返回 400；`GET /api/watchlist` 不再接受 `market` 参数（传了也忽略），响应里不再有 `board` 字段；`/api/watchlist/resolve` 只返回美股候选。
- **研究观察卡**：情景字段 `profit_cny` 删除，利润须同时写 `profit` 和 `currency`。
- **迁移 `021_drop_ashare.sql`**：删除 `cn_observations`、`cn_collection_state`，以及 CN 观察名单行、`CN:` 研究卡及其版本、`ashares` 任务行；`job_reports` 的历史行保留。
- **只支持本机部署**：删除 `deploy/`（NUC + systemd）、`Dockerfile`、`.dockerignore`、`scripts/build-push.sh` 和 Sealos 部署文档。
- **文档路径**：spec 和 plan 从 `docs/superpowers/` 移到 `docs/specs/`、`docs/plans/`；v1 时期的 spec 和 plan 移到 `docs/archive/roadmap-v1/`。

### 已知限制

- 所有规则都未经验证（Phase 0 正式 Gate HOLD）；复盘只给描述性统计。
- 已在真实库验收的部分有：迁移、服务重载、页面与接口检查、一次真实周度推送。尚未出现第一个无冲突的买入单元，所以真实数据上的计划价位、Agent 计划和三方对比还没有核对。待验收清单见 [backlog](docs/roadmap/backlog.md#3-未完成的使用验收)。
- v1 遗留功能（Hermes、市场信号与策略评分、事件研究、美股财季数据与研究观察卡）原样保留，下一版决定合并还是删除。
- yfinance 资讯源不稳定；Agent 额度错误码按文档初值实现，还需要用真实响应核对。
