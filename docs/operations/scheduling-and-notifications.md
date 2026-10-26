# 调度与通知

## 调度线程

调度线程随 API 进程启动（`api/app.py` 的 lifespan 拉起 `tasks/scheduler.py:run_forever`），`SCHEDULER_ENABLED=0` 或缺数据库时不启动。它每 `SCHEDULER_TICK_SECONDS`（默认 60 秒）醒一次：

- 取出 `enabled AND (next_run_at IS NULL OR next_run_at <= now)` 的任务（`FOR UPDATE SKIP LOCKED`）。
- 按 `REGISTRY` 派发；库里有、注册表里没有的任务记为 `unregistered job` 并跳过，不中断循环。
- 跑完按 `time_local` / `weekday_mask`（ISO 周几，如 `1-5`）/ `timezone` 算下一次运行时间，写回 `next_run_at`、`last_run_at`。
- 单个任务抛异常只记 `error`，循环继续。

### 任务注册表

| 任务 | 模块 | 迁移种子 | 默认通知频道 |
| --- | --- | --- | --- |
| `workbench` | `tasks/workbench.py` | 北京 06:30，周二至周六 | `signals`（每日计划推送） |
| `workbench_review` | `tasks/workbench_review.py` | 北京 08:00，每天，插入为关闭 | `signals`（周/月复盘推送） |
| `filings` | `tasks/filings.py` | 北京 09:30，周一至周五（迁移 023 之前是美东 09:00） | `earnings`；开启 SEC 监控后改为 Bot 直发，见 [SEC 采集](../features/sec-filings.md) |

每个任务页面上的 `?` 说明来自 `tasks/catalog.py` 的 `JOB_INFO`，随 `GET /api/jobs/scheduled` 的 `description` 字段下发；前端不再自带文案。改说明只改后端注册表。

迁移种子只是默认值。改时间或开关在「设置 → 定时任务」操作（`PATCH /api/jobs/scheduled/{name}`），下一个 tick 生效，不用重启。

### 手动运行

- 「工具 → 任务中心」的「立即运行」与「按日期运行」（`{"date"}` 或 `{"from","to"}`，上限 92 天；未来日期、倒序或超限返回 400）。
- API：`POST /api/jobs/{name}/run`，返回 `run_id`，用 `GET /api/runs/{run_id}` 轮询。
- 工作台批处理手动运行**不推送**；手动运行总是针对最近一个已收盘的交易日（纽约 17:00 后算当天收盘）。

## 任务外壳与运行报告

所有任务都经 `tasks/_harness.py` 的 `run_task` 运行：生成 `run_id`，捕获异常为结构化 `status="error"`，写 `job_reports`（`task`、`run_id`、`status`、起止时间、`trigger_source`、`summary`），再交给通知层。`job_reports` 写入时剪掉 30 天前的行。

「工具 → 运行记录」按任务筛选、每 15 秒刷新；`GET /api/jobs/reports?task=&limit=`（limit 1–200）。页面通过 `GET /api/events`（SSE）免刷新更新。

## 批处理采集的锁与拉取记录

工作台批处理（定时与手动）在采集阶段按固定顺序（`bars`、`news`、`sec_filings`、`fred`）持有会话级 Postgres advisory lock（键 `hashtext('data_family:<id>')`，专用连接、用完即放），避免与数据菜单的手动拉取同时写同一张数据表；`universe` 只读范围文件，不加锁。锁跨进程有效，命令行运行的批处理同样遵守。

采集阶段结束后（区制阶段之前），每个已记录的数据族向 `data_fetch_runs` 各追加一行（`job = workbench`，`trigger` 为 `scheduled` / `manual_batch`；显式 `tickers`/`pool` 的调用不写记录，也没有 `universe` 行）。写入在独立事务里，失败（包括迁移 024 未执行）只记在运行报告的 `summary.data_status`，不影响批处理结果。表结构与状态口径见[数据基础设计](../specs/2026-10-26-v2.3-data-foundation-design.md)。

## 通知

配置是 `config.py` 的 `NotifyConfig`，「设置 → 推送配置」写入 `notify_settings` 后覆盖它：

| 字段 | 说明 |
| --- | --- |
| `channel` | 全局单选：`discord` 或 `email` |
| `discord_enabled` | Discord 总开关 |
| `webhooks` | `{频道: url}`；未配置时退回环境变量 `DISCORD_WEBHOOK_SIGNALS` / `_DAILY` / `_EARNINGS` |
| `task_channels` | 任务 → 频道；默认 `workbench`、`workbench_review` → `signals`，`filings` → `earnings` |
| `task_enabled` | 每个任务的通知开关 |
| `email` | 发件人、收件人、SMTP 主机与端口；密码只取环境变量 `SMTP_PASSWORD` |

派发顺序：总开关关 → 不发；该任务开关关 → `task_disabled`；没有频道 → `no_channel`；否则发送，失败返回 `send_failed: …`，不让任务失败。工作台的每日推送和复盘推送由各自的任务自己发（`run_task(..., notify=False)`），结果写在运行报告的 `summary.push` 里。

验证：「设置 → 推送配置」点「验证」发测试消息（`POST /api/settings/notify/test`，body `{"channel": "signals"}`）。webhook 只返回「是否已配置」，不回显明文。
