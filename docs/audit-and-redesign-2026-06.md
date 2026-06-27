# 美股投资助手 —— 方案审计与重构报告

> 版本：2026-06-26 ｜ 范围：架构审计（4 层）+ UI 重设计 + 实施路线图
> 代码库：`/home/jianjustin/workspaces/investment-assistant`（远程服务器）
> 说明：本地方案目录（Mac OneDrive `02-项目/美股投资助手`）在本服务器不可访问，本报告基于仓库代码 + `docs/` 实际实现审计得出。

---

## 0. 一句话结论

当前系统是一个**"规则引擎 + 仪表盘"的可用雏形**，但与目标方案存在三个根本性缺口：

1. **能力层**：邮件推送**完全不存在**；Hermes 实际**不推送任何东西**（只写占位文件）；DeepSeek 用的是**伪造的模型 ID `deepseek-v4-pro`**，线上调用大概率 400 且被静默吞掉。
2. **数据层**：**宏观指标采集完全缺失**（没有 FRED/利率/CPI/信用利差，所谓"宏观"只是 SPY+VIX 的换皮）；**结构化财务数据缺失**（只下载 SEC 原始 HTML，从不抽取 EPS/营收）；价格全靠单一 yfinance，无重试/缓存/落库。
3. **策略+指导层**：**回测引擎完全不存在**（"回测"只在路线图和 LLM 提示词里出现）；所有评分都是**最新一根 K 线的点估计**，从未被历史验证；指导层只产出"证据和待办问题"，**不产出 买/卖/持 的交易建议**，也没有前瞻推演。

UI 是 vanilla TS + 全量 innerHTML 重渲染，**全站只有一条手搓 SVG 折线图**，对投资工具而言可视化几乎为零。

下文给出每层的「现状 → 差距 → 重构方案」，以及一张分阶段落地路线图。

---

## 1. 现状架构总览

```
┌────────────────────────────────────────────────────────────────────┐
│  Web 仪表盘 (vanilla TS + Vite + Tailwind)  ←—— 全量 innerHTML 重渲染 │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ /api/*  (stdlib http.server，手写路由)
┌──────────────────────────────┴─────────────────────────────────────┐
│  investment_assistant/  (新包，systemd 实际运行路径)                  │
│   ├─ hermes/      能力层：deepseek_client / daily(占位) / macro      │
│   │               / decision_evidence / agents(仅元数据)            │
│   ├─ market/      市场信号：SPY 200MA + VIX → green/yellow/red       │
│   ├─ tickers/     个股趋势快照 (RS vs SPY/QQQ)                       │
│   ├─ strategies/  trend_relative_strength 加权打分(唯一策略)         │
│   ├─ filings/     SEC EDGAR 下载(仅存 HTML 文件)                     │
│   └─ research/    brief / execution_plan (★无任何调用方，死代码)     │
│                                                                      │
│  data/ signals/ notify/ ops/ vault/  (旧"earnings-agent"代码)        │
│   └─ Discord 推送只在这条旧路径里，生产 daily 流程从不触发           │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                    PostgreSQL 16 (Docker, 127.0.0.1:5433)
                    4 张表：market_signals / watchlist_items
                            / ticker_signal_snapshots / strategy_scores
```

**两套并行代码库**是最大的工程债：`investment_assistant/`（生产路径）反向依赖旧 `data/` 包取价/取 filings，而旧的 `signals/ notify/ ops/ vault/` 在生产路径中已是死代码。README/docs 几乎全在描述旧系统，严重误导。

---

## 2. 四层审计结论

### 2.1 Hermes 能力层

**目标**：Discord + 邮件推送；基于 DeepSeek 完成投资深度研究。

| 能力 | 现状 | 差距 |
|---|---|---|
| DeepSeek 深度研究 | `hermes/deepseek_client.py` 单函数 `request_json_completion`，stdlib `urllib` POST，`response_format=json_object` | 模型 ID `deepseek-v4-pro` **非真实**（真实为 `deepseek-chat`/`deepseek-reasoner`），`thinking`/`reasoning_effort` 为非标准参数；`except Exception: return None` **吞掉所有错误**；**无重试/无退避/无 token 上限/无成本统计**；45s 同步阻塞在 HTTP 工作线程内 |
| Discord 推送 | `notify/discord.py` 三个 webhook 频道，模板完整 | **只被旧 `ops/daily_scan.py`/`earnings_monitor.py` 调用**，Hermes 生产 daily 流程从不发 Discord |
| 邮件推送 | **不存在** | 全仓 0 处 `smtplib/smtp/sendgrid/ses`；`notify/__init__.py` 为空文件。**目标最大缺口** |
| 每日编排 | `hermes/daily.py` → `assistant.daily_brief()` | `daily_brief()` 是**占位桩**：写死一个 `daily-brief-placeholder.md`，**不调 LLM、不推送、无真实内容** |
| 深度研究编排 | `agents.py` 仅存配置（CRUD），`filing_digest`/`watchlist_research`/反方挑战 Agent 均 `planned` 未执行 | 没有多步研究链路 |

**关键文件**：`hermes/deepseek_client.py:15,47`、`hermes/assistant.py:8`、`hermes/daily.py:15`、`notify/`（缺 `email.py`）。

**重构方案**
- **新增邮件能力**：`notify/email.py`，`EmailClient.send(subject, html, text)` + `from_env()`（`SMTP_HOST/PORT/USER/PASSWORD/EMAIL_FROM/EMAIL_TO`，或 SendGrid/SES API）；配套 HTML 邮件模板。
- **打通推送**：把 `run_daily` 的占位 brief 改为真实内容（宏观分析 + 决策证据 + 交易建议），并新增可注入的 `notify_step`（沿用现有依赖注入测试模式），同时下发 Discord + 邮件。
- **修复 DeepSeek**：换真实模型 ID 并集中配置（现散落 6 处）；用分类异常 + 日志替换裸 `except`；加 429/5xx 重试退避 + `max_tokens`；把 LLM 调用移出请求线程（后台任务 + run_log 轮询，run_log 已存在）。
- **深度研究链路**：宏观 → 个股 → 财报摘要 → 反方挑战 的多步编排，复用已定义但未执行的 agent 角色。

---

### 2.2 数据采集层

**目标**：宏观指标采集；美股财报 + 行情采集。

| 数据 | 来源 | 落库 | 问题 |
|---|---|---|---|
| 行情 OHLCV | yfinance（非官方） | **不落库**，每次重算重新全量下载 | 单点依赖、无重试/退避/缓存、`^VIX` 偶发空值 |
| 市场信号 | SPY 200MA + VIX | `market_signals` 表 | `signal_date` 永远写 `date.today()`，周末/节假日落入陈旧收盘价 |
| 个股趋势 | yfinance 衍生 | `ticker_signal_snapshots` | MA 用 `.tail(N).mean()` 而非滚动 SMA |
| 财报日历 | yfinance `earnings_dates` | 不落库 | ±2 天窗 + EPS 非 NaN，易漏报 |
| SEC 财报 | EDGAR submissions/Archives | **仅存 HTML 文件**，无 DB | 无 XBRL `companyfacts`，**从不抽取 EPS/营收/指引**；历史分页未默认启用 |
| **宏观指标** | **无** | **无** | **完全缺失** |

**宏观是最大缺口**：`hermes/macro_analyst.py` 名为"宏观"，实为对 `market_signals`（SPY+VIX）的再解读；真正的 10Y/Fed Funds/CPI/HY 利差只作为**硬编码"下次去看一下"的提醒字符串**出现，背后零数据。

**关键文件**：`data/price.py:5`、`data/sec.py:236,300`、`market/service.py:52`、`tickers/trend.py:90`、`macro_analyst.py:205,277`。

**重构方案**
- **接入真实宏观源**：FRED API（免费，需 key）采集 DGS10/DGS2（含 2s10s）、FEDFUNDS/DFF、CPIAUCSL、失业率、HY OAS（BAMLH0A0HYM2）→ 新表 `macro_indicators(series_id, date, value, source, fetched_at)`，喂给 `_classify_macro_state` 取代 SPY/VIX 推断。
- **结构化财务**：接 SEC XBRL `companyfacts`/`companyconcept`，把营收/EPS/毛利/现金流落入 `fundamentals` 表；filings 元数据落 `filings` 表（现仅文件系统、不可查）。
- **行情可靠性**：原始 OHLCV 落表（可复现 + 回测基底）；所有 yfinance/EDGAR 调用加 重试 + 退避 + 限流；CIK 映射落盘缓存；增加备用付费源（Tiingo/Polygon/Alpha Vantage）消除单点。
- **新鲜度守卫**：`signal_date` 取实际最新 bar 日期而非 `today()`。

---

### 2.3 策略层

**目标**：根据美股数据完成回测等分析。

- **唯一策略** = `trend_relative_strength`：权重全硬编码（uptrend+30 / 均线多头+20 / 跑赢SPY+15 / 跑赢QQQ+15 / 放量+10 / 宏观offense+10），上限 100。自带免责声明"评分是证据非指令"。
- 其余为信号：`signals/technicals.py`（RS/VCP/MA reclaim，阈值 0.70、1.2 硬编码，**不落库**）、市场门 green/yellow/red。
- "手动策略评分"只是手动**触发**上面这一个策略，非独立策略。

**核心缺口 —— 回测引擎完全不存在**。全仓搜索 `backtest|回测|win.?rate|drawdown|sharpe|equity.?curve` 仅命中：① 路线图标注"Phase 4 规划中"；② LLM 提示词里的流程阶段名。**没有任何历史模拟、胜率、回撤、收益指标**。每个评分都是最新一根 K 线的点估计，从未被验证。

**其他风险**：所有阈值/权重无校准来源；`run_strategy_score_scan` 拉**实时**宏观却写回快照的 `score_date`，重跑会**篡改历史评分**（upsert）；数据/DB 异常被静默吞成空 `[]`。

**重构方案**
- **建真实回测引擎** `investment_assistant/backtest/engine.py`：输入 信号函数 + 价格源 + 日期区间 + 持有规则；**严格 point-in-time 回放**——重构取价器接受 `as_of` 参数，对历史每个 `signal_date` 切片 `[:signal_date]` 再调用现有 `classify_ticker_trend`/`score_trend_relative_strength`（防前视偏差的关键）。
- **指标**：+5/+10/+20d 前瞻收益、胜率、盈亏比、最大回撤、对 SPY 超额；落 `backtest_reports` 表；按分数档位（0–40/40–70/70–100）分桶，用前瞻收益**反推权重**取代拍脑袋的 +30/+20。
- **配置化所有魔法阈值**，使其可调可回测；评分改为自动夜间任务，宏观上下文按 `signal_date` 冻结。

---

### 2.4 指导层

**目标**：根据分析结果对后续行情推演，提供交易建议。

- **决策证据** `decision_evidence.py` 是主要产物：聚合 宏观态 + top20 关注个股 + top20 策略分 → `{summary, risk_questions, next_actions}`，可选 DeepSeek 精修。但**不产出 买/卖/持**，明确"不做自动交易指令"，输出只是"证据 + 人工待办"。
- **研究简报** `research/brief.py`、**执行计划** `research/execution_plan.py`：**均无任何应用层调用方**（死代码，仅测试引用）；人工闸门 approve/reject/revise 是 UI 占位。
- **前瞻推演 = 完全缺失**：`forward/projection/scenario/推演` 零实现。
- 唯一方向性输出在旧路径 `ops/daily_scan.py` → Discord，只报"哪个技术信号触发"，非买卖决策、无 进/出场/仓位。

**重构方案**
- **信号→建议管线**：确定性映射 `(宏观态, 策略分, 技术信号) → {action: long|watch|wait|avoid, conviction, 建议止损, 建议目标, 仓位%}`；给 `ExecutionPlan` 加 进场/止损/目标/R 倍数/最大仓位 量化字段，并**真正调用** `create_execution_plan`；建议落 `execution_plans` 表，使日后可与已实现收益回连做准确率统计。
- **前瞻推演** `guidance/projection.py`：基于当前价 + ATR 波动率给出 基准/乐观/悲观 价格路径，并用回测胜率做概率加权期望值，作为 `scenarios[]` 注入决策证据。
- 打通"研究 → 发现 → 回测 → 观点 → 计划"端到端链路，接上现有人工闸门。

---

## 3. UI 重新设计

### 3.1 现状与问题
- **技术栈**：vanilla TS + Vite 6 + Tailwind 3，唯一依赖 lucide 图标。**每次交互全量 `root.innerHTML` 重建 + 重绑所有事件**——表单丢焦点、丢滚动、闪烁；单一全局 `state` 对象 + 手动 `render()`。
- **18 个路由 / 8 个分组**，侧栏 288px 双行标签 + 嵌套手风琴，chrome 过重。
- **可视化几乎为零**：全站唯一图表是 `market.ts:155-182` 手搓的一条 VIX SVG 折线（无坐标轴/标签/tooltip/交互）。**无任何图表库**，无 K 线、无回测净值曲线、无宏观时间序列、无评分分布。
- 视觉：Inter 字体**实际未加载**静默回退；只有一个 teal 主色 + 散落的 Tailwind 粉彩；数字用正文字体不对齐；卡片千篇一律像设置表单。decision-evidence/raw 直接打印 `key: value` 裸对象。
- 加载是 13 个 `/api` 并行 `Promise.all` 全有或全无阻塞，无骨架屏、无自动刷新；human-gate 用写死的 TSLA mock。

### 3.2 重设计方案

**框架选择（建议：Svelte 5）**
- 保持 vanilla：零迁移但全量重渲染是卡顿根因，重做交互图表/抽屉很痛，不值。
- React：生态最大但运行时最重、样板最多。
- **Svelte（推荐）**：编译为接近 vanilla 的小体积 JS，真正响应式替换 `state+render()`，与现有 per-feature `render*` 分解天然契合，Tailwind 已就绪，Vite 原生支持。后端是框架无关 JSON，无需改动。
- 备选 Preact + signals（要 JSX + 极小体积时）。

**信息架构**（18→6，任务导向）
1. **Dashboard 今日态势**：宏观态 hero + 市场信号图 + 关注热力 + KPI 条（合并 workbench + market-overview）。
2. **Market**：信号时序图（K 线/面积）+ 派发日可视化 + 趋势判断（合并 market-*）。
3. **Watchlist & Tickers**：表格 + 个股详情抽屉（均线堆叠图、RS vs SPY/QQQ 图）。
4. **Strategy**：评分分布图 + 表（证据/限制）+ **回测净值曲线**（合并 strategy-scores + runs）。
5. **Hermes**：overview/agents/ideas/decision-evidence/human-gate 子视图。
6. **System**：services/operations/filings/raw（管理区）。

**视觉系统**
- **设计 token**（CSS 变量）：`--bg/--surface/--surface-2/--border/--text/--text-muted/--accent/--success/--warn/--danger`，取代散落的 Tailwind 粉彩；保留 teal 主色 + 真正的中性色阶 + 金融涨跌红绿对；分层 elevation。
- **字体**：自托管 Inter 变体（UI）+ 等宽/tabular 数字（`font-variant-numeric: tabular-nums`）让金融数字列对齐；建立 display/h1/h2/body/caption 真实字号梯度。
- **布局**：细窄可折叠图标栏侧边；密集数据表（粘性表头、斑马/悬停、可排序）；右侧**详情抽屉**取代裸对象 dump。
- **暗色模式**：token 驱动（`data-theme` 切换），替换硬编码 `bg-slate-950`。
- **响应式**：卡片单列回流，宽表冻结首列 + 横向滚动。

**图表库（最高 ROI 升级）**
- **价格/市场时序 + K 线**：TradingView Lightweight Charts（~45KB，金融专用，十字光标/时间轴，免费）。
- **仪表盘通用（评分分布、宏观柱、净值/回测曲线、热力）**：ECharts（主题化、原生暗色）或体积敏感时用 uPlot。
- 数据已在 `/api/market/signals`、`/api/tickers/trends`、`/api/strategies/scores`，只缺可视化。

**交互/后端配合**
- 加自动刷新（轮询或给 `server.py` 加 SSE 推送新信号/任务完成）。
- 用 per-panel 骨架屏替换全有或全无阻塞加载。
- 先把 human-gate / strategy-runs 接真实端点再前置展示。

---

## 4. 基础设施与安全（横切）

- **安全（先做）**：仪表盘鉴权**默认失败开放**（`server.py:757` 无密码即放行）且绑 `0.0.0.0:8787` 明文无 TLS。改为：无密码则拒绝启动 / 仅绑 `127.0.0.1` + nginx/Caddy 反代做 TLS+鉴权。
- **迁移**：`db.apply_migration` 仅顺序执行 SQL，**无 `schema_migrations` 版本表**，无法 `ALTER`/run-once。引入 Alembic 或最简版本账本。补 `strategy_scores.source_snapshot_id → ticker_signal_snapshots(id)` 外键。引入连接池。
- **调度**：daily timer `OnCalendar=08:30` 跑在主机本地时区、未与 `config.brief_time_local` 对齐，应钉死 US/Eastern；定时任务应写 `run_log`（现仅手动运行写）。
- **测试/CI**：19 个测试均 mock 离线；`test_db_sql.py` 只断言迁移文件**含子串**、从不执行 SQL；**无 CI**、无 `pyproject.toml`。加 GitHub Actions（lint+pytest+Postgres service 容器真实 DB 测试）。
- **仓库卫生**：消除两套并行代码库——要么把 `data/ signals/` 折进 `investment_assistant`，要么形式化为共享库；删真正死代码（`vault/`、`ops/daily_scan.py`、根目录重复脚本、`sec_downloader` 三处 shim）；依赖加上界 + lockfile（uv/pip-tools），`pytest` 移到 dev 依赖；重写 README/getting-started 指向真实部署。

---

## 5. 分阶段落地路线图

> 原则：先补**目标硬缺口**（邮件推送 / 宏观采集 / 回测引擎 / 交易建议），再做 UI 重做，安全项贯穿始终插在最前。

### Phase 0 — 止血与对齐（0.5 周）
- 修 DeepSeek 模型 ID + 错误处理 + 重试；仪表盘鉴权改为 fail-closed + 绑 127.0.0.1。
- 重写 README/docs 指向真实部署；标注两套代码库边界。

### Phase 1 — 能力层补全（1 周）
- 新增 `notify/email.py` + 邮件模板；打通 `run_daily` 真实 brief + Discord/邮件双推送。
- DeepSeek 调用移出请求线程（后台任务 + run_log）。

### Phase 2 — 数据层补全（1.5 周）
- FRED 宏观采集 + `macro_indicators` 表，喂入宏观分类。
- SEC XBRL 结构化财务 + `fundamentals`/`filings` 表。
- OHLCV 落库 + 全链路重试/退避/缓存 + 新鲜度守卫；备用价源。

### Phase 3 — 策略回测引擎（1.5 周）
- `backtest/engine.py` 严格 point-in-time 回放 + 指标 + `backtest_reports` 表。
- 阈值/权重配置化；按分数档分桶反推权重；评分改夜间自动任务、宏观按日冻结。

### Phase 4 — 指导层（1 周）
- 信号→建议映射（action/仓位/止损/目标）+ `execution_plans` 落表 + 真实人工闸门。
- `guidance/projection.py` 前瞻 base/bull/bear 推演 + 概率加权期望。

### Phase 5 — UI 重做（2 周）
- 迁移 Svelte 5 + 设计 token + 暗色模式；信息架构 18→6。
- 接入 Lightweight Charts + ECharts：市场时序/K 线、个股均线 RS、评分分布、**回测净值曲线**、宏观时序。
- 骨架屏 + 自动刷新（SSE）。

### Phase 6 — 工程化收尾（0.5 周）
- Alembic 迁移 + 外键 + 连接池；GitHub Actions CI + 真实 DB 测试；依赖锁定；删死代码。

---

## 6. 目标 ↔ 现状 ↔ 缺口 一览

| 目标 | 现状 | 状态 |
|---|---|---|
| Hermes Discord 推送 | 代码在，但只在旧路径，生产不触发 | ⚠️ 需打通 |
| Hermes 邮件推送 | 不存在 | ❌ 缺失 |
| DeepSeek 深度研究 | 单次 JSON 调用，模型 ID 伪造、错误吞掉、无重试 | ⚠️ 形同虚设 |
| 宏观指标采集 | 仅 SPY+VIX 换皮，无利率/CPI/信用 | ❌ 缺失 |
| 财报采集 | 仅下载 HTML，不抽取结构化财务 | ⚠️ 半成品 |
| 行情采集 | yfinance 单点，不落库、无重试 | ⚠️ 脆弱 |
| 回测分析 | 完全不存在，只有点估计打分 | ❌ 缺失 |
| 行情推演 | 完全不存在 | ❌ 缺失 |
| 交易建议 | 只产"证据+待办"，不出买卖持 | ❌ 缺失 |
| UI | vanilla 全量重渲染，全站一条折线 | ⚠️ 需重做 |
