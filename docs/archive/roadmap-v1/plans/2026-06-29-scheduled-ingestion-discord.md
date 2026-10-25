# 定时采集任务 + pg 调度器 + 可配置 Discord 推送 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 08:30 单体 daily 拆分重构为 `metrics`(08:00)/`filings`(09:00) 两个职责单一的定时任务，配一个自研 postgres 调度守护进程、一张 30 天 TTL 的 `job_reports` 报告表、以及可配置的 Discord 推送层。

**Architecture:** 自研 `tasks/scheduler.py` 守护进程按 `scheduled_jobs`(pg) 表定时触发已注册 job；每个 job 经共享外壳 `tasks/_harness.py` 执行→写 `job_reports`(pg)→按 `NotifyConfig` 经 `notify/notifier.py` 推 Discord。`metrics` 复用现有 market/ticker 服务，`filings` 新建真实 SEC EDGAR 下载器拉昨日新提交财报落盘。systemd 只保活一个常驻 service，取消全部 timer。

**Tech Stack:** Python 3.11、psycopg3 + psycopg_pool、PostgreSQL 16、requests、zoneinfo、pytest。外部源：SEC EDGAR（`SEC_USER_AGENT`）、Discord webhook、yfinance（经现有 market 服务）。

## Global Constraints

- **分支**：从 `main` 切 `feat/scheduled-ingestion-discord`；不主动 push；提交结尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **每个 PR**：新增/改动逻辑有单测；外部调用（SEC/Discord/yfinance/DB）**全部 mock 或注入**，离线可跑；触碰 schema 必带迁移文件，迁移用 `CREATE TABLE IF NOT EXISTS` + `ON CONFLICT DO NOTHING` 幂等。
- **不新增裸 `except Exception` 吞错**：外部失败结构化记录到 `job_reports`/返回，不静默。
- **迁移编号**：本工作占 `006_job_reports`、`007_scheduled_jobs`；原 Phase 2 数据层（`docs/superpowers/plans/2026-06-27-phase2-data-layer.md`）届时顺延为 008 起（Task 9 同步改文档）。
- **优雅降级**：无 `INVESTMENT_ASSISTANT_DATABASE_URL` 时报告/快照路径跳过不崩；无 `SEC_USER_AGENT` 时下载器返回空结果不崩；`NotifyConfig.discord_enabled=False` 或某任务关时不推送。
- **复用既有风格**：DB 写法对齐 `db.upsert_market_signal`（`with conn.cursor() as cur` + 具名参数 + `conn.commit()`）；run_id 形如 `db`/`strategies` 里的 `f"{kind}-{YYYYmmddHHMMSS}-{uuid8}"`。
- **退役单体 daily（本计划范围）**：Task 8 删除 `hermes/daily.py`、`tasks/daily.py`、`ops/hermes_daily.py` 及 `tests/test_hermes_daily.py`、`tests/test_tasks_daily.py`（其功能被 metrics/filings 取代，brief 逻辑删除）。
- **spec**：`docs/superpowers/specs/2026-06-29-scheduled-ingestion-discord-design.md`。

---

## File Structure

```
investment_assistant/
  tasks/
    _harness.py        # 新：run_task 外壳（run_id→执行→job_reports→notifier）
    metrics.py         # 新：08:00 指标任务（market signal + ticker 快照）
    filings.py         # 新：09:00 财报任务（SEC 下载落盘）
    scheduler.py       # 新：自研 pg 调度守护进程（compute_next_run + tick loop + registry）
    nightly_scores.py  # 改：run() 经 _harness 路由（收编为 'scores' job）
  filings/
    __init__.py        # 新
    service.py         # 新：download_configured_filings（满足既存测试 + 默认 since_date=昨日）
    sec_downloader.py  # 新：SecEdgarDownloader（真实 SEC EDGAR submissions + 落盘）
  notify/
    notifier.py        # 新：dispatch（按 NotifyConfig 决定是否/向哪个频道推送）
    discord.py         # 改：DiscordClient.from_config（webhook 覆盖 env）
    templates.py       # 改：metrics_summary_embed / filings_digest_embed / scores_summary_embed
  config.py            # 改：NotifyConfig 扩展 webhooks/task_channels/task_enabled
  db.py                # 改：insert_job_report(+剪枝) / due_scheduled_jobs / reschedule_job
migrations/
  006_job_reports.sql  007_scheduled_jobs.sql
deploy/
  systemd/hermes-investment-scheduler.service  # 新
  install.sh           # 改：装 scheduler service、移除废弃 timer
docs/
  scheduling-and-notifications.md  # 新
tests/
  test_job_reports_repository.py  test_scheduled_jobs_repository.py
  test_harness.py  test_notifier.py  test_config_notify.py
  test_metrics_task.py  test_filings_task.py  test_sec_downloader.py  test_scheduler.py
  test_db_sql.py（追加 006/007 断言）  test_filing_service.py（既存，转绿）
```

删除（Task 8）：`investment_assistant/hermes/daily.py`、`investment_assistant/tasks/daily.py`、`investment_assistant/ops/hermes_daily.py`、`tests/test_hermes_daily.py`、`tests/test_tasks_daily.py`。

---

## Task 1：迁移 `006_job_reports` + 报告仓储

**Files:**
- Create: `migrations/006_job_reports.sql`
- Modify: `investment_assistant/db.py`
- Create: `tests/test_job_reports_repository.py`
- Modify: `tests/test_db_sql.py`

**Interfaces:**
- Produces: `db.insert_job_report(conn, *, task: str, run_id: str, status: str, started_at, finished_at, summary: dict) -> None`（写入后剪枝 30 天）。

- [ ] **Step 1: 写迁移断言** —— 追加到 `tests/test_db_sql.py`（文件顶部已 `from pathlib import Path`）：

```python
def test_job_reports_migration():
    sql = Path("migrations/006_job_reports.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS job_reports" in sql
    assert "task        TEXT NOT NULL" in sql or "task TEXT NOT NULL" in sql
    assert "run_id" in sql and "status" in sql
    assert "summary     JSONB" in sql or "summary JSONB" in sql
    assert "created_at  TIMESTAMPTZ" in sql or "created_at TIMESTAMPTZ" in sql
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_sql.py::test_job_reports_migration -q`
Expected: FAIL（文件不存在）。

- [ ] **Step 3: 写 `migrations/006_job_reports.sql`：**

```sql
CREATE TABLE IF NOT EXISTS job_reports (
  id          BIGSERIAL PRIMARY KEY,
  task        TEXT NOT NULL,
  run_id      TEXT NOT NULL,
  status      TEXT NOT NULL,
  started_at  TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_reports_task_created
  ON job_reports (task, created_at DESC);
```

- [ ] **Step 4: 写仓储测试** —— `tests/test_job_reports_repository.py`：

```python
from datetime import UTC, datetime

from investment_assistant import db


class FakeCursor:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.store.append((sql, params))


class FakeConn:
    def __init__(self):
        self.store = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.commits += 1


def test_insert_job_report_writes_and_prunes():
    conn = FakeConn()
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    db.insert_job_report(
        conn, task="metrics", run_id="metrics-1", status="success",
        started_at=now, finished_at=now, summary={"n": 1},
    )
    sqls = [sql for sql, _ in conn.store]
    assert any("INSERT INTO job_reports" in s for s in sqls)
    assert any("DELETE FROM job_reports" in s and "30 days" in s for s in sqls)
    assert conn.commits == 1
```

- [ ] **Step 5: 运行确认失败**

Run: `python -m pytest tests/test_job_reports_repository.py -q`
Expected: FAIL（`insert_job_report` 未定义）。

- [ ] **Step 6: 在 `db.py` 末尾追加：**

```python
def insert_job_report(
    conn,
    *,
    task: str,
    run_id: str,
    status: str,
    started_at,
    finished_at,
    summary: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_reports (task, run_id, status, started_at, finished_at, summary)
            VALUES (%(task)s, %(run_id)s, %(status)s, %(started_at)s, %(finished_at)s, %(summary)s::jsonb)
            """,
            {
                "task": task,
                "run_id": run_id,
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "summary": json.dumps(summary or {}, ensure_ascii=False, default=str),
            },
        )
        cur.execute("DELETE FROM job_reports WHERE created_at < now() - INTERVAL '30 days'")
    conn.commit()
```
> `db.py` 顶部已 `import json` 与 `from typing import Any`，无需新增 import。

- [ ] **Step 7: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_job_reports_repository.py tests/test_db_sql.py -q`（PASS）
```bash
git add migrations/006_job_reports.sql investment_assistant/db.py tests/test_job_reports_repository.py tests/test_db_sql.py
git commit -m "feat(db): job_reports migration (006) + insert/prune repository"
```

---

## Task 2：迁移 `007_scheduled_jobs` + 调度仓储

**Files:**
- Create: `migrations/007_scheduled_jobs.sql`
- Modify: `investment_assistant/db.py`
- Create: `tests/test_scheduled_jobs_repository.py`
- Modify: `tests/test_db_sql.py`

**Interfaces:**
- Produces:
  - `db.due_scheduled_jobs(conn, *, now) -> list[dict]`（`SELECT ... FOR UPDATE SKIP LOCKED`，返回到期 job dict，键 `id,name,time_local,weekday_mask,timezone,next_run_at`）。
  - `db.reschedule_job(conn, name: str, *, next_run_at, last_run_at) -> None`。

- [ ] **Step 1: 写迁移断言** —— 追加到 `tests/test_db_sql.py`：

```python
def test_scheduled_jobs_migration():
    sql = Path("migrations/007_scheduled_jobs.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS scheduled_jobs" in sql
    assert "name         TEXT NOT NULL UNIQUE" in sql or "name TEXT NOT NULL UNIQUE" in sql
    assert "time_local" in sql and "weekday_mask" in sql and "timezone" in sql
    assert "next_run_at" in sql
    assert "'metrics'" in sql and "'filings'" in sql and "'scores'" in sql  # seed
    assert "ON CONFLICT (name) DO NOTHING" in sql
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_sql.py::test_scheduled_jobs_migration -q`
Expected: FAIL。

- [ ] **Step 3: 写 `migrations/007_scheduled_jobs.sql`：**

```sql
CREATE TABLE IF NOT EXISTS scheduled_jobs (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  time_local   TEXT NOT NULL,
  weekday_mask TEXT NOT NULL DEFAULT '1-5',
  timezone     TEXT NOT NULL DEFAULT 'America/New_York',
  enabled      BOOLEAN NOT NULL DEFAULT TRUE,
  next_run_at  TIMESTAMPTZ,
  last_run_at  TIMESTAMPTZ,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO scheduled_jobs (name, time_local, weekday_mask, timezone) VALUES
  ('metrics', '08:00', '1-5', 'America/New_York'),
  ('filings', '09:00', '1-5', 'America/New_York'),
  ('scores',  '18:00', '1-5', 'America/New_York')
ON CONFLICT (name) DO NOTHING;
```

- [ ] **Step 4: 写仓储测试** —— `tests/test_scheduled_jobs_repository.py`：

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


def test_due_scheduled_jobs_uses_skip_locked():
    rows = [(1, "metrics", "08:00", "1-5", "America/New_York", None)]
    conn = FakeConn(rows=rows)
    out = db.due_scheduled_jobs(conn, now=datetime(2026, 6, 29, 12, 0, tzinfo=UTC))
    assert out[0]["name"] == "metrics" and out[0]["time_local"] == "08:00"
    assert any("FOR UPDATE SKIP LOCKED" in sql for sql, _ in conn.store)


def test_reschedule_job_updates_next_run():
    conn = FakeConn()
    db.reschedule_job(
        conn, "metrics",
        next_run_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        last_run_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
    )
    assert any("UPDATE scheduled_jobs" in sql for sql, _ in conn.store)
    assert conn.commits == 1
```

- [ ] **Step 5: 运行确认失败**

Run: `python -m pytest tests/test_scheduled_jobs_repository.py -q`
Expected: FAIL。

- [ ] **Step 6: 在 `db.py` 末尾追加：**

```python
def due_scheduled_jobs(conn, *, now) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, time_local, weekday_mask, timezone, next_run_at
            FROM scheduled_jobs
            WHERE enabled AND (next_run_at IS NULL OR next_run_at <= %(now)s)
            FOR UPDATE SKIP LOCKED
            """,
            {"now": now},
        )
        rows = cur.fetchall()
    keys = ["id", "name", "time_local", "weekday_mask", "timezone", "next_run_at"]
    return [dict(zip(keys, row)) for row in rows]


def reschedule_job(conn, name: str, *, next_run_at, last_run_at) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scheduled_jobs
            SET next_run_at = %(next_run_at)s, last_run_at = %(last_run_at)s, updated_at = now()
            WHERE name = %(name)s
            """,
            {"name": name, "next_run_at": next_run_at, "last_run_at": last_run_at},
        )
    conn.commit()
```

- [ ] **Step 7: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_scheduled_jobs_repository.py tests/test_db_sql.py -q`（PASS）
```bash
git add migrations/007_scheduled_jobs.sql investment_assistant/db.py tests/test_scheduled_jobs_repository.py tests/test_db_sql.py
git commit -m "feat(db): scheduled_jobs migration (007) + due/reschedule repository"
```

---

## Task 3：Discord 配置扩展 + `from_config`

**Files:**
- Modify: `investment_assistant/config.py:41-47`（`NotifyConfig`）
- Modify: `investment_assistant/notify/discord.py`
- Create: `tests/test_config_notify.py`

**Interfaces:**
- Produces:
  - `NotifyConfig` 新字段：`webhooks: dict[str,str]`、`task_channels: dict[str,str]`、`task_enabled: dict[str,bool]`。
  - `DiscordClient.from_config(notify_cfg) -> DiscordClient`（webhook 优先 config，回退 env）。

- [ ] **Step 1: 写测试** —— `tests/test_config_notify.py`：

```python
from investment_assistant.config import _config_from_dict
from investment_assistant.notify.discord import DiscordChannel, DiscordClient


def test_notify_config_defaults():
    cfg = _config_from_dict({})
    assert cfg.notify.discord_enabled is True
    assert cfg.notify.task_channels["metrics"] == "daily"
    assert cfg.notify.task_channels["filings"] == "earnings"
    assert cfg.notify.task_enabled["metrics"] is True


def test_notify_config_override_from_dict():
    cfg = _config_from_dict({"notify": {
        "discord_enabled": False,
        "webhooks": {"daily": "https://hook/daily"},
        "task_enabled": {"filings": False},
    }})
    assert cfg.notify.discord_enabled is False
    assert cfg.notify.webhooks["daily"] == "https://hook/daily"
    assert cfg.notify.task_enabled["filings"] is False


def test_from_config_prefers_config_webhook(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_EARNINGS", "env-earnings")
    monkeypatch.setenv("DISCORD_WEBHOOK_SIGNALS", "env-signals")
    monkeypatch.setenv("DISCORD_WEBHOOK_DAILY", "env-daily")
    from investment_assistant.config import NotifyConfig
    cfg = NotifyConfig(webhooks={"daily": "cfg-daily"})
    client = DiscordClient.from_config(cfg)
    assert client._urls[DiscordChannel.DAILY] == "cfg-daily"
    assert client._urls[DiscordChannel.EARNINGS] == "env-earnings"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_config_notify.py -q`
Expected: FAIL。

- [ ] **Step 3: 改 `NotifyConfig`（`config.py`）** —— 替换现有定义为：

```python
@dataclass(frozen=True)
class NotifyConfig:
    """Notification channel toggles for the Hermes capability layer."""

    discord_enabled: bool = True
    email_enabled: bool = True
    webhooks: dict[str, str] = field(default_factory=dict)
    task_channels: dict[str, str] = field(
        default_factory=lambda: {"metrics": "daily", "filings": "earnings", "scores": "signals"}
    )
    task_enabled: dict[str, bool] = field(
        default_factory=lambda: {"metrics": True, "filings": True, "scores": True}
    )
```
> `_config_from_dict` 已对 `notify` 走 `_dataclass_from_dict`；dict 字段命中 `else` 分支直接赋值，无需新解析逻辑。

- [ ] **Step 4: 加 `DiscordClient.from_config`（`notify/discord.py`，置于 `from_env` 下方）：**

```python
    @classmethod
    def from_config(cls, notify_cfg) -> "DiscordClient":
        from dotenv import load_dotenv
        import os
        load_dotenv()

        def url(channel: str, env_key: str) -> str:
            return notify_cfg.webhooks.get(channel) or os.environ.get(env_key, "")

        return cls(
            earnings_url=url("earnings", "DISCORD_WEBHOOK_EARNINGS"),
            signals_url=url("signals", "DISCORD_WEBHOOK_SIGNALS"),
            daily_url=url("daily", "DISCORD_WEBHOOK_DAILY"),
        )
```

- [ ] **Step 5: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_config_notify.py -q`（PASS）
```bash
git add investment_assistant/config.py investment_assistant/notify/discord.py tests/test_config_notify.py
git commit -m "feat(notify): configurable Discord (per-task toggles, channel routing, webhook override)"
```

---

## Task 4：Discord 模板 + `notify/notifier.py`

**Files:**
- Modify: `investment_assistant/notify/templates.py`
- Create: `investment_assistant/notify/notifier.py`
- Create: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `NotifyConfig`、`DiscordClient`、`DiscordChannel`、新模板。
- Produces:
  - `templates.metrics_summary_embed(summary: dict) -> dict`、`templates.filings_digest_embed(summary: dict) -> dict`、`templates.scores_summary_embed(summary: dict) -> dict`。
  - `notifier.dispatch(task: str, status: str, summary: dict, notify_cfg, *, client=None) -> dict`（返回 `{"sent": bool, ...}`）。

- [ ] **Step 1: 写测试** —— `tests/test_notifier.py`：

```python
from investment_assistant.config import NotifyConfig
from investment_assistant.notify import notifier


class FakeClient:
    def __init__(self):
        self.sent = []

    def send(self, channel, payload):
        self.sent.append((channel, payload))


def test_dispatch_skips_when_globally_disabled():
    out = notifier.dispatch("metrics", "success", {}, NotifyConfig(discord_enabled=False), client=FakeClient())
    assert out["sent"] is False and out["reason"] == "discord_disabled"


def test_dispatch_skips_when_task_disabled():
    cfg = NotifyConfig(task_enabled={"metrics": False})
    out = notifier.dispatch("metrics", "success", {}, cfg, client=FakeClient())
    assert out["sent"] is False and out["reason"] == "task_disabled"


def test_dispatch_routes_to_channel():
    client = FakeClient()
    summary = {"market_status": "green", "vix": 15.0, "tickers": [{"ticker": "NVDA", "trend_state": "uptrend"}]}
    out = notifier.dispatch("metrics", "success", summary, NotifyConfig(), client=client)
    assert out["sent"] is True and out["channel"] == "daily"
    assert client.sent and "embeds" in client.sent[0][1]


def test_dispatch_send_failure_is_structured():
    class Boom(FakeClient):
        def send(self, channel, payload):
            raise RuntimeError("network")

    out = notifier.dispatch("filings", "success", {"filings": []}, NotifyConfig(), client=Boom())
    assert out["sent"] is False and "send_failed" in out["reason"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_notifier.py -q`
Expected: FAIL（`notifier` 不存在）。

- [ ] **Step 3: 加模板（`notify/templates.py` 末尾）：**

```python
def metrics_summary_embed(summary: dict) -> dict:
    status = str(summary.get("market_status", "?")).upper()
    vix = summary.get("vix")
    tickers = summary.get("tickers", [])
    rows = "\n".join(f"• **{t.get('ticker')}** — {t.get('trend_state', '?')}" for t in tickers[:10]) or "无"
    return {
        "embeds": [{
            "title": "🗓 每日指标 · 08:00",
            "color": 3447003,
            "fields": [
                {"name": "市场环境", "value": f"{status} | VIX {vix}", "inline": False},
                {"name": f"关注列表 ({len(tickers)})", "value": rows, "inline": False},
            ],
            "footer": _footer(),
        }]
    }


def filings_digest_embed(summary: dict) -> dict:
    filings = summary.get("filings", [])
    rows = "\n".join(
        f"• **{f.get('ticker')}** {f.get('form')} — {f.get('filed_at', '')}" for f in filings[:15]
    ) or "昨日无新财报"
    return {
        "embeds": [{
            "title": "📄 昨日财报 · 09:00",
            "color": 15844367,
            "fields": [
                {"name": f"新提交 ({summary.get('downloaded_count', 0)})", "value": rows, "inline": False},
            ],
            "footer": _footer(),
        }]
    }


def scores_summary_embed(summary: dict) -> dict:
    rows = summary.get("rows", [])
    listing = "\n".join(
        f"• **{r.get('ticker')}** — {r.get('score')}" for r in rows[:10]
    ) or "无评分"
    return {
        "embeds": [{
            "title": "📈 策略评分 · 18:00",
            "color": 10070709,
            "fields": [
                {"name": f"评分 ({len(rows)})", "value": listing, "inline": False},
            ],
            "footer": _footer(),
        }]
    }
```

- [ ] **Step 4: 实现 `notify/notifier.py`：**

```python
from __future__ import annotations

from typing import Any

from investment_assistant.notify.discord import DiscordChannel, DiscordClient
from investment_assistant.notify.templates import (
    filings_digest_embed,
    metrics_summary_embed,
    scores_summary_embed,
)

_EMBED_BUILDERS = {
    "metrics": metrics_summary_embed,
    "filings": filings_digest_embed,
    "scores": scores_summary_embed,
}


def dispatch(task: str, status: str, summary: dict[str, Any], notify_cfg, *, client=None) -> dict[str, Any]:
    if not notify_cfg.discord_enabled:
        return {"sent": False, "reason": "discord_disabled"}
    if notify_cfg.task_enabled.get(task) is False:
        return {"sent": False, "reason": "task_disabled"}
    channel_name = notify_cfg.task_channels.get(task)
    if not channel_name:
        return {"sent": False, "reason": "no_channel"}

    builder = _EMBED_BUILDERS.get(task)
    payload = builder(summary) if builder else {"content": f"[{task}] {status}"}
    try:
        cli = client or DiscordClient.from_config(notify_cfg)
        cli.send(DiscordChannel(channel_name), payload)
        return {"sent": True, "channel": channel_name}
    except Exception as exc:  # 通知失败不拖垮任务；结构化返回
        return {"sent": False, "reason": f"send_failed: {exc}"}
```

- [ ] **Step 5: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_notifier.py tests/test_notify_discord.py -q`（PASS）
```bash
git add investment_assistant/notify/templates.py investment_assistant/notify/notifier.py tests/test_notifier.py
git commit -m "feat(notify): job embeds + config-driven dispatch"
```

---

## Task 5：共享外壳 `tasks/_harness.py`

**Files:**
- Create: `investment_assistant/tasks/_harness.py`
- Create: `tests/test_harness.py`

**Interfaces:**
- Consumes: `db.insert_job_report`、`notifier.dispatch`、`run_log.append_run`、`AssistantConfig`。
- Produces: `tasks._harness.run_task(task: str, fn: Callable[[], dict], *, config) -> dict`（返回 `{"run_id","task","status","summary"}`）。内部 `_record(...)` 写 `job_reports`（有 DB 时）+ `append_run`。

- [ ] **Step 1: 写测试** —— `tests/test_harness.py`：

```python
from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import _harness


def test_run_task_success(monkeypatch):
    recorded = []
    sent = []
    monkeypatch.setattr(_harness, "_record", lambda **kw: recorded.append(kw))
    monkeypatch.setattr(_harness, "dispatch", lambda *a, **k: sent.append(a))
    out = _harness.run_task("metrics", lambda: {"n": 1}, config=AssistantConfig())
    assert out["status"] == "success"
    assert out["task"] == "metrics" and out["run_id"].startswith("metrics-")
    assert recorded[0]["status"] == "success" and recorded[0]["summary"] == {"n": 1}
    assert sent and sent[0][0] == "metrics"


def test_run_task_captures_exception(monkeypatch):
    recorded = []
    monkeypatch.setattr(_harness, "_record", lambda **kw: recorded.append(kw))
    monkeypatch.setattr(_harness, "dispatch", lambda *a, **k: None)

    def boom():
        raise RuntimeError("kaboom")

    out = _harness.run_task("filings", boom, config=AssistantConfig())
    assert out["status"] == "error"
    assert "kaboom" in out["summary"]["error"]
    assert recorded[0]["status"] == "error"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_harness.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 `tasks/_harness.py`：**

```python
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

from investment_assistant.config import AssistantConfig
from investment_assistant.hermes.run_log import append_run
from investment_assistant.notify.notifier import dispatch


def run_task(task: str, fn: Callable[[], dict[str, Any]], *, config: AssistantConfig) -> dict[str, Any]:
    run_id = f"{task}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC)
    try:
        summary = fn() or {}
        status = "success"
    except Exception as exc:  # 结构化记录，不静默
        summary = {"error": str(exc)}
        status = "error"
    finished_at = datetime.now(UTC)
    _record(task=task, run_id=run_id, status=status, started_at=started_at,
            finished_at=finished_at, summary=summary)
    dispatch(task, status, summary, config.notify)
    return {"run_id": run_id, "task": task, "status": status, "summary": summary}


def _record(*, task: str, run_id: str, status: str, started_at, finished_at, summary: dict[str, Any]) -> None:
    append_run({"type": task, "run_id": run_id, "status": status, "summary": summary})
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return
    from investment_assistant.db import connect, insert_job_report

    with connect(database_url) as conn:
        insert_job_report(conn, task=task, run_id=run_id, status=status,
                          started_at=started_at, finished_at=finished_at, summary=summary)
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_harness.py -q`（PASS）
```bash
git add investment_assistant/tasks/_harness.py tests/test_harness.py
git commit -m "feat(tasks): shared task harness (run_id -> job_reports -> discord)"
```

---

## Task 6：指标任务 `tasks/metrics.py`

**Files:**
- Create: `investment_assistant/tasks/metrics.py`
- Create: `tests/test_metrics_task.py`

**Interfaces:**
- Consumes: `market.service.compute_market_signal`、`db.upsert_market_signal`、`services.tickers.run_ticker_trend_scan`、`tasks._harness.run_task`。
- Produces: `tasks.metrics._core(config) -> dict`（summary）；`tasks.metrics.run(config) -> dict`（经 harness）；`tasks.metrics.main()`。

- [ ] **Step 1: 写测试** —— `tests/test_metrics_task.py`：

```python
from types import SimpleNamespace

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import metrics


def test_core_builds_summary(monkeypatch):
    signal = SimpleNamespace(market_status="green", vix_close=15.0, signal_date="2026-06-29")
    monkeypatch.setattr(metrics, "compute_market_signal", lambda cfg, **kw: signal)
    monkeypatch.setattr(metrics, "run_ticker_trend_scan", lambda payload: {
        "rows": [{"ticker": "NVDA", "trend_state": "uptrend"}], "failures": []})
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)

    summary = metrics._core(AssistantConfig())
    assert summary["market_status"] == "green"
    assert summary["vix"] == 15.0
    assert summary["tickers"][0]["ticker"] == "NVDA"


def test_run_goes_through_harness(monkeypatch):
    monkeypatch.setattr(metrics, "_core", lambda config: {"market_status": "green"})
    captured = {}

    def fake_run_task(task, fn, *, config):
        captured["task"] = task
        return {"task": task, "status": "success", "summary": fn()}

    monkeypatch.setattr(metrics, "run_task", fake_run_task)
    out = metrics.run(AssistantConfig())
    assert captured["task"] == "metrics" and out["summary"]["market_status"] == "green"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_metrics_task.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 `tasks/metrics.py`：**

```python
from __future__ import annotations

import argparse
import json
import os
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.db import connect, upsert_market_signal
from investment_assistant.market.service import compute_market_signal
from investment_assistant.services.tickers import run_ticker_trend_scan
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig) -> dict[str, Any]:
    signal = compute_market_signal(config.market)
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if database_url:
        with connect(database_url) as conn:
            upsert_market_signal(conn, signal)
    scan = run_ticker_trend_scan({"mode": "metrics"})
    return {
        "market_status": signal.market_status,
        "vix": signal.vix_close,
        "signal_date": str(signal.signal_date),
        "tickers": [
            {"ticker": r.get("ticker"), "trend_state": r.get("trend_state")}
            for r in scan.get("rows", [])
        ],
        "errors": scan.get("failures", []),
    }


def run(config: AssistantConfig) -> dict[str, Any]:
    return run_task("metrics", lambda: _core(config), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily 08:00 metrics task")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    print(json.dumps(run(load_config(args.config)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_metrics_task.py -q`（PASS）
```bash
git add investment_assistant/tasks/metrics.py tests/test_metrics_task.py
git commit -m "feat(tasks): 08:00 metrics task (market signal + ticker snapshots)"
```

---

## Task 7：财报任务 `filings/service.py` + `filings/sec_downloader.py` + `tasks/filings.py`

**Files:**
- Create: `investment_assistant/filings/__init__.py`, `investment_assistant/filings/service.py`, `investment_assistant/filings/sec_downloader.py`
- Create: `investment_assistant/tasks/filings.py`
- Create: `tests/test_sec_downloader.py`, `tests/test_filings_task.py`
- Test（既存，转绿）: `tests/test_filing_service.py`

**Interfaces:**
- Produces:
  - `filings.service.download_configured_filings(tickers, cfg, *, downloader=None, since_date=None) -> {"downloaded_count": int, "files": list[Path], "errors": dict}`。
  - `filings.sec_downloader.SecEdgarDownloader(*, getter=None, cache_dir=None)` 带 `download_filings_batch(ticker, form_types, since_date, output_base) -> list[Path]`。
  - 模块函数 `filings.sec_downloader._download_document(url, dest, *, headers) -> Path`（测试可 monkeypatch）。

- [ ] **Step 1: 先确认既存测试当前失败**

Run: `python -m pytest tests/test_filing_service.py -q`
Expected: ERROR（`ModuleNotFoundError: investment_assistant.filings.service`）。

- [ ] **Step 2: 写下载器测试** —— `tests/test_sec_downloader.py`：

```python
from datetime import date

from investment_assistant.filings import sec_downloader
from investment_assistant.filings.sec_downloader import SecEdgarDownloader


def make_getter(tickers_json, submissions_json):
    def _getter(url, **kw):
        if "company_tickers.json" in url:
            return tickers_json, {"ok": True, "error": None, "status_code": 200}
        if "submissions" in url:
            return submissions_json, {"ok": True, "error": None, "status_code": 200}
        return None, {"ok": False, "error": "404", "status_code": 404}
    return _getter


def test_download_filters_by_form_and_yesterday(tmp_path, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    tickers_json = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}
    submissions_json = {"filings": {"recent": {
        "form": ["10-Q", "8-K", "10-K"],
        "filingDate": ["2026-06-28", "2026-06-28", "2026-06-01"],
        "accessionNumber": ["acc-q", "acc-8k", "acc-k"],
        "primaryDocument": ["q.htm", "8k.htm", "k.htm"],
    }}}
    getter = make_getter(tickers_json, submissions_json)
    written = []
    monkeypatch.setattr(sec_downloader, "_download_document",
                        lambda url, dest, *, headers: (written.append((url, dest)) or dest))

    dl = SecEdgarDownloader(getter=getter, cache_dir=tmp_path)
    out = dl.download_filings_batch("AAPL", ["10-Q", "10-K"], date(2026, 6, 28), tmp_path / "filings")
    # 仅 2026-06-28 的 10-Q 命中（10-K 日期不符、8-K 表单不符）
    assert len(out) == 1
    assert "10-Q" in str(out[0])


def test_download_degrades_without_user_agent(tmp_path, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    dl = SecEdgarDownloader(getter=lambda *a, **k: (None, {"ok": False}), cache_dir=tmp_path)
    out = dl.download_filings_batch("AAPL", ["10-Q"], date(2026, 6, 28), tmp_path / "filings")
    assert out == []
```

- [ ] **Step 3: 运行确认失败**

Run: `python -m pytest tests/test_sec_downloader.py -q`
Expected: FAIL。

- [ ] **Step 4: 实现 `filings/sec_downloader.py`：**

```python
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Callable

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{doc}"
Getter = Callable[..., tuple[dict[str, Any] | None, dict[str, Any]]]


def _download_document(url: str, dest: Path, *, headers: dict[str, str]) -> Path:
    import requests

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


class SecEdgarDownloader:
    def __init__(self, *, getter: Getter | None = None, cache_dir: Path | None = None):
        if getter is None:
            from investment_assistant.data import http

            getter = http.get_json
        self._get = getter
        self._cache_dir = Path(cache_dir) if cache_dir else None

    def _headers(self, ua: str) -> dict[str, str]:
        return {"User-Agent": ua}

    def _resolve_cik(self, ticker: str, ua: str) -> str | None:
        data: dict[str, Any] | None = None
        cache = (self._cache_dir / "company_tickers.json") if self._cache_dir else None
        if cache and cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
        else:
            data, status = self._get(COMPANY_TICKERS_URL, headers=self._headers(ua))
            if status["ok"] and data and cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(data), encoding="utf-8")
        if not data:
            return None
        target = ticker.strip().upper()
        for entry in data.values():
            if str(entry.get("ticker", "")).upper() == target:
                return f"{int(entry['cik_str']):010d}"
        return None

    def download_filings_batch(
        self, ticker: str, form_types: list[str], since_date: date, output_base: Path
    ) -> list[Path]:
        ua = os.environ.get("SEC_USER_AGENT")
        if not ua:
            return []  # 优雅降级：无 UA 不下载
        cik = self._resolve_cik(ticker, ua)
        if not cik:
            return []
        payload, status = self._get(SUBMISSIONS_URL.format(cik=cik), headers=self._headers(ua))
        if not status["ok"] or not payload:
            return []
        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accns = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        target_day = since_date.isoformat()
        out: list[Path] = []
        for i, form in enumerate(forms):
            if form not in form_types or str(dates[i]) != target_day:
                continue
            accession = accns[i]
            doc = docs[i] if i < len(docs) and docs[i] else f"{accession}.txt"
            dest = Path(output_base) / ticker.upper() / form / f"{accession}-{Path(doc).name}"
            url = ARCHIVE_DOC_URL.format(
                cik_int=int(cik), accession_nodash=accession.replace("-", ""), doc=doc
            )
            out.append(_download_document(url, dest, headers=self._headers(ua)))
        return out
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_sec_downloader.py -q`
Expected: PASS。

- [ ] **Step 6: 实现 `filings/__init__.py`（空）与 `filings/service.py`：**

```python
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from investment_assistant.config import FilingsConfig


class FilingDownloader(Protocol):
    def download_filings_batch(
        self, ticker: str, form_types: list[str], since_date: date, output_base: Path
    ) -> list[Path]:
        ...


def _default_downloader() -> FilingDownloader:
    from investment_assistant.filings.sec_downloader import SecEdgarDownloader

    return SecEdgarDownloader()


def download_configured_filings(
    tickers: list[str],
    cfg: FilingsConfig,
    *,
    downloader: FilingDownloader | None = None,
    since_date: date | None = None,
) -> dict[str, Any]:
    dl = downloader or _default_downloader()
    when = since_date or (date.today() - timedelta(days=1))  # 默认昨日 T-1
    files: list[Path] = []
    errors: dict[str, str] = {}
    for raw in tickers:
        ticker = str(raw or "").strip().upper()
        if not ticker:
            continue
        try:
            files.extend(dl.download_filings_batch(ticker, list(cfg.forms), when, cfg.output_dir))
        except Exception as exc:  # 单标的失败不影响其余
            errors[ticker] = str(exc)
    return {"downloaded_count": len(files), "files": files, "errors": errors}
```
> 既存 `tests/test_filing_service.py` 断言 `downloader.calls[0]` 的 `(ticker, form_types=list(cfg.forms), output_base=cfg.output_dir)`；本实现传参顺序与之一致（`since_date` 不被该测试约束）。

- [ ] **Step 7: 运行确认既存契约转绿**

Run: `python -m pytest tests/test_filing_service.py -q`
Expected: PASS。

- [ ] **Step 8: 写 filings 任务测试** —— `tests/test_filings_task.py`：

```python
from datetime import date
from pathlib import Path

from investment_assistant.config import AssistantConfig, FilingsConfig
from investment_assistant.tasks import filings


def test_core_summarizes_downloads(monkeypatch, tmp_path):
    def fake_download(tickers, cfg, *, downloader=None, since_date=None):
        return {"downloaded_count": 1, "files": [tmp_path / "NVDA/10-Q/acc.htm"], "errors": {}}

    monkeypatch.setattr(filings, "download_configured_filings", fake_download)
    cfg = AssistantConfig(filings=FilingsConfig(output_dir=tmp_path))
    summary = filings._core(cfg)
    assert summary["downloaded_count"] == 1
    assert summary["filings"][0]["ticker"] == "NVDA"


def test_run_goes_through_harness(monkeypatch):
    monkeypatch.setattr(filings, "_core", lambda config: {"downloaded_count": 0, "filings": []})
    captured = {}

    def fake_run_task(task, fn, *, config):
        captured["task"] = task
        return {"task": task, "status": "success", "summary": fn()}

    monkeypatch.setattr(filings, "run_task", fake_run_task)
    out = filings.run(AssistantConfig())
    assert captured["task"] == "filings" and out["summary"]["downloaded_count"] == 0
```

- [ ] **Step 9: 运行确认失败**

Run: `python -m pytest tests/test_filings_task.py -q`
Expected: FAIL。

- [ ] **Step 10: 实现 `tasks/filings.py`：**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.filings.service import download_configured_filings
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig) -> dict[str, Any]:
    result = download_configured_filings(config.watchlist, config.filings)
    filings_meta: list[dict[str, Any]] = []
    for path in result.get("files", []):
        parts = Path(path).parts
        ticker = parts[-3] if len(parts) >= 3 else None
        form = parts[-2] if len(parts) >= 2 else None
        filings_meta.append({"ticker": ticker, "form": form, "path": str(path)})
    return {
        "downloaded_count": result.get("downloaded_count", 0),
        "filings": filings_meta,
        "errors": result.get("errors", {}),
    }


def run(config: AssistantConfig) -> dict[str, Any]:
    return run_task("filings", lambda: _core(config), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily 09:00 filings task")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    print(json.dumps(run(load_config(args.config)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
```
> `filed_at` 不从落盘路径还原（路径不含日期）；摘要以 `ticker/form/path` 为准，模板里 `filed_at` 缺省显示空——满足「昨日财报清单」展示需求。

- [ ] **Step 11: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_filings_task.py tests/test_sec_downloader.py tests/test_filing_service.py -q`（PASS）
```bash
git add investment_assistant/filings tests/test_sec_downloader.py tests/test_filings_task.py
git add investment_assistant/tasks/filings.py
git commit -m "feat(filings): real SEC EDGAR downloader + 09:00 filings task (fixes daily import, greens existing test)"
```

---

## Task 8：自研调度器 `tasks/scheduler.py` + 收编 scores

**Files:**
- Create: `investment_assistant/tasks/scheduler.py`
- Modify: `investment_assistant/tasks/nightly_scores.py`
- Create: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `db.due_scheduled_jobs`、`db.reschedule_job`、`tasks.{metrics,filings,nightly_scores}.run`、`config.load_config`。
- Produces:
  - `scheduler.compute_next_run(time_local, weekday_mask, timezone, *, after) -> datetime`（UTC-aware）。
  - `scheduler.REGISTRY: dict[str, Callable[[AssistantConfig], dict]]`。
  - `scheduler.run_due_jobs(conn, config, *, now, registry=REGISTRY) -> list[dict]`。

- [ ] **Step 1: 写测试** —— `tests/test_scheduler.py`：

```python
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import scheduler


def test_compute_next_run_same_day_when_time_ahead():
    after = datetime(2026, 6, 29, 11, 0, tzinfo=UTC)  # Mon 07:00 ET
    nxt = scheduler.compute_next_run("08:00", "1-5", "America/New_York", after=after)
    local = nxt.astimezone(ZoneInfo("America/New_York"))
    assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 6, 29, 8, 0)


def test_compute_next_run_skips_weekend():
    after = datetime(2026, 6, 26, 18, 0, tzinfo=UTC)  # Fri afternoon ET
    nxt = scheduler.compute_next_run("08:00", "1-5", "America/New_York", after=after)
    local = nxt.astimezone(ZoneInfo("America/New_York"))
    assert local.isoweekday() == 1  # Monday


def test_run_due_jobs_runs_and_reschedules(monkeypatch):
    ran = []
    rescheduled = []
    monkeypatch.setattr(scheduler, "due_scheduled_jobs",
                        lambda conn, *, now: [{"id": 1, "name": "metrics", "time_local": "08:00",
                                               "weekday_mask": "1-5", "timezone": "America/New_York",
                                               "next_run_at": None}])
    monkeypatch.setattr(scheduler, "reschedule_job",
                        lambda conn, name, *, next_run_at, last_run_at: rescheduled.append((name, next_run_at)))
    registry = {"metrics": lambda config: ran.append("metrics") or {"ok": True}}
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    out = scheduler.run_due_jobs(object(), AssistantConfig(), now=now, registry=registry)
    assert ran == ["metrics"]
    assert rescheduled and rescheduled[0][0] == "metrics"
    assert out[0]["name"] == "metrics"


def test_run_due_jobs_unknown_name_records_error(monkeypatch):
    monkeypatch.setattr(scheduler, "due_scheduled_jobs",
                        lambda conn, *, now: [{"id": 9, "name": "ghost", "time_local": "08:00",
                                               "weekday_mask": "1-5", "timezone": "America/New_York",
                                               "next_run_at": None}])
    monkeypatch.setattr(scheduler, "reschedule_job", lambda *a, **k: None)
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    out = scheduler.run_due_jobs(object(), AssistantConfig(), now=now, registry={})
    assert out[0]["status"] == "error" and "unregistered" in out[0]["error"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_scheduler.py -q`
Expected: FAIL。

- [ ] **Step 3: 重构 `tasks/nightly_scores.py` 暴露 `run(config)`：** 替换文件为：

```python
from __future__ import annotations

import argparse
import json
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig) -> dict[str, Any]:
    from investment_assistant.services.strategies import run_strategy_score_scan

    return run_strategy_score_scan({"mode": "nightly"})


def run(config: AssistantConfig) -> dict[str, Any]:
    return run_task("scores", lambda: _core(config), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nightly strategy score task")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    print(json.dumps(run(load_config(args.config)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
```
> 注：若既存 `tests/test_nightly_scores*.py` 断言旧 `run()`（无参）签名，同步更新为 `run(load_config(None))` 或 monkeypatch `_core`。先 `grep -rn "nightly_scores" tests/` 核对。

- [ ] **Step 4: 实现 `tasks/scheduler.py`：**

```python
from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.db import connect, due_scheduled_jobs, reschedule_job
from investment_assistant.tasks import filings as filings_task
from investment_assistant.tasks import metrics as metrics_task
from investment_assistant.tasks import nightly_scores as scores_task

logger = logging.getLogger(__name__)

REGISTRY: dict[str, Callable[[AssistantConfig], dict[str, Any]]] = {
    "metrics": metrics_task.run,
    "filings": filings_task.run,
    "scores": scores_task.run,
}


def _parse_weekday_mask(mask: str) -> set[int]:
    days: set[int] = set()
    for part in str(mask).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            days.update(range(int(a), int(b) + 1))
        else:
            days.add(int(part))
    return days


def compute_next_run(time_local: str, weekday_mask: str, timezone: str, *, after: datetime) -> datetime:
    tz = ZoneInfo(timezone)
    hh, mm = (int(x) for x in time_local.split(":"))
    days = _parse_weekday_mask(weekday_mask)
    after_local = after.astimezone(tz)
    for offset in range(0, 8):
        cand_day = (after_local + timedelta(days=offset)).date()
        if cand_day.isoweekday() not in days:
            continue
        cand = datetime(cand_day.year, cand_day.month, cand_day.day, hh, mm, tzinfo=tz)
        if cand > after_local:
            return cand.astimezone(UTC)
    raise ValueError(f"no matching weekday in mask {weekday_mask!r}")


def run_due_jobs(conn, config: AssistantConfig, *, now: datetime, registry=REGISTRY) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for job in due_scheduled_jobs(conn, now=now):
        name = job["name"]
        fn = registry.get(name)
        if fn is None:
            logger.warning("scheduled job %s is not registered; skipping", name)
            results.append({"name": name, "status": "error", "error": "unregistered job"})
        else:
            try:
                outcome = fn(config)
                results.append({"name": name, "status": outcome.get("status", "success")})
            except Exception as exc:  # 任务自身异常已被 harness 记录；这里兜底不中断循环
                logger.exception("scheduled job %s crashed", name)
                results.append({"name": name, "status": "error", "error": str(exc)})
        next_run_at = compute_next_run(job["time_local"], job["weekday_mask"], job["timezone"], after=now)
        reschedule_job(conn, name, next_run_at=next_run_at, last_run_at=now)
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config(None)
    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    tick_seconds = int(os.environ.get("SCHEDULER_TICK_SECONDS", "60"))
    logger.info("scheduler started; tick=%ss", tick_seconds)
    while True:
        try:
            with connect(database_url) as conn:
                run_due_jobs(conn, config, now=datetime.now(UTC))
        except Exception:  # 主循环兜底，记录后继续
            logger.exception("scheduler tick failed")
        time.sleep(tick_seconds)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_scheduler.py -q`（PASS）
```bash
git add investment_assistant/tasks/scheduler.py investment_assistant/tasks/nightly_scores.py tests/test_scheduler.py
git commit -m "feat(tasks): self-hosted pg scheduler daemon + scores via harness"
```

---

## Task 9：退役单体 daily + systemd 切换

**Files:**
- Delete: `investment_assistant/hermes/daily.py`, `investment_assistant/tasks/daily.py`, `investment_assistant/ops/hermes_daily.py`, `tests/test_hermes_daily.py`, `tests/test_tasks_daily.py`
- Create: `deploy/systemd/hermes-investment-scheduler.service`
- Delete: `deploy/systemd/hermes-investment-daily.service`, `deploy/systemd/hermes-investment-daily.timer`, `deploy/systemd/hermes-investment-scores.timer`
- Modify: `deploy/install.sh`

- [ ] **Step 1: 确认无残留引用** —— 删除前 grep：

Run: `grep -rn "hermes.daily\|tasks.daily\|ops.hermes_daily\|run_daily" investment_assistant/ tests/ deploy/`
Expected: 仅命中即将删除的文件自身（若命中其它文件，先改其引用为新任务模块）。

- [ ] **Step 2: 删除退役模块与测试**

```bash
git rm investment_assistant/hermes/daily.py investment_assistant/tasks/daily.py investment_assistant/ops/hermes_daily.py
git rm tests/test_hermes_daily.py tests/test_tasks_daily.py
```

- [ ] **Step 3: 写新 service `deploy/systemd/hermes-investment-scheduler.service`：**

```ini
[Unit]
Description=Hermes investment assistant scheduler daemon
After=network-online.target investment-assistant-postgres.service
Wants=network-online.target investment-assistant-postgres.service

[Service]
Type=simple
User=jianjustin
Group=jianjustin
WorkingDirectory=/opt/hermes-investment-assistant/app
EnvironmentFile=/opt/hermes-investment-assistant/.env
ExecStart=/opt/hermes-investment-assistant/.venv/bin/python -m investment_assistant.tasks.scheduler
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: 删除废弃 timer/service**

```bash
git rm deploy/systemd/hermes-investment-daily.service deploy/systemd/hermes-investment-daily.timer deploy/systemd/hermes-investment-scores.timer
```
> 保留 `hermes-investment-scores.service` 供手动 `systemctl start hermes-investment-scores`（一次性补跑）。

- [ ] **Step 5: 改 `deploy/install.sh` 的 enable 行** —— 把 `hermes-investment-daily.timer` 替换为 `hermes-investment-scheduler.service`，并移除 `hermes-investment-scores.timer`。当前（`install.sh:47`）：

```bash
systemctl enable investment-assistant-postgres.service hermes-investment-dashboard.service hermes-investment-daily.timer
```
改为：

```bash
systemctl enable investment-assistant-postgres.service hermes-investment-dashboard.service hermes-investment-scheduler.service
```
> 若 `install.sh` 另有 enable `hermes-investment-scores.timer` 的行，一并删除；`*.timer` 安装行（`install.sh:45`）保留无害（已无 timer 文件则改为不报错的 glob 或忽略）。Step 编辑前先 `grep -n "timer\|scores\|daily\|scheduler" deploy/install.sh` 核对实际行。

- [ ] **Step 6: 验证导入与回归**

Run: `python -c "import investment_assistant.tasks.scheduler; import investment_assistant.tasks.metrics; import investment_assistant.tasks.filings; print('ok')"`
Expected: 打印 `ok`。
Run: `python -m pytest -q`
Expected: PASS（退役测试已删；其余全绿）。

- [ ] **Step 7: Commit**

```bash
git add deploy/systemd/hermes-investment-scheduler.service deploy/install.sh
git commit -m "chore(deploy): scheduler service replaces daily/scores timers; retire monolithic daily"
```

---

## Task 10：文档 + Phase 2 编号同步 + 全回归

**Files:**
- Create: `docs/scheduling-and-notifications.md`
- Modify: `docs/superpowers/plans/2026-06-27-phase2-data-layer.md`

- [ ] **Step 1: 写 `docs/scheduling-and-notifications.md`** —— 记录：
  - `scheduled_jobs` 表与 seed（metrics 08:00 / filings 09:00 / scores 18:00，America/New_York，Mon..Fri）；如何改时间/开关（`UPDATE scheduled_jobs ...`）。
  - `job_reports` 表与 30 天 TTL（写入即剪枝）。
  - `tasks/_harness.py` 外壳契约；各任务 `python -m investment_assistant.tasks.{metrics,filings,nightly_scores}` 手动单跑方式。
  - 调度守护进程 `python -m investment_assistant.tasks.scheduler` + systemd `hermes-investment-scheduler.service`（`Restart=always`，无 timer）。
  - Discord 配置：`NotifyConfig.{discord_enabled,webhooks,task_channels,task_enabled}`；webhook 优先 config 后 env。
  - SEC 下载器：`SEC_USER_AGENT` 必需，无则降级；落盘路径 `<output_dir>/<ticker>/<form>/<accession>-<doc>`。

- [ ] **Step 2: 同步 Phase 2 计划编号** —— 编辑 `docs/superpowers/plans/2026-06-27-phase2-data-layer.md`：在 Global Constraints 顶部加一行说明「006/007 已被『定时采集 + 调度器』计划占用，本计划迁移顺延为 008_macro_indicators / 009_fundamentals / 010_filings / 011_price_bars」，并把正文中 006-009 的引用整体 +2。

- [ ] **Step 3: 全套件回归**

Run: `python -m pytest -q`
Expected: PASS（DB 集成测试在无 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 时 skip）。

- [ ] **Step 4: Commit**

```bash
git add docs/scheduling-and-notifications.md docs/superpowers/plans/2026-06-27-phase2-data-layer.md
git commit -m "docs: scheduling & notifications guide; renumber Phase 2 migrations to 008+"
```

---

## Self-Review（对照 spec）

**1. Spec 覆盖：**
- §4.1 job_reports + 30天TTL → Task 1。✅
- §4.2 scheduled_jobs + seed → Task 2。✅
- §5 调度器（compute_next_run/registry/run_due_jobs/misfire=next_run_at<=now/未注册记error/兜底不崩）→ Task 8。✅
- §6 harness（run_id→job_reports+append_run→notifier；异常结构化）→ Task 5。✅
- §7.1 metrics（market signal + ticker 快照 + 删 brief）→ Task 6（删 brief 由 Task 9 退役 daily 完成）。✅
- §7.2 filings（真实 SEC 下载器 + 昨日T-1 + 既存测试转绿 + 修 daily import）→ Task 7。✅
- §8 Discord 可配置（NotifyConfig 扩展 + notifier + from_config）→ Task 3+4。✅
- §9 编号衔接 → Task 10。✅
- §10 systemd（单 service，取消 timer）→ Task 9。✅
- §11 测试矩阵 → 各任务测试齐备。✅

**2. Placeholder 扫描：** 每个代码步骤给完整代码（迁移全文、仓储全文、下载器全文、调度器全文、任务全文、测试全文）；无 TBD/“similar to”。Task 3/9 中「先 grep 核对实际行」是**针对既有文件真实行号可能漂移**的防御性核对，非占位。

**3. 类型/命名一致性：** `insert_job_report`、`due_scheduled_jobs`、`reschedule_job`、`compute_next_run`、`run_due_jobs`、`REGISTRY`、`run_task`、`dispatch`、`from_config`、`_core/run/main`、`download_configured_filings`、`SecEdgarDownloader.download_filings_batch`、`_download_document` 全程一致；任务名常量 `metrics/filings/scores` 在 seed、registry、task_channels、task_enabled、模板映射间一致。

**衔接/前置：** 本计划独立可跑（不依赖未完成的 Phase 2）；唯一与 Phase 2 的交集是迁移编号（Task 10 同步）。SEC 下载器抢先实现了 Phase 2 T2.2 的下载部分，Phase 2 本体只需补 filing 元数据入 pg。
