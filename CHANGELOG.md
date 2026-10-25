# Changelog

版本号与 roadmap 版本对应：`v2.x` 对应 [roadmap v2](docs/roadmap/v2-decision-loop.md)。

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
