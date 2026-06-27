# 美股投资助手 —— 执行计划（从审计方案拆解）

> 来源：`docs/audit-and-redesign-2026-06.md`
> 生成：2026-06-27 ｜ 状态基线：`main` @ `45deb39` + 未提交工作树
> 用法：每个任务都是一个可独立交付、可验证的工作单元。`验收` 列为合并门槛。
> 标注：⬜ 未开始 · 🟡 进行中（工作树已有改动）· ✅ 已完成

---

## 0. 当前工作树盘点（先消化再继续）

未提交改动已经把 **Phase 0 的一半**做掉了，继续前先确认状态：

| 文件 | 已有改动 | 含义 |
|---|---|---|
| `investment_assistant/config.py` | 新增 `llm/notify/prices` 嵌套配置段；`model_default="deepseek-chat"` | Phase 0 配置化 + Phase 1 邮件开关已起步 |
| `investment_assistant/dashboard/server.py` | `_resolve_bind_host()` 无密码拒绝公网绑定（fail-closed） | Phase 0 安全项已落 |
| `investment_assistant/hermes/deepseek_client.py` | `request_json_completion_verbose` 返回结构化错误 | Phase 0 错误处理已起步 |
| `investment_assistant/db.py` | （待 diff 确认） | 可能含迁移/schema 改动 |
| `tests/test_phase0_spine.py` | 新增脊柱测试 | 锁定 Phase 0 契约 |
| `investment_assistant/dashboard/health.py`、`status_page.py` | 新文件（未跟踪） | 健康检查 / 状态页 |
| `pyproject.toml` | 新文件（未跟踪） | Phase 6 工程化起步 |

**T0.0 — 消化工作树**
- 动作：`git diff` 通读以上文件；`pytest tests/test_phase0_spine.py` 跑通；决定先提交这批 WIP 再继续，避免后续任务与之冲突。
- 验收：工作树 WIP 测试全绿；WIP 以 1～2 个语义清晰的 commit 落地。

---

## Phase 0 — 止血与对齐（剩余项）

> 目标硬缺口前置：模型 ID / 错误处理 / 安全 / 文档对齐。多数已在工作树中，下面是补完项。

**T0.1 — DeepSeek 模型 ID 集中化 🟡**
- 现状：`deepseek-v4-pro` 仍散落在 `test_market_signal_admin_api.py`、`test_hermes_macro_analyst.py` 与生产调用处。
- 动作：所有调用读 `cfg.llm.model` / `cfg.llm.deep_research_model`；删除硬编码 `deepseek-v4-pro`；更新仍引用旧 ID 的测试为真实 ID。
- 文件：`hermes/deepseek_client.py`、`hermes/macro_analyst.py`、`hermes/decision_evidence.py`、相关测试。
- 验收：`grep -rn deepseek-v4-pro` 仅命中“断言不等于旧 ID”的负向测试；线上一次真实调用返回 200。

**T0.2 — DeepSeek 重试 / 退避 / token 上限 🟡**
- 动作：在 `deepseek_client` 加 429/5xx 指数退避重试（`cfg.llm.max_retries`）、`max_tokens`、超时；裸 `except Exception` 改为分类异常 + 日志；保留 verbose 错误返回。
- 验收：单测注入 429→429→200 验证重试；注入 500×N 验证最终结构化失败而非吞掉。

**T0.3 — 安全收尾 🟡**
- 现状：`_resolve_bind_host` 已 fail-closed。
- 动作：确认默认绑 `127.0.0.1`；文档化“公网暴露须 nginx/Caddy 反代 + TLS + 鉴权”；为 `_authorized` 加单测（无密码拒绝 / 错密码拒绝 / 正确放行）。
- 验收：`test_dashboard_server.py` 覆盖三种鉴权路径；无密码 + 公网 host 时进程拒绝启动。

**T0.4 — 文档对齐**
- 动作：重写 `README.md` / `docs/getting-started` 指向真实部署路径（`investment_assistant/`，systemd），明确标注两套代码库边界与 `data/ signals/ notify/ ops/ vault/` 旧路径为遗留。
- 验收：README 不再描述旧 earnings-agent 为主路径；含真实启动命令。

---

## Phase 1 — 能力层补全（邮件 + 推送打通）

**T1.1 — 邮件客户端**
- 动作：新建 `notify/email.py`：`EmailClient.send(subject, html, text)` + `EmailClient.from_env()`（`SMTP_HOST/PORT/USER/PASSWORD/EMAIL_FROM/EMAIL_TO`）；预留 SendGrid/SES 适配位；HTML 邮件模板。
- 文件：`notify/email.py`（新）、`notify/templates/`（新）。
- 验收：单测用 `smtplib` mock 验证拼装与发送；`from_env()` 缺变量时返回禁用态而非崩溃。

**T1.2 — 真实 daily brief**
- 现状：`hermes/daily.py` / `assistant.daily_brief()` 是写死占位文件的桩。
- 动作：`run_daily` 产出真实内容 = 宏观分析 + 决策证据 +（Phase 4 后）交易建议；用依赖注入的 `notify_step` 同时下发 Discord + 邮件。
- 文件：`hermes/daily.py`、`hermes/assistant.py`、`notify/discord.py`（复用）。
- 验收：`test_hermes_daily.py` 验证 brief 含真实区块、`notify_step` 被调用且同时命中两个渠道；不再写 `daily-brief-placeholder.md`。

**T1.3 — LLM 调用移出请求线程**
- 动作：将同步 45s DeepSeek 调用改为后台任务 + `run_log` 轮询（`run_log` 已存在）；API 立即返回 run id，前端轮询状态。
- 文件：`hermes/` 编排层、`dashboard/server.py`（run 端点）。
- 验收：触发深研的 API 在 <1s 返回 run id；run_log 记录 pending→done；HTTP 工作线程不再阻塞。

**T1.4 — 深度研究多步链路（可拆为后续迭代）**
- 动作：宏观 → 个股 → 财报摘要 → 反方挑战 的编排，复用 `agents.py` 已定义但未执行的角色。
- 验收：一条端到端 run 产出四段结构化结果并落 run_log。

---

## Phase 2 — 数据层补全

**T2.1 — FRED 宏观采集 + `macro_indicators` 表**
- 动作：迁移 `005_macro_indicators.sql`（`series_id, date, value, source, fetched_at`，主键 `(series_id,date)`）；新建 `data/fred.py` 采集 DGS10/DGS2(2s10s)/FEDFUNDS/DFF/CPIAUCSL/失业率/HY OAS(BAMLH0A0HYM2)，带重试退避。
- 动作：`_classify_macro_state` 改读 `macro_indicators` 取代 SPY/VIX 推断。
- 文件：`migrations/005_*.sql`、`data/fred.py`（新）、`hermes/macro_analyst.py`。
- 验收：采集任务落库；`test_hermes_macro_analyst.py` 改为基于真实指标分类；FRED 无 key 时优雅降级。

**T2.2 — SEC XBRL 结构化财务 + `fundamentals` / `filings` 表**
- 动作：迁移建 `fundamentals`（营收/EPS/毛利/现金流）与 `filings`（元数据）表；接 `companyfacts`/`companyconcept` 抽取并落库；CIK 映射落盘缓存。
- 文件：`migrations/006_*.sql`、`data/sec.py`、`filings/`。
- 验收：给定 ticker 抽出最近若干季营收/EPS 入 `fundamentals`；filings 可 DB 查询而非仅文件系统。

**T2.3 — OHLCV 落库 + 可靠性 + 新鲜度守卫**
- 动作：迁移建 `price_bars` 表；`data/price.py` 落库 + 重试/退避/限流 + 缓存；备用付费源（Tiingo/Polygon/Alpha Vantage 之一）消除单点；`signal_date` 取实际最新 bar 日期而非 `today()`。
- 文件：`migrations/007_*.sql`、`data/price.py`、`market/service.py`、`tickers/trend.py`。
- 验收：重复运行不重复全量下载（命中缓存/库）；周末跑出的 `signal_date` = 最近交易日；主源失败自动切备用。
- 备注：MA 顺手修为滚动 SMA（现 `.tail(N).mean()`）。

---

## Phase 3 — 策略回测引擎（目标硬缺口）

**T3.1 — Point-in-time 取价器改造**
- 动作：重构取价器接受 `as_of` 参数，对历史每个 `signal_date` 返回 `[:signal_date]` 切片（防前视偏差的关键基建）。
- 文件：`data/price.py`、`tickers/trend.py`、`strategies/`。
- 验收：单测证明 `as_of=D` 时不可见 D 之后任何 bar。

**T3.2 — 回测引擎**
- 动作：新建 `investment_assistant/backtest/engine.py`：输入 信号函数 + 价格源 + 日期区间 + 持有规则；对历史每个信号日切片回放 `classify_ticker_trend` / `score_trend_relative_strength`。
- 验收：在固定历史样本上产出确定性结果；无前视（用 T3.1 取价器）。

**T3.3 — 指标 + `backtest_reports` 表 + 权重反推**
- 动作：计算 +5/+10/+20d 前瞻收益、胜率、盈亏比、最大回撤、对 SPY 超额；落 `backtest_reports`；按分数档（0–40/40–70/70–100）分桶，用前瞻收益反推权重取代硬编码 +30/+20。
- 文件：`migrations/008_*.sql`、`backtest/engine.py`、`strategies/trend_relative_strength.py`。
- 验收：报告含全部指标并落库；权重由回测产出而非常量。

**T3.4 — 配置化阈值 + 夜间自动评分 + 宏观冻结**
- 动作：所有魔法阈值/权重移入 config；评分改夜间自动任务；`run_strategy_score_scan` 按 `signal_date` 冻结宏观上下文，重跑不再篡改历史 `score_date`（修 upsert 篡改）。
- 验收：历史评分重跑幂等不变；阈值改 config 即生效。

---

## Phase 4 — 指导层（交易建议 + 推演）

**T4.1 — 信号→建议映射**
- 动作：确定性映射 `(宏观态, 策略分, 技术信号) → {action: long|watch|wait|avoid, conviction, 止损, 目标, 仓位%}`。
- 文件：`investment_assistant/guidance/`（新）。
- 验收：给定输入组合产出确定建议；边界档位有单测。

**T4.2 — ExecutionPlan 量化 + 落表 + 真实闸门**
- 动作：给 `ExecutionPlan` 加 进场/止损/目标/R 倍数/最大仓位 字段；**真正调用** `create_execution_plan`（现为死代码）；落 `execution_plans` 表；接通 UI 人工 approve/reject/revise 闸门。
- 文件：`research/execution_plan.py`、`migrations/009_*.sql`、`dashboard/server.py`。
- 验收：一条建议端到端入库并可在 UI 走完闸门；日后可与已实现收益回连。

**T4.3 — 前瞻推演**
- 动作：新建 `guidance/projection.py`：基于现价 + ATR 给 base/bull/bear 价格路径，用 T3.3 回测胜率做概率加权期望，作为 `scenarios[]` 注入决策证据。
- 验收：决策证据含三情景 + 期望值；推演随 ATR/胜率变化。

---

## Phase 5 — UI 重做（Svelte 5 + 图表）

**T5.1 — Svelte 5 迁移骨架**
- 动作：引入 Svelte 5 + Vite（后端 JSON 无需改）；建设计 token（CSS 变量 `--bg/--surface/--border/--text/--accent/--success/--warn/--danger`）；自托管 Inter + tabular-nums；`data-theme` 暗色。
- 验收：现有页面以响应式替换 `state+render()`，交互不再丢焦点/滚动。

**T5.2 — 信息架构 18→6**
- 动作：Dashboard / Market / Watchlist&Tickers / Strategy / Hermes / System 六区重组（按审计 §3.2）。
- 验收：6 个顶层路由可达，旧 18 路由内容无丢失。

**T5.3 — 图表接入**
- 动作：Lightweight Charts 做市场时序/K 线、个股均线+RS；ECharts 做评分分布、宏观时序、**回测净值曲线**、热力。数据已在现有 `/api/*`。
- 验收：每个目标图表渲染真实数据，含坐标轴/tooltip。

**T5.4 — 加载体验 + 自动刷新**
- 动作：per-panel 骨架屏替换全有或全无 `Promise.all`；`server.py` 加 SSE 推送新信号/任务完成；human-gate/strategy-runs 接真实端点。
- 验收：首屏分区渐进加载；新信号无需手刷新即出现。

---

## Phase 6 — 工程化收尾

**T6.1 — 迁移版本化 + 外键 + 连接池**
- 动作：引入 Alembic（或最简 `schema_migrations` 账本）支持 `ALTER`/run-once；补 `strategy_scores.source_snapshot_id → ticker_signal_snapshots(id)` 外键；引入连接池。
- 验收：迁移可重复安全执行；外键约束生效。

**T6.2 — 调度对齐**
- 动作：daily timer 钉死 US/Eastern 并与 `config.brief_time_local` 对齐；定时任务也写 `run_log`。
- 验收：timer 触发时间与配置一致；自动 run 留痕。

**T6.3 — CI + 真实 DB 测试**
- 动作：GitHub Actions（lint + pytest + Postgres service 容器）；`test_db_sql.py` 改为真正执行 SQL 而非子串断言；`pyproject.toml` 锁依赖（uv/pip-tools），`pytest` 移 dev 依赖。
- 验收：CI 绿；迁移在容器 DB 真实跑通。

**T6.4 — 仓库卫生**
- 动作：消除两套并行代码库（`data/ signals/` 折进 `investment_assistant` 或形式化为共享库）；删死代码（`vault/`、`ops/daily_scan.py`、根目录重复脚本、`sec_downloader` 三处 shim）。
- 验收：单一生产路径；`grep` 无死引用。

---

## 依赖与排期建议

```
Phase 0 (剩余, 0.3w) ──► Phase 1 (1w) ─┐
                                       ├─► Phase 4 (1w) ──► Phase 5 (2w)
Phase 2 (1.5w) ──► Phase 3 (1.5w) ─────┘                        ▲
Phase 6 贯穿（CI 尽早，迁移版本化在 Phase 2 前最佳）───────────────┘
```

- **关键路径**：Phase 2（数据）→ Phase 3（回测）→ Phase 4（建议）→ Phase 5（净值曲线可视化）。
- **建议先插 T6.1 迁移版本化**：Phase 2 起要建 5 张新表，先有版本化迁移机制再动 schema。
- **可并行**：Phase 1（能力层）与 Phase 2/3（数据/策略）无强耦合，可双线推进。

## 横切验收门槛（每个 PR）

- 新增/改动逻辑有单测；外部调用（FRED/SEC/yfinance/SMTP/DeepSeek）全部 mock。
- 触碰 schema 必带迁移文件且容器 DB 跑通。
- 不引入新的裸 `except` 吞错；外部失败结构化上报。
