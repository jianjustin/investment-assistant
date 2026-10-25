# Phase 0 — 数据质量地基 + 事件研究框架 设计 Spec

> 创建：2026-06-30 ｜ 作者：自主 subagent（资深量化/投研系统工程师视角）
> 源需求（已批准）：`docs/roadmap/01-phase0-data-quality-and-event-study.md`
> 方向论证：`docs/roadmap/00-principles-and-direction.md`、`docs/roadmap/README.md`
> 配套实施 plan：`docs/superpowers/plans/2026-06-30-phase0-data-quality-event-study.md`

---

## 0. 自主模式说明

本 spec 由自主 subagent 在隔离 worktree 中产出。roadmap 文档即**已批准的方向**，无法逐一向用户提问，因此 brainstorming 的"交互提问 + 用户批准闸门"改为**自主模式**：我自己探索了仓库代码上下文，对关键设计点列出 2-3 个方案并选定，决策与假设记录在 §3 各节的「决策」块中。下文所有"为什么这样做"都可在代码现状里找到依据。

---

## 1. 目标与范围

### 1.1 一句话目标

用**最小成本**拿到「我关注的信号到底有没有边际信息」的诚实答案：把分散的信号事件**池化成足够样本**，计算信号触发后 +1/+5/+20 交易日的**前瞻超额收益分布**（事件研究 A 层），并先解决**复权 / point-in-time 取价**这个隐形地基。

### 1.2 范围内（In Scope）

- **Task 0.1 数据质量地基**：统一复权口径 + split 跳变校验；point-in-time as-of 取价器 `get_price_history_asof`；交易日历（+N 交易日、跳过假日/停牌）。
- **Task 0.2 事件研究引擎**：`research/event_study.py`，输入 `list[Event]`，输出 `EventStudyResult`（含 `n` / 均值 / 中位数 / 命中率 / t 值 / 置信区间 / 区制分层 / 自动 caveats）。
- **Task 0.3 报告入口**：定时任务（事件研究每日刷新缓存 + 推送摘要）+ **配套手动 CLI**（指定历史日期/区间回放）。
- **审计 + 日志化**：事件研究、数据质量校验、PIT 取价凡能在 dashboard 触发/展示的，都复用 `job_reports` / `run_log` / `_harness` 记录「谁/何时/什么参数/什么结果」。
- **可选**：`event_studies` 结果缓存表（迁移 012，见 §3.6 编号决策）。
- **只读 API + 前端衔接点**：暴露 `GET /api/research/event-study*` 只读端点（优雅降级），数据结构对齐 `EventStudyResult` 供 Phase 3 可视化复用。

### 1.3 范围外（Out of Scope，YAGNI）

- 横截面 IC（B 层）、全组合回测（C 层）——roadmap 明确排在 Phase 0 之后。
- 参数寻优 / 反推权重——`00 §2` 明确禁止（过拟合）。
- EPS surprise 的真实结构化数据——Phase 1 才落库；Phase 0 用 yfinance `earnings_dates` 占位。
- 前端 ECharts 可视化组件——Phase 3 才画；Phase 0 只保证数据结构对齐。
- 新增重依赖：不引入 `pandas_market_calendars`（见 §3.3 决策，自维护最简 NYSE 假日表）。

### 1.4 验收标准

1. `get_price_history_asof(t, end_date, days)` 切片不含 `end_date` 之后任何 bar（前视偏差守卫，有测试）。
2. split 跳变校验：mock 含 2:1 split 的未复权序列触发告警；复权序列不触发（有测试）。
3. `+5 交易日`在跨假日时落到正确交易日（有测试）。
4. `run_event_study(...)` 在构造的已知前瞻收益 mock 上，`mean_excess` / `hit_rate` / 基准扣减计算正确；`n<30` 自动填 `caveats`；区制分层调用 `compute_market_signal_for_date`（有测试，全 mock 离线）。
5. 定时任务经 `_harness.run_task` 落 `job_reports` + `run_log` + Discord 摘要；手动 CLI 与定时共享同一核心函数，仅入口不同（有测试）。
6. 只读端点无 DB 时返回空 + `{"degraded": true}`，不崩。

---

## 2. 现状盘点（设计依据）

实施前已读以下代码，设计完全嫁接现有机制，不另造轮子：

| 现状资产 | 位置 | Phase 0 如何复用 |
|----------|------|------------------|
| as-of 切片取价雏形 | `market/service.py:_default_price_fetcher_until(ticker, days, target_date)` | 提炼为 `data/price.get_price_history_asof`，事件研究 + 区制标签共用 |
| 当日复权取价 | `data/price.py:get_price_history`（`yf.Ticker.history(period=...)`，返回 OHLCV） | 加 `auto_adjust` 口径 + split 校验 |
| 历史市场状态 | `market/service.py:compute_market_signal_for_date(config, target_date, ...)` → `MarketSignal.market_status ∈ {green,yellow,red}` | 事件研究区制分层直接调用，按事件日打标签 |
| 信号来源 | `tickers/trend.py:classify_ticker_trend`（`above_ma_stack`/`outperform_spy` 等）、`strategies/trend_relative_strength.py` | 派生 `Event`（`rs_strong`/`ma_reclaim`/`score_high`） |
| 任务审计/日志骨架 | `tasks/_harness.py:run_task(task, fn, *, config)` → `run_log`(文件) + `job_reports`(DB, 迁移006) + Discord `dispatch` | 事件研究/质量校验定时任务全部经此入口 |
| 任务标准结构 | `tasks/metrics.py`/`filings.py`/`nightly_scores.py`：`_core(config)` + `run(config)=run_task(...)` + `main()` argparse CLI | 新任务照搬此三段式 |
| 调度注册表 | `tasks/scheduler.py:REGISTRY`（name→`Callable[[AssistantConfig],dict]`）+ `scheduled_jobs`(迁移007) | 注册 `event_study` 后，dashboard「立即运行」`POST /api/jobs/{name}/run` 与定时调度**零额外代码**即可用 |
| 后台运行 + SSE | `tasks/runner.py:submit/get/subscribe`、`api/routes/runs.py` | 手动触发异步执行、前端订阅运行状态 |
| 手动回放范式 | `services/market.py:fetch_market_signals`（date / from-to，≤45 天上限，每日 upsert + 结构化 failures） | 事件研究手动 CLI/服务照此模式（as-of 回放、区间上限、结构化失败） |
| 配置脚手架 | `config.py:BacktestConfig(horizons=[5,10,20])`、`StrategyParams(rs_strong=1.2,...)`、`PriceConfig` | 填充 horizons / 事件阈值，无需重设计配置结构 |
| 只读服务 + 降级范式 | `services/jobs.py`（`_has_db()` + `degraded` 标志）、`services/tickers.py`（无 DB 返回 `[]`） | 事件研究只读服务照此降级 |
| 路由注册 | `api/router.py:register(method, exact=/prefix=)` + `api/routes/__init__.py` 显式 import | 新增 `api/routes/research.py` 并加入 `__init__` import |

**关键结论**：Phase 0 的"审计 + 日志化"与"定时/手动双入口"两条硬约束，**完全由现有 `_harness` + `REGISTRY` + `runner` + `market.fetch_market_signals` 范式覆盖**，新代码只需把事件研究核心函数塞进这套既有管道。

---

## 3. 关键设计决策（自主选定，含备选与理由）

### 3.1 PIT 取价器的归属与签名

**问题**：`_default_price_fetcher_until` 当前私有于 `market/service.py`，事件研究也要 as-of 切片，放哪？

- 方案 A：在 `market/service.py` 原地公开。✗ 取价是数据层职责，放 market 层造成 research→market 的横向依赖。
- 方案 B（**选定**）：在 `data/price.py` 新增公共 `get_price_history_asof(ticker, end_date, *, days, fetcher=None)`，返回截至 `end_date`（含）的、行数≤`days` 交易日的复权 OHLCV；`market/service._default_price_fetcher_until` 改为薄封装调用它（保持向后兼容，不破坏现有 `compute_market_signal_for_date`）。
- 方案 C：全新 `data/asof.py`。✗ 与 `get_price_history` 同属取价，分文件徒增认知成本。

**决策**：方案 B。签名 `get_price_history_asof(ticker: str, end_date: date, *, days: int = 260, fetcher: AsofFetcher | None = None) -> pd.DataFrame`。`fetcher` 可注入便于离线测试（默认走 yfinance，按 `end_date` 用 `start/end` 区间拉取后再 `df.loc[:end_date]` 二次裁剪，双保险防前视）。

### 3.2 复权口径与 split 校验

- **复权口径**：`get_price_history` 显式 `auto_adjust=True`（yfinance 默认已 True，但显式声明锁死口径，防版本漂移）；保留 OHLCV 五列不变（不引入 raw/adj 双列，YAGNI——事件研究只需一致复权序列）。
- **split 校验**：新增纯函数 `detect_split_jumps(frame, *, threshold=0.5, earnings_dates=None) -> list[dict]`，扫描相邻日收益，|ret|>threshold 且非财报日 → 记一条 `{date, prev_close, close, ret, suspected: "unadjusted_split"}`。**只告警不改数**（数据修复是 Phase 1 OHLCV 落库的事）；校验结果进 job summary，dashboard 可见。
- 备选：用 yfinance `splits` 对账。✗ 仍依赖网络且 Phase 0 重点是"发现污染"而非"修复"，跳变启发式离线可测、足够。

### 3.3 交易日历

- 方案 A：引入 `pandas_market_calendars`。✗ 重依赖，且仓库纪律倾向最小依赖。
- 方案 B（**选定**）：新增 `data/calendar.py`，自维护一份**最简 NYSE 假日表 + 周末规则**，提供 `is_trading_day(d)`、`add_trading_days(d, n)`、`trading_days_between(start, end)`。固定假日（元旦/独立日/圣诞等）按"逢周末顺延"规则生成，浮动假日（MLK/总统日/阵亡/劳动节/感恩节）按"第 N 个星期 X"规则生成，Good Friday 用已知日期表覆盖近年。常量化、纯函数、离线可测。
- 方案 C：仅周末过滤，忽略假日。✗ "+5 交易日"会系统性偏移，污染 PEAD 量级效应。

**假设**：标的池为美股（watchlist `CRDO/MU/RKLB/NVDA` 全美股），故只做 NYSE 日历。若未来加港股/A 股，再扩展 calendar 模块。

### 3.4 事件研究引擎的数据契约

`research/event_study.py`：

```python
@dataclass(frozen=True)
class Event:
    ticker: str
    date: date
    kind: str                      # eps_beat|eps_miss|rs_strong|ma_reclaim|vcp|score_high
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class HorizonStat:
    horizon: int
    n: int
    mean_excess: float
    median: float
    hit_rate: float                # 超额收益 > 0 的比例
    t_stat: float
    ci95: tuple[float, float]
    std: float

@dataclass(frozen=True)
class EventStudyResult:
    kind: str
    n: int
    horizons: dict[int, HorizonStat]
    by_regime: dict[str, dict[int, HorizonStat]]   # green/yellow/red → horizon → stat
    caveats: list[str]
    generated_at: datetime
    params: dict[str, Any]         # 审计：horizons/benchmark/since/sample 等

def run_event_study(
    events, *, horizons=(1, 5, 20), benchmark="SPY",
    price_fetcher=None, regime_fn=None, calendar=None,
) -> EventStudyResult: ...
```

**统计纪律（写进实现，硬性）**：
- **超额收益** = 个股前瞻收益 − 同期基准（SPY）前瞻收益，绝不报绝对收益（否则测的是大盘 beta）。
- 每个 `HorizonStat` 必带 `n` + `ci95`；`n<30` → `caveats` 追加"n<30, 结论不可信"。
- **区制分层**：每个事件按 `regime_fn(event.date)`（默认 `compute_market_signal_for_date`）打 green/yellow/red，分层重算 `HorizonStat`。
- **t 值 / CI**：单样本 t（`mean/(std/sqrt(n))`），CI95 = `mean ± 1.96*std/sqrt(n)`（大样本近似；小样本已被 caveats 标注不可信，不引入 scipy）。
- **不做参数寻优**：只描述现有信号前瞻分布。

**依赖注入**：`price_fetcher`/`regime_fn`/`calendar` 全部可注入，默认绑定真实实现 → 测试全 mock、离线可跑。

### 3.5 事件来源（Phase 0 占位策略）

复用现有信号，不新造：

| kind | 触发定义 | Phase 0 来源 |
|------|---------|--------------|
| `rs_strong` | `relative_strength_spy>0` 且 `rs_score≥rs_strong(1.2)` | `tickers/trend.py` 扫描历史快照 |
| `ma_reclaim` | 价格上穿 21EMA（用 ma20 近似，记 caveat） | `tickers/trend.py` |
| `score_high` | `trend_relative_strength` 分数进高档(≥70) | `strategies/` |
| `eps_beat`/`eps_miss` | yfinance `earnings_dates` 占位（Phase 1 接真实 surprise） | 占位，meta 标 `source:"placeholder"` |

事件抽取放 `research/event_sources.py`（与引擎解耦：引擎只吃 `list[Event]`，来源单独可测、可替换）。

### 3.6 结果缓存表与迁移编号

- on-disk 迁移已到 `008_notify_settings`；README §4 规划 `012 event_studies`，但 009-011 属 Phase 1（ohlcv/breadth/fundamentals），Phase 0 先落地时它们可能尚不存在。
- **决策**：`event_studies` 缓存表为**可选增强**（引擎本身无状态、可纯算）。落地时取**下一个可用编号**：若 Phase 1 的 009-011 尚未落地，本表占 `009_event_studies.sql`；若已落地则顺延。**在 plan 中以"下一个可用编号"描述并在 Step 中用 `ls migrations/` 实测确认**，避免与并行 agent 编号冲突。表结构：`(kind, params_hash)` 唯一，`result JSONB`，`generated_at`，幂等 `CREATE TABLE IF NOT EXISTS` + `ON CONFLICT DO UPDATE`。
- 缓存非必需路径：无 DB 时引擎照常计算返回，只是不落缓存（降级）。

### 3.7 审计 + 日志化落地（硬约束 1）

**一切经 `_harness.run_task`**，不另造审计：

- 定时任务 `tasks/event_study.py`：`_core(config)` 抽事件→跑引擎→（可选）写缓存→返回结构化 summary（含 `kind`、各 `n`、是否 degraded、split 告警计数、参数）；`run(config)=run_task("event_study", _core, config=config)` 自动落 `run_log`(文件 JSONL) + `job_reports`(DB) + Discord 摘要。
- **审计字段映射**：`job_reports.run_id`=谁/哪次（harness 生成 `event_study-<ts>-<uuid>`）、`started_at/finished_at`=何时、`summary.params`=用什么参数、`summary`=产生什么结果、`status`=success/error。dashboard 工具层「运行记录/数据结果」`GET /api/jobs/reports?task=event_study` 直接展示，无需新表。
- **手动触发审计**：dashboard「立即运行」走 `runner.submit` → 但需保证它也落 `job_reports`。决策：手动触发也调用 `run(config)`（内部即 `run_task`），故同样落审计（与现有 metrics 等任务一致）。
- 数据质量校验（split 告警）作为 summary 子字段随事件研究任务一并记录，不单设任务（YAGNI；校验是取价副产物）。

### 3.8 定时 / 手动双入口（硬约束 2）

**DRY：定时与手动共享同一核心**，仅入口与"as-of 日期"不同。

- 共享核心：`research/event_study.run_event_study(...)` + `research/event_sources.collect_events(config, *, asof, since)`。
- **定时入口** `tasks/event_study.py:run(config)`：`asof=today`，跑当前事件研究、刷新缓存、推送摘要。注册进 `scheduler.REGISTRY["event_study"]` + 在 `scheduled_jobs` 迁移补一行（或文档说明手动 INSERT）。
- **手动 CLI** `python -m investment_assistant.research.event_study --kind rs_strong --since 2022-01-01 [--asof 2024-03-01]`：
  - 用于**历史周期回放验证**：`--asof` 指定历史 as-of 日期 → 所有取价/区制走该日切片，可离线复现"如果我站在 2024-03-01 看，这个信号的前瞻分布是什么"。
  - 打印各 horizon 均值/命中率/CI/区制分层表（人读）。
  - **同样经 `run_task` 落审计**（可加 `--no-record` 仅打印不落库，默认落库），与定时共用 `_core`。
  - 范围回放（区间）参照 `market.fetch_market_signals` 的 from-to + 上限模式。
- **为什么手动入口必要**：定时只跑"今天"，无法离线验证历史、无法回测信号。手动 `--asof`/`--since` 让你对任意历史窗口复算，是 Phase 0「先证伪」决策门的工具。

### 3.9 只读 API 与前端衔接

- 新增 `api/routes/research.py` + `services/research.py`：
  - `GET /api/research/event-study?kind=rs_strong&since=2022-01-01` → 读缓存（有 DB）或即时计算（小样本）→ 返回 `EventStudyResult` 的 JSON（`degraded` 标志遵循现有范式）。
  - `GET /api/research/event-study/kinds` → 可用事件类型列表。
- 触发统一走工具层 `POST /api/jobs/event_study/run`（复用现有 jobs 路由，**无需新触发端点**）。
- 数据结构对齐 `EventStudyResult`，Phase 3 可直接喂 ECharts。Phase 0 不写前端组件。

---

## 4. 组件与数据流

### 4.1 模块清单（每个单元单一职责、可独立测试）

```
investment_assistant/
  data/
    price.py        # 改：get_price_history 显式复权口径；+get_price_history_asof；+detect_split_jumps
    calendar.py     # 新：NYSE 交易日历（is_trading_day/add_trading_days/trading_days_between）
  research/
    event_study.py  # 新：Event/HorizonStat/EventStudyResult + run_event_study + main() CLI
    event_sources.py# 新：collect_events(config,*,asof,since) 从现有信号派生 Event
  services/
    research.py     # 新：event_study_view（只读+降级）、可选缓存读写
  tasks/
    event_study.py  # 新：_core(config)+run(config)=run_task(...)+main()；注册 REGISTRY
  api/routes/
    research.py     # 新：GET /api/research/event-study*
    __init__.py     # 改：import research
  market/service.py # 改：_default_price_fetcher_until 薄封装 get_price_history_asof
migrations/
  0NN_event_studies.sql  # 可选：下一个可用编号（实测确认），结果缓存
```

### 4.2 依赖方向（守住分层 `routes → services → db/tasks`）

```
api/routes/research.py ─→ services/research.py ─→ db (缓存表, 可选) 
                                              └─→ research/event_study.run_event_study
tasks/event_study.py ─→ research/event_sources.collect_events ─→ tickers/strategies (派生事件)
                    └─→ research/event_study.run_event_study ─→ data/price.get_price_history_asof
                                                            └─→ market/service.compute_market_signal_for_date (regime_fn)
                    └─(经)→ tasks/_harness.run_task ─→ run_log + db.insert_job_report + notify.dispatch
research/event_study (CLI main) ─→ 同 tasks/event_study.run（DRY 共享核心）
```

引擎 `run_event_study` 不直接 import market/data（通过注入的 `price_fetcher`/`regime_fn`/`calendar` 默认绑定），保证可单测、无副作用。

### 4.3 一次事件研究的数据流

1. `collect_events(config, asof=D, since=S)` 扫描 watchlist 历史信号 → `list[Event]`（每个含 ticker/date/kind）。
2. 对每个 event：`get_price_history_asof(ticker, event.date+horizon交易日, ...)` 取前瞻价 + 同期 SPY → 算超额收益；`regime_fn(event.date)` 打区制标签。
3. 按 kind 聚合 → 各 horizon 的 `HorizonStat`（n/mean/median/hit/t/CI）；按区制分层重算。
4. `n<30` 自动填 caveats；组装 `EventStudyResult`。
5. 定时/手动经 `run_task` 落审计；只读 API 返回 JSON。

---

## 5. 错误处理与降级

- **不静默吞错**：取价失败的事件结构化记入 `result.params["skipped"]`（含 ticker/date/error），不中断整体；引擎返回成功但 summary 标注跳过数。
- **优雅降级**：只读 `services/research` 无 `INVESTMENT_ASSISTANT_DATABASE_URL` → 返回 `{"result": null, "degraded": true}`（或即时计算但不落缓存）。
- **前视偏差守卫**：`get_price_history_asof` 二次 `df.loc[:end_date]` 裁剪，任何越界 bar 视为 bug（测试断言）。
- **样本不足**：不抛错，照算并以 caveats 标注，把"诚实"交给报告读者。
- **敏感值**：事件研究不涉密；任务 summary 不含任何凭证。Discord 摘要只含统计量。

---

## 6. 测试策略（TDD，全离线）

| 单元 | 关键测试 | mock 点 |
|------|---------|---------|
| `data/calendar.py` | `add_trading_days` 跨假日正确；周末跳过；MLK/感恩节浮动假日命中 | 纯函数，无 mock |
| `data/price.get_price_history_asof` | 切片不含 end_date 之后 bar；行数≤days | 注入 fetcher（构造含未来 bar 的 frame） |
| `data/price.detect_split_jumps` | 含 2:1 split 未复权序列告警；复权序列不告警；财报日跳变豁免 | 纯函数 |
| `research/event_study.run_event_study` | mean_excess/hit_rate/基准扣减；n<30 填 caveats；区制分层调用 regime_fn | 注入 price_fetcher/regime_fn/calendar |
| `research/event_sources.collect_events` | 从 mock 快照派生正确 kind/date | 注入信号扫描 |
| `services/research` | 无 DB 降级 degraded；有 DB 读缓存 | monkeypatch _with_conn/env |
| `tasks/event_study` | `_core` 组装 summary；`run` 走 harness（同 metrics 测法） | monkeypatch _core/run_task |
| `api/routes/research` | 端点经 dispatch 返回结构；降级标志 | monkeypatch service |
| CLI `main()` | `--asof`/`--since`/`--kind` 解析；`--no-record` 不落库 | monkeypatch run |

测试文件：`tests/test_data_calendar.py`、`test_data_price_asof.py`、`test_event_study.py`、`test_event_sources.py`、`test_services_research.py`、`test_event_study_task.py`、`test_research_api.py`。

---

## 7. 两条硬约束如何被满足（自查）

**约束 1 — Dashboard 可审计 + 日志化**：
- 事件研究/数据质量校验/PIT 取价的产出全部经 `tasks/_harness.run_task` → 自动落 `run_log`(文件 JSONL) + `job_reports`(DB, 迁移006) + Discord。
- 审计四要素映射：run_id=哪次触发、started/finished_at=何时、summary.params=什么参数、summary+status=什么结果。
- dashboard 工具层 `GET /api/jobs/reports?task=event_study` / `GET /api/jobs/metrics` **零新表零新审计代码**即可展示。手动触发（`POST /api/jobs/event_study/run`）走同一 `run(config)`，同样落审计。
- **未另造审计系统**——完全复用现有 `_harness`/`job_reports`/`run_log`。

**约束 2 — 自动/定时必须配套手动脚本（可历史回放）**：
- 定时 `tasks/event_study.py` 与手动 `python -m investment_assistant.research.event_study` **共享 `_core` + `run_event_study`**（DRY）。
- 手动入口 `--asof <历史日期>` / `--since` / 区间 → 对历史周期回放验证：站在任意历史日重算信号前瞻分布，离线复现，支撑 Phase 0 决策门「先证伪」。
- 手动入口同样经 `run_task` 落审计（可 `--no-record` 关闭）。

---

## 8. 实施顺序（plan 将据此展开 TDD 步骤）

1. `data/calendar.py`（无依赖，先做）
2. `data/price.py`：`get_price_history_asof` + `detect_split_jumps` + 复权口径；回填 `market/service` 薄封装
3. `research/event_study.py`：引擎 + dataclasses（注入式，可纯测）
4. `research/event_sources.py`：事件派生
5. `services/research.py` + 可选缓存迁移（编号实测确认）
6. `tasks/event_study.py`：定时任务 + 注册 REGISTRY
7. `research/event_study.py` 的 `main()` CLI（手动回放）
8. `api/routes/research.py` + `__init__` 注册
9. 文档/README 衔接（仅必要，避免与并行 agent 冲突——本 Phase 0 只动自身新增文件 + price.py/market.service.py/routes __init__ 等必要点）

---

## 9. 假设与待确认（记录，不阻塞）

- **假设 A**：标的池为美股，仅需 NYSE 日历。
- **假设 B**：`ma_reclaim` Phase 0 用 ma20 近似 21EMA，结果标 caveat；Phase 1 有真实 EMA 后替换。
- **假设 C**：EPS 事件 Phase 0 用 yfinance `earnings_dates` 占位，meta 标 `source:"placeholder"`，不作去留结论依据。
- **假设 D**：缓存表编号在落地时实测 `ls migrations/` 取下一可用编号，规划倾向 `009`（若 Phase1 未先落地）；plan 用"下一个可用编号"措辞。
- **待确认**（不阻塞 Phase 0）：watchlist 实际规模/风格影响样本聚合方式（README §6 第 2 条），Phase 0 先按当前默认池跑，报告里标注样本来源。
