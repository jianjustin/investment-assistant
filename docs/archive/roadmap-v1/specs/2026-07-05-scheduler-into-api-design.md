# 调度器并入 API 进程设计（scheduler-into-api）

日期：2026-07-05
状态：已确认，待实现

## 背景与问题

当前部署形态是"一库两进程"：API 应用与调度器应用共用同一镜像，各自在 Sealos 上挂载了路径同为 `/srv/investment-assistant/filings` 的 Local Storage。但两个应用的持久卷是**各自独立的 PVC**，路径相同不等于共享存储，由此产生文件"分家"问题：

- 定时（09:00）filings 任务由调度器进程执行，htm 落在调度器的卷上；
- 前端下载按钮走 API 进程的 `/api/filings/records/{id}/download`，按数据库 `filings.file_path` 读**本进程本地文件系统**——调度器下载的文件在 API 容器里不存在，返回 404 `filing file missing`。

同时，任务执行收敛到 API 后，独立调度器唯一剩下的工作是"到点触发"，而 `due_scheduled_jobs` 查询 `next_run_at <= now`（`db.py:318`）意味着**补跑语义是 `scheduled_jobs` 表天然自带的**——任何进程恢复轮询后都会领走过期任务。中间加队列或 HTTP 转发不增加价值。

## 决策

**调度循环作为后台守护线程并入 API 进程，调度器应用下线。**（备选方案"薄调度器 + DB 队列"与"HTTP 触发"已评估并否决：前者的独立进程只剩搬运一行数据的工作，后者与自动补跑需求冲突。）

已确认的需求语义：

- API 重启/升级窗口错过触发点 → **自动补跑**（由 `next_run_at <= now` 天然满足）。
- 调度器卷上的历史 htm → **不迁移**，用 filings 任务按日期范围回补重下（单次 ≤92 天）；`upsert_filing` 按 `(accession_number, primary_document)` 冲突更新，`file_path` 自动改指 API 卷。

## 组件改动

### 1. `investment_assistant/tasks/scheduler.py`

- `REGISTRY`、`compute_next_run`、`run_due_jobs` 原样保留。
- 现有 `main()` 的 while 循环重构为：

  ```python
  def run_forever(stop_event, *, database_url, config, tick_seconds) -> None
  ```

  - 用 `stop_event.wait(tick_seconds)` 代替 `time.sleep`，支持优雅停止；
  - 单 tick 兜底 try/except 照搬现有逻辑（DB 闪断等记日志后等下一 tick，线程不退出）。
- **删除 `main()` 与 `__main__` 入口**：防止按旧文档再起独立调度进程造成任务双跑。旧的调度器应用换用新镜像会启动失败，操作者可立即发现。

### 2. `investment_assistant/api/app.py`

- `create_app()` 增加 FastAPI lifespan：
  - 启动时，若 `SCHEDULER_ENABLED != "0"` 且配置了 `INVESTMENT_ASSISTANT_DATABASE_URL`，创建 `threading.Event` 并启动守护调度线程（target 为 `run_forever`）；
  - 无 DB URL 时不起线程，只记一条 log（与现有 degraded 模式一致）；
  - 关闭时 `stop_event.set()`。
- `SCHEDULER_TICK_SECONDS`（默认 60）继续生效。

### 3. 调度器心跳可见性

- 调度线程每个 tick 更新模块级 `last_tick_at`（内存变量即可）；
- `/api/health` 增加 `scheduler` 检查项：`running` / `disabled`（未启用或无 DB）/ 最近一次 tick 时间。

### 4. 明确不做的事

- 不加 `job_queue` 表；
- 不做 `scheduled_jobs` 的原子领取锁。防双跑依赖两点：**API 应用副本数保持 1**（与 `runner` 内存态运行状态的既有约束一致），以及删除调度器 CLI 入口。

## 数据流（改造后）

- **定时路径**：API 内调度线程每 tick 轮询 `scheduled_jobs`，到期任务在调度线程内顺序执行 → `_harness` 写 `job_reports` + 发通知 → `reschedule_job` 推进 `next_run_at`。
- **手动路径**：前端 → `trigger_job` → `runner.submit` 后台线程执行，完全不变。
- **文件路径**：filings 的 htm 只落在 API 应用挂载的唯一持久卷上，下载端点从此总能读到本进程下载的文件。

## 错误处理与已知取舍

- 单个 tick 失败：记日志，等下一 tick，线程不退出。
- 单任务异常：`run_due_jobs` 与 `_harness` 双层兜底，不影响同 tick 其它任务。
- 已知取舍（不改行为）：任务在调度线程内顺序执行，某任务卡死会阻塞后续定时任务——现状的独立调度器同样如此，非本次引入。
- API 重启会中断正在执行的任务——现状调度器重启同样如此。

## 部署与迁移步骤（Sealos）

1. 构建推送新镜像（`scripts/build-push.sh`）。
2. **删除调度器应用**（必须先于 API 更新，否则旧调度器进程与新 API 调度线程会短暂同时轮询造成双跑；删除后到 API 更新完成之间错过的触发点由补跑覆盖）。
3. API 应用更新镜像 tag；内存建议 512Mi → 768Mi（吃下原调度器份额）；核对原来只配在调度器侧的 env（`SEC_USER_AGENT`、`DEEPSEEK_API_KEY`、`DISCORD_WEBHOOK_*`——API 侧已有则跳过）。
4. 前端任务中心手动回补 filings：按日期范围重下（单次 ≤92 天），`file_path` 随 upsert 更新为 API 卷路径。
5. 确认列表页下载正常后，删除调度器应用的旧 PVC。
6. 更新 `docs/deployment-sealos.md`：删除"第 3 步：部署调度器应用"，资源表改为 PG + API 两组件，env 表合并。

## 测试

- 现有 `compute_next_run` / `run_due_jobs` 测试不动。
- 新增 `run_forever` 测试：注入 fake connect 与极小 tick，验证 (a) `stop_event` 能让循环在一个 tick 内退出；(b) 单 tick 异常不终止循环。
- 新增 lifespan 测试：`SCHEDULER_ENABLED=0` 或无 DB URL 时不起线程；正常路径下 `/api/health` 出现 `scheduler` 心跳字段。
- 清理引用 `scheduler.main` 的既有测试与文档（如有）。

## 成功标准

- 调度器应用下线后，`metrics` / `filings` / `scores`（及已配置的 `event_study`）按 `scheduled_jobs` 配置在 API 进程内准点执行，`job_reports` 有记录。
- 定时下载的 htm 通过前端下载按钮可以直接下载（不再 404）。
- 重启 API 应用跨过某任务触发点后，恢复上线的第一个 tick 内该任务被补跑。
- `/api/health` 能看到调度线程心跳。
