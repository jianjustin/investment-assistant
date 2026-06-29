# 定时采集任务 + pg 调度器 + 可配置 Discord 推送 — Design Spec

> 状态：设计已确认，待写实现计划（writing-plans）。
> 日期：2026-06-29　分支建议：从 `main` 切 `feat/scheduled-ingestion-discord`。

## 1. 背景与目标

把现有 08:30 单体 `tasks/daily.py`（market + filings + LLM brief，经 `ops.hermes_daily` 由 systemd timer 触发）**拆分重构**为两个职责单一的定时任务，并：

1. **任务 A（每日 08:00 ET）—— 美股关键指标**：复用现有 market service + 个股趋势快照，落库到既有 `market_signals` / `ticker_signal_snapshots`；生成日志报告；按配置推送 Discord。
2. **任务 B（每日 09:00 ET）—— 昨日关注列表财报**：新建真实 SEC EDGAR 下载器，拉取关注列表公司「昨日（T-1）新提交」的 10-Q/10-K 落盘；生成日志报告；按配置推送 Discord。
3. **调度层改为 postgres 自研方案**：用一个常驻守护进程 + `scheduled_jobs` 表取代 systemd timer，计划状态存 pg、可查询、可后续 UI 配置。
4. **Discord 推送成为可配置系统设置**：全局开关 + 每任务开关 + 频道路由 + webhook 可在配置文件覆盖 env。

### 1.1 非目标 / 本轮不做（Non-Goals）

- **LLM 每日简报 brief**：本轮从 daily 链路中**删除**，后续单独作为第三个调度 job 再补。
- **filing 元数据入 pg**（Phase 2 的 `filings` 表）：本轮财报**只落盘**；元数据入库留给 Phase 2 本体。
- **Phase 2 数据层**（FRED 宏观 / SEC XBRL 基本面 / OHLCV 落库 + 新鲜度守卫）：与本设计正交，本轮不触碰；唯一交集是「抢先用掉迁移编号」（见 §9）。
- **完整 cron 表达式**：调度器只支持「每日 HH:MM + 周几掩码」，不支持秒级/月级/复杂 cron（YAGNI）。

## 2. 现状关键事实（设计依据）

- **调度现状**：systemd timer + oneshot service（`deploy/systemd/`，`OnCalendar=... America/New_York`）。现有 `hermes-investment-daily.timer`(08:30→`ops.hermes_daily`)、`hermes-investment-scores.timer`(18:00→`tasks.nightly_scores`)、常驻 `hermes-investment-dashboard.service`。
- **Discord 现状**：`notify/discord.py`（`DiscordClient`，频道 earnings/signals/daily，webhook 读 env）+ `notify/templates.py`（embed 模板）。`config.NotifyConfig.discord_enabled: bool` **已存在但未被任何代码消费**。
- **报告现状**：`hermes/run_log.append_run(record)` 追加写 JSONL 文件（`RUN_LOG_PATH`）。
- **现有 daily 实现**：`tasks/daily.py:run()` → `hermes/daily.py:run_daily()`（market_step + filing_step + brief_step，步骤可注入）。`ops/hermes_daily.py` 仅是转发 shim。
- **财报下载契约（既存测试 `tests/test_filing_service.py`）**：
  `download_configured_filings(tickers: list[str], cfg: FilingsConfig, *, downloader) -> {"downloaded_count": int, "files": list[Path]}`；
  downloader 协议：`download_filings_batch(ticker, form_types, since_date, output_base) -> list[Path]`。
  测试断言 `calls[0]` 的 `(ticker, form_types, output_base)`，**不约束 `since_date`** → 「昨日 T-1」语义可自由设定。
  当前 `investment_assistant/filings/` 模块不存在，故该测试收集失败、`hermes/daily.py` 非 dry-run filing 步骤 import 失败。
- **复用入口**：`market/service.py:compute_market_signal(...)`、`db.upsert_market_signal(conn, signal)`；个股快照经 `services/strategies.run_strategy_score_scan` 路径产出并持久化到 `ticker_signal_snapshots`（`strategy_scores` 已 FK 引用其 id）。
- **配置加载**：`config.load_config` + `_dataclass_from_dict` 已支持从 JSON 浅覆盖 frozen dataclass（bool/int/float/list 自动转型，dict 直接赋值）。

## 3. 架构总览

```
                 ┌─────────────────────────────────────────────┐
 systemd         │  hermes-investment-scheduler.service          │
 (Restart=always)│   = python -m investment_assistant.tasks.scheduler
                 │                                               │
                 │   tick loop (~60s):                           │
                 │     claim due jobs (FOR UPDATE SKIP LOCKED)   │
                 │     ├─ run via harness ──► job_reports (pg)   │
                 │     │                  └─► notifier ─► Discord │
                 │     └─ recompute next_run_at (zoneinfo, DST)  │
                 └──────────────┬────────────────────────────────┘
                                │ registry: name -> callable
            ┌───────────────────┼────────────────────┐
            ▼                   ▼                    ▼
   tasks/metrics.py     tasks/filings.py     tasks/nightly_scores.py
   (08:00 指标)         (09:00 财报)          (18:00 评分, 收编)
            │                   │
   compute_market_signal   filings/service.py
   + ticker snapshots      + filings/sec_downloader.py (真实 SEC EDGAR)

   pg 表：scheduled_jobs(计划)  job_reports(运行报告, 30天TTL)
   配置：NotifyConfig(扩展)  notify/notifier.py(新)
```

**调度状态全部存 postgres**：`scheduled_jobs` 是计划真值表，`job_reports` 是运行历史。systemd 只负责保活**一个**守护进程（不再有 timer）。各任务模块仍保留 `main()`，可 `python -m investment_assistant.tasks.<name>` 手动单跑（脱离调度器，便于调试/补跑）。

## 4. 数据库迁移

### 4.1 `migrations/006_job_reports.sql`

```sql
CREATE TABLE IF NOT EXISTS job_reports (
  id          BIGSERIAL PRIMARY KEY,
  task        TEXT NOT NULL,                       -- 'metrics' | 'filings' | 'scores'
  run_id      TEXT NOT NULL,
  status      TEXT NOT NULL,                       -- 'success' | 'error'
  started_at  TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  summary     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 条数 / 清单 / 错误
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_reports_task_created
  ON job_reports (task, created_at DESC);
```

- **30 天 TTL**：在 `db.insert_job_report` 写入后，于同一连接执行
  `DELETE FROM job_reports WHERE created_at < now() - INTERVAL '30 days';`（无需独立清理任务）。

### 4.2 `migrations/007_scheduled_jobs.sql`

```sql
CREATE TABLE IF NOT EXISTS scheduled_jobs (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,               -- 'metrics' | 'filings' | 'scores'
  time_local   TEXT NOT NULL,                      -- 'HH:MM'
  weekday_mask TEXT NOT NULL DEFAULT '1-5',        -- ISO 周几集合, 1=Mon..7=Sun, 形如 '1-5'
  timezone     TEXT NOT NULL DEFAULT 'America/New_York',
  enabled      BOOLEAN NOT NULL DEFAULT TRUE,
  next_run_at  TIMESTAMPTZ,                        -- NULL = 启动时按计划首次计算
  last_run_at  TIMESTAMPTZ,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- 迁移文件随后 seed 三行（`INSERT ... ON CONFLICT (name) DO NOTHING`）：
  `('metrics','08:00',...)`、`('filings','09:00',...)`、`('scores','18:00',...)`，`next_run_at` 置 NULL（首跳计算）。
- 幂等：全部 `CREATE TABLE IF NOT EXISTS` + `ON CONFLICT DO NOTHING`。

## 5. 调度器 `tasks/scheduler.py`（自研守护进程）

**职责**：常驻进程，按 `scheduled_jobs` 定时触发已注册 job，写报告、推送、算下次运行时间。

**Job 注册表**：模块级 `dict[str, Callable[[AssistantConfig], dict]]`，初始注册 `metrics`、`filings`、`scores`（指向各任务模块的 `run(config)`）。注册表是「name → 可执行」的唯一映射；`scheduled_jobs.name` 必须命中注册表，否则该行被跳过并记一条 `error` 报告。

**tick 循环**（默认 60s 周期，`SCHEDULER_TICK_SECONDS` 可覆盖）：
1. `SELECT ... FROM scheduled_jobs WHERE enabled AND (next_run_at IS NULL OR next_run_at <= now()) FOR UPDATE SKIP LOCKED`——抢占到期行（多实例/重入不重跑）。
2. 对每个到期 job：经 §6 harness 执行 `registry[name](config)`；
3. 计算并写回 `next_run_at = compute_next_run(time_local, weekday_mask, timezone, after=now())`、`last_run_at=now()`、`updated_at=now()`。

**`compute_next_run(time_local, weekday_mask, timezone, *, after)`**（纯函数，独立可测）：
- 用 `zoneinfo.ZoneInfo(timezone)` 把「下一个满足 weekday_mask 的 HH:MM」换算为带时区的 `next_run_at`（UTC 存储）；天然处理夏令时切换。
- `after` 之后的最近一个匹配时刻；同日 HH:MM 已过则顺延到下个匹配日。

**错过补跑（misfire）**：守护进程宕机期间 `next_run_at` 落在过去 → tick 时仍满足 `next_run_at <= now()` 即补跑一次，随后 `compute_next_run(after=now())` 前移；每个 job 每跳至多补一次（不堆积历史多次触发）。

**首次计算**：`next_run_at IS NULL`（seed 行）→ 视为到期，首跳立即跑一次并前移。若需避免「装机即跑」，可在 seed 时改为预填一个未来 `next_run_at`——本设计默认 NULL=首跳跑（实现计划中明确，供选择）。

**健壮性**：单个 job 执行抛错只落 `job_reports`(status=error) 且 tick 继续；调度器主循环捕获并记录、不退出。`SIGTERM` 优雅停（systemd stop）。

**并发保护**：同名 job 若上次仍在跑（极端慢任务），由 `FOR UPDATE SKIP LOCKED` + 事务边界天然避免同一行被两 tick 同时领取。

## 6. 共享外壳 `tasks/_harness.py`（方案 A 核心）

**职责**：把「报告落库 + Discord 推送 + run_id」收敛为一处，杜绝两任务样板漂移。

**接口**：
`run_task(task: str, fn: Callable[[], dict], *, config: AssistantConfig) -> dict`
1. 生成 `run_id = f"{task}-{YYYYmmddHHMMSS}-{uuid8}"`、`started_at`。
2. `try: result = fn()` → `status='success'`；`except Exception as exc:` → `status='error'`，`summary={"error": str(exc)}`（结构化记录，不静默吞）。
3. `db.insert_job_report(conn, task=..., run_id=..., status=..., started_at, finished_at, summary)`（写入即剪枝 30 天）。
4. `notifier.dispatch(task, status, summary, config.notify)`——按配置决定是否/向哪个频道推送。
5. 返回 `{"run_id", "task", "status", "summary"}`。

- 兼容保留：仍调用 `run_log.append_run(...)`（JSONL）作为本地副本；pg `job_reports` 为权威。
- 各任务模块 `run(config)` 内部即 `return run_task("metrics", lambda: _core(config), config=config)`，故手动 `python -m ...` 与调度器走同一外壳。

## 7. 任务实现

### 7.1 任务 A：`tasks/metrics.py`（08:00）

- **核心步骤** `_core(config)`：
  1. `signal = compute_market_signal(config.market, run_id=...)`；`with connect(db_url) as conn: upsert_market_signal(conn, signal)`。
  2. 触发个股趋势快照刷新（复用 `services/strategies` / `services/tickers` 既有产出 `ticker_signal_snapshots` 的路径），收集每只 watchlist 标的的快照摘要。
  3. 返回 `summary = {"market_status", "vix", "signal_date", "tickers": [{ticker, 关键字段...}], "errors": [...]}`。
- **Discord**：`metrics_summary_embed(summary)`（新模板，复用 `daily_summary_embed` 思路：市场环境 + 关注列表摘要）。
- **删除 brief**：移除 `hermes/daily.py` 的 `brief_step` 链路与 `_daily_brief_step`；`run_daily` 不再产出 brief（或整体由 metrics/filings 两任务取代，daily 模块退役——实现计划定夺保留 shim 还是删除）。

### 7.2 任务 B：`tasks/filings.py`（09:00）

- **新建** `investment_assistant/filings/__init__.py`、`filings/service.py`、`filings/sec_downloader.py`。
- `filings/service.py:download_configured_filings(tickers, cfg, *, downloader=None, since_date=None)`：
  - 严格满足既存 `tests/test_filing_service.py` 契约（返回 `{"downloaded_count","files"}`；调 `downloader.download_filings_batch(ticker, form_types=list(cfg.forms), since_date, output_base=cfg.output_dir)`）。
  - `since_date` 缺省 = **昨日**（`date.today() - 1d`）；单标的失败不影响其余（结构化收集 `errors`）。
- `filings/sec_downloader.py:SecEdgarDownloader`：实现 `download_filings_batch`，打 SEC `submissions/CIK##########.json`，筛 `form ∈ forms 且 filing_date == since_date`（即昨日新提交），下载 primary document 落盘 `output_base/<ticker>/<form>/<accession>.htm`；带 `User-Agent: SEC_USER_AGENT` 头、复用 `data/http.get_json` 重试/退避；无 `SEC_USER_AGENT` 时优雅降级（结构化禁用态，不崩）。CIK 解析复用/对齐 Phase 2 `company_tickers.json` 缓存约定。
- **核心步骤** `_core(config)`：`result = download_configured_filings(config.watchlist, config.filings, downloader=SecEdgarDownloader())`；`summary = {"downloaded_count", "filings": [{ticker, form, filed_at, path}], "errors": {...}}`。
- **Discord**：`filings_digest_embed(summary)`（新模板：昨日新财报清单）。
- **修复**：本任务一并修好 `hermes/daily.py` 因缺 `filings.service` 导致的 import 失败、并让 `tests/test_filing_service.py` 转绿。

## 8. Discord 可配置层

### 8.1 `config.NotifyConfig` 扩展

```python
@dataclass(frozen=True)
class NotifyConfig:
    discord_enabled: bool = True                       # 全局总开关（已存在，本轮真正接入）
    email_enabled: bool = True
    webhooks: dict[str, str] = field(default_factory=dict)        # channel -> url，覆盖 env
    task_channels: dict[str, str] = field(default_factory=lambda: {
        "metrics": "daily", "filings": "earnings", "scores": "signals"})
    task_enabled: dict[str, bool] = field(default_factory=lambda: {
        "metrics": True, "filings": True, "scores": True})
```

- `_config_from_dict` 已对 `notify` 走 `_dataclass_from_dict`，dict 字段直接赋值即可（无需新解析分支；实现时验证 dict 覆盖语义符合预期）。

### 8.2 `notify/notifier.py`（新）

- `dispatch(task: str, status: str, summary: dict, notify_cfg: NotifyConfig) -> dict`：
  1. `discord_enabled` 为假，或 `task_enabled.get(task) is False` → 跳过（返回 `{"sent": False, "reason": ...}`）。
  2. 解析频道 `task_channels[task]` → `DiscordChannel`；构造对应 embed（metrics/filings/scores 模板）。
  3. webhook 取值优先 `notify_cfg.webhooks[channel]`，回退 `DiscordClient.from_env()` 的 env。
  4. 调 `DiscordClient.send(channel, payload)`；失败结构化返回（不让通知错误拖垮任务——由 harness 记 `job_reports`）。
- `DiscordClient` 增加「按 config webhooks 覆盖构造」的类方法（保留 `from_env` 兼容）。

## 9. 迁移编号与 Phase 2 衔接

- 本工作用掉 `006_job_reports`、`007_scheduled_jobs`。
- 原 `2026-06-27-phase2-data-layer.md` 计划假设 006-009=macro/fundamentals/filings/price_bars——**届时 Phase 2 顺延为 008 起**（008_macro_indicators / 009_fundamentals / 010_filings / 011_price_bars）。本 spec 落地后需同步更新 Phase 2 计划的编号与「前置依赖」说明。
- 本工作新建的 `filings/sec_downloader.py` 抢先实现了 Phase 2 T2.2 的「真实 SEC 下载器」部分；Phase 2 本体只需补 filing **元数据入 pg**（`filings` 表 + `upsert_filing`），可直接复用本下载器。

## 10. 部署 / systemd

- **新增** `deploy/systemd/hermes-investment-scheduler.service`：`Type=simple`、`Restart=always`、`ExecStart=.../python -m investment_assistant.tasks.scheduler`、`EnvironmentFile=...env`、`After/Wants=...postgres`。
- **废弃** `hermes-investment-daily.{timer,service}` 与 `hermes-investment-scores.timer`（`scores` 收编进 `scheduled_jobs`；`hermes-investment-scores.service` 可保留供手动 `systemctl start` 或一并删除——实现计划定夺）。
- 更新 `deploy/install.sh`：安装新 service、`systemctl enable hermes-investment-scheduler.service`，从 enable 列表移除被废弃的 timer。
- `migrate` 已有 `python -m investment_assistant.migrate`（T6.1），install 流程先迁移再起调度器，确保 006/007 + seed 就位。

## 11. 测试策略（全部离线、外部调用 mock）

| 测试 | 覆盖 |
| --- | --- |
| `test_scheduler.py` | `compute_next_run`（含周几掩码、HH:MM 已过顺延、DST 边界）、到期判定、misfire 补跑一次、注册表未命中记 error、单 job 抛错不中断循环 |
| `test_harness.py` | 成功/异常两路均写 `job_reports`、调 notifier、返回结构；异常被结构化捕获 |
| `test_job_reports_repository.py` | `insert_job_report` 写入 + 30 天剪枝 SQL（Fake conn 录 SQL） |
| `test_scheduled_jobs_repository.py` | 领取/回写 `next_run_at`/`last_run_at`、`FOR UPDATE SKIP LOCKED` 出现在 SQL |
| `test_metrics_task.py` | `_core` 注入 fake market/snapshot → summary 结构；不触网 |
| `test_filings_task.py` | `download_configured_filings` + fake downloader → summary；`since_date` 默认昨日 |
| `test_sec_downloader.py` | `SecEdgarDownloader.download_filings_batch` mock `data/http.get_json`：按 form + 昨日 filing_date 过滤、落盘路径、无 `SEC_USER_AGENT` 降级 |
| `test_notifier.py` | 全局关 / 每任务关 / 频道路由 / config webhook 覆盖 env / 发送失败结构化 |
| `test_db_sql.py`（追加） | 006/007 迁移断言（表名、列、UNIQUE、seed） |
| `test_filing_service.py`（既存） | 由「收集失败」转 **PASS** |

- 横切：不新增裸 `except Exception` 吞错（重试后结构化抛出/返回）；迁移幂等；DB 集成测试在无 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 时 skip。

## 12. 实现节奏（建议顺序，便于 TDD 分 PR）

1. 迁移 `006_job_reports` + `db.insert_job_report`(+剪枝) + 仓储测试。
2. 迁移 `007_scheduled_jobs` + 仓储（领取/回写）+ 测试 + seed。
3. `tasks/_harness.py`（依赖 1）。
4. `config.NotifyConfig` 扩展 + `notify/notifier.py` + 模板 + 测试。
5. `tasks/metrics.py`（依赖 3、4）+ 删除 brief。
6. `filings/service.py` + `filings/sec_downloader.py` + `tasks/filings.py`（依赖 3、4）；既存 `test_filing_service.py` 转绿。
7. `tasks/scheduler.py`（依赖 2、3、5、6；收编 scores）+ 测试。
8. systemd 新 service + `install.sh` 切换；废弃旧 timer。
9. 同步更新 Phase 2 计划迁移编号（→008 起）；新增 `docs/scheduling-and-notifications.md`。
10. 全套件回归 `python -m pytest -q`。

## 13. 待实现计划阶段定夺的细节（非阻塞）

- `tasks/daily.py` / `ops/hermes_daily.py`：退役删除 vs 保留为「手动一次性跑全部」shim。
- `hermes-investment-scores.service`：删除 vs 保留供手动触发。
- seed 行 `next_run_at`：NULL=装机即跑 vs 预填未来时刻。
- scores 任务接入 harness 时，其现有 `append_run` 记录与新 `job_reports` 的并存方式。
