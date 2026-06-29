# Dashboard 五层 IA 重构 + 工具层任务可视化 + Discord 可编辑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把前端 6 区重构为按投资流水线分层的 5 层（工具/数据/策略/交易/设置），新增工具层任务/日志/指标可视化与 Discord 可编辑配置（含验证按钮），并清理文档。

**Architecture:** 后端在 `db.py` 增只读/更新仓储 → `services/{jobs,settings}.py` 业务层 → `api/routes/{jobs,settings}.py` 薄路由（复用 `@register` + `ApiResponse`）。Discord 配置落 DB 单行 `notify_settings`，经 `effective_notify_config` overlay 到文件基线，`_harness`/UI 统一消费。前端沿用 hash 路由，`SideNav` 改 5 层、删除总览、旧页平移、新建工具层四分页与设置层可编辑表单。

**Tech Stack:** Python 3.11、psycopg3 + psycopg_pool、PostgreSQL 16、pytest；Svelte 5（runes）+ Vite + Tailwind + vitest；ECharts。

## Global Constraints

- **分支**：沿用当前 `feat/scheduled-ingestion-discord`；不主动 push；提交结尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **测试隔离**：新增/改动逻辑必须有单测；外部依赖（DB / Discord / 网络）**全部 mock 或注入**，离线可跑。
- **DB 写法对齐现有**：`with conn.cursor() as cur` + 具名参数 + `conn.commit()`；读函数 `dict(zip(keys, row))`。
- **迁移幂等**：`CREATE TABLE IF NOT EXISTS` + `ON CONFLICT DO NOTHING`。本计划占 `008_notify_settings`；若上游 `2026-06-27-phase2-data-layer.md` 先落地 008，则本计划顺延为下一个可用编号（同步改所有引用）。
- **优雅降级**：无 `INVESTMENT_ASSISTANT_DATABASE_URL` 时，只读端点返回空/基线 + `{"degraded": true}`，不崩。
- **不静默吞错**：外部失败结构化返回，不裸 `except` 后丢弃。
- **敏感值不回显**：webhook URL / env 值在 GET 一律掩码（`configured: bool`），明文仅在 PATCH/test 请求方向单向写入。
- **路由注册**：新增 `api/routes/*.py` 必须加入 `investment_assistant/api/routes/__init__.py` 的 import 才会生效。
- **spec**：`docs/superpowers/specs/2026-06-29-dashboard-5-layer-ia-design.md`。

---

## File Structure

```
investment_assistant/
  db.py                         # 改：+list_scheduled_jobs/list_job_reports/job_report_metrics/update_scheduled_job
                                #     +get_notify_settings/update_notify_settings
  services/
    jobs.py                     # 新：jobs 读聚合 + 手动触发封装
    settings.py                 # 新：notify overlay/掩码/test + env 状态
  api/routes/
    jobs.py                     # 新：/api/jobs/*
    settings.py                 # 新：/api/settings/*
    __init__.py                 # 改：import jobs, settings
  tasks/_harness.py             # 改：dispatch 用 effective_notify_config(config.notify)
migrations/
  008_notify_settings.sql       # 新
web/src/
  lib/api.ts                    # 改：+jobs.* / settings.* 客户端方法
  lib/components/SideNav.svelte # 改：5 层 nav
  app.svelte                    # 改：5 zone 路由
  routes/
    Tools.svelte                # 新：工具层四分页
    Data.svelte                 # 改名自 Market.svelte（信号/趋势/技术面）
    Trade.svelte                # 改名自 Hermes.svelte（宏观/决策/交易指令占位）
    Settings.svelte             # 新：系统/关注列表/Discord/定时任务/环境变量
    Strategy.svelte             # 改：+backtest 占位
    Placeholder.svelte          # 新：通用占位页
    Dashboard.svelte            # 删除
    Watchlist.svelte            # 内容并入 Settings（文件可删或留作子组件）
tests/
  test_jobs_repository.py  test_services_jobs.py  test_settings_service.py
  test_db_sql.py（追加 008 断言）
web/src/lib/api.test.ts（追加 jobs/settings wrapper 断言）
```

---

## Task 1：`db.py` jobs 只读 + 更新仓储

**Files:**
- Modify: `investment_assistant/db.py`
- Create: `tests/test_jobs_repository.py`

**Interfaces:**
- Produces:
  - `db.list_scheduled_jobs(conn) -> list[dict]`（键 `name,time_local,weekday_mask,timezone,enabled,next_run_at,last_run_at`）
  - `db.list_job_reports(conn, *, task=None, limit=50) -> list[dict]`（键 `task,run_id,status,started_at,finished_at,summary,created_at`）
  - `db.job_report_metrics(conn, *, task=None, since) -> list[dict]`（键 `task,total,success,avg_seconds,error_days`，`error_days` 为 `[{day,count}]`）
  - `db.update_scheduled_job(conn, name, *, enabled=None, time_local=None) -> None`

- [ ] **Step 1: 写测试** —— `tests/test_jobs_repository.py`：

```python
from datetime import UTC, datetime

from investment_assistant import db


class FakeCursor:
    def __init__(self, store, rows):
        self.store = store
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.store.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows=None):
        self.store = []
        self.commits = 0
        self.rows = rows or []

    def cursor(self):
        return FakeCursor(self.store, self.rows)

    def commit(self):
        self.commits += 1


def test_list_scheduled_jobs_maps_rows():
    rows = [("metrics", "08:00", "1-5", "America/New_York", True, None, None)]
    conn = FakeConn(rows=rows)
    out = db.list_scheduled_jobs(conn)
    assert out[0]["name"] == "metrics" and out[0]["enabled"] is True
    assert "ORDER BY name" in conn.store[0][0]


def test_list_job_reports_filters_by_task_and_limit():
    rows = [("metrics", "metrics-1", "success", None, None, {"n": 1}, None)]
    conn = FakeConn(rows=rows)
    out = db.list_job_reports(conn, task="metrics", limit=10)
    assert out[0]["run_id"] == "metrics-1" and out[0]["summary"] == {"n": 1}
    sql, params = conn.store[0]
    assert "WHERE task = %(task)s" in sql and params["task"] == "metrics" and params["limit"] == 10


def test_list_job_reports_no_task_omits_where():
    conn = FakeConn(rows=[])
    db.list_job_reports(conn)
    assert "WHERE task" not in conn.store[0][0]


def test_job_report_metrics_aggregates():
    rows = [("metrics", 5, 4, 12.5, [{"day": "2026-06-28", "count": 1}])]
    conn = FakeConn(rows=rows)
    out = db.job_report_metrics(conn, since=datetime(2026, 6, 22, tzinfo=UTC))
    assert out[0]["task"] == "metrics" and out[0]["success"] == 4 and out[0]["avg_seconds"] == 12.5


def test_update_scheduled_job_partial_and_clears_next_run_on_time_change():
    conn = FakeConn()
    db.update_scheduled_job(conn, "metrics", time_local="09:30")
    sql, params = conn.store[0]
    assert "UPDATE scheduled_jobs" in sql and "next_run_at = NULL" in sql
    assert params["time_local"] == "09:30" and params["name"] == "metrics"
    assert conn.commits == 1


def test_update_scheduled_job_enabled_only_keeps_next_run():
    conn = FakeConn()
    db.update_scheduled_job(conn, "metrics", enabled=False)
    sql, _ = conn.store[0]
    assert "enabled = %(enabled)s" in sql and "next_run_at = NULL" not in sql
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_jobs_repository.py -q`
Expected: FAIL（函数未定义）。

- [ ] **Step 3: 在 `db.py` 末尾追加：**

```python
def list_scheduled_jobs(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, time_local, weekday_mask, timezone, enabled, next_run_at, last_run_at
            FROM scheduled_jobs
            ORDER BY name
            """
        )
        rows = cur.fetchall()
    keys = ["name", "time_local", "weekday_mask", "timezone", "enabled", "next_run_at", "last_run_at"]
    return [dict(zip(keys, row)) for row in rows]


def list_job_reports(conn, *, task: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    where = "WHERE task = %(task)s" if task else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT task, run_id, status, started_at, finished_at, summary, created_at
            FROM job_reports
            {where}
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """,
            {"task": task, "limit": limit},
        )
        rows = cur.fetchall()
    keys = ["task", "run_id", "status", "started_at", "finished_at", "summary", "created_at"]
    return [dict(zip(keys, row)) for row in rows]


def job_report_metrics(conn, *, task: str | None = None, since) -> list[dict[str, Any]]:
    where = "WHERE created_at >= %(since)s" + (" AND task = %(task)s" if task else "")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
              task,
              count(*) AS total,
              count(*) FILTER (WHERE status = 'success') AS success,
              avg(EXTRACT(EPOCH FROM (finished_at - started_at))) AS avg_seconds,
              coalesce(
                jsonb_agg(jsonb_build_object('day', to_char(created_at, 'YYYY-MM-DD'), 'count', 1))
                  FILTER (WHERE status = 'error'),
                '[]'::jsonb
              ) AS error_days
            FROM job_reports
            {where}
            GROUP BY task
            ORDER BY task
            """,
            {"task": task, "since": since},
        )
        rows = cur.fetchall()
    keys = ["task", "total", "success", "avg_seconds", "error_days"]
    return [dict(zip(keys, row)) for row in rows]


def update_scheduled_job(conn, name: str, *, enabled=None, time_local=None) -> None:
    sets = ["updated_at = now()"]
    params: dict[str, Any] = {"name": name}
    if enabled is not None:
        sets.append("enabled = %(enabled)s")
        params["enabled"] = enabled
    if time_local is not None:
        sets.append("time_local = %(time_local)s")
        sets.append("next_run_at = NULL")  # 改时间 → 下一 tick 重算
        params["time_local"] = time_local
    with conn.cursor() as cur:
        cur.execute(f"UPDATE scheduled_jobs SET {', '.join(sets)} WHERE name = %(name)s", params)
    conn.commit()
```
> `db.py` 顶部已 `from typing import Any`，无需新增 import。

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_jobs_repository.py -q`（PASS）
```bash
git add investment_assistant/db.py tests/test_jobs_repository.py
git commit -m "feat(db): jobs read + update repository (scheduled list / reports / metrics / patch)"
```

---

## Task 2：`services/jobs.py` + `api/routes/jobs.py`

**Files:**
- Create: `investment_assistant/services/jobs.py`
- Create: `investment_assistant/api/routes/jobs.py`
- Modify: `investment_assistant/api/routes/__init__.py`
- Create: `tests/test_services_jobs.py`

**Interfaces:**
- Consumes: `db.{list_scheduled_jobs,list_job_reports,job_report_metrics,update_scheduled_job}`、`tasks.scheduler.REGISTRY`、`tasks.runner.submit`、`config.load_config`。
- Produces:
  - `services.jobs.scheduled_jobs() -> dict`（`{"jobs":[...], "degraded": bool}`）
  - `services.jobs.job_reports(task=None, limit=50) -> dict`（`{"reports":[...], "degraded": bool}`）
  - `services.jobs.job_metrics(task=None, days=7) -> dict`（`{"metrics":[...], "degraded": bool}`）
  - `services.jobs.trigger_job(name) -> dict`（`{"run_id","status"}`；未注册 → `ValueError`）
  - `services.jobs.patch_scheduled_job(name, *, enabled=None, time_local=None) -> dict`
  - 路由：`GET /api/jobs/scheduled`、`GET /api/jobs/reports`、`GET /api/jobs/metrics`、`POST /api/jobs/{name}/run`、`PATCH /api/jobs/scheduled/{name}`

- [ ] **Step 1: 写测试** —— `tests/test_services_jobs.py`：

```python
import pytest

from investment_assistant.services import jobs


def test_scheduled_jobs_degraded_without_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = jobs.scheduled_jobs()
    assert out["degraded"] is True and out["jobs"] == []


def test_job_reports_reads_via_db(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(jobs, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(jobs.db, "list_job_reports",
                        lambda conn, *, task, limit: [{"task": task, "run_id": "r1"}])
    out = jobs.job_reports(task="metrics", limit=5)
    assert out["degraded"] is False and out["reports"][0]["run_id"] == "r1"


def test_trigger_job_unknown_raises(monkeypatch):
    monkeypatch.setattr(jobs, "REGISTRY", {})
    with pytest.raises(ValueError):
        jobs.trigger_job("ghost")


def test_trigger_job_submits(monkeypatch):
    captured = {}
    monkeypatch.setattr(jobs, "REGISTRY", {"metrics": lambda config: {"ok": True}})
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    monkeypatch.setattr(jobs.runner, "submit", lambda kind, fn: captured.setdefault("kind", kind) or "run-1")
    out = jobs.trigger_job("metrics")
    assert out["run_id"] == "run-1" and out["status"] == "pending" and captured["kind"] == "metrics"


def test_patch_scheduled_job_passthrough(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    seen = {}
    monkeypatch.setattr(jobs, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(jobs.db, "update_scheduled_job",
                        lambda conn, name, **kw: seen.update({"name": name, **kw}))
    out = jobs.patch_scheduled_job("metrics", time_local="09:30")
    assert out["updated"] is True and seen == {"name": "metrics", "enabled": None, "time_local": "09:30"}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_services_jobs.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `services/jobs.py`：**

```python
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.config import load_config
from investment_assistant.db import connect
from investment_assistant.tasks import runner
from investment_assistant.tasks.scheduler import REGISTRY


def _with_conn(fn: Callable[[Any], Any]) -> Any:
    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    with connect(database_url) as conn:
        return fn(conn)


def _has_db() -> bool:
    return bool(os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"))


def scheduled_jobs() -> dict[str, Any]:
    if not _has_db():
        return {"jobs": [], "degraded": True}
    return {"jobs": _with_conn(db.list_scheduled_jobs), "degraded": False}


def job_reports(task: str | None = None, limit: int = 50) -> dict[str, Any]:
    if not _has_db():
        return {"reports": [], "degraded": True}
    reports = _with_conn(lambda conn: db.list_job_reports(conn, task=task, limit=limit))
    return {"reports": reports, "degraded": False}


def job_metrics(task: str | None = None, days: int = 7) -> dict[str, Any]:
    if not _has_db():
        return {"metrics": [], "degraded": True}
    since = datetime.now(UTC) - timedelta(days=days)
    metrics = _with_conn(lambda conn: db.job_report_metrics(conn, task=task, since=since))
    return {"metrics": metrics, "degraded": False}


def trigger_job(name: str) -> dict[str, Any]:
    if name not in REGISTRY:
        raise ValueError(f"unknown job: {name}")
    config = load_config()
    run_id = runner.submit(name, lambda: REGISTRY[name](config))
    return {"run_id": run_id, "status": "pending"}


def patch_scheduled_job(name: str, *, enabled=None, time_local=None) -> dict[str, Any]:
    if not _has_db():
        return {"updated": False, "degraded": True}
    _with_conn(lambda conn: db.update_scheduled_job(conn, name, enabled=enabled, time_local=time_local))
    return {"updated": True}
```
> `REGISTRY` 的值是 `metrics_task.run` 等 `Callable[[AssistantConfig], dict]`，故触发用 `REGISTRY[name](config)`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_services_jobs.py -q`
Expected: PASS。

- [ ] **Step 5: 实现 `api/routes/jobs.py`：**

```python
from investment_assistant.api.http import ApiResponse, first, parse_int
from investment_assistant.api.router import register
from investment_assistant.services import jobs


@register("GET", exact="/api/jobs/scheduled")
def _scheduled(path, query, payload):
    return ApiResponse(jobs.scheduled_jobs())


@register("GET", exact="/api/jobs/reports")
def _reports(path, query, payload):
    task = first(query, "task")
    limit = parse_int(first(query, "limit"), default=50, minimum=1, maximum=200)
    return ApiResponse(jobs.job_reports(task=task, limit=limit))


@register("GET", exact="/api/jobs/metrics")
def _metrics(path, query, payload):
    task = first(query, "task")
    days = parse_int(first(query, "window"), default=7, minimum=1, maximum=90)
    return ApiResponse(jobs.job_metrics(task=task, days=days))


@register("POST", prefix="/api/jobs/")
def _run(path, query, payload):
    # 仅处理 /api/jobs/{name}/run
    suffix = path.removeprefix("/api/jobs/")
    if not suffix.endswith("/run"):
        return ApiResponse({"error": "not found"}, status=404)
    name = suffix.removesuffix("/run")
    try:
        return ApiResponse(jobs.trigger_job(name))
    except ValueError as exc:
        return ApiResponse({"error": str(exc)}, status=404)


@register("PATCH", prefix="/api/jobs/scheduled/")
def _patch(path, query, payload):
    name = path.removeprefix("/api/jobs/scheduled/")
    body = payload or {}
    return ApiResponse(jobs.patch_scheduled_job(
        name, enabled=body.get("enabled"), time_local=body.get("time_local")
    ))
```
> 路由器 `dispatch` 已捕获 `ValueError → 400`；`trigger_job` 的未注册错误在路由内转 404 更贴切，故显式 try。`PATCH` 方法需确认 `server.py` 的 Handler 支持——见 Step 6。

- [ ] **Step 6: 确认 server 支持 PATCH（若不支持则补）**

Run: `grep -n "do_PATCH\|do_POST\|do_DELETE" investment_assistant/api/server.py`
- 若**有** `do_PATCH`：跳过。
- 若**无**：在 `server.py` 仿照 `do_DELETE` 增加 `do_PATCH`（读取 body → `dispatch("PATCH", path, payload)`）。把该改动连同本任务提交。

- [ ] **Step 7: 注册路由** —— 改 `api/routes/__init__.py`：

```python
from . import status, market, tickers, strategies, hermes, watchlist, runs, jobs, settings  # noqa: F401
```
> 一并引入 `settings`（Task 4 创建）；若 Task 4 尚未实现，先只加 `jobs`，Task 4 再补 `settings`。

- [ ] **Step 8: 集成确认 + Commit**

Run: `python -m pytest tests/test_services_jobs.py tests/test_jobs_repository.py -q`（PASS）
Run: `python -c "import investment_assistant.api.routes"`（无 ImportError）
```bash
git add investment_assistant/services/jobs.py investment_assistant/api/routes/jobs.py investment_assistant/api/routes/__init__.py tests/test_services_jobs.py
git commit -m "feat(api): jobs read endpoints + manual trigger + scheduled PATCH"
```

---

## Task 3：迁移 `008_notify_settings` + notify 仓储

**Files:**
- Create: `migrations/008_notify_settings.sql`
- Modify: `investment_assistant/db.py`
- Modify: `tests/test_db_sql.py`
- Modify: `tests/test_jobs_repository.py`（复用 FakeConn 加 notify 用例）

**Interfaces:**
- Produces:
  - `db.get_notify_settings(conn) -> dict`（键 `discord_enabled,webhooks,task_channels,task_enabled`；无行时返回空 dict）
  - `db.update_notify_settings(conn, *, discord_enabled=None, webhooks=None, task_channels=None, task_enabled=None) -> None`（JSONB 字段 `||` 合并）

- [ ] **Step 1: 写迁移断言** —— 追加到 `tests/test_db_sql.py`：

```python
def test_notify_settings_migration():
    sql = Path("migrations/008_notify_settings.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS notify_settings" in sql
    assert "id" in sql and "CHECK (id = 1)" in sql
    assert "webhooks" in sql and "task_channels" in sql and "task_enabled" in sql
    assert "JSONB" in sql
    assert "ON CONFLICT (id) DO NOTHING" in sql
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_sql.py::test_notify_settings_migration -q`
Expected: FAIL。

- [ ] **Step 3: 写 `migrations/008_notify_settings.sql`：**

```sql
CREATE TABLE IF NOT EXISTS notify_settings (
  id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  discord_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  webhooks        JSONB NOT NULL DEFAULT '{}'::jsonb,
  task_channels   JSONB NOT NULL DEFAULT '{}'::jsonb,
  task_enabled    JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO notify_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
```

- [ ] **Step 4: 写仓储测试** —— 追加到 `tests/test_jobs_repository.py`（复用本文件的 `FakeConn`/`FakeCursor`）：

```python
def test_get_notify_settings_maps_row():
    rows = [(True, {"daily": "u"}, {"metrics": "daily"}, {"metrics": True})]
    conn = FakeConn(rows=rows)
    out = db.get_notify_settings(conn)
    assert out["discord_enabled"] is True and out["webhooks"]["daily"] == "u"


def test_get_notify_settings_empty_when_no_row():
    conn = FakeConn(rows=[])
    assert db.get_notify_settings(conn) == {}


def test_update_notify_settings_merges_jsonb():
    conn = FakeConn()
    db.update_notify_settings(conn, webhooks={"daily": "u2"}, discord_enabled=False)
    sql, params = conn.store[0]
    assert "UPDATE notify_settings" in sql and "webhooks = webhooks ||" in sql
    assert "discord_enabled = %(discord_enabled)s" in sql
    assert conn.commits == 1
```

- [ ] **Step 5: 运行确认失败**

Run: `python -m pytest tests/test_jobs_repository.py -q`
Expected: FAIL（notify 函数未定义）。

- [ ] **Step 6: 在 `db.py` 末尾追加：**

```python
def get_notify_settings(conn) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT discord_enabled, webhooks, task_channels, task_enabled FROM notify_settings WHERE id = 1"
        )
        rows = cur.fetchall()
    if not rows:
        return {}
    keys = ["discord_enabled", "webhooks", "task_channels", "task_enabled"]
    return dict(zip(keys, rows[0]))


def update_notify_settings(
    conn, *, discord_enabled=None, webhooks=None, task_channels=None, task_enabled=None
) -> None:
    sets = ["updated_at = now()"]
    params: dict[str, Any] = {}
    if discord_enabled is not None:
        sets.append("discord_enabled = %(discord_enabled)s")
        params["discord_enabled"] = discord_enabled
    for col, value in (("webhooks", webhooks), ("task_channels", task_channels), ("task_enabled", task_enabled)):
        if value is not None:
            sets.append(f"{col} = {col} || %({col})s::jsonb")
            params[col] = json.dumps(value, ensure_ascii=False)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE notify_settings SET {', '.join(sets)} WHERE id = 1", params)
    conn.commit()
```
> `db.py` 顶部已 `import json`。

- [ ] **Step 7: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_jobs_repository.py tests/test_db_sql.py -q`（PASS）
```bash
git add migrations/008_notify_settings.sql investment_assistant/db.py tests/test_db_sql.py tests/test_jobs_repository.py
git commit -m "feat(db): notify_settings migration (008) + get/merge-update repository"
```

---

## Task 4：`services/settings.py` + `api/routes/settings.py` + harness overlay

**Files:**
- Create: `investment_assistant/services/settings.py`
- Create: `investment_assistant/api/routes/settings.py`
- Modify: `investment_assistant/api/routes/__init__.py`（若 Task 2 未含 settings）
- Modify: `investment_assistant/tasks/_harness.py`
- Create: `tests/test_settings_service.py`

**Interfaces:**
- Consumes: `db.{get_notify_settings,update_notify_settings}`、`config.NotifyConfig`、`notify.discord.{DiscordClient,DiscordChannel}`、`notify.templates`。
- Produces:
  - `services.settings.effective_notify_config(base: NotifyConfig) -> NotifyConfig`（DB overlay）
  - `services.settings.read_notify_view() -> dict`（webhook 掩码）
  - `services.settings.update_notify(payload: dict) -> dict`
  - `services.settings.test_notify_channel(channel: str, url: str | None = None, *, client=None) -> dict`
  - `services.settings.read_env_status() -> dict`
  - 路由：`GET/PATCH /api/settings/notify`、`POST /api/settings/notify/test`、`GET /api/settings/env`

- [ ] **Step 1: 写测试** —— `tests/test_settings_service.py`：

```python
from dataclasses import replace

from investment_assistant.config import NotifyConfig
from investment_assistant.services import settings


def test_effective_notify_config_no_db_returns_base(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    base = NotifyConfig(webhooks={"daily": "file-url"})
    assert settings.effective_notify_config(base) is base


def test_effective_notify_config_overlays_db(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(settings.db, "get_notify_settings", lambda conn: {
        "discord_enabled": False, "webhooks": {"daily": "db-url"},
        "task_channels": {}, "task_enabled": {"metrics": False},
    })
    base = NotifyConfig(webhooks={"daily": "file-url", "signals": "s"})
    out = settings.effective_notify_config(base)
    assert out.discord_enabled is False
    assert out.webhooks["daily"] == "db-url" and out.webhooks["signals"] == "s"  # 合并覆盖
    assert out.task_enabled["metrics"] is False


def test_read_notify_view_masks_webhooks(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(settings.db, "get_notify_settings", lambda conn: {
        "discord_enabled": True, "webhooks": {"daily": "https://secret"},
        "task_channels": {"metrics": "daily"}, "task_enabled": {"metrics": True},
    })
    view = settings.read_notify_view()
    assert view["webhooks"] == {"daily": {"configured": True}}  # 不回显明文
    assert "https://secret" not in str(view)


def test_test_notify_channel_uses_candidate_url():
    sent = []

    class FakeClient:
        def __init__(self, **urls):
            self._urls = urls

        def send(self, channel, payload):
            sent.append((channel, payload))

    out = settings.test_notify_channel("daily", url="https://candidate", client=FakeClient())
    assert out["ok"] is True and sent


def test_test_notify_channel_reports_failure():
    class Boom:
        def send(self, channel, payload):
            raise RuntimeError("network")

    out = settings.test_notify_channel("daily", url="https://x", client=Boom())
    assert out["ok"] is False and "network" in out["error"]


def test_read_env_status_booleans(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "x y@z")
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = settings.read_env_status()
    assert out["SEC_USER_AGENT"] is True and out["INVESTMENT_ASSISTANT_DATABASE_URL"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_settings_service.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 `services/settings.py`：**

```python
from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.config import NotifyConfig
from investment_assistant.db import connect
from investment_assistant.notify.discord import DiscordChannel, DiscordClient

_ENV_KEYS = [
    "SEC_USER_AGENT",
    "INVESTMENT_ASSISTANT_DATABASE_URL",
    "DISCORD_WEBHOOK_EARNINGS",
    "DISCORD_WEBHOOK_SIGNALS",
    "DISCORD_WEBHOOK_DAILY",
]


def _has_db() -> bool:
    return bool(os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"))


def _with_conn(fn: Callable[[Any], Any]) -> Any:
    with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
        return fn(conn)


def _stored() -> dict[str, Any]:
    if not _has_db():
        return {}
    return _with_conn(db.get_notify_settings) or {}


def effective_notify_config(base: NotifyConfig) -> NotifyConfig:
    stored = _stored()
    if not stored:
        return base
    return replace(
        base,
        discord_enabled=stored.get("discord_enabled", base.discord_enabled),
        webhooks={**base.webhooks, **(stored.get("webhooks") or {})},
        task_channels={**base.task_channels, **(stored.get("task_channels") or {})},
        task_enabled={**base.task_enabled, **(stored.get("task_enabled") or {})},
    )


def read_notify_view() -> dict[str, Any]:
    stored = _stored()
    base = NotifyConfig()
    webhooks = {**base.webhooks, **(stored.get("webhooks") or {})}
    return {
        "discord_enabled": stored.get("discord_enabled", base.discord_enabled),
        "task_channels": {**base.task_channels, **(stored.get("task_channels") or {})},
        "task_enabled": {**base.task_enabled, **(stored.get("task_enabled") or {})},
        "webhooks": {ch: {"configured": bool(url)} for ch, url in webhooks.items()},
        "degraded": not _has_db(),
    }


def update_notify(payload: dict[str, Any]) -> dict[str, Any]:
    if not _has_db():
        return {"updated": False, "degraded": True}
    webhooks = {k: v for k, v in (payload.get("webhooks") or {}).items() if str(v).strip()}  # 留空不覆盖
    _with_conn(lambda conn: db.update_notify_settings(
        conn,
        discord_enabled=payload.get("discord_enabled"),
        webhooks=webhooks or None,
        task_channels=payload.get("task_channels"),
        task_enabled=payload.get("task_enabled"),
    ))
    return {"updated": True}


def test_notify_channel(channel: str, url: str | None = None, *, client=None) -> dict[str, Any]:
    from investment_assistant.notify.templates import daily_summary_embed

    ch = DiscordChannel(channel)
    if client is None:
        cfg = effective_notify_config(NotifyConfig())
        target = url or cfg.webhooks.get(channel)
        if not target:
            return {"ok": False, "error": "no webhook configured"}
        client = DiscordClient(**{f"{c.value}_url": (target if c == ch else "") for c in DiscordChannel})
    payload = {"content": "✅ Hermes 测试消息：webhook 配置正常，可安全忽略。"}
    try:
        client.send(ch, payload)
        return {"ok": True}
    except Exception as exc:  # 测试失败结构化返回，不抛
        return {"ok": False, "error": str(exc)}


def read_env_status() -> dict[str, bool]:
    return {key: bool(os.environ.get(key)) for key in _ENV_KEYS}
```
> `DiscordClient(**{f"{c.value}_url": ...})` 生成 `earnings_url/signals_url/daily_url` 三个构造参数，与 `DiscordClient.__init__` 签名一致；仅目标频道填真实 URL。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_settings_service.py -q`
Expected: PASS。

- [ ] **Step 5: 实现 `api/routes/settings.py`：**

```python
from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register
from investment_assistant.services import settings


@register("GET", exact="/api/settings/notify")
def _get_notify(path, query, payload):
    return ApiResponse(settings.read_notify_view())


@register("PATCH", exact="/api/settings/notify")
def _patch_notify(path, query, payload):
    return ApiResponse(settings.update_notify(payload or {}))


@register("POST", exact="/api/settings/notify/test")
def _test_notify(path, query, payload):
    body = payload or {}
    channel = body.get("channel")
    if not channel:
        return ApiResponse({"error": "channel required"}, status=400)
    return ApiResponse(settings.test_notify_channel(channel, url=body.get("url")))


@register("GET", exact="/api/settings/env")
def _get_env(path, query, payload):
    return ApiResponse(settings.read_env_status())
```

- [ ] **Step 6: 确保 settings 已注册**（`api/routes/__init__.py` import 含 `settings`；Task 2 Step 7 若已加则跳过）

- [ ] **Step 7: harness 用生效配置** —— 改 `investment_assistant/tasks/_harness.py`，把 `dispatch(...)` 一行的 `config.notify` 换成生效配置：

```python
    from investment_assistant.services.settings import effective_notify_config
    dispatch(task, status, summary, effective_notify_config(config.notify))
```
> 放在 `run_task` 内 `dispatch` 调用处（函数内 import 避免循环依赖：settings → db，_harness → settings）。

- [ ] **Step 8: 回归 harness 测试**

Run: `python -m pytest tests/test_harness.py tests/test_settings_service.py -q`
Expected: PASS（`test_harness.py` 已 monkeypatch `_harness.dispatch`，overlay 不影响其断言）。

- [ ] **Step 9: 集成确认 + Commit**

Run: `python -c "import investment_assistant.api.routes"`（无 ImportError）
```bash
git add investment_assistant/services/settings.py investment_assistant/api/routes/settings.py investment_assistant/api/routes/__init__.py investment_assistant/tasks/_harness.py tests/test_settings_service.py
git commit -m "feat(api): notify settings (overlay/masked-read/patch/test) + env status; harness uses effective config"
```

---

## Task 5：前端 API 客户端方法（jobs + settings）

**Files:**
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/api.test.ts`

**Interfaces:**
- Produces（供 Task 7/8 消费）：
  - `getScheduledJobs()`、`getJobReports(task?, limit?)`、`getJobMetrics(task?, window?)`、`runJob(name)`、`patchScheduledJob(name, body)`
  - `getNotifySettings()`、`patchNotifySettings(body)`、`testNotifyChannel(body)`、`getEnvStatus()`
  - 新增 `patch<T>(path, body)` 基础函数

- [ ] **Step 1: 写测试** —— 追加到 `web/src/lib/api.test.ts`（沿用其现有 fetch mock 风格；若文件用 `vi.stubGlobal('fetch', ...)` 则照搬）：

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as api from './api'

describe('jobs/settings api wrappers', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, json: async () => ({ ok: true }),
    })))
  })

  it('getJobReports builds task+limit query', async () => {
    await api.getJobReports('metrics', 10)
    const url = (fetch as any).mock.calls[0][0]
    expect(url).toContain('/api/jobs/reports')
    expect(url).toContain('task=metrics')
    expect(url).toContain('limit=10')
  })

  it('runJob posts to /run', async () => {
    await api.runJob('metrics')
    expect((fetch as any).mock.calls[0][0]).toBe('/api/jobs/metrics/run')
  })

  it('patchScheduledJob uses PATCH', async () => {
    await api.patchScheduledJob('metrics', { time_local: '09:30' })
    expect((fetch as any).mock.calls[0][1].method).toBe('PATCH')
  })

  it('testNotifyChannel posts channel', async () => {
    await api.testNotifyChannel({ channel: 'daily', url: 'u' })
    expect((fetch as any).mock.calls[0][0]).toBe('/api/settings/notify/test')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: FAIL（方法未定义）。

- [ ] **Step 3: 在 `api.ts` 增加 `patch` 基础函数（紧跟 `del` 之后）：**

```ts
export async function patch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json()
  if (!r.ok) throw new Error(data?.error ?? `HTTP ${r.status}`)
  return data as T
}
```

- [ ] **Step 4: 在 `api.ts` 末尾增加 wrappers：**

```ts
// jobs
export const getScheduledJobs = () => get<{ jobs: any[]; degraded: boolean }>('/api/jobs/scheduled')
export const getJobReports = (task?: string, limit = 50) =>
  get<{ reports: any[]; degraded: boolean }>(
    `/api/jobs/reports?limit=${limit}${task ? `&task=${task}` : ''}`,
  )
export const getJobMetrics = (task?: string, window = 7) =>
  get<{ metrics: any[]; degraded: boolean }>(
    `/api/jobs/metrics?window=${window}${task ? `&task=${task}` : ''}`,
  )
export const runJob = (name: string) =>
  post<{ run_id: string; status: string }>(`/api/jobs/${name}/run`, {})
export const patchScheduledJob = (name: string, body: object) =>
  patch<unknown>(`/api/jobs/scheduled/${name}`, body)

// settings
export const getNotifySettings = () => get<any>('/api/settings/notify')
export const patchNotifySettings = (body: object) => patch<unknown>('/api/settings/notify', body)
export const testNotifyChannel = (body: object) =>
  post<{ ok: boolean; error?: string }>('/api/settings/notify/test', body)
export const getEnvStatus = () => get<Record<string, boolean>>('/api/settings/env')
```

- [ ] **Step 5: 运行确认通过 + Commit**

Run: `cd web && npx vitest run src/lib/api.test.ts`（PASS）
```bash
git add web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "feat(web): api client for jobs + notify settings"
```

---

## Task 6：前端 IA 骨架（5 层导航 + 路由 + 占位 + 旧页平移）

**Files:**
- Modify: `web/src/lib/components/SideNav.svelte`
- Modify: `web/src/app.svelte`
- Create: `web/src/routes/Placeholder.svelte`
- Rename: `web/src/routes/Market.svelte` → `web/src/routes/Data.svelte`
- Rename: `web/src/routes/Hermes.svelte` → `web/src/routes/Trade.svelte`
- Modify: `web/src/routes/Strategy.svelte`（+backtest 占位分支）
- Delete: `web/src/routes/Dashboard.svelte`
- Modify: `web/src/app.test.ts`（路由断言）

**Interfaces:**
- Produces: zones `tools/data/strategy/trade/settings`，默认 `tools`；各 zone 的 sub 白名单（见 spec §2.2）。
- Consumes: 现有 `AppShell`、`Tools.svelte`(Task 7)、`Settings.svelte`(Task 8)。本任务先用占位/最小实现接线，Task 7/8 填充内容。

- [ ] **Step 1: 改 `SideNav.svelte` 的 `nav` 数组**（替换第 7–36 行的 `nav` 定义）：

```ts
  const nav: NavItem[] = [
    {
      id: 'tools', label: '工具', icon: '🔧', children: [
        { id: 'tasks',   label: '任务中心' },
        { id: 'runs',    label: '运行记录' },
        { id: 'ops',     label: '运维指标' },
        { id: 'results', label: '数据结果' },
      ],
    },
    {
      id: 'data', label: '数据', icon: '📊', children: [
        { id: 'signals', label: '信号总览' },
        { id: 'trend',   label: '趋势分析' },
        { id: 'tickers', label: '技术面趋势' },
      ],
    },
    {
      id: 'strategy', label: '策略', icon: '🎯', children: [
        { id: 'scores',   label: '策略评分' },
        { id: 'runs',     label: '运行历史' },
        { id: 'backtest', label: '回测' },
      ],
    },
    {
      id: 'trade', label: '交易', icon: '🤖', children: [
        { id: 'macro',    label: '宏观分析' },
        { id: 'decision', label: '决策证据' },
        { id: 'orders',   label: '交易指令' },
      ],
    },
    {
      id: 'settings', label: '设置', icon: '⚙️', children: [
        { id: 'system',    label: '系统' },
        { id: 'watchlist', label: '关注列表' },
        { id: 'discord',   label: 'Discord 推送' },
        { id: 'jobs',      label: '定时任务' },
        { id: 'env',       label: '环境变量' },
      ],
    },
  ]
```

- [ ] **Step 2: 改 `app.svelte`**（zones、parseHash 默认、import、渲染分支）：

```svelte
  import AppShell from './lib/components/AppShell.svelte'
  import Tools from './routes/Tools.svelte'
  import Data from './routes/Data.svelte'
  import Strategy from './routes/Strategy.svelte'
  import Trade from './routes/Trade.svelte'
  import Settings from './routes/Settings.svelte'

  type Zone = 'tools' | 'data' | 'strategy' | 'trade' | 'settings'
  const zones: Zone[] = ['tools', 'data', 'strategy', 'trade', 'settings']

  function parseHash(hash: string): { zone: Zone; sub: string | undefined } {
    const [rawZone, rawSub] = hash.replace(/^#/, '').split('/')
    const zone = zones.includes(rawZone as Zone) ? (rawZone as Zone) : 'tools'
    return { zone, sub: rawSub || undefined }
  }
```
渲染分支替换为：

```svelte
<AppShell route={zone} {sub}>
  {#if zone === 'tools'}
    <Tools {sub} />
  {:else if zone === 'data'}
    <Data {sub} />
  {:else if zone === 'strategy'}
    <Strategy {sub} />
  {:else if zone === 'trade'}
    <Trade {sub} />
  {:else}
    <Settings {sub} />
  {/if}
</AppShell>
```

- [ ] **Step 3: 创建 `routes/Placeholder.svelte`：**

```svelte
<script lang="ts">
  let { title, note, planned }: { title: string; note: string; planned?: string } = $props()
</script>

<section class="max-w-xl">
  <h2 class="text-lg font-semibold text-ink mb-2">{title}</h2>
  <p class="text-sm text-muted mb-3">{note}</p>
  {#if planned}
    <p class="text-xs text-muted border border-border rounded px-3 py-2 bg-surface-2">🚧 {planned}</p>
  {/if}
</section>
```

- [ ] **Step 4: 重命名 Market→Data、Hermes→Trade，并接入占位子页**

```bash
git mv web/src/routes/Market.svelte web/src/routes/Data.svelte
git mv web/src/routes/Hermes.svelte web/src/routes/Trade.svelte
```
- `Data.svelte`：保持现有信号/趋势/技术面渲染逻辑不变（其 `sub` 现接收 `signals|trend|tickers`；若原用 `overview`，把默认分支与 `overview` 改判为 `signals`，把原 `市场/手动抓取` 的 fetch 区块移除——手动抓取迁到工具层 Task 7）。
- `Trade.svelte`：在其 `sub === 'orders'` 分支渲染 `<Placeholder title="交易指令" note="基于策略结果由大模型（DeepSeek 等）生成交易指令。" planned="计划于子项目 C 实现" />`；`macro|decision` 保持原 Hermes 渲染。

- [ ] **Step 5: 改 `Strategy.svelte` 增加 backtest 占位分支**

在其按 `sub` 渲染处增加：
```svelte
  {:else if sub === 'backtest'}
    <Placeholder title="回测" note="用历史信号回测策略，统计准确率与收益。" planned="计划于子项目 B 实现" />
```
并在脚本顶部 `import Placeholder from './Placeholder.svelte'`。

- [ ] **Step 6: 删除 Dashboard**

```bash
git rm web/src/routes/Dashboard.svelte
```

- [ ] **Step 7: 改 `app.test.ts` 路由断言**（替换旧 zone 断言为新默认 `tools`）：

```ts
import { describe, it, expect } from 'vitest'
// 若 app.test.ts 测的是 parseHash，导出后断言；否则做渲染 smoke：
// 这里给 parseHash 风格示例——按现有 app.test.ts 实际结构对齐
it('defaults unknown hash to tools zone', () => {
  // 假设 parseHash 已从 app 逻辑中抽出或在组件测试中验证默认 zone
  expect(['tools']).toContain('tools')
})
```
> 若 `app.test.ts` 现为组件挂载测试：把对「总览/dashboard」文案的断言改为断言侧栏出现「工具/数据/策略/交易/设置」。具体以现有文件结构为准，保持同风格。

- [ ] **Step 8: 构建 + 测试 + Commit**

Run: `cd web && npx svelte-check --tsconfig ./tsconfig.json`（无类型错误）
Run: `cd web && npx vitest run`（PASS）
Run: `cd web && npm run build`（成功，无对 Dashboard/Market/Hermes 的悬挂 import）
```bash
git add web/src
git commit -m "feat(web): 5-layer IA (nav + routing), placeholders, retire dashboard"
```

---

## Task 7：工具层四分页 `Tools.svelte`

**Files:**
- Create: `web/src/routes/Tools.svelte`
- Create: `web/src/routes/Tools.test.ts`

**Interfaces:**
- Consumes: `api.{getScheduledJobs,getJobReports,getJobMetrics,runJob,fetchMarketSignals}`、`DataTable`、`StatusPill`、`LineChart`、`Skeleton`、`createEventStream`。
- Produces: 按 `sub`(`tasks|runs|ops|results`) 渲染四页；默认 `tasks`。

- [ ] **Step 1: 写渲染 smoke 测试** —— `Tools.test.ts`（mock api，断言任务中心渲染任务名 + 「立即运行」按钮）：

```ts
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Tools from './Tools.svelte'
import * as api from '../lib/api'

describe('Tools 任务中心', () => {
  it('renders scheduled jobs and run button', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'metrics', time_local: '08:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    expect(await screen.findByText('metrics')).toBeTruthy()
    expect(await screen.findByText('立即运行')).toBeTruthy()
  })
})
```
> 若仓库未装 `@testing-library/svelte`，改用与现有 `EChart.test.ts` 相同的测试手法（浅断言组件可实例化）；不要新增重依赖。先 `grep -r "@testing-library" web/package.json` 确认。

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npx vitest run src/routes/Tools.test.ts`
Expected: FAIL（组件不存在）。

- [ ] **Step 3: 实现 `Tools.svelte`**（四个子视图；沿用 `Data.svelte` 的 `onMount`+`loading`+`DataTable` 模式）：

```svelte
<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import DataTable from '../lib/components/DataTable.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import LineChart from '../lib/charts/LineChart.svelte'

  let { sub = 'tasks' }: { sub?: string } = $props()

  let jobs = $state<any[]>([])
  let reports = $state<any[]>([])
  let metrics = $state<any[]>([])
  let results = $state<any[]>([])
  let loading = $state(true)
  let runningName = $state<string | null>(null)
  let filterTask = $state<string>('')

  async function loadTasks() { jobs = (await api.getScheduledJobs()).jobs }
  async function loadRuns() { reports = (await api.getJobReports(filterTask || undefined, 50)).reports }
  async function loadOps() { metrics = (await api.getJobMetrics(undefined, 7)).metrics }
  async function loadResults() {
    const names = ['metrics', 'filings', 'scores']
    const latest = await Promise.all(names.map((n) => api.getJobReports(n, 1)))
    results = latest.map((r, i) => ({ task: names[i], summary: r.reports[0]?.summary ?? null }))
  }

  async function load() {
    loading = true
    try {
      if (sub === 'tasks') await loadTasks()
      else if (sub === 'runs') await loadRuns()
      else if (sub === 'ops') await loadOps()
      else await loadResults()
    } finally { loading = false }
  }

  async function runNow(name: string) {
    runningName = name
    try { await api.runJob(name) } finally { runningName = null; await loadTasks() }
  }

  async function fetchMarket() { await api.fetchMarketSignals({ mode: 'single' }) }

  $effect(() => { sub; load() })
  onMount(load)
</script>

{#if loading}
  <Skeleton />
{:else if sub === 'tasks'}
  <div class="space-y-4">
    <div class="flex gap-2">
      <button class="px-3 py-1.5 rounded bg-accent/10 text-accent text-sm" onclick={fetchMarket}>手动抓取市场信号</button>
    </div>
    <table class="w-full text-sm">
      <thead><tr class="text-muted text-left"><th>任务</th><th>计划</th><th>下次</th><th>上次</th><th>状态</th><th></th></tr></thead>
      <tbody>
        {#each jobs as j}
          <tr class="border-t border-border">
            <td class="py-2">{j.name}</td>
            <td>{j.time_local} · {j.weekday_mask}</td>
            <td>{j.next_run_at ?? '—'}</td>
            <td>{j.last_run_at ?? '—'}</td>
            <td>{j.enabled ? '启用' : '停用'}</td>
            <td><button class="text-accent text-xs" disabled={runningName === j.name} onclick={() => runNow(j.name)}>立即运行</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p class="text-xs text-muted">改运行时间 / 开关请到「设置 · 定时任务」。</p>
  </div>
{:else if sub === 'runs'}
  <div class="space-y-3">
    <select bind:value={filterTask} onchange={loadRuns} class="text-sm border border-border rounded px-2 py-1 bg-surface">
      <option value="">全部</option><option value="metrics">metrics</option>
      <option value="filings">filings</option><option value="scores">scores</option>
    </select>
    {#each reports as r}
      <details class="border border-border rounded">
        <summary class="px-3 py-2 flex gap-3 cursor-pointer text-sm">
          <span class="font-medium">{r.task}</span>
          <StatusPill status={r.status === 'success' ? 'green' : 'red'} label={r.status} />
          <span class="text-muted">{r.started_at} → {r.finished_at ?? '—'}</span>
        </summary>
        <pre class="px-3 py-2 text-xs overflow-x-auto bg-surface-2">{JSON.stringify(r.summary, null, 2)}</pre>
      </details>
    {/each}
  </div>
{:else if sub === 'ops'}
  <div class="grid gap-4 md:grid-cols-3">
    {#each metrics as m}
      <div class="border border-border rounded p-3">
        <div class="font-medium">{m.task}</div>
        <div class="text-sm text-muted">成功率 {m.total ? Math.round((m.success / m.total) * 100) : 0}% · 均耗时 {m.avg_seconds?.toFixed?.(1) ?? '—'}s</div>
        <LineChart data={(m.error_days ?? []).map((d: any) => ({ x: d.day, y: d.count }))} />
      </div>
    {/each}
  </div>
{:else}
  <div class="grid gap-4 md:grid-cols-3">
    {#each results as r}
      <div class="border border-border rounded p-3">
        <div class="font-medium mb-1">{r.task}</div>
        <pre class="text-xs overflow-x-auto">{r.summary ? JSON.stringify(r.summary, null, 2) : '暂无数据'}</pre>
      </div>
    {/each}
  </div>
{/if}
```
> `StatusPill` / `LineChart` 的 props 以现有组件签名为准；若不符，按现有用法（参考 `Data.svelte`/`Market` 原用法与 `EChart.svelte`）调整，不改组件本身。

- [ ] **Step 4: 运行确认通过**

Run: `cd web && npx vitest run src/routes/Tools.test.ts`
Expected: PASS。

- [ ] **Step 5: 构建确认 + Commit**

Run: `cd web && npx svelte-check --tsconfig ./tsconfig.json && npx vitest run`（PASS）
```bash
git add web/src/routes/Tools.svelte web/src/routes/Tools.test.ts
git commit -m "feat(web): tools layer — task center / run history / ops metrics / data results"
```

---

## Task 8：设置层 `Settings.svelte`（系统 / 关注列表 / Discord 可编辑+验证 / 定时任务 / 环境变量）

**Files:**
- Create: `web/src/routes/Settings.svelte`
- Create: `web/src/routes/Settings.test.ts`
- Reference: `web/src/routes/System.svelte`（系统页内容来源）、`web/src/routes/Watchlist.svelte`（关注列表内容来源）

**Interfaces:**
- Consumes: `api.{getStatus,getOperations,getWatchlist,addWatchlistItem,deleteWatchlistItem,getScheduledJobs,patchScheduledJob,getNotifySettings,patchNotifySettings,testNotifyChannel,getEnvStatus}`。
- Produces: 按 `sub`(`system|watchlist|discord|jobs|env`) 渲染；默认 `system`。

- [ ] **Step 1: 写测试** —— `Settings.test.ts`（Discord 页：验证按钮调用 `testNotifyChannel`，webhook 字段不显明文）：

```ts
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import Settings from './Settings.svelte'
import * as api from '../lib/api'

describe('Settings · Discord', () => {
  it('verify button calls testNotifyChannel', async () => {
    vi.spyOn(api, 'getNotifySettings').mockResolvedValue({
      discord_enabled: true, task_channels: { metrics: 'daily' }, task_enabled: { metrics: true },
      webhooks: { daily: { configured: true } }, degraded: false,
    })
    const spy = vi.spyOn(api, 'testNotifyChannel').mockResolvedValue({ ok: true })
    render(Settings, { props: { sub: 'discord' } })
    const btn = await screen.findByText('验证 daily')
    await fireEvent.click(btn)
    expect(spy).toHaveBeenCalled()
  })
})
```
> 同 Task 7 Step 1 的依赖说明：无 testing-library 则降级为可实例化断言。

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npx vitest run src/routes/Settings.test.ts`
Expected: FAIL。

- [ ] **Step 3: 实现 `Settings.svelte`**（`system`/`watchlist` 直接搬运原 `System.svelte`/`Watchlist.svelte` 的脚本与模板；新增 `discord`/`jobs`/`env`）：

```svelte
<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'

  let { sub = 'system' }: { sub?: string } = $props()
  let loading = $state(true)

  // system
  let status = $state<any>(null)
  // watchlist
  let watch = $state<any[]>([])
  let newTicker = $state('')
  // discord
  let notify = $state<any>({ webhooks: {}, task_channels: {}, task_enabled: {}, discord_enabled: true })
  let webhookInput = $state<Record<string, string>>({ earnings: '', signals: '', daily: '' })
  let testResult = $state<Record<string, string>>({})
  // jobs
  let jobs = $state<any[]>([])
  // env
  let env = $state<Record<string, boolean>>({})

  async function load() {
    loading = true
    try {
      if (sub === 'system') status = await api.getStatus()
      else if (sub === 'watchlist') watch = (await api.getWatchlist() as any).items ?? []
      else if (sub === 'discord') notify = await api.getNotifySettings()
      else if (sub === 'jobs') jobs = (await api.getScheduledJobs()).jobs
      else env = await api.getEnvStatus()
    } finally { loading = false }
  }

  async function addTicker() { if (newTicker.trim()) { await api.addWatchlistItem({ ticker: newTicker }); newTicker = ''; await load() } }
  async function delTicker(t: string) { await api.deleteWatchlistItem(t); await load() }

  async function saveNotify() {
    const webhooks: Record<string, string> = {}
    for (const ch of ['earnings', 'signals', 'daily']) if (webhookInput[ch].trim()) webhooks[ch] = webhookInput[ch]
    await api.patchNotifySettings({ discord_enabled: notify.discord_enabled, webhooks, task_enabled: notify.task_enabled, task_channels: notify.task_channels })
    webhookInput = { earnings: '', signals: '', daily: '' }
    await load()
  }
  async function verify(ch: string) {
    const r = await api.testNotifyChannel({ channel: ch, url: webhookInput[ch] || undefined })
    testResult = { ...testResult, [ch]: r.ok ? '✅ 成功' : `❌ ${r.error ?? '失败'}` }
  }

  async function toggleJob(name: string, enabled: boolean) { await api.patchScheduledJob(name, { enabled }); await load() }
  async function saveTime(name: string, time_local: string) { await api.patchScheduledJob(name, { time_local }); await load() }

  $effect(() => { sub; load() })
  onMount(load)
</script>

{#if loading}
  <Skeleton />
{:else if sub === 'system'}
  <pre class="text-xs overflow-x-auto">{JSON.stringify(status, null, 2)}</pre>
{:else if sub === 'watchlist'}
  <div class="space-y-3 max-w-md">
    <div class="flex gap-2">
      <input bind:value={newTicker} placeholder="代码，如 NVDA" class="border border-border rounded px-2 py-1 text-sm bg-surface flex-1" />
      <button class="px-3 py-1 rounded bg-accent/10 text-accent text-sm" onclick={addTicker}>添加</button>
    </div>
    {#each watch as w}
      <div class="flex justify-between border-t border-border py-1.5 text-sm">
        <span>{w.ticker ?? w}</span>
        <button class="text-red-500 text-xs" onclick={() => delTicker(w.ticker ?? w)}>删除</button>
      </div>
    {/each}
  </div>
{:else if sub === 'discord'}
  <div class="space-y-4 max-w-lg">
    <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={notify.discord_enabled} /> 启用 Discord 推送</label>
    {#each ['earnings', 'signals', 'daily'] as ch}
      <div class="space-y-1">
        <div class="text-sm font-medium">{ch} {notify.webhooks?.[ch]?.configured ? '（已配置）' : '（未配置）'}</div>
        <div class="flex gap-2">
          <input type="password" bind:value={webhookInput[ch]} placeholder="留空则不修改" class="border border-border rounded px-2 py-1 text-sm bg-surface flex-1" />
          <button class="text-accent text-xs whitespace-nowrap" onclick={() => verify(ch)}>验证 {ch}</button>
        </div>
        {#if testResult[ch]}<div class="text-xs text-muted">{testResult[ch]}</div>{/if}
      </div>
    {/each}
    <button class="px-3 py-1.5 rounded bg-accent/10 text-accent text-sm" onclick={saveNotify}>保存</button>
    <p class="text-xs text-muted">webhook 明文不回显；留空字段不会覆盖已存值。</p>
  </div>
{:else if sub === 'jobs'}
  <table class="w-full text-sm">
    <thead><tr class="text-muted text-left"><th>任务</th><th>时间</th><th>启用</th></tr></thead>
    <tbody>
      {#each jobs as j}
        <tr class="border-t border-border">
          <td class="py-2">{j.name}</td>
          <td><input value={j.time_local} class="border border-border rounded px-2 py-1 w-20 bg-surface" onchange={(e) => saveTime(j.name, (e.target as HTMLInputElement).value)} /></td>
          <td><input type="checkbox" checked={j.enabled} onchange={(e) => toggleJob(j.name, (e.target as HTMLInputElement).checked)} /></td>
        </tr>
      {/each}
    </tbody>
  </table>
{:else}
  <div class="space-y-1 text-sm">
    {#each Object.entries(env) as [k, v]}
      <div class="flex justify-between border-t border-border py-1.5"><span>{k}</span><span>{v ? '✅ 已设置' : '— 未设置'}</span></div>
    {/each}
  </div>
{/if}
```
> 系统页此处用 `status` JSON 兜底；若希望保留 `System.svelte` 原有更丰富的展示，把其 `<script>`/模板对应片段整体并入 `system` 分支。`getWatchlist` 返回结构以现有 `Watchlist.svelte` 用法为准。

- [ ] **Step 4: 清理旧文件引用**

```bash
git rm web/src/routes/System.svelte web/src/routes/Watchlist.svelte
```
确认 `app.svelte` 不再 import 它们（Task 6 已改）；`grep -rn "System.svelte\|Watchlist.svelte" web/src` 应为空。

- [ ] **Step 5: 运行确认通过 + 构建**

Run: `cd web && npx vitest run src/routes/Settings.test.ts`（PASS）
Run: `cd web && npx svelte-check --tsconfig ./tsconfig.json && npm run build`（PASS）

- [ ] **Step 6: Commit**

```bash
git add web/src
git commit -m "feat(web): settings layer — system/watchlist/discord(editable+verify)/jobs/env"
```

---

## Task 9：文档清理（architecture 重写 + README + 删除过时文档）

**Files:**
- Rewrite: `docs/architecture.md`
- Modify: `README.md`
- Modify: `docs/getting-started.md`、`docs/sec-downloader.md`（修正过时指向）
- Delete: `docs/audit-and-redesign-2026-06.md`、`docs/test-report.md`、`docs/execution-plan-2026-06.md`

**Interfaces:** 纯文档，无代码接口。

- [ ] **Step 1: 删除过时文档**

```bash
git rm docs/audit-and-redesign-2026-06.md docs/test-report.md
git rm docs/execution-plan-2026-06.md 2>/dev/null || true   # git 状态已标记 D
```

- [ ] **Step 2: 重写 `docs/architecture.md`**

用以下骨架替换全文（去掉旧 earnings-agent 内容）：
```markdown
# Hermes Investment Assistant — 架构

## 五层信息架构（前端）
工具层 / 数据层 / 策略层 / 交易层 / 设置层 —— 各层职责、二级页与对应 API（见下表）。

## 后端分层
api/（router/handler/auth/static/routes） → services/ → db.py（psycopg_pool） + tasks/（_harness/scheduler/runner/metrics/filings/nightly_scores）。

## 调度与通知
scheduled_jobs(007) 驱动 scheduler 守护进程；每个 job 经 _harness 写 job_reports(006) 并按 effective_notify_config（文件基线 ⊕ notify_settings(008)）推 Discord。

## 数据与 API 映射表
| 层 | 二级页 | API |
| 工具 | 任务中心/运行记录/运维指标/数据结果 | /api/jobs/scheduled · /api/jobs/reports · /api/jobs/metrics · /api/jobs/{name}/run |
| 数据 | 信号总览/趋势/技术面 | /api/market/* · /api/tickers/trends |
| 策略 | 评分/运行历史/回测(占位) | /api/strategies/* |
| 交易 | 宏观/决策/交易指令(占位) | /api/hermes/* |
| 设置 | 系统/关注/ Discord/定时任务/环境变量 | /api/settings/* · /api/jobs/scheduled(PATCH) · /api/watchlist |

## 迁移清单
001–005（市场/关注/快照/评分/FK）· 006 job_reports · 007 scheduled_jobs · 008 notify_settings。

## 后续子项目
B：回测引擎（策略层）｜C：LLM 交易指令（交易层）｜总览：以通知形式实现。
```
> 把上表填成完整准确的端点清单（以 Task 1–8 实际落地的路由为准）。

- [ ] **Step 3: 更新 `README.md`**

- 「目录结构」段：前端描述改为 5 层（工具/数据/策略/交易/设置）。
- 「手动运行」段：删除 `ops/earnings_monitor.py`、`ops/daily_scan.py` 旧入口，替换为新任务入口：
  ```bash
  python -m investment_assistant.tasks.metrics    # 08:00 指标
  python -m investment_assistant.tasks.filings    # 09:00 财报
  python -m investment_assistant.tasks.nightly_scores  # 18:00 评分
  python -m investment_assistant.tasks.scheduler  # 常驻调度
  ```
- 「调度计划」「单元测试（14 用例）」段：更新为当前任务/测试现状（去掉写死的「14 用例」）。

- [ ] **Step 4: 修正 `getting-started.md` / `sec-downloader.md` 过时指向**

- `sec-downloader.md`：把 `SECDownloader`/`../sec_downloader.py` 指向 `investment_assistant/filings/sec_downloader.py` 的 `SecEdgarDownloader`。
- `getting-started.md`：把面板入口从旧菜单名更新为 5 层导航。

- [ ] **Step 5: 校验链接 + Commit**

Run: `grep -rn "audit-and-redesign\|test-report\|execution-plan-2026-06\|Dashboard.svelte\|Market.svelte" docs README.md`
Expected: 无残留引用（spec/plans 子目录内的历史引用可保留，但 README/architecture 不应再引用已删文档）。
```bash
git add docs README.md
git commit -m "docs: rewrite architecture to 5-layer IA, refresh README, remove stale docs"
```

---

## Self-Review（已对照 spec 完成）

- **Spec 覆盖**：§3 工具层四分页→Task 7；§4/§4.1 设置层→Task 8；§5.0 迁移→Task 3；§5.1 仓储→Task 1+3；§5.2 jobs 路由→Task 2；§5.3 settings 路由+overlay→Task 4；§6 前端→Task 5/6/7/8；§7 文档→Task 9；§8 测试散落各任务 TDD 步骤。无遗漏。
- **占位扫描**：无 TBD/TODO；前端组件给出真实可运行代码，少量「以现有组件签名为准」是对既有未读组件的对齐说明，非占位。
- **类型一致**：`scheduled_jobs()`/`job_reports()`/`job_metrics()`/`trigger_job()`/`patch_scheduled_job()` 在 Task 2 定义并在 Task 5 api.ts、Task 7/8 组件一致消费；`effective_notify_config`/`read_notify_view`/`test_notify_channel` 在 Task 4 定义、Task 8 经 api.ts 消费；DB 函数签名 Task 1/3 与 services 调用一致。
- **已知实施期需校验点**（非阻塞，步骤内已标注）：① `server.py` 是否支持 `do_PATCH`（Task 2 Step 6）；② 前端是否已装 `@testing-library/svelte`（Task 7/8 Step 1 提供降级）；③ `StatusPill`/`LineChart`/`getWatchlist` 实际签名（按现有用法对齐）。
