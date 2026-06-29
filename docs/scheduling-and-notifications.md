# 定时采集与通知（Scheduling & Notifications）

本文档记录 `scheduled-ingestion-discord` 工作的运行机制：基于 PostgreSQL 的调度守护进程、`scheduled_jobs` / `job_reports` 两张表、任务外壳（harness）契约、可配置的 Discord 通知，以及 SEC EDGAR 下载器。

---

## 1. 调度守护进程（pg scheduler）

入口：`python -m investment_assistant.tasks.scheduler`（`investment_assistant/tasks/scheduler.py`）。

这是一个**长驻守护进程**，不依赖 systemd timer / cron。它按固定节拍（tick）轮询 `scheduled_jobs` 表，把到期的 job 派发给注册表里的任务函数：

- **tick 循环**：每 `SCHEDULER_TICK_SECONDS`（环境变量，默认 `60` 秒）醒来一次，用 `due_scheduled_jobs(conn, now=...)` 取出 `enabled AND (next_run_at IS NULL OR next_run_at <= now)` 的 job（`FOR UPDATE SKIP LOCKED`，多实例安全）。
- **registry**：`REGISTRY = {"metrics": ..., "filings": ..., "scores": ...}`。job 名未注册时只记 `warning` 并跳过，不崩。
- **misfire / 重排**：每个 job 跑完后调用 `compute_next_run(time_local, weekday_mask, timezone, after=now)` 算出下一次运行时间，写回 `next_run_at` + `last_run_at`（`reschedule_job`）。
- **兜底不中断**：单个 job 抛异常被捕获并记 `error`，循环继续；整个 tick 抛异常被主循环 `try/except` 兜底记录后继续 sleep。

### systemd 服务

部署单元：`deploy/systemd/hermes-investment-scheduler.service`。

```ini
[Service]
Type=simple
ExecStart=/opt/hermes-investment-assistant/.venv/bin/python -m investment_assistant.tasks.scheduler
Restart=always
RestartSec=10
```

关键点：**只有一个 service（`Restart=always`），没有任何 timer**——所有定时语义都搬进了 `scheduled_jobs` 表里，由守护进程自己读表决定何时跑。环境从 `EnvironmentFile=/opt/hermes-investment-assistant/.env` 加载（含 `INVESTMENT_ASSISTANT_DATABASE_URL` 等）。

---

## 2. `scheduled_jobs` 表与 seed

迁移：`migrations/007_scheduled_jobs.sql`。

| 列 | 说明 |
| --- | --- |
| `name` | job 名（唯一），须与 `REGISTRY` 的 key 对应 |
| `time_local` | 本地时间 `HH:MM` |
| `weekday_mask` | ISO 周几掩码，默认 `1-5`（周一到周五） |
| `timezone` | IANA 时区，默认 `America/New_York` |
| `enabled` | 是否启用 |
| `next_run_at` / `last_run_at` | 调度器维护的下次 / 上次运行时间 |

seed（`ON CONFLICT (name) DO NOTHING`，幂等）：

| name | time_local | weekday_mask | timezone |
| --- | --- | --- | --- |
| `metrics` | `08:00` | `1-5` | `America/New_York` |
| `filings` | `09:00` | `1-5` | `America/New_York` |
| `scores` | `18:00` | `1-5` | `America/New_York` |

### 改时间 / 开关 job

直接 SQL 改表即可，下一个 tick 自动生效（无需重启进程）：

```sql
-- 把 scores 改到 17:30
UPDATE scheduled_jobs SET time_local = '17:30' WHERE name = 'scores';

-- 临时停掉 filings
UPDATE scheduled_jobs SET enabled = FALSE WHERE name = 'filings';

-- 只在周一/三/五跑 metrics
UPDATE scheduled_jobs SET weekday_mask = '1,3,5' WHERE name = 'metrics';
```

---

## 3. `job_reports` 表与 30 天 TTL

迁移：`migrations/006_job_reports.sql`。每次任务运行都会写一条记录：`task / run_id / status / started_at / finished_at / summary(JSONB)`。

**30 天 TTL**：每次 `insert_job_report` 在插入后立即执行剪枝（`investment_assistant/db.py`）：

```sql
DELETE FROM job_reports WHERE created_at < now() - INTERVAL '30 days'
```

即「写入即剪枝」，无需额外的清理任务。无 DB（`INVESTMENT_ASSISTANT_DATABASE_URL` 未设）时跳过落库，只走文件 run-log。

---

## 4. 任务外壳（harness）契约

外壳：`investment_assistant/tasks/_harness.py` 的 `run_task(task, fn, *, config)`。所有定时任务都通过它运行，统一处理：

1. 生成 `run_id`（`{task}-{UTC时间戳}-{8位hex}`）。
2. 调用 `fn()` 拿到 `summary`；**异常被结构化捕获**（`status="error"`，`summary={"error": ...}`），不静默吞错。
3. `_record(...)`：写文件 run-log（`append_run`）**并且**在有 DB 时写 `job_reports`（`insert_job_report`）。
4. `dispatch(task, status, summary, config.notify)`：把结果推给通知层（见 §5）。
5. 返回 `{"run_id", "task", "status", "summary"}`。

### 手动单跑

每个任务都是可独立运行的模块（带 `--config` 参数）：

```bash
python -m investment_assistant.tasks.metrics          # 行情 + ticker 快照（08:00）
python -m investment_assistant.tasks.filings          # SEC filings 下载（09:00）
python -m investment_assistant.tasks.nightly_scores   # 策略评分（scores，18:00）
```

注意调度 job 名是 `scores`，对应的模块是 `tasks.nightly_scores`。

---

## 5. Discord 通知配置

配置在 `NotifyConfig`（`investment_assistant/config.py`），通知逻辑在 `investment_assistant/notify/notifier.py` 的 `dispatch(...)`。

| 字段 | 说明 |
| --- | --- |
| `discord_enabled` | 全局开关；`False` 时直接返回 `{"sent": False, "reason": "discord_disabled"}` |
| `webhooks` | `{channel: url}` 显式 webhook 覆盖；优先于 env |
| `task_channels` | 任务 → 频道路由，默认 `{"metrics": "daily", "filings": "earnings", "scores": "signals"}` |
| `task_enabled` | 每任务开关，默认全 `True`；某任务 `False` 时跳过 |

### 派发判定（`dispatch`）顺序

1. `discord_enabled` 为假 → 不发。
2. `task_enabled.get(task) is False` → 不发（`task_disabled`）。
3. `task_channels.get(task)` 为空 → 不发（`no_channel`）。
4. 否则用 `_EMBED_BUILDERS[task]` 构造 embed，经 `DiscordClient.from_config(notify_cfg)` 发送到对应频道。
5. 发送失败结构化返回（`send_failed: ...`），**不拖垮任务**。

### webhook 解析：config 优先，env 兜底

`DiscordClient.from_config`（`investment_assistant/notify/discord.py`）按 `notify_cfg.webhooks.get(channel) or os.environ.get(env_key)` 解析每个频道：

| channel | 对应 env |
| --- | --- |
| `earnings` | `DISCORD_WEBHOOK_EARNINGS` |
| `signals` | `DISCORD_WEBHOOK_SIGNALS` |
| `daily` | `DISCORD_WEBHOOK_DAILY` |

即：先看 `NotifyConfig.webhooks` 里有没有显式 URL，没有再回退到环境变量。

---

## 6. SEC EDGAR 下载器

实现：`investment_assistant/filings/sec_downloader.py` 的 `SecEdgarDownloader`；由 `investment_assistant/filings/service.py` 的 `download_configured_filings(...)` 编排（filings 任务调用）。

- **`SEC_USER_AGENT` 必需**：未设置时 `download_filings_batch` 直接返回 `[]`（优雅降级，不崩）。格式约定 `Name email@example.com`。
- **拉取范围**：默认抓「昨日（T-1）」当天 filed 的 filings——`download_configured_filings` 的 `since_date` 缺省为 `date.today() - timedelta(days=1)`，并按 `FilingsConfig.forms` 过滤表单类型。
- **落盘路径**：`<output_dir>/<TICKER>/<FORM>/<accession>-<doc>`（ticker 大写、按表单分目录、文件名前缀 accession）。
- **CIK 解析**：经 `company_tickers.json`（可选 `cache_dir` 落盘缓存）把 ticker 映射为 10 位补零 CIK。
- **单标的容错**：某 ticker 抛异常被 `download_configured_filings` 捕获进 `errors`，不影响其余标的。

### 共享 HTTP 助手

`SecEdgarDownloader` 的默认 getter 是 `investment_assistant/data/http.py` 的 `get_json`（重试 / 退避 / 超时 / 结构化错误）。该 helper 由本次 `scheduled-ingestion-discord` 工作**从 Phase 2 计划的 Task 1 提前引入**，因此 Phase 2 数据层计划里的「`data/http.py` 共享重试助手」已实现、可跳过（详见 `docs/superpowers/plans/2026-06-27-phase2-data-layer.md`）。测试中可通过 `getter=` 注入 mock，离线可跑。
