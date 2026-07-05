# 调度器并入 API 进程实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 调度循环作为守护线程并入 API 进程，独立调度器应用下线，filings 文件统一落 API 卷。

**Architecture:** `tasks/scheduler.py` 的 while 循环重构为可优雅停止的 `run_forever(stop_event, ...)`，由 `api/app.py` 的 FastAPI lifespan 在启动时拉起守护线程；`/api/health` 通过模块级心跳变量暴露调度线程状态。`REGISTRY`、`compute_next_run`、`run_due_jobs`、`scheduled_jobs` 表全部不动。

**Tech Stack:** Python 3.14 / FastAPI / threading / pytest（fixture `client` 见 `tests/conftest.py`）

**Spec:** `docs/superpowers/specs/2026-07-05-scheduler-into-api-design.md`

## Global Constraints

- 环境变量契约：`SCHEDULER_ENABLED` 默认 `"1"`，仅 `"0"` 表示关闭；`SCHEDULER_TICK_SECONDS` 默认 `60`；`INVESTMENT_ASSISTANT_DATABASE_URL` 缺失时不起调度线程。
- 防双跑前提：API 应用副本数保持 1；**不加** `job_queue` 表，**不加** `scheduled_jobs` 领取锁。
- 删除 `tasks/scheduler.py` 的 `main()` 与 `__main__` 入口（防止独立调度进程再被拉起）。
- 注释/docstring 用中文，风格与现有代码一致（简短、说明"为什么"）。
- 现有 `tests/conftest.py` 的 `client` fixture 是 `TestClient(create_app())` **不带 with**，不触发 lifespan——存量测试不会意外起调度线程；lifespan 测试必须用 `with TestClient(...)`。
- 测试命令统一 `python -m pytest <path> -v`，最终全量回归 `python -m pytest`。

## File Structure

| 文件 | 动作 | 职责 |
|------|------|------|
| `investment_assistant/tasks/scheduler.py` | 修改 | `run_forever` 循环 + `last_tick_at()` 心跳；删除 `main()` |
| `investment_assistant/api/app.py` | 修改 | lifespan 启停调度线程 |
| `investment_assistant/services/health.py` | 修改 | 新增 `check_scheduler` 并注册进 `CHECKS` |
| `tests/test_scheduler.py` | 修改 | 追加 `run_forever` 测试 |
| `tests/test_api_app.py` | 修改 | 追加 lifespan 测试 |
| `tests/test_services_health.py` | 新建 | `check_scheduler` 单测 |
| `README.md` / `docs/getting-started.md` / `docs/scheduling-and-notifications.md` / `docs/deployment-sealos.md` | 修改 | 移除独立调度进程的启动方式，改为单应用形态 |

---

### Task 1: `scheduler.run_forever` + 心跳，删除 CLI 入口

**Files:**
- Modify: `investment_assistant/tasks/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: 现有 `run_due_jobs(conn, config, *, now, registry=REGISTRY)`、`connect(database_url)`（均已在 scheduler.py 内）。
- Produces: `run_forever(stop_event: threading.Event, *, database_url: str, config: AssistantConfig, tick_seconds: float = 60) -> None`；`last_tick_at() -> datetime | None`（Task 2、Task 3 依赖这两个名字）。

- [ ] **Step 1: 写失败测试** — 在 `tests/test_scheduler.py` 顶部把 import 区改为：

```python
import threading
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import scheduler
```

文件末尾追加：

```python
class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_run_forever_ticks_and_stops_via_stop_event(monkeypatch):
    ticks = []
    monkeypatch.setattr(scheduler, "connect", lambda url: _FakeConn())
    monkeypatch.setattr(scheduler, "run_due_jobs",
                        lambda conn, config, *, now: ticks.append(now) or [])
    stop = threading.Event()
    t = threading.Thread(
        target=scheduler.run_forever,
        kwargs={"stop_event": stop, "database_url": "postgresql://fake",
                "config": AssistantConfig(), "tick_seconds": 0.01},
        daemon=True,
    )
    t.start()
    for _ in range(200):  # 最多等 1s，等到第一个 tick
        if ticks:
            break
        time.sleep(0.005)
    stop.set()
    t.join(timeout=1)
    assert not t.is_alive()
    assert ticks
    assert scheduler.last_tick_at() is not None


def test_run_forever_survives_tick_exception(monkeypatch):
    calls = []

    def _boom(url):
        calls.append(1)
        raise RuntimeError("db down")

    monkeypatch.setattr(scheduler, "connect", _boom)
    stop = threading.Event()
    t = threading.Thread(
        target=scheduler.run_forever,
        kwargs={"stop_event": stop, "database_url": "postgresql://fake",
                "config": AssistantConfig(), "tick_seconds": 0.01},
        daemon=True,
    )
    t.start()
    for _ in range(200):  # 等到第 2 次调用，证明首次异常没有终止循环
        if len(calls) >= 2:
            break
        time.sleep(0.005)
    stop.set()
    t.join(timeout=1)
    assert len(calls) >= 2
    assert not t.is_alive()


def test_scheduler_module_has_no_cli_main():
    assert not hasattr(scheduler, "main")  # 独立调度进程入口已删除，防双跑
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: 新增 3 个测试 FAIL（`run_forever`/`last_tick_at` 不存在、`main` 仍存在），原有 4 个 PASS。

- [ ] **Step 3: 实现** — 修改 `investment_assistant/tasks/scheduler.py`：

删除 `main()` 函数和 `if __name__ == "__main__":` 块；import 区删除因此不再使用的 `os`、`time`、`load_config`（`logging`、`connect`、`datetime` 等保留）。在 `run_due_jobs` 之后追加：

```python
_last_tick_at: datetime | None = None


def last_tick_at() -> datetime | None:
    """最近一次调度 tick 完成时间（UTC）；线程尚未跑过则为 None，供 health 心跳用。"""
    return _last_tick_at


def run_forever(stop_event, *, database_url: str, config: AssistantConfig,
                tick_seconds: float = 60) -> None:
    """调度循环：驻留 API 进程的守护线程入口，stop_event 置位后在一个 tick 内退出。"""
    global _last_tick_at
    logger.info("scheduler thread started; tick=%ss", tick_seconds)
    while not stop_event.is_set():
        try:
            with connect(database_url) as conn:
                run_due_jobs(conn, config, now=datetime.now(UTC))
        except Exception:  # 主循环兜底，记录后继续
            logger.exception("scheduler tick failed")
        _last_tick_at = datetime.now(UTC)
        stop_event.wait(tick_seconds)
```

注意 `datetime`/`UTC` 已在文件头部 import；`AssistantConfig` 已 import。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: 全部 PASS（4 旧 + 3 新）。

- [ ] **Step 5: 提交**

```bash
git add investment_assistant/tasks/scheduler.py tests/test_scheduler.py
git commit -m "feat(scheduler): run_forever 循环支持 stop_event 与心跳，删除独立 CLI 入口"
```

---

### Task 2: FastAPI lifespan 启停调度线程

**Files:**
- Modify: `investment_assistant/api/app.py`
- Test: `tests/test_api_app.py`

**Interfaces:**
- Consumes: Task 1 的 `scheduler.run_forever(stop_event, *, database_url, config, tick_seconds)`。
- Produces: `create_app()` 返回的 app 在 lifespan 启动阶段按 env 决定是否拉起名为 `"scheduler"` 的守护线程；关闭阶段 `stop_event.set()`。

- [ ] **Step 1: 写失败测试** — 在 `tests/test_api_app.py` 顶部 import 区补充：

```python
import time

from fastapi.testclient import TestClient

from investment_assistant.api.app import create_app
from investment_assistant.tasks import scheduler
```

文件末尾追加：

```python
def test_lifespan_starts_and_stops_scheduler_thread(monkeypatch):
    started = {}

    def _fake_run_forever(*, stop_event, database_url, config, tick_seconds):
        started["url"] = database_url
        started["tick"] = tick_seconds
        started["stop_event"] = stop_event
        stop_event.wait(5)

    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("SCHEDULER_TICK_SECONDS", "1")
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)  # 默认即启用
    monkeypatch.setattr(scheduler, "run_forever", _fake_run_forever)
    with TestClient(create_app()):
        for _ in range(200):  # 线程启动是异步的，最多等 1s
            if "stop_event" in started:
                break
            time.sleep(0.005)
        assert started["url"] == "postgresql://fake"
        assert started["tick"] == 1
        assert not started["stop_event"].is_set()
    assert started["stop_event"].is_set()  # lifespan 退出时优雅停止


def test_lifespan_scheduler_disabled_by_env(monkeypatch):
    called = []
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    monkeypatch.setattr(scheduler, "run_forever", lambda **kw: called.append(1))
    with TestClient(create_app()):
        pass
    assert not called


def test_lifespan_scheduler_skipped_without_database(monkeypatch):
    called = []
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setattr(scheduler, "run_forever", lambda **kw: called.append(1))
    with TestClient(create_app()):
        pass
    assert not called
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_api_app.py -v`
Expected: `test_lifespan_starts_and_stops_scheduler_thread` FAIL（lifespan 不存在，`started` 为空），其余两个新测试可能"假通过"（无 lifespan 自然不调用）——以第一个测试失败为准；存量测试 PASS。

- [ ] **Step 3: 实现** — 修改 `investment_assistant/api/app.py`：

顶部 import 区补充：

```python
import logging
import os
import threading
from contextlib import asynccontextmanager
```

并加模块级 `logger = logging.getLogger(__name__)`。在 `create_app()` 定义之前加：

```python
@asynccontextmanager
async def _lifespan(app: FastAPI):
    """启动时按 env 拉起调度守护线程；关闭时置位 stop_event 优雅退出。"""
    from investment_assistant.config import load_config
    from investment_assistant.tasks import scheduler as _scheduler

    stop_event: threading.Event | None = None
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if os.environ.get("SCHEDULER_ENABLED", "1") != "0" and database_url:
        stop_event = threading.Event()
        threading.Thread(
            target=_scheduler.run_forever,
            kwargs={
                "stop_event": stop_event,
                "database_url": database_url,
                "config": load_config(None),
                "tick_seconds": int(os.environ.get("SCHEDULER_TICK_SECONDS", "60")),
            },
            name="scheduler",
            daemon=True,
        ).start()
        logger.info("scheduler thread launched")
    else:
        logger.info("scheduler thread disabled (SCHEDULER_ENABLED=0 或未配置数据库)")
    try:
        yield
    finally:
        if stop_event is not None:
            stop_event.set()
```

`create_app()` 中的 FastAPI 构造改为：

```python
    app = FastAPI(
        title="Hermes Investment Assistant",
        default_response_class=CompatJSONResponse,
        lifespan=_lifespan,
    )
```

注意：`_scheduler.run_forever` 的属性查找发生在 lifespan 执行时（函数体内 import + 线程启动时取属性），因此测试里 `monkeypatch.setattr(scheduler, "run_forever", ...)` 能生效。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_api_app.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add investment_assistant/api/app.py tests/test_api_app.py
git commit -m "feat(api): FastAPI lifespan 内嵌调度线程（SCHEDULER_ENABLED 开关）"
```

---

### Task 3: `/api/health` 调度心跳检查

**Files:**
- Modify: `investment_assistant/services/health.py`
- Test: 新建 `tests/test_services_health.py`

**Interfaces:**
- Consumes: Task 1 的 `scheduler.last_tick_at()`（内部读模块级 `scheduler._last_tick_at`，测试直接 monkeypatch 该变量）。
- Produces: `check_scheduler() -> dict`（uniform check 形状，`id="scheduler"`、`category="infrastructure"`），注册进 `health.CHECKS`，随 `/api/health` 返回。

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_services_health.py`：

```python
from datetime import UTC, datetime, timedelta

from investment_assistant.services import health
from investment_assistant.tasks import scheduler


def test_check_scheduler_disabled_by_env(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    out = health.check_scheduler()
    assert out["id"] == "scheduler"
    assert out["category"] == "infrastructure"
    assert out["status"] == "degraded"
    assert out["meta"]["enabled"] is False


def test_check_scheduler_disabled_without_database(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = health.check_scheduler()
    assert out["status"] == "degraded"
    assert out["meta"]["enabled"] is False


def test_check_scheduler_enabled_but_no_tick_yet(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(scheduler, "_last_tick_at", None)
    out = health.check_scheduler()
    assert out["status"] == "degraded"
    assert out["meta"]["last_tick_at"] is None


def test_check_scheduler_running(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(scheduler, "_last_tick_at", datetime.now(UTC))
    out = health.check_scheduler()
    assert out["status"] == "up"


def test_check_scheduler_stale_tick_reports_down(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("SCHEDULER_TICK_SECONDS", "60")
    monkeypatch.setattr(scheduler, "_last_tick_at",
                        datetime.now(UTC) - timedelta(seconds=600))
    out = health.check_scheduler()
    assert out["status"] == "down"


def test_check_scheduler_registered_in_checks():
    assert health.check_scheduler in health.CHECKS
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_services_health.py -v`
Expected: FAIL，`AttributeError: ... has no attribute 'check_scheduler'`。

- [ ] **Step 3: 实现** — 修改 `investment_assistant/services/health.py`：

在 `check_filings_storage` 之后（storage 段与 online 段之间）追加：

```python
def check_scheduler() -> dict[str, Any]:
    """调度线程心跳：驻留 API 进程的守护线程，超过 3 个 tick 无心跳视为 down。"""
    from investment_assistant.tasks import scheduler as _scheduler

    enabled = (
        os.environ.get("SCHEDULER_ENABLED", "1") != "0"
        and bool(os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"))
    )
    if not enabled:
        return _check("scheduler", "调度线程", "infrastructure", "degraded",
                      "未启用（SCHEDULER_ENABLED=0 或未配置数据库）",
                      meta={"enabled": False, "last_tick_at": None})
    last = _scheduler.last_tick_at()
    if last is None:
        return _check("scheduler", "调度线程", "infrastructure", "degraded",
                      "已启用但尚未完成首个 tick",
                      meta={"enabled": True, "last_tick_at": None})
    tick = int(os.environ.get("SCHEDULER_TICK_SECONDS", "60"))
    age = (datetime.now(UTC) - last).total_seconds()
    meta = {"enabled": True, "last_tick_at": last.isoformat()}
    if age > tick * 3:
        return _check("scheduler", "调度线程", "infrastructure", "down",
                      f"心跳超时：上次 tick 在 {int(age)} 秒前", meta=meta)
    return _check("scheduler", "调度线程", "infrastructure", "up",
                  f"运行中，上次 tick 在 {int(age)} 秒前", meta=meta)
```

并在 `CHECKS` 列表中 `check_daily_timer` 之后插入一行 `check_scheduler,`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_services_health.py -v`
Expected: 6 个测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add investment_assistant/services/health.py tests/test_services_health.py
git commit -m "feat(health): /api/health 增加调度线程心跳检查"
```

---

### Task 4: 文档更新为单应用形态 + 全量回归

**Files:**
- Modify: `docs/deployment-sealos.md`
- Modify: `README.md:107`
- Modify: `docs/getting-started.md:108`
- Modify: `docs/scheduling-and-notifications.md`

**Interfaces:**
- Consumes: 无代码依赖，描述 Task 1-3 的最终形态。
- Produces: 文档不再出现 `python -m investment_assistant.tasks.scheduler`（历史 plans/specs 除外）。

- [ ] **Step 1: 更新 `docs/deployment-sealos.md`**

1. 形态表（第 5-11 行）改为两组件，"一库两进程"改为"一库一进程"：

```markdown
本项目部署形态为「一库一进程」：

| 组件 | 启动命令 | 说明 |
|------|---------|------|
| PostgreSQL | —（Sealos 数据库应用托管） | 唯一持久状态源 |
| API 服务 | 镜像默认 CMD（migrate → uvicorn :8787） | 前端静态页 + `/api/*` + 内嵌调度线程（按 `scheduled_jobs` 表触发任务） |
```

2. 资源规划表删除"调度器应用"行，API 内存 512Mi → 768Mi，余量相应改为 ~512Mi。
3. 删除"第 3 步：部署调度器应用"整节；后续步骤编号顺延（原第 4 步验证清单变第 3 步）。
4. API 应用 env 表补充一行：`SCHEDULER_TICK_SECONDS`｜可选｜调度轮询间隔秒数，默认 60；说明 `SCHEDULER_ENABLED=0` 可关闭内嵌调度线程（调试用）。
5. 持久卷说明改为："挂载 `/srv/investment-assistant/filings`，1–2Gi（SEC filings 下载目录；定时与手动下载都由本进程执行，文件统一落此卷）"。
6. "已知限制"补充一条：调度线程随 API 重启中断，恢复后 `next_run_at <= now` 的过期任务在首个 tick 自动补跑。
7. 文末追加"从两进程形态迁移"小节（按 spec 部署迁移步骤）：

```markdown
## 从两进程形态迁移

1. `scripts/build-push.sh` 构建推送新镜像。
2. **先删除调度器应用**（避免旧调度进程与新 API 调度线程双跑；删除到 API 更新完成之间错过的触发点由补跑覆盖）。
3. API 应用更新镜像 tag；内存建议提到 768Mi；核对原调度器侧的 env（`SEC_USER_AGENT`、`DEEPSEEK_API_KEY`、`DISCORD_WEBHOOK_*`）在 API 侧已配置。
4. 前端任务中心手动回补 filings（按日期范围重下，单次 ≤92 天），`file_path` 随 upsert 自动改指 API 卷。
5. 确认列表页下载正常后，删除调度器应用遗留的 PVC。
```

- [ ] **Step 2: 更新其余三处文档**

1. `README.md:107`：删除 `python -m investment_assistant.tasks.scheduler        # 常驻调度守护进程` 一行，如上下文需要说明调度，改为一句"调度线程随 API 服务启动（`SCHEDULER_ENABLED=0` 可关）"。
2. `docs/getting-started.md:108`：同样删除该启动命令行，补一句同上说明。
3. `docs/scheduling-and-notifications.md`：第 9 行入口描述改为"调度线程随 API 进程启动（`api/app.py` lifespan 拉起 `tasks/scheduler.py:run_forever`），不再有独立进程入口"；第 25 行附近的 systemd `ExecStart=... tasks.scheduler` 示例段删除或标注为已废弃（该 service 不再需要，API service 即可）。

- [ ] **Step 3: 全量回归**

Run: `python -m pytest`
Expected: 全部 PASS，无新增失败。

Run: `grep -rn "tasks.scheduler" README.md docs/getting-started.md docs/scheduling-and-notifications.md docs/deployment-sealos.md`
Expected: 无输出（或仅剩"已废弃"标注处）。

- [ ] **Step 4: 提交**

```bash
git add docs/deployment-sealos.md README.md docs/getting-started.md docs/scheduling-and-notifications.md
git commit -m "docs: 部署与使用文档改为单应用形态（调度器并入 API）"
```

---

## 验收对照（spec 成功标准）

- 定时任务在 API 进程内执行：Task 1 + Task 2（`run_forever` 驻留 lifespan 线程）。
- htm 可下载不再 404：形态变更的直接结果（文件与下载端点同进程同卷），部署迁移后由 spec 步骤 4 回补验证。
- 重启补跑：`due_scheduled_jobs` 的 `next_run_at <= now` 语义未动，Task 1 测试覆盖循环存活性。
- `/api/health` 心跳：Task 3。
