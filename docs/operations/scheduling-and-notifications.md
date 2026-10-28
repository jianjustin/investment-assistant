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
- 手动批处理（`POST /api/workbench/run` 或任务中心的「立即运行」）有两个 run_id：API 返回、页面轮询用的 runner run_id，与任务外壳（harness）写 `job_reports` 的 run_id。数据库记录一律用 harness 的 run_id。

## 任务外壳与运行报告

所有任务都经 `tasks/_harness.py` 的 `run_task` 运行：生成 `run_id`，捕获异常为结构化 `status="error"`，写 `job_reports`（`task`、`run_id`、`status`、起止时间、`trigger_source`、`summary`），再交给通知层。`job_reports` 写入时剪掉 30 天前的行。`workbench` 任务以 `pass_run_id=True` 让任务函数拿到这个 `run_id` 并传给 `run_batch`，批处理新写的 `data_fetch_runs`、`screen_runs`、`signal_candidates` 行都带同一个 `run_id`，与 `job_reports` 同源；其余任务仍是 `fn()` 无参调用。

「工具 → 运行记录」按任务筛选、每 15 秒刷新；`GET /api/jobs/reports?task=&limit=`（limit 1–200）。页面通过 `GET /api/events`（SSE）免刷新更新。

## 批处理采集的锁与拉取记录

工作台批处理（定时与手动）在采集阶段按固定顺序（`bars`、`news`、`sec_filings`、`fred`）持有会话级 Postgres advisory lock（键 `hashtext('data_family:<id>')`，专用连接、用完即放），避免与数据菜单的手动拉取同时写同一张数据表；`universe` 只读范围文件，不加锁。锁跨进程有效，命令行运行的批处理同样遵守。

采集阶段结束后（区制阶段之前），每个已记录的数据族向 `data_fetch_runs` 各追加一行（`job = workbench`，`trigger` 为 `scheduled` / `manual_batch`，记录带该次运行的 `run_id`；显式 `tickers`/`pool` 的调用只写 `bars`、`news`、`sec_filings`、`fred` 四行，没有 `universe` 行）。写入在独立事务里，失败（包括迁移 024 未执行）只记在运行报告的 `summary.data_status`，不影响批处理结果。表结构与状态口径见[数据基础设计](../specs/2026-10-26-v2.3-data-foundation-design.md)。

`filings` 任务（下载器与监控两种模式）结束后同样追加一行 `sec_filings`（`job = filings`，`trigger` 按 `trigger_source` 取 `scheduled` / `manual_batch`），记录带该次运行的 `run_id`。目标按模式取实际采集清单：监控模式是监控观察名单文件（`sec_monitor.watchlist_path` 中「采集=是」的成员；成功时即 `summary.tickers`），下载器模式是 `config.watchlist`，与批处理的「当前池 + 持仓」不同，`detail.targets_source` 如实注明。整次采集失败记一条 `{"target": "*"}` 哨兵（不进 `target_count`）；Discord 投递这类非标的错误记在 `detail.non_target_errors`，不伪造成采集目标。写入失败只记在任务返回值的 `data_status`，不影响任务结果与运行报告；定时路径的返回值字段会被调度器丢弃，因此同时向 stderr 打一行 `[data_fetch_runs] write failed family=sec_filings job=filings trigger=<trigger> error=<脱敏原因>` 作为可检索落点。

## 批处理阶段证据

每次 `workbench` 任务（定时、手动、非交易日）向 `stage_runs` 追加恰好 8 行（`stages_version = stages-2`），阶段顺序固定为 `collect`、`screen`、`regime`、`signals`、`plan`、`agent`、`review`、`push`；任务开始时若迁移 026 未执行（查询失败也按未执行处理），本次按 `stages-1` 记 7 行，没有 `review` 行（025 的约束本来也不允许），运行报告 `errors` 有一条 `timeline: migration_026_missing`。`run_id` 与 `job_reports` 的 `run_id` 相同，`trigger` 为 `scheduled` / `manual_batch`。每行记状态（`success` / `partial` / `degraded` / `failed` / `skipped`）、输入与产出计数、按原因分组的跳过、逐目标失败、降级、产出引用（数据拉取行、筛选、区制、候选、计划、Agent 运行、复查记录与新版计划的 id）与耗时。`push` 之前的阶段由批处理在各自的位置记，`push` 由任务层记；表只追加，不在 `WORKBENCH_TABLES` 里，缺表不影响批处理。

- 整阶段跳过的原因：`not_trading_day`（纽约休市，`push` 之前的全部阶段）、`migration_026_missing`（`review`，只在直接以 `stages-2` 记账而库缺 026 时出现）、`explicit_pool`（`screen`）、`manual_run`（手动运行不推送）、`already_pushed`、`task_disabled`、`agent_unavailable: <原因>`（缺 key 或关闭，压过「当天没有单元」的空跑成功；`review` 阶段在没有复查对象时同样如此，有对象时照常记账并标 `degraded`）、`not_reached`（运行正常结束但该阶段没有执行）。
- 中途抛异常：已写的阶段保留，出错的阶段与其后未写的阶段记 `failed`，原因 `aborted: <异常摘要>`，仍是 8 行（`stages-1` 为 7 行）。`review` 阶段整体出错只记该阶段 `failed` 与 `errors` 一条 `review: <原因>`，不中断推送。
- 休市日的 `push` 发的是休市一行，记 `detail.closed = true`。
- 写入失败（含迁移 025 未执行）只记在运行报告 `summary.stage_status = {"written": n, "error": …}`，不进 `summary.errors`，不改变任务状态。任务因异常失败时运行报告只有 `error`，没有 `stage_status`。

### 运行一览（v2.6）

阶段证据在「今日」顶部以「运行一览」展示，数据来自只读接口 `GET /api/workbench/run-overview?session=YYYY-MM-DD[&run_id=…]`（`session` 缺省为最近已收盘交易日），实现是 `workbench/run_overview.py`。它**只读 `stage_runs`**（一个只读事务，不读别的表、不调用外部数据源），每个阶段返回与行逐字段相同的数字（`input_count`、`output_count`、`skips`、`failures`、`degradations`、`reason`、`duration_ms`），另加后端按模板拼好的一句话 `sentence`、原因文案（`reason_text`、`skips[].text`、`degradations[].text`）、状态文案 `status_text` 和该阶段的概念卡 `concepts`；整次运行另有 `headline`（如「定时运行 · 06:30 开始 · 用时 3 分 12 秒 · 8 个阶段：成功 6 · 降级 1 · 跳过 1」，时间为北京时间）。

- **同一天多次运行**：默认显示该交易日最后开始的、**不是休市空跑**的那次（休市空跑 = `push` 之前的阶段全部 `skipped` 且原因为 `not_trading_day`）；只有休市空跑时才显示它，`headline` 写「纽约休市，未运行（只推送一行休市说明）」。`runs` 列出同日全部运行（`run_id`、`trigger`、`trigger_text`：定时 / 手动 / 休市、`stages_version`、开始与结束时间、行数、`closed`），`run_id` 指定其中一次；不属于该日 → 404，日期非法 → 400，数据库不可用 → 503。
- **边界**：`stage_runs` 表不存在 → `ready: false`、`note`「迁移 025 未执行，暂无阶段证据」；这一天没有任何行 → `note`「这一天没有阶段证据：当天没有运行，或运行早于 v2.4（2026-10-27 起才记录）」；`stages-1` 运行在 `push` 前补一行 `not_recorded` 占位（计数为 `null`）；缺某个阶段行 → `missing`「这一阶段没有证据行（记账失败，见运行报告）」；注册表之外的阶段排在最后，句子「未知阶段」。
- **原因文案**：先查 `run_overview.REASON_TEXT`（只放 `agent.REASON_TEXT` 没有的代码，含降级 kind 与规则跳过原因），再查 `agent.REASON_TEXT`，不认识的代码原样显示；带参数的 `agent_unavailable: <x>`、`aborted: <x>`、`<规则 id>:<原因>` 按规则拼。
- **命令行（只读）**：`python -m investment_assistant.workbench.run_overview --session YYYY-MM-DD [--run-id ID]`，先打印 `headline`，再逐行打印 `阶段 · 状态 · 句子 · 输入/产出`；没有阶段证据（打印说明）退出码 1，参数错误、`--run-id` 不属于该日或数据库不可用退出码 2。

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
