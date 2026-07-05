# 工具模块优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 工具模块收敛为"任务中心+运行记录"两个子页，4 个定时任务全部支持日期/日期范围回补，通知展示实际日期，新增 filings 表与数据模块"财报"Tab（筛选+单个 htm 下载）。

**Architecture:** 后端 FastAPI（investment_assistant/api）+ 服务层（services/）+ psycopg 直写 SQL（db.py）+ 版本化 SQL 迁移（migrations/NNN_*.sql）。任务经 `tasks/_harness.run_task()` 统一记录 job_reports 并触发 Discord 通知。前端 Svelte 5（web/src），vitest 测试。

**Tech Stack:** Python 3.13 / FastAPI / psycopg / pytest；Svelte 5 / TypeScript / vitest / Tailwind。

**Spec:** `docs/superpowers/specs/2026-07-04-tools-module-optimization-design.md`

## Global Constraints

- 日期校验（所有任务统一，`services/jobs.py`）：拒绝未来日期；`from <= to`；范围上限 **92 天**；单日用 `date`，范围用 `from`/`to`。
- `job_reports.trigger_source` 只有两个值：`'scheduled'` | `'manual'`（列名不用 `trigger`，避免与 SQL 关键字混淆）。
- metrics / scores 历史回补**跳过周末**（`isoweekday() >= 6`）；单日失败不中断整个范围，计入 summary。
- 一次触发（单日或范围）只产生**一条** job_report 与**一条**通知；范围回补的 summary 按天聚合在 `days` 数组里。
- `POST /api/market/signals/fetch` **保留**（Settings 系统页的 operations registry 引用它），仅前端 Tools 不再调用。
- scores 历史回补的宏观环境取**当前状态**（历史宏观不回放），summary 里注明。
- 所有 UI 文案中文；git 提交信息遵循仓库风格：`feat(ui): 中文描述` / `fix(api): ...`，结尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- Python 测试：`python -m pytest tests/<file> -v`（在仓库根目录）。前端测试：`cd web && npx vitest run src/<path>`。
- 迁移文件编号接续现有 009：本计划新增 `010_job_reports_target_dates.sql` 与 `011_filings.sql`。

---

### Task 1: Migration 010 + db.py job_reports 读写扩展

**Files:**
- Create: `migrations/010_job_reports_target_dates.sql`
- Modify: `investment_assistant/db.py:277-303`（insert_job_report）、`investment_assistant/db.py:349-364`（list_job_reports）
- Test: `tests/test_db_sql.py`、`tests/test_job_reports_repository.py`

**Interfaces:**
- Produces: `db.insert_job_report(conn, *, task, run_id, status, started_at, finished_at, summary, target_start_date: date|None = None, target_end_date: date|None = None, trigger_source: str = "scheduled") -> None`
- Produces: `db.list_job_reports(...)` 返回的每行 dict 多三个键：`target_start_date`、`target_end_date`、`trigger_source`

- [ ] **Step 1: 写失败测试**

在 `tests/test_db_sql.py` 末尾追加：

```python
def test_job_reports_target_dates_migration():
    sql = Path("migrations/010_job_reports_target_dates.sql").read_text()
    assert "ALTER TABLE job_reports" in sql
    assert "target_start_date DATE" in sql
    assert "target_end_date DATE" in sql
    assert "trigger_source TEXT NOT NULL DEFAULT 'scheduled'" in sql
```

在 `tests/test_job_reports_repository.py` 末尾追加（复用文件里已有的 FakeConn）：

```python
def test_insert_job_report_writes_target_dates_and_trigger():
    from datetime import date

    conn = FakeConn()
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    db.insert_job_report(
        conn, task="filings", run_id="filings-1", status="success",
        started_at=now, finished_at=now, summary={},
        target_start_date=date(2026, 6, 1), target_end_date=date(2026, 6, 30),
        trigger_source="manual",
    )
    sql, params = conn.store[0]
    assert "target_start_date" in sql and "trigger_source" in sql
    assert params["target_start_date"] == date(2026, 6, 1)
    assert params["trigger_source"] == "manual"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_sql.py::test_job_reports_target_dates_migration tests/test_job_reports_repository.py::test_insert_job_report_writes_target_dates_and_trigger -v`
Expected: FAIL（迁移文件不存在 / insert 不接受新参数）

- [ ] **Step 3: 写迁移与实现**

创建 `migrations/010_job_reports_target_dates.sql`：

```sql
-- 运行记录补充"指定日期"与触发来源：
-- target_start_date/target_end_date 为本次运行的目标数据日期（单日时两者相等），
-- trigger_source 区分定时(scheduled)与手动(manual)触发。
ALTER TABLE job_reports ADD COLUMN IF NOT EXISTS target_start_date DATE;
ALTER TABLE job_reports ADD COLUMN IF NOT EXISTS target_end_date DATE;
ALTER TABLE job_reports ADD COLUMN IF NOT EXISTS trigger_source TEXT NOT NULL DEFAULT 'scheduled';
```

`db.py` 中 `insert_job_report` 改为：

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
    target_start_date=None,
    target_end_date=None,
    trigger_source: str = "scheduled",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_reports (
              task, run_id, status, started_at, finished_at, summary,
              target_start_date, target_end_date, trigger_source
            )
            VALUES (
              %(task)s, %(run_id)s, %(status)s, %(started_at)s, %(finished_at)s, %(summary)s::jsonb,
              %(target_start_date)s, %(target_end_date)s, %(trigger_source)s
            )
            """,
            {
                "task": task,
                "run_id": run_id,
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "summary": json.dumps(summary or {}, ensure_ascii=False, default=str),
                "target_start_date": target_start_date,
                "target_end_date": target_end_date,
                "trigger_source": trigger_source,
            },
        )
        cur.execute("DELETE FROM job_reports WHERE created_at < now() - INTERVAL '30 days'")
    conn.commit()
```

`list_job_reports` 的 SELECT 与 keys 同步加三列：

```python
def list_job_reports(conn, *, task: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    where = "WHERE task = %(task)s" if task else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT task, run_id, status, started_at, finished_at, summary, created_at,
                   target_start_date, target_end_date, trigger_source
            FROM job_reports
            {where}
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """,
            {"task": task, "limit": limit},
        )
        rows = cur.fetchall()
    keys = ["task", "run_id", "status", "started_at", "finished_at", "summary", "created_at",
            "target_start_date", "target_end_date", "trigger_source"]
    return [dict(zip(keys, row)) for row in rows]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_db_sql.py tests/test_job_reports_repository.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add migrations/010_job_reports_target_dates.sql investment_assistant/db.py tests/test_db_sql.py tests/test_job_reports_repository.py
git commit -m "feat(db): job_reports 记录指定日期与触发来源（migration 010）"
```

---

### Task 2: harness 透传目标日期与触发来源

**Files:**
- Modify: `investment_assistant/tasks/_harness.py`
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: Task 1 的 `db.insert_job_report(..., target_start_date, target_end_date, trigger_source)`
- Produces: `run_task(task: str, fn, *, config, target_start_date: date|None = None, target_end_date: date|None = None, trigger_source: str = "scheduled") -> dict`
- Produces: 调用 `dispatch(task, status, summary, cfg, target_start_date=..., target_end_date=...)`（Task 3 实现该签名）

- [ ] **Step 1: 写失败测试**

在 `tests/test_harness.py` 末尾追加：

```python
def test_run_task_records_target_dates_and_trigger(monkeypatch):
    from datetime import date

    recorded = []
    monkeypatch.setattr(_harness, "_record", lambda **kw: recorded.append(kw))
    monkeypatch.setattr(_harness, "dispatch", lambda *a, **k: None)
    _harness.run_task(
        "filings", lambda: {}, config=AssistantConfig(),
        target_start_date=date(2026, 6, 1), target_end_date=date(2026, 6, 30),
        trigger_source="manual",
    )
    assert recorded[0]["target_start_date"] == date(2026, 6, 1)
    assert recorded[0]["target_end_date"] == date(2026, 6, 30)
    assert recorded[0]["trigger_source"] == "manual"


def test_run_task_passes_dates_to_dispatch(monkeypatch):
    from datetime import date

    sent = {}
    monkeypatch.setattr(_harness, "_record", lambda **kw: None)
    monkeypatch.setattr(
        _harness, "dispatch",
        lambda task, status, summary, cfg, **kw: sent.update(kw),
    )
    _harness.run_task(
        "metrics", lambda: {}, config=AssistantConfig(),
        target_start_date=date(2026, 7, 3), target_end_date=date(2026, 7, 3),
    )
    assert sent == {"target_start_date": date(2026, 7, 3), "target_end_date": date(2026, 7, 3)}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_harness.py -v`
Expected: 新增两个测试 FAIL（run_task 不接受新参数）

- [ ] **Step 3: 实现**

`_harness.py` 全量改为：

```python
from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from typing import Any, Callable

from investment_assistant.config import AssistantConfig
from investment_assistant.hermes.run_log import append_run
from investment_assistant.notify.notifier import dispatch


def run_task(
    task: str,
    fn: Callable[[], dict[str, Any]],
    *,
    config: AssistantConfig,
    target_start_date: date | None = None,
    target_end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
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
            finished_at=finished_at, summary=summary,
            target_start_date=target_start_date, target_end_date=target_end_date,
            trigger_source=trigger_source)
    from investment_assistant.services.settings import effective_notify_config
    dispatch(task, status, summary, effective_notify_config(config.notify),
             target_start_date=target_start_date, target_end_date=target_end_date)
    return {"run_id": run_id, "task": task, "status": status, "summary": summary}


def _record(*, task: str, run_id: str, status: str, started_at, finished_at,
            summary: dict[str, Any], target_start_date=None, target_end_date=None,
            trigger_source: str = "scheduled") -> None:
    append_run({"type": task, "run_id": run_id, "status": status, "summary": summary})
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return
    from investment_assistant.db import connect, insert_job_report

    with connect(database_url) as conn:
        insert_job_report(conn, task=task, run_id=run_id, status=status,
                          started_at=started_at, finished_at=finished_at, summary=summary,
                          target_start_date=target_start_date, target_end_date=target_end_date,
                          trigger_source=trigger_source)
```

注意：此时 `notify.dispatch` 还不接受 `target_start_date`/`target_end_date`——测试里 dispatch 已被 monkeypatch，因此 Task 2 可独立通过；真实签名在 Task 3 落地。**Task 2 与 Task 3 必须在同一次部署里上线。**

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_harness.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/tasks/_harness.py tests/test_harness.py
git commit -m "feat(tasks): run_task 透传目标日期与触发来源"
```

---

### Task 3: 通知实际日期 + 范围回补汇总模板

**Files:**
- Modify: `investment_assistant/notify/notifier.py`
- Modify: `investment_assistant/notify/templates.py:95-144`（metrics/filings/scores 三个 embed）
- Test: `tests/test_notifier.py`

**Interfaces:**
- Produces: `dispatch(task, status, summary, notify_cfg, *, client=None, target_start_date=None, target_end_date=None) -> dict`
- Produces: `templates.date_label_for(start: date|None, end: date|None) -> str`（"2026-07-03" 或 "2026-06-01 ~ 2026-06-30"，None 时取今天）
- Produces: 三个 embed 函数新签名 `xxx_embed(summary: dict, *, date_label: str | None = None) -> dict`
- Consumes: metrics/scores 范围回补 summary 的 `days` 数组（Task 4/5 产出，元素形如 `{"date": "...", "market_status"/"count": ..., "error"?: "..."}`）；filings summary 的 `filings[].filing_date`（Task 9 产出）

- [ ] **Step 1: 写失败测试**

在 `tests/test_notifier.py` 末尾追加：

```python
from datetime import date

from investment_assistant.notify import templates


def test_date_label_single_range_and_default():
    assert templates.date_label_for(date(2026, 7, 3), date(2026, 7, 3)) == "2026-07-03"
    assert templates.date_label_for(date(2026, 6, 1), date(2026, 6, 30)) == "2026-06-01 ~ 2026-06-30"
    assert templates.date_label_for(None, None) == date.today().isoformat()


def test_filings_embed_uses_actual_date_label():
    payload = templates.filings_digest_embed(
        {"downloaded_count": 0, "filings": []}, date_label="2026-06-01 ~ 2026-06-30")
    assert payload["embeds"][0]["title"] == "📄 财报 · 2026-06-01 ~ 2026-06-30"
    assert "昨日" not in payload["embeds"][0]["title"]


def test_metrics_embed_renders_backfill_days():
    summary = {"days": [
        {"date": "2026-06-01", "market_status": "green"},
        {"date": "2026-06-02", "error": "no data"},
    ]}
    payload = templates.metrics_summary_embed(summary, date_label="2026-06-01 ~ 2026-06-02")
    field = payload["embeds"][0]["fields"][0]
    assert "回补" in field["name"]
    assert "2026-06-01" in field["value"] and "GREEN" in field["value"]
    assert "no data" in field["value"]


def test_scores_embed_renders_backfill_days():
    summary = {"days": [{"date": "2026-06-01", "count": 4, "failures": 0}]}
    payload = templates.scores_summary_embed(summary, date_label="2026-06-01")
    assert payload["embeds"][0]["title"] == "📈 策略评分 · 2026-06-01"
    assert "4" in payload["embeds"][0]["fields"][0]["value"]


def test_dispatch_passes_date_label_into_embed():
    client = FakeClient()
    notifier.dispatch(
        "filings", "success", {"downloaded_count": 1, "filings": []}, NotifyConfig(),
        client=client, target_start_date=date(2026, 7, 3), target_end_date=date(2026, 7, 3),
    )
    assert client.sent[0][1]["embeds"][0]["title"] == "📄 财报 · 2026-07-03"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: 新增测试 FAIL（date_label_for 不存在）

- [ ] **Step 3: 实现**

`templates.py`：新增 `date_label_for`，改三个 embed（其余函数不动）：

```python
def date_label_for(start: date | None, end: date | None) -> str:
    if start is None:
        return date.today().isoformat()
    if end is None or end == start:
        return start.isoformat()
    return f"{start.isoformat()} ~ {end.isoformat()}"


def metrics_summary_embed(summary: dict, *, date_label: str | None = None) -> dict:
    label = date_label or date.today().isoformat()
    days = summary.get("days")
    if days:
        rows = "\n".join(
            f"• {d.get('date')} — " + (f"❌ {d.get('error')}" if d.get("error")
                                       else str(d.get("market_status", "?")).upper())
            for d in days[:15]
        ) or "无"
        fields = [{"name": f"回补 ({len(days)} 天)", "value": rows, "inline": False}]
    else:
        status = str(summary.get("market_status", "?")).upper()
        vix = summary.get("vix")
        tickers = summary.get("tickers", [])
        rows = "\n".join(f"• **{t.get('ticker')}** — {t.get('trend_state', '?')}" for t in tickers[:10]) or "无"
        fields = [
            {"name": "市场环境", "value": f"{status} | VIX {vix}", "inline": False},
            {"name": f"关注列表 ({len(tickers)})", "value": rows, "inline": False},
        ]
    return {
        "embeds": [{
            "title": f"🗓 每日指标 · {label}",
            "color": 3447003,
            "fields": fields,
            "footer": _footer(),
        }]
    }


def filings_digest_embed(summary: dict, *, date_label: str | None = None) -> dict:
    label = date_label or date.today().isoformat()
    filings = summary.get("filings", [])
    rows = "\n".join(
        f"• **{f.get('ticker')}** {f.get('form')} — {f.get('filing_date') or f.get('filed_at', '')}"
        for f in filings[:15]
    ) or "该日期无新财报"
    return {
        "embeds": [{
            "title": f"📄 财报 · {label}",
            "color": 15844367,
            "fields": [
                {"name": f"新提交 ({summary.get('downloaded_count', 0)})", "value": rows, "inline": False},
            ],
            "footer": _footer(),
        }]
    }


def scores_summary_embed(summary: dict, *, date_label: str | None = None) -> dict:
    label = date_label or date.today().isoformat()
    days = summary.get("days")
    if days:
        listing = "\n".join(
            f"• {d.get('date')} — " + (f"❌ {d.get('error')}" if d.get("error")
                                       else f"{d.get('count', 0)} 条评分")
            for d in days[:15]
        ) or "无"
        fields = [{"name": f"回补 ({len(days)} 天)", "value": listing, "inline": False}]
    else:
        rows = summary.get("rows", [])
        listing = "\n".join(f"• **{r.get('ticker')}** — {r.get('score')}" for r in rows[:10]) or "无评分"
        fields = [{"name": f"评分 ({len(rows)})", "value": listing, "inline": False}]
    return {
        "embeds": [{
            "title": f"📈 策略评分 · {label}",
            "color": 10070709,
            "fields": fields,
            "footer": _footer(),
        }]
    }
```

`notifier.py` 的 `dispatch` 改为：

```python
from investment_assistant.notify.templates import (
    date_label_for,
    filings_digest_embed,
    metrics_summary_embed,
    scores_summary_embed,
)

def dispatch(task: str, status: str, summary: dict[str, Any], notify_cfg, *,
             client=None, target_start_date=None, target_end_date=None) -> dict[str, Any]:
    if not notify_cfg.discord_enabled:
        return {"sent": False, "reason": "discord_disabled"}
    if notify_cfg.task_enabled.get(task) is False:
        return {"sent": False, "reason": "task_disabled"}
    channel_name = notify_cfg.task_channels.get(task)
    if not channel_name:
        return {"sent": False, "reason": "no_channel"}

    builder = _EMBED_BUILDERS.get(task)
    if builder:
        payload = builder(summary, date_label=date_label_for(target_start_date, target_end_date))
    else:
        payload = {"content": f"[{task}] {status}"}
    try:
        cli = client or DiscordClient.from_config(notify_cfg)
        cli.send(DiscordChannel(channel_name), payload)
        return {"sent": True, "channel": channel_name}
    except Exception as exc:  # 通知失败不拖垮任务；结构化返回
        return {"sent": False, "reason": f"send_failed: {exc}"}
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_notifier.py tests/test_notify_discord.py tests/test_harness.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/notify/notifier.py investment_assistant/notify/templates.py tests/test_notifier.py
git commit -m "feat(notify): 通知标题改用实际日期，支持范围回补汇总"
```

---

### Task 4: metrics 任务日期回补

**Files:**
- Modify: `investment_assistant/tasks/metrics.py`
- Test: `tests/test_metrics_task.py`

**Interfaces:**
- Consumes: Task 2 的 `run_task(..., target_start_date, target_end_date, trigger_source)`；`market.service.compute_market_signal_for_date(config.market, target_date, *, run_id)`（已存在）；`services.tickers.run_ticker_trend_scan(payload)` 已支持 `payload["date"]`
- Produces: `metrics.run(config, *, start_date: date|None = None, end_date: date|None = None, trigger_source: str = "scheduled") -> dict`
- Produces: 回补 summary 形如 `{"requested": {"from","to"}, "days": [{"date", "market_status"} | {"date", "error"}], "tickers_scanned": int, "errors": [...]}`

- [ ] **Step 1: 写失败测试**

在 `tests/test_metrics_task.py` 末尾追加：

```python
from datetime import date


def test_core_backfill_iterates_weekdays_and_skips_weekend(monkeypatch):
    scans = []
    monkeypatch.setattr(
        metrics, "compute_market_signal_for_date",
        lambda cfg, d, **kw: SimpleNamespace(market_status="green", signal_date=d))
    monkeypatch.setattr(
        metrics, "run_ticker_trend_scan",
        lambda payload: scans.append(payload) or {"rows": [], "count": 2, "failures": []})
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)

    # 2026-07-03 周五，07-04/05 周末跳过，07-06 周一
    summary = metrics._core(AssistantConfig(), start_date=date(2026, 7, 3), end_date=date(2026, 7, 6))
    assert [d["date"] for d in summary["days"]] == ["2026-07-03", "2026-07-06"]
    assert summary["tickers_scanned"] == 4
    assert scans[0]["date"] == "2026-07-03" and scans[0]["mode"] == "metrics"


def test_core_backfill_day_error_does_not_abort(monkeypatch):
    def boom(cfg, d, **kw):
        if d == date(2026, 7, 3):
            raise ValueError("no data")
        return SimpleNamespace(market_status="green", signal_date=d)

    monkeypatch.setattr(metrics, "compute_market_signal_for_date", boom)
    monkeypatch.setattr(metrics, "run_ticker_trend_scan",
                        lambda payload: {"rows": [], "count": 0, "failures": []})
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)

    summary = metrics._core(AssistantConfig(), start_date=date(2026, 7, 3), end_date=date(2026, 7, 6))
    assert summary["days"][0] == {"date": "2026-07-03", "error": "no data"}
    assert summary["days"][1]["market_status"] == "green"
    assert len(summary["errors"]) == 1


def test_run_passes_target_dates_to_harness(monkeypatch):
    captured = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured.update(kw)
        return {"run_id": "x", "task": task, "status": "success", "summary": {}}

    monkeypatch.setattr(metrics, "run_task", fake_run_task)
    metrics.run(AssistantConfig(), start_date=date(2026, 6, 1), end_date=date(2026, 6, 5),
                trigger_source="manual")
    assert captured == {
        "target_start_date": date(2026, 6, 1),
        "target_end_date": date(2026, 6, 5),
        "trigger_source": "manual",
    }
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_metrics_task.py -v`
Expected: 新增测试 FAIL（_core 不接受日期参数）

- [ ] **Step 3: 实现**

`metrics.py` 全量改为：

```python
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import date, timedelta
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.db import connect, upsert_market_signal
from investment_assistant.market.service import compute_market_signal, compute_market_signal_for_date
from investment_assistant.services.tickers import run_ticker_trend_scan
from investment_assistant.tasks._harness import run_task


def _core(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    if start_date is None:
        return _core_today(config)
    return _core_backfill(config, start_date, end_date or start_date)


def _core_today(config: AssistantConfig) -> dict[str, Any]:
    signal = compute_market_signal(config.market)
    _persist_signal(signal)
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


def _core_backfill(config: AssistantConfig, start: date, end: date) -> dict[str, Any]:
    days: list[dict[str, Any]] = []
    tickers_scanned = 0
    target = start
    while target <= end:
        if target.isoweekday() >= 6:  # 跳过周末
            target += timedelta(days=1)
            continue
        run_id = f"backfill-metrics-{target.isoformat()}-{uuid.uuid4().hex[:8]}"
        try:
            signal = compute_market_signal_for_date(config.market, target, run_id=run_id)
            _persist_signal(signal)
            scan = run_ticker_trend_scan({"mode": "metrics", "date": target.isoformat()})
            tickers_scanned += scan.get("count", 0)
            days.append({"date": target.isoformat(), "market_status": signal.market_status})
        except Exception as exc:  # 单日失败不中断整个范围
            days.append({"date": target.isoformat(), "error": str(exc)})
        target += timedelta(days=1)
    return {
        "requested": {"from": start.isoformat(), "to": end.isoformat()},
        "days": days,
        "tickers_scanned": tickers_scanned,
        "errors": [d for d in days if d.get("error")],
    }


def _persist_signal(signal) -> None:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if database_url:
        with connect(database_url) as conn:
            upsert_market_signal(conn, signal)


def run(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    target_start = start_date or date.today()
    target_end = end_date or target_start
    return run_task(
        "metrics",
        lambda: _core(config, start_date=start_date, end_date=end_date),
        config=config,
        target_start_date=target_start,
        target_end_date=target_end,
        trigger_source=trigger_source,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily 08:00 metrics task")
    parser.add_argument("--config", default=None)
    parser.add_argument("--date", default=None, help="回补指定单日（YYYY-MM-DD）")
    parser.add_argument("--from", dest="from_date", default=None, help="回补范围起始日（YYYY-MM-DD）")
    parser.add_argument("--to", dest="to_date", default=None, help="回补范围结束日（YYYY-MM-DD）")
    args = parser.parse_args()
    if args.date:
        start = end = date.fromisoformat(args.date)
    else:
        start = date.fromisoformat(args.from_date) if args.from_date else None
        end = date.fromisoformat(args.to_date) if args.to_date else None
    print(json.dumps(
        run(load_config(args.config), start_date=start, end_date=end, trigger_source="manual"),
        ensure_ascii=False, indent=2, default=str,
    ))


if __name__ == "__main__":
    main()
```

注意：原 `_core` 里的 DB 写入逻辑挪进了 `_persist_signal`，`test_core_builds_summary` 等既有测试对 `_core` 的行为不变（今天路径）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_metrics_task.py -v`
Expected: 全部 PASS（含既有测试）

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/tasks/metrics.py tests/test_metrics_task.py
git commit -m "feat(tasks): metrics 支持指定日期/范围历史回补"
```

---

### Task 5: scores 任务日期回补

**Files:**
- Modify: `investment_assistant/services/strategies.py:39-106`（strategy_input_snapshots、run_strategy_score_scan）
- Modify: `investment_assistant/tasks/nightly_scores.py`
- Test: `tests/test_scores_backfill.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `run_task(...)` 扩展签名
- Produces: `strategy_input_snapshots(signal_date: date|None = None)` — 传日期时只取该日快照
- Produces: `run_strategy_score_scan(payload)` 支持 `payload["date"]`（ISO 字符串）
- Produces: `nightly_scores.run(config, *, start_date=None, end_date=None, trigger_source="scheduled")`；回补 summary `{"requested", "days": [{"date","count","failures"}|{"date","error"}], "total", "note"}`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_scores_backfill.py`：

```python
from datetime import date

from investment_assistant.config import AssistantConfig
from investment_assistant.services import strategies
from investment_assistant.tasks import nightly_scores


def test_scan_passes_date_to_snapshot_query(monkeypatch):
    seen = {}

    def fake_snapshots(signal_date=None):
        seen["signal_date"] = signal_date
        return []

    monkeypatch.setattr(strategies, "strategy_input_snapshots", fake_snapshots)
    monkeypatch.setattr(strategies, "latest_strategy_market_context",
                        lambda: {"macro_state": "neutral"})
    out = strategies.run_strategy_score_scan({"mode": "backfill", "date": "2026-06-15"})
    assert seen["signal_date"] == date(2026, 6, 15)
    assert out["count"] == 0


def test_scores_core_backfill_aggregates_days(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "investment_assistant.services.strategies.run_strategy_score_scan",
        lambda payload: calls.append(payload) or {"count": 3, "failures": [], "rows": []})

    # 2026-07-03 周五 → 07-06 周一，周末跳过
    summary = nightly_scores._core(
        AssistantConfig(), start_date=date(2026, 7, 3), end_date=date(2026, 7, 6))
    assert [d["date"] for d in summary["days"]] == ["2026-07-03", "2026-07-06"]
    assert summary["total"] == 6
    assert calls[0]["date"] == "2026-07-03"
    assert "宏观" in summary["note"]


def test_scores_run_passes_target_dates(monkeypatch):
    captured = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured.update(kw)
        return {"status": "success"}

    monkeypatch.setattr(nightly_scores, "run_task", fake_run_task)
    nightly_scores.run(AssistantConfig(), start_date=date(2026, 6, 1),
                       end_date=date(2026, 6, 5), trigger_source="manual")
    assert captured["target_start_date"] == date(2026, 6, 1)
    assert captured["trigger_source"] == "manual"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_scores_backfill.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`strategies.py` 中 `strategy_input_snapshots` 改为（函数体内加 WHERE 过滤）：

```python
def strategy_input_snapshots(signal_date: date | None = None) -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return []
    where = "WHERE error IS NULL"
    params: dict[str, Any] = {}
    if signal_date is not None:
        where += " AND signal_date = %(signal_date)s"
        params["signal_date"] = signal_date
    try:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT DISTINCT ON (ticker)
                           id, ticker, signal_date, trend_state, attention_level,
                           trigger_reason, relative_strength_spy, relative_strength_qqq,
                           volume_ratio, run_id, created_at, updated_at
                    FROM ticker_signal_snapshots
                    {where}
                    ORDER BY ticker ASC, signal_date DESC, updated_at DESC
                    """,
                    params,
                )
                rows = cur.fetchall()
    except Exception:
        return []
    keys = [
        "id", "ticker", "signal_date", "trend_state", "attention_level",
        "trigger_reason", "relative_strength_spy", "relative_strength_qqq",
        "volume_ratio", "run_id", "created_at", "updated_at",
    ]
    return [dict(zip(keys, row)) for row in rows]
```

`run_strategy_score_scan` 开头两行改为：

```python
def run_strategy_score_scan(payload: dict[str, Any]) -> dict[str, Any]:
    raw_date = payload.get("date")
    target_date = date.fromisoformat(str(raw_date)) if raw_date else None
    snapshots = strategy_input_snapshots(signal_date=target_date)
    market = latest_strategy_market_context()
    # ...其余不变
```

`nightly_scores.py` 全量改为：

```python
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.tasks._harness import run_task


def _core(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    from investment_assistant.services.strategies import run_strategy_score_scan

    if start_date is None:
        return run_strategy_score_scan({"mode": "nightly"})

    days: list[dict[str, Any]] = []
    end = end_date or start_date
    target = start_date
    while target <= end:
        if target.isoweekday() >= 6:  # 跳过周末
            target += timedelta(days=1)
            continue
        try:
            result = run_strategy_score_scan({"mode": "backfill", "date": target.isoformat()})
            days.append({
                "date": target.isoformat(),
                "count": result.get("count", 0),
                "failures": len(result.get("failures", [])),
            })
        except Exception as exc:  # 单日失败不中断整个范围
            days.append({"date": target.isoformat(), "error": str(exc)})
        target += timedelta(days=1)
    return {
        "requested": {"from": start_date.isoformat(), "to": end.isoformat()},
        "days": days,
        "total": sum(d.get("count", 0) for d in days),
        "note": "宏观环境取当前状态（历史宏观未回放）",
    }


def run(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    target_start = start_date or date.today()
    target_end = end_date or target_start
    return run_task(
        "scores",
        lambda: _core(config, start_date=start_date, end_date=end_date),
        config=config,
        target_start_date=target_start,
        target_end_date=target_end,
        trigger_source=trigger_source,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Nightly strategy score task")
    parser.add_argument("--config", default=None)
    parser.add_argument("--date", default=None, help="回补指定单日（YYYY-MM-DD）")
    parser.add_argument("--from", dest="from_date", default=None, help="回补范围起始日（YYYY-MM-DD）")
    parser.add_argument("--to", dest="to_date", default=None, help="回补范围结束日（YYYY-MM-DD）")
    args = parser.parse_args()
    if args.date:
        start = end = date.fromisoformat(args.date)
    else:
        start = date.fromisoformat(args.from_date) if args.from_date else None
        end = date.fromisoformat(args.to_date) if args.to_date else None
    print(json.dumps(
        run(load_config(args.config), start_date=start, end_date=end, trigger_source="manual"),
        ensure_ascii=False, indent=2, default=str,
    ))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_scores_backfill.py tests/test_strategy_scoring.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/services/strategies.py investment_assistant/tasks/nightly_scores.py tests/test_scores_backfill.py
git commit -m "feat(tasks): scores 支持按历史日期回补评分"
```

---

### Task 6: filings / event_study 签名统一

**Files:**
- Modify: `investment_assistant/tasks/filings.py:36-46`（run）
- Modify: `investment_assistant/tasks/event_study.py:44-45`（run）
- Test: `tests/test_filings_task.py`、`tests/test_event_study_task.py`

**Interfaces:**
- Produces: `filings.run(config, *, start_date=None, end_date=None, trigger_source="scheduled")` — 自然目标日 T-1
- Produces: `event_study.run(config, *, start_date=None, end_date=None, trigger_source="scheduled")` — 内部映射 `since=start_date, asof=end_date`；`_core` 的 asof/since/kinds 签名不变（CLI main 仍用）

- [ ] **Step 1: 写失败测试**

在 `tests/test_filings_task.py` 末尾追加：

```python
def test_run_passes_natural_target_dates(monkeypatch):
    from datetime import date, timedelta

    from investment_assistant.config import AssistantConfig
    from investment_assistant.tasks import filings

    captured = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured.update(kw)
        return {"status": "success"}

    monkeypatch.setattr(filings, "run_task", fake_run_task)
    filings.run(AssistantConfig())
    yesterday = date.today() - timedelta(days=1)
    assert captured == {
        "target_start_date": yesterday,
        "target_end_date": yesterday,
        "trigger_source": "scheduled",
    }
```

在 `tests/test_event_study_task.py` 末尾追加：

```python
def test_run_maps_start_end_to_since_asof(monkeypatch):
    from datetime import date

    from investment_assistant.config import AssistantConfig
    from investment_assistant.tasks import event_study

    captured = {}
    core_args = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured.update(kw)
        fn()
        return {"status": "success"}

    monkeypatch.setattr(event_study, "run_task", fake_run_task)
    monkeypatch.setattr(event_study, "_core",
                        lambda config, **kw: core_args.update(kw) or {})
    event_study.run(AssistantConfig(), start_date=date(2026, 1, 1),
                    end_date=date(2026, 6, 30), trigger_source="manual")
    assert core_args == {"asof": date(2026, 6, 30), "since": date(2026, 1, 1)}
    assert captured["trigger_source"] == "manual"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_filings_task.py tests/test_event_study_task.py -v`
Expected: 新增测试 FAIL

- [ ] **Step 3: 实现**

`filings.py` 的 `run` 改为（`_core` 与 `main` 不变，`main` 里 `run(...)` 调用追加 `trigger_source="manual"`）：

```python
from datetime import date, timedelta  # 文件顶部 import 更新


def run(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    target_start = start_date or (date.today() - timedelta(days=1))  # 自然目标日 T-1
    target_end = end_date or target_start
    return run_task(
        "filings",
        lambda: _core(config, start_date=start_date, end_date=end_date),
        config=config,
        target_start_date=target_start,
        target_end_date=target_end,
        trigger_source=trigger_source,
    )
```

`event_study.py` 的 `run` 改为（`_core`、`main` 不变）：

```python
def run(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    trigger_source: str = "scheduled",
) -> dict[str, Any]:
    target_start = start_date or date.today()
    target_end = end_date or target_start
    return run_task(
        "event_study",
        lambda: _core(config, asof=end_date, since=start_date),
        config=config,
        target_start_date=target_start,
        target_end_date=target_end,
        trigger_source=trigger_source,
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_filings_task.py tests/test_event_study_task.py tests/test_scheduler.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/tasks/filings.py investment_assistant/tasks/event_study.py tests/test_filings_task.py tests/test_event_study_task.py
git commit -m "feat(tasks): filings/event_study 统一日期签名与目标日记录"
```

---

### Task 7: API 统一日期校验 + 删除运维指标后端

**Files:**
- Modify: `investment_assistant/services/jobs.py`
- Modify: `investment_assistant/api/routes/jobs.py`（删 `/api/jobs/metrics` 路由）
- Modify: `investment_assistant/db.py:367-391`（删 `job_report_metrics`）
- Test: `tests/test_services_jobs.py`、`tests/test_jobs_repository.py`

**Interfaces:**
- Consumes: 4 个任务的 `run(config, *, start_date, end_date, trigger_source)`（Task 4/5/6）
- Produces: `jobs._date_kwargs(payload) -> dict`（空 dict 或 `{"start_date": date, "end_date": date}`）；`MAX_RANGE_DAYS = 92`
- Produces: `trigger_job(name, payload)` 对所有任务传日期并固定 `trigger_source="manual"`
- Removes: `jobs.job_metrics`、`db.job_report_metrics`、`GET /api/jobs/metrics`

- [ ] **Step 1: 更新测试（含失败的新用例）**

`tests/test_services_jobs.py`：
1. 把所有 fake REGISTRY 的 lambda 改为接受 `**kw`（trigger_job 现在总是传 `trigger_source`）：`lambda config, **kw: ...`；
2. `test_trigger_job_filings_passes_date_range` / `test_trigger_job_filings_single_date` 的断言改为包含 trigger_source：

```python
    assert seen == {"start_date": date(2026, 6, 1), "end_date": date(2026, 6, 30),
                    "trigger_source": "manual"}
```
（单日用例同理：`{"start_date": date(2026, 6, 15), "end_date": date(2026, 6, 15), "trigger_source": "manual"}`）

3. `test_trigger_job_submits` 断言不变（无日期时仅多 trigger_source，改 lambda 即可）。
4. 末尾追加：

```python
def test_trigger_job_metrics_accepts_dates(monkeypatch):
    from datetime import date

    seen = {}
    monkeypatch.setattr(jobs, "REGISTRY", {"metrics": lambda config, **kw: seen.update(kw) or {}})
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    submitted = {}
    monkeypatch.setattr(jobs.runner, "submit", lambda kind, fn: submitted.update({"fn": fn}) or "run-9")
    jobs.trigger_job("metrics", {"date": "2026-06-15"})
    submitted["fn"]()
    assert seen == {"start_date": date(2026, 6, 15), "end_date": date(2026, 6, 15),
                    "trigger_source": "manual"}


def test_trigger_job_rejects_future_date(monkeypatch):
    from datetime import date, timedelta

    monkeypatch.setattr(jobs, "REGISTRY", {"metrics": lambda config, **kw: {}})
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        jobs.trigger_job("metrics", {"date": tomorrow})
```

`tests/test_jobs_repository.py`：删除 `test_job_report_metrics_aggregates`（第 60 行起的函数）。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_services_jobs.py -v`
Expected: 新用例 FAIL（metrics 不传日期 / 未来日期不报错）

- [ ] **Step 3: 实现**

`services/jobs.py`：删除 `job_metrics`、`MAX_FILINGS_RANGE_DAYS`、`_filings_kwargs`，改为：

```python
MAX_RANGE_DAYS = 92  # 所有任务共用：一次最多回补约一个季度


def _date_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    raw_date = payload.get("date")
    raw_from = payload.get("from") or payload.get("start_date")
    raw_to = payload.get("to") or payload.get("end_date")
    if raw_date:
        start = end = date.fromisoformat(str(raw_date))
    elif raw_from or raw_to:
        if not raw_from or not raw_to:
            raise ValueError("from and to are both required for a range")
        start = date.fromisoformat(str(raw_from))
        end = date.fromisoformat(str(raw_to))
    else:
        return {}
    if end < start:
        raise ValueError("to must be greater than or equal to from")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValueError(f"date range is limited to {MAX_RANGE_DAYS} days")
    if end > date.today():
        raise ValueError("date must not be in the future")
    return {"start_date": start, "end_date": end}


def trigger_job(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in REGISTRY:
        raise UnknownJobError(f"unknown job: {name}")
    config = load_config()
    kwargs = _date_kwargs(payload or {})
    run_id = runner.submit(name, lambda: REGISTRY[name](config, trigger_source="manual", **kwargs))
    return {"run_id": run_id, "status": "pending"}
```

同时删掉文件顶部不再使用的 `datetime`/`timedelta` import（保留 `date`）。

`api/routes/jobs.py`：删除 `metrics` 路由（第 21-23 行）。

`db.py`：删除 `job_report_metrics` 函数（第 367-391 行）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_services_jobs.py tests/test_jobs_repository.py tests/test_api_app.py tests/test_api_contract.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/services/jobs.py investment_assistant/api/routes/jobs.py investment_assistant/db.py tests/test_services_jobs.py tests/test_jobs_repository.py
git commit -m "feat(api): 全任务统一日期校验；删除运维指标后端接口"
```

---

### Task 8: Migration 011 filings 表 + db 读写函数

**Files:**
- Create: `migrations/011_filings.sql`
- Modify: `investment_assistant/db.py`（文件末尾追加 4 个函数）
- Test: `tests/test_db_sql.py`、`tests/test_filings_repository.py`（新建）

**Interfaces:**
- Produces: `db.upsert_filing(conn, *, ticker, form, filing_date, accession_number, primary_document, file_path, run_id=None) -> None`
- Produces: `db.list_filings(conn, *, ticker=None, form=None, start_date=None, end_date=None, limit=50) -> list[dict]`（键：id/ticker/form/filing_date/accession_number/primary_document/file_path/downloaded_at/created_at）
- Produces: `db.get_filing(conn, filing_id) -> dict | None`（同上键）
- Produces: `db.list_filing_tickers(conn) -> list[str]`

- [ ] **Step 1: 写失败测试**

`tests/test_db_sql.py` 末尾追加：

```python
def test_filings_migration_defines_index_table():
    sql = Path("migrations/011_filings.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS filings" in sql
    assert "ticker TEXT NOT NULL" in sql
    assert "form TEXT NOT NULL" in sql
    assert "filing_date DATE NOT NULL" in sql
    assert "accession_number TEXT NOT NULL" in sql
    assert "UNIQUE (accession_number, primary_document)" in sql
    assert "idx_filings_ticker_date" in sql
```

创建 `tests/test_filings_repository.py`：

```python
from datetime import date

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

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class FakeConn:
    def __init__(self):
        self.store = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.commits += 1


def test_upsert_filing_conflicts_on_accession():
    conn = FakeConn()
    db.upsert_filing(
        conn, ticker="AAPL", form="10-Q", filing_date=date(2026, 6, 28),
        accession_number="acc-1", primary_document="q.htm",
        file_path="/data/AAPL/10-Q/acc-1-q.htm",
    )
    sql, params = conn.store[0]
    assert "INSERT INTO filings" in sql
    assert "ON CONFLICT (accession_number, primary_document)" in sql
    assert params["ticker"] == "AAPL" and params["run_id"] is None
    assert conn.commits == 1


def test_list_filings_applies_filters():
    conn = FakeConn()
    db.list_filings(conn, ticker="AAPL", form="10-Q",
                    start_date=date(2026, 1, 1), end_date=date(2026, 6, 30), limit=20)
    sql, params = conn.store[0]
    assert "ticker = %(ticker)s" in sql and "form = %(form)s" in sql
    assert "filing_date >= %(start_date)s" in sql and "filing_date <= %(end_date)s" in sql
    assert params["limit"] == 20


def test_get_filing_by_id_returns_none_when_missing():
    assert db.get_filing(FakeConn(), 42) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_sql.py::test_filings_migration_defines_index_table tests/test_filings_repository.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

创建 `migrations/011_filings.sql`：

```sql
-- 财报文件索引：sec_downloader 每下载/发现一份文件写一行，
-- 供数据模块「财报」Tab 筛选与单个下载；文件本体仍在文件系统。
CREATE TABLE IF NOT EXISTS filings (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  form TEXT NOT NULL,
  filing_date DATE NOT NULL,
  accession_number TEXT NOT NULL,
  primary_document TEXT NOT NULL,
  file_path TEXT NOT NULL,
  run_id TEXT,
  downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (accession_number, primary_document)
);
CREATE INDEX IF NOT EXISTS idx_filings_ticker_date ON filings (ticker, filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_filings_date ON filings (filing_date DESC);
```

`db.py` 末尾追加：

```python
_FILING_KEYS = ["id", "ticker", "form", "filing_date", "accession_number",
                "primary_document", "file_path", "downloaded_at", "created_at"]


def upsert_filing(
    conn, *, ticker: str, form: str, filing_date, accession_number: str,
    primary_document: str, file_path: str, run_id: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filings (
              ticker, form, filing_date, accession_number, primary_document, file_path, run_id
            ) VALUES (
              %(ticker)s, %(form)s, %(filing_date)s, %(accession_number)s,
              %(primary_document)s, %(file_path)s, %(run_id)s
            )
            ON CONFLICT (accession_number, primary_document) DO UPDATE SET
              file_path = EXCLUDED.file_path,
              run_id = COALESCE(EXCLUDED.run_id, filings.run_id)
            """,
            {
                "ticker": ticker, "form": form, "filing_date": filing_date,
                "accession_number": accession_number, "primary_document": primary_document,
                "file_path": file_path, "run_id": run_id,
            },
        )
    conn.commit()


def list_filings(conn, *, ticker: str | None = None, form: str | None = None,
                 start_date=None, end_date=None, limit: int = 50) -> list[dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if ticker:
        clauses.append("ticker = %(ticker)s")
        params["ticker"] = ticker
    if form:
        clauses.append("form = %(form)s")
        params["form"] = form
    if start_date is not None:
        clauses.append("filing_date >= %(start_date)s")
        params["start_date"] = start_date
    if end_date is not None:
        clauses.append("filing_date <= %(end_date)s")
        params["end_date"] = end_date
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, ticker, form, filing_date, accession_number,
                   primary_document, file_path, downloaded_at, created_at
            FROM filings
            {where}
            ORDER BY filing_date DESC, ticker ASC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()
    return [dict(zip(_FILING_KEYS, row)) for row in rows]


def get_filing(conn, filing_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ticker, form, filing_date, accession_number,
                   primary_document, file_path, downloaded_at, created_at
            FROM filings
            WHERE id = %(id)s
            """,
            {"id": filing_id},
        )
        row = cur.fetchone()
    return dict(zip(_FILING_KEYS, row)) if row else None


def list_filing_tickers(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM filings ORDER BY ticker")
        rows = cur.fetchall()
    return [row[0] for row in rows]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_db_sql.py tests/test_filings_repository.py tests/test_migration_runner.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add migrations/011_filings.sql investment_assistant/db.py tests/test_db_sql.py tests/test_filings_repository.py
git commit -m "feat(db): filings 财报索引表与读写函数（migration 011）"
```

---

### Task 9: 下载器返回元数据并写索引

**Files:**
- Modify: `investment_assistant/filings/sec_downloader.py:55-85`（download_filings_batch）
- Modify: `investment_assistant/filings/service.py`
- Modify: `investment_assistant/tasks/filings.py:14-33`（_core）
- Test: `tests/test_sec_downloader.py`、`tests/test_filing_service.py`、`tests/test_filings_task.py`

**Interfaces:**
- Consumes: Task 8 的 `db.upsert_filing(...)`
- Produces: `SecEdgarDownloader.download_filings_batch(...) -> list[dict]`，元素：`{"ticker", "form", "filing_date", "accession_number", "primary_document", "path", "downloaded": bool}`（文件已存在时 `downloaded=False`，跳过下载但仍返回元数据）
- Produces: `download_configured_filings(...) -> {"downloaded_count": int(仅新下载), "filings": [meta...], "errors": {...}}`，并把索引 upsert 进 filings 表（无 DB 时静默跳过）
- Produces: filings 任务 summary 的 `filings[]` 含 `filing_date`（Task 3 的 embed 消费）

- [ ] **Step 1: 更新测试**

`tests/test_sec_downloader.py`：两个既有测试的断言从 Path 改为 dict——

```python
    # test_download_filters_by_form_and_yesterday 末尾改为：
    assert len(out) == 1
    assert out[0]["form"] == "10-Q"
    assert out[0]["ticker"] == "AAPL"
    assert out[0]["filing_date"] == "2026-06-28"
    assert out[0]["accession_number"] == "acc-q"
    assert out[0]["primary_document"] == "q.htm"
    assert out[0]["downloaded"] is True
```

（`test_download_date_range_hits_multiple_days` 仅保留 `assert len(out) == 2`。）

末尾追加：

```python
def test_download_skips_existing_file_but_returns_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    tickers_json = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}
    submissions_json = {"filings": {"recent": {
        "form": ["10-Q"],
        "filingDate": ["2026-06-28"],
        "accessionNumber": ["acc-q"],
        "primaryDocument": ["q.htm"],
    }}}
    dest = tmp_path / "filings" / "AAPL" / "10-Q" / "acc-q-q.htm"
    dest.parent.mkdir(parents=True)
    dest.write_text("<html>cached</html>")
    called = []
    monkeypatch.setattr(sec_downloader, "_download_document",
                        lambda url, d, *, headers: called.append(url))

    dl = SecEdgarDownloader(getter=make_getter(tickers_json, submissions_json), cache_dir=tmp_path)
    out = dl.download_filings_batch(
        "AAPL", ["10-Q"], date(2026, 6, 28), date(2026, 6, 28), tmp_path / "filings")
    assert called == []  # 未重复下载
    assert out[0]["downloaded"] is False
    assert out[0]["path"] == str(dest)
```

`tests/test_filing_service.py`：FakeDownloader 改为返回元数据，并断言写索引——

```python
from datetime import date, timedelta
from pathlib import Path

from investment_assistant.config import FilingsConfig
from investment_assistant.filings import service
from investment_assistant.filings.service import download_configured_filings


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download_filings_batch(self, ticker, form_types, start_date, end_date, output_base):
        self.calls.append((ticker, form_types, start_date, end_date, output_base))
        path = Path(output_base) / ticker / form_types[0] / "000-test.htm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html>ok</html>")
        return [{
            "ticker": ticker, "form": form_types[0], "filing_date": str(start_date),
            "accession_number": "000", "primary_document": "test.htm",
            "path": str(path), "downloaded": True,
        }]


def test_download_configured_filings_uses_runtime_output_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    cfg = FilingsConfig(forms=["10-Q", "10-K"], lookback_years=1, output_dir=tmp_path / "filings")
    downloader = FakeDownloader()

    result = download_configured_filings(["NVDA"], cfg, downloader=downloader)

    assert downloader.calls[0][0] == "NVDA"
    assert downloader.calls[0][1] == ["10-Q", "10-K"]
    assert downloader.calls[0][4] == tmp_path / "filings"
    assert result["downloaded_count"] == 1
    assert result["filings"][0]["ticker"] == "NVDA"


def test_download_defaults_to_t_minus_1(tmp_path, monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    cfg = FilingsConfig(forms=["10-Q"], lookback_years=1, output_dir=tmp_path / "filings")
    downloader = FakeDownloader()

    download_configured_filings(["NVDA"], cfg, downloader=downloader)

    yesterday = date.today() - timedelta(days=1)
    assert downloader.calls[0][2] == yesterday
    assert downloader.calls[0][3] == yesterday


def test_download_passes_explicit_date_range(tmp_path, monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    cfg = FilingsConfig(forms=["10-Q"], lookback_years=1, output_dir=tmp_path / "filings")
    downloader = FakeDownloader()

    download_configured_filings(
        ["NVDA"], cfg, downloader=downloader,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )

    assert downloader.calls[0][2] == date(2026, 6, 1)
    assert downloader.calls[0][3] == date(2026, 6, 30)


def test_download_persists_filing_index(tmp_path, monkeypatch):
    cfg = FilingsConfig(forms=["10-Q"], lookback_years=1, output_dir=tmp_path / "filings")
    persisted = []
    monkeypatch.setattr(service, "_persist_filing_index", lambda metas: persisted.extend(metas))

    download_configured_filings(["NVDA"], cfg, downloader=FakeDownloader())
    assert persisted and persisted[0]["accession_number"] == "000"
```

`tests/test_filings_task.py`：`_core` 相关断言改为消费元数据（找到构造 fake `download_configured_filings` 的测试，把返回值改为 `{"downloaded_count": 1, "filings": [{"ticker": "NVDA", "form": "10-Q", "filing_date": "2026-06-28", "path": "/x/NVDA/10-Q/a.htm", "downloaded": True}], "errors": {}}`，断言 `summary["filings"][0]["filing_date"] == "2026-06-28"`）。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_sec_downloader.py tests/test_filing_service.py tests/test_filings_task.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`sec_downloader.py` 的循环体改为：

```python
        out: list[dict[str, Any]] = []
        for i, form in enumerate(forms):
            if form not in form_types or not (first_day <= str(dates[i]) <= last_day):
                continue
            accession = accns[i]
            doc = docs[i] if i < len(docs) and docs[i] else f"{accession}.txt"
            doc_name = Path(doc).name
            dest = Path(output_base) / ticker.upper() / form / f"{accession}-{doc_name}"
            downloaded = False
            if not dest.exists():  # 已存在则跳过下载，但仍返回元数据供索引回补
                url = ARCHIVE_DOC_URL.format(
                    cik_int=int(cik), accession_nodash=accession.replace("-", ""), doc=doc
                )
                _download_document(url, dest, headers=self._headers(ua))
                downloaded = True
            out.append({
                "ticker": ticker.upper(),
                "form": form,
                "filing_date": str(dates[i]),
                "accession_number": accession,
                "primary_document": doc_name,
                "path": str(dest),
                "downloaded": downloaded,
            })
        return out
```

（返回类型注解改为 `list[dict[str, Any]]`，`Protocol` 同步改。）

`service.py` 全量改为：

```python
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Protocol

from investment_assistant.config import FilingsConfig


class FilingDownloader(Protocol):
    def download_filings_batch(
        self, ticker: str, form_types: list[str], start_date: date, end_date: date, output_base
    ) -> list[dict[str, Any]]:
        ...


def _default_downloader() -> FilingDownloader:
    from investment_assistant.filings.sec_downloader import SecEdgarDownloader

    return SecEdgarDownloader()


def download_configured_filings(
    tickers: list[str],
    cfg: FilingsConfig,
    *,
    downloader: FilingDownloader | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    dl = downloader or _default_downloader()
    first = start_date or (date.today() - timedelta(days=1))  # 默认昨日 T-1
    last = end_date or first
    filings_meta: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for raw in tickers:
        ticker = str(raw or "").strip().upper()
        if not ticker:
            continue
        try:
            filings_meta.extend(dl.download_filings_batch(ticker, list(cfg.forms), first, last, cfg.output_dir))
        except Exception as exc:  # 单标的失败不影响其余
            errors[ticker] = str(exc)
    _persist_filing_index(filings_meta)
    return {
        "downloaded_count": sum(1 for m in filings_meta if m.get("downloaded")),
        "filings": filings_meta,
        "errors": errors,
    }


def _persist_filing_index(filings_meta: list[dict[str, Any]]) -> None:
    if not filings_meta:
        return
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return
    from investment_assistant.db import connect, upsert_filing

    with connect(database_url) as conn:
        for meta in filings_meta:
            upsert_filing(
                conn,
                ticker=meta["ticker"],
                form=meta["form"],
                filing_date=date.fromisoformat(meta["filing_date"]),
                accession_number=meta["accession_number"],
                primary_document=meta["primary_document"],
                file_path=meta["path"],
            )
```

`tasks/filings.py` 的 `_core` 改为（不再解析路径）：

```python
def _core(
    config: AssistantConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    result = download_configured_filings(
        config.watchlist, config.filings, start_date=start_date, end_date=end_date
    )
    return {
        "downloaded_count": result.get("downloaded_count", 0),
        "filings": [
            {"ticker": m.get("ticker"), "form": m.get("form"),
             "filing_date": m.get("filing_date"), "path": m.get("path")}
            for m in result.get("filings", [])
        ],
        "errors": result.get("errors", {}),
    }
```

（顶部 `from pathlib import Path` 若不再使用则删除。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_sec_downloader.py tests/test_filing_service.py tests/test_filings_task.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/filings/sec_downloader.py investment_assistant/filings/service.py investment_assistant/tasks/filings.py tests/test_sec_downloader.py tests/test_filing_service.py tests/test_filings_task.py
git commit -m "feat(filings): 下载器返回元数据并写 filings 索引表"
```

---

### Task 10: 财报查询/下载 API + 移除旧 /api/filings

**Files:**
- Create: `investment_assistant/services/filings.py`
- Create: `investment_assistant/api/routes/filings.py`
- Modify: `investment_assistant/api/routes/__init__.py`
- Modify: `investment_assistant/api/routes/status.py`（删 `/api/filings` 路由）
- Modify: `investment_assistant/services/status.py`（删 `filing_rows`；`filing_status` 保留——`status_payload` 还在用）
- Test: `tests/test_services_filings.py`（新建）、`tests/test_dashboard_server.py`

**Interfaces:**
- Consumes: Task 8 的 `db.list_filings/get_filing/list_filing_tickers`
- Produces: `GET /api/filings/records?ticker=&form=&from=&to=&limit=` → `{"records": [...], "tickers": [...], "degraded": bool}`
- Produces: `GET /api/filings/records/{filing_id}/download` → FileResponse（htm）；记录不存在或文件丢失 → 404
- Removes: `GET /api/filings`、`status.filing_rows`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_services_filings.py`：

```python
import pytest

from investment_assistant.services import filings as filings_svc


def test_filing_records_degraded_without_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = filings_svc.filing_records()
    assert out == {"records": [], "tickers": [], "degraded": True}


def test_filing_records_queries_db(monkeypatch):
    from datetime import date

    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    seen = {}
    monkeypatch.setattr(filings_svc, "connect", lambda url: _FakeCtx("CONN"))
    monkeypatch.setattr(filings_svc.db, "list_filings",
                        lambda conn, **kw: seen.update(kw) or [{"id": 1, "ticker": "AAPL"}])
    monkeypatch.setattr(filings_svc.db, "list_filing_tickers", lambda conn: ["AAPL"])
    out = filings_svc.filing_records(ticker="AAPL", form="10-Q",
                                     from_="2026-01-01", to="2026-06-30", limit=20)
    assert out["records"][0]["ticker"] == "AAPL" and out["tickers"] == ["AAPL"]
    assert seen["start_date"] == date(2026, 1, 1) and seen["limit"] == 20


class _FakeCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *a):
        return False


def test_download_path_missing_record_raises_lookup(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(filings_svc, "connect", lambda url: _FakeCtx("CONN"))
    monkeypatch.setattr(filings_svc.db, "get_filing", lambda conn, i: None)
    with pytest.raises(LookupError):
        filings_svc.filing_download_path(42)


def test_download_path_missing_file_raises_filenotfound(monkeypatch, tmp_path):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(filings_svc, "connect", lambda url: _FakeCtx("CONN"))
    monkeypatch.setattr(filings_svc.db, "get_filing",
                        lambda conn, i: {"id": i, "file_path": str(tmp_path / "gone.htm")})
    with pytest.raises(FileNotFoundError):
        filings_svc.filing_download_path(1)


def test_download_route_404s(client, monkeypatch):
    monkeypatch.setattr(filings_svc, "filing_download_path",
                        lambda i: (_ for _ in ()).throw(LookupError("filing 9 not found")))
    resp = client.get("/api/filings/records/9/download")
    assert resp.status_code == 404


def test_download_route_serves_file(client, monkeypatch, tmp_path):
    f = tmp_path / "a.htm"
    f.write_text("<html>report</html>")
    monkeypatch.setattr(filings_svc, "filing_download_path", lambda i: f)
    resp = client.get("/api/filings/records/1/download")
    assert resp.status_code == 200
    assert b"report" in resp.content
```

`tests/test_dashboard_server.py`：删除对 `GET /api/filings` 与 `filing_rows` 的断言（第 33-39 行附近，保留同函数中其它路由的断言；若该测试函数只测 /api/filings 则整个删除）。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_services_filings.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

创建 `investment_assistant/services/filings.py`：

```python
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from investment_assistant import db
from investment_assistant.db import connect


def _parse_date(raw: str | None) -> date | None:
    return date.fromisoformat(str(raw)) if raw else None


def filing_records(*, ticker: str | None = None, form: str | None = None,
                   from_: str | None = None, to: str | None = None,
                   limit: int = 50) -> dict[str, Any]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return {"records": [], "tickers": [], "degraded": True}
    start_date = _parse_date(from_)
    end_date = _parse_date(to)
    with connect(database_url) as conn:
        records = db.list_filings(conn, ticker=ticker or None, form=form or None,
                                  start_date=start_date, end_date=end_date, limit=limit)
        tickers = db.list_filing_tickers(conn)
    return {"records": records, "tickers": tickers, "degraded": False}


def filing_download_path(filing_id: int) -> Path:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        raise LookupError("database is not configured")
    with connect(database_url) as conn:
        row = db.get_filing(conn, filing_id)
    if row is None:
        raise LookupError(f"filing {filing_id} not found")
    path = Path(row["file_path"])
    if not path.is_file():
        raise FileNotFoundError(f"filing file missing: {path}")
    return path
```

创建 `investment_assistant/api/routes/filings.py`：

```python
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from investment_assistant.api.http import parse_int
from investment_assistant.services import filings as _filings

router = APIRouter()


@router.get("/api/filings/records")
def records(ticker: str | None = None, form: str | None = None,
            from_: str | None = Query(default=None, alias="from"),
            to: str | None = None, limit: str | None = None):
    return _filings.filing_records(
        ticker=ticker, form=form, from_=from_, to=to,
        limit=parse_int(limit, default=50, minimum=1, maximum=500),
    )


@router.get("/api/filings/records/{filing_id}/download")
def download(filing_id: int):
    try:
        path = _filings.filing_download_path(filing_id)
    except (LookupError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, filename=path.name)
```

`routes/__init__.py` 改为：

```python
from . import status, market, tickers, strategies, hermes, watchlist, runs, jobs, settings, research, filings

ALL_ROUTERS = [
    status.router, market.router, tickers.router, strategies.router,
    hermes.router, watchlist.router, runs.router, jobs.router,
    settings.router, research.router, filings.router,
]
```

`routes/status.py`：删除 `filings()` 路由（第 25-27 行）。`services/status.py`：删除 `filing_rows`（第 32-52 行）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_services_filings.py tests/test_dashboard_server.py tests/test_services_status.py tests/test_api_contract.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/services/filings.py investment_assistant/api/routes/filings.py investment_assistant/api/routes/__init__.py investment_assistant/api/routes/status.py investment_assistant/services/status.py tests/test_services_filings.py tests/test_dashboard_server.py
git commit -m "feat(api): 财报索引查询与单个下载接口，移除旧 /api/filings"
```

---

### Task 11: 前端 api.ts 更新

**Files:**
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/app.test.ts`（mock 键同步）

**Interfaces:**
- Produces: `getFilingRecords(params?) -> Promise<{records: FilingRecord[]; tickers: string[]; degraded: boolean}>`
- Produces: `filingDownloadUrl(id: number) -> string`
- Removes: `getFilings`、`getJobMetrics`、`fetchMarketSignals`

- [ ] **Step 1: 修改 api.ts**

删除第 62 行 `getFilings`、第 67 行 `fetchMarketSignals`、第 88-91 行 `getJobMetrics`。在文件末尾（research 段之后）追加：

```ts
// filings
export interface FilingRecord {
  id: number
  ticker: string
  form: string
  filing_date: string
  accession_number: string
  primary_document: string
  file_path: string
  downloaded_at: string
  created_at: string
}
export const getFilingRecords = (
  params: { ticker?: string; form?: string; from?: string; to?: string; limit?: number } = {},
) => {
  const q = new URLSearchParams()
  if (params.ticker) q.set('ticker', params.ticker)
  if (params.form) q.set('form', params.form)
  if (params.from) q.set('from', params.from)
  if (params.to) q.set('to', params.to)
  q.set('limit', String(params.limit ?? 100))
  return get<{ records: FilingRecord[]; tickers: string[]; degraded: boolean }>(
    `/api/filings/records?${q.toString()}`,
  )
}
export const filingDownloadUrl = (id: number) => `/api/filings/records/${id}/download`
```

- [ ] **Step 2: 修改 app.test.ts mocks**

在 `web/src/app.test.ts` 的 api mock 对象里删除 `getFilings`、`getJobMetrics`、`fetchMarketSignals` 三个键，追加：

```ts
  getFilingRecords: vi.fn(async () => ({ records: [], tickers: [], degraded: false })),
```

- [ ] **Step 3: 运行确认（编译 + 既有测试）**

Run: `cd web && npx vitest run src/app.test.ts src/lib/api.test.ts`
Expected: PASS（Tools.test.ts 此时会因 fetchMarketSignals 被删而编译失败——属预期，Task 12 修复；不要在本步运行全量测试）

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/api.ts web/src/app.test.ts
git commit -m "feat(ui): api 客户端增加财报接口，移除运维指标/手动信号抓取"
```

---

### Task 12: Tools 页收敛 + 运行记录表格/弹窗 + SideNav

**Files:**
- Modify: `web/src/routes/Tools.svelte`（大改，见下方完整文件）
- Modify: `web/src/lib/components/SideNav.svelte:9-15`（删 ops/results 两个 child）
- Test: `web/src/routes/Tools.test.ts`（重写受影响用例）

**Interfaces:**
- Consumes: `api.runJob(name, payload)`、`api.getJobReports` 返回行的 `target_start_date/target_end_date/trigger_source`（Task 1/7 产出）
- Consumes: `FetchDateModal`（props：open/title/description/defaultLabel/defaultPayload/maxRangeDays/onConfirm/onclose，onConfirm 收 `{}` | `{date}` | `{from,to}`）

- [ ] **Step 1: 更新 Tools.test.ts**

保留前三个用例（jobs 渲染、? 弹窗、秒级时间）。删除三个 `fetchMarketSignals` 用例与旧 filings 用例，替换为：

```ts
  it('dated run via modal passes date range to runJob', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'metrics', time_local: '08:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    const spy = vi.spyOn(api, 'runJob').mockResolvedValue({ run_id: 'r1', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByText('按日期运行'))
    await fireEvent.click(await screen.findByText('日期范围'))
    await fireEvent.input(document.querySelector('#fetch-range-from') as HTMLInputElement, { target: { value: '2026-06-01' } })
    await fireEvent.input(document.querySelector('#fetch-range-to') as HTMLInputElement, { target: { value: '2026-06-30' } })
    await fireEvent.click(await screen.findByText('确认'))
    expect(spy).toHaveBeenCalledWith('metrics', { from: '2026-06-01', to: '2026-06-30' })
  })

  it('dated run modal rejects ranges over 92 days', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'filings', time_local: '09:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    const spy = vi.spyOn(api, 'runJob').mockResolvedValue({ run_id: 'r1', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByText('按日期运行'))
    await fireEvent.click(await screen.findByText('日期范围'))
    await fireEvent.input(document.querySelector('#fetch-range-from') as HTMLInputElement, { target: { value: '2026-01-01' } })
    await fireEvent.input(document.querySelector('#fetch-range-to') as HTMLInputElement, { target: { value: '2026-06-30' } })
    expect(await screen.findByText('超出上限：一次最多拉取 92 天')).toBeTruthy()
    expect((screen.getByText('确认') as HTMLButtonElement).disabled).toBe(true)
    expect(spy).not.toHaveBeenCalled()
  })

  it('runs table shows target dates, trigger source and detail modal', async () => {
    vi.spyOn(api, 'getJobReports').mockResolvedValue({
      reports: [{
        task: 'filings', status: 'success', trigger_source: 'manual', run_id: 'r9',
        started_at: '2026-07-04T09:00:00+00:00', finished_at: '2026-07-04T09:00:12+00:00',
        target_start_date: '2026-06-01', target_end_date: '2026-06-30',
        summary: { downloaded_count: 3 },
      }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'runs' } })
    expect(await screen.findByText('2026-06-01 ~ 2026-06-30')).toBeTruthy()
    expect(screen.getByText('手动')).toBeTruthy()
    await fireEvent.click(screen.getByText('详情'))
    expect(await screen.findByText(/downloaded_count/)).toBeTruthy()
    expect(screen.getByText(/r9/)).toBeTruthy()
  })
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npx vitest run src/routes/Tools.test.ts`
Expected: FAIL

- [ ] **Step 3: 重写 Tools.svelte**

完整新文件：

```svelte
<script lang="ts">
  import * as api from '../lib/api'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import { fmtTime } from '../lib/format'
  import Modal from '../lib/components/Modal.svelte'
  import FetchDateModal from '../lib/components/FetchDateModal.svelte'

  let { sub = 'tasks' }: { sub?: string } = $props()
  // 旧 hash（ops/results）一律回落到任务中心
  const view = $derived(sub === 'runs' ? 'runs' : 'tasks')

  const JOB_HELP: Record<string, { goal: string; details: string[] }> = {
    metrics: {
      goal: '每个交易日早间更新市场环境与关注列表趋势。',
      details: [
        '拉取 SPY 收盘价与 200 日均线、VIX 恐慌指数，计算市场红绿灯信号（green / yellow / red）。',
        '对关注列表标的逐一扫描趋势状态（上升 / 震荡 / 下降），写入数据库，供看板与策略评分使用。',
        '支持「按日期运行」历史回补：用该日历史行情重算信号与快照（周末自动跳过）。',
      ],
    },
    filings: {
      goal: '自动跟踪关注列表公司的 SEC 信息披露。',
      details: [
        '从 SEC EDGAR 下载 10-Q / 10-K 等财报文件，按「标的 / 表单类型」归档到本地，并写入财报索引。',
        '定时运行默认拉取昨日（T-1）披露；也可点「按日期运行」回补历史。',
      ],
    },
    scores: {
      goal: '收盘后为关注列表标的计算「趋势相对强度」策略得分，作为研究证据。',
      details: [
        '加分制，满分 100：上升趋势 +30、均线多头排列 +20、跑赢 SPY +15、跑赢 QQQ +15、量能扩张 +10、宏观进攻状态 +10。',
        '例如 score=30 表示仅命中「上升趋势」一项；<40 视为弱、40–70 中等、≥70 强。',
        '分数只是证据汇总，不构成交易指令。',
      ],
    },
    event_study: {
      goal: '验证信号的历史有效性（事件研究）。',
      details: [
        '对三类事件——rs_strong（相对强度走强）、ma_reclaim（收复均线）、score_high（策略高分）——统计事件发生后 5 / 10 / 20 个交易日的收益分布。',
        '结果缓存到数据库，研究页直接读取。',
      ],
    },
  }

  const DATE_FETCH: Record<string, { description: string; defaultLabel: string }> = {
    metrics: { description: '按历史日期回补市场信号与关注列表快照（周末自动跳过）。', defaultLabel: '今日' },
    filings: { description: '从 SEC EDGAR 回补财报文件，按披露日匹配。', defaultLabel: '昨日（T-1）' },
    scores: { description: '按历史日期回补策略评分（基于该日快照，宏观取当前状态）。', defaultLabel: '今日' },
    event_study: { description: '重算事件研究：开始日为事件下界，结束日为 as-of。', defaultLabel: '默认（全量）' },
  }

  let helpJob = $state<string | null>(null)
  let dateJob = $state<string | null>(null)
  let jobs = $state<any[]>([])
  let reports = $state<any[]>([])
  let detailReport = $state<any | null>(null)
  let loading = $state(true)
  let runningName = $state<string | null>(null)
  let filterTask = $state<string>('')
  let actionMsg = $state('')

  async function loadTasks() { jobs = (await api.getScheduledJobs()).jobs }
  async function loadRuns() { reports = (await api.getJobReports(filterTask || undefined, 50)).reports }

  async function load() {
    loading = true
    try {
      if (view === 'tasks') await loadTasks()
      else await loadRuns()
    } finally { loading = false }
  }

  async function runNow(name: string) {
    runningName = name
    try { await api.runJob(name) } finally { runningName = null; await loadTasks() }
  }

  async function submitDated(payload: Record<string, string>) {
    const name = dateJob
    dateJob = null
    if (!name) return
    try {
      const r = await api.runJob(name, payload)
      actionMsg = `${name} 已提交（${r.run_id}），结果见「运行记录」`
    } catch (e: any) {
      actionMsg = `${name} 提交失败：${e?.message ?? e}`
    }
  }

  function fmtTargetDates(r: any): string {
    if (!r.target_start_date) return '—'
    if (!r.target_end_date || r.target_end_date === r.target_start_date) return r.target_start_date
    return `${r.target_start_date} ~ ${r.target_end_date}`
  }

  function fmtDuration(r: any): string {
    if (!r.started_at || !r.finished_at) return '—'
    const s = (new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000
    return `${s.toFixed(1)}s`
  }

  $effect(() => { view; load() })
</script>

{#if loading}
  <Skeleton />
{:else if view === 'tasks'}
  <div class="space-y-4">
    {#if actionMsg}<p class="text-xs text-muted">{actionMsg}</p>{/if}
    <table class="w-full text-sm">
      <thead><tr class="text-muted text-left"><th>任务</th><th>计划</th><th>下次</th><th>上次</th><th>状态</th><th></th></tr></thead>
      <tbody>
        {#each jobs as j}
          <tr class="border-t border-border">
            <td class="py-2">
              {j.name}
              {#if JOB_HELP[j.name]}
                <button
                  class="inline-flex items-center justify-center w-4 h-4 ml-1 rounded-full border border-border text-muted text-[10px] align-middle hover:border-accent hover:text-accent transition-colors"
                  aria-label={`${j.name} 说明`}
                  onclick={() => helpJob = j.name}
                >?</button>
              {/if}
            </td>
            <td>{j.time_local} · {j.weekday_mask}</td>
            <td>{fmtTime(j.next_run_at)}</td>
            <td>{fmtTime(j.last_run_at)}</td>
            <td>{j.enabled ? '启用' : '停用'}</td>
            <td class="whitespace-nowrap text-right space-x-3">
              <button class="text-accent text-xs" onclick={() => dateJob = j.name}>按日期运行</button>
              <button class="text-accent text-xs" disabled={runningName === j.name} onclick={() => runNow(j.name)}>立即运行</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>

    <FetchDateModal
      open={dateJob !== null}
      title={`${dateJob ?? ''} · 按日期运行`}
      description={dateJob ? (DATE_FETCH[dateJob]?.description ?? '') : ''}
      defaultLabel={dateJob ? (DATE_FETCH[dateJob]?.defaultLabel ?? '默认') : '默认'}
      defaultPayload={{}}
      maxRangeDays={92}
      onConfirm={submitDated}
      onclose={() => dateJob = null}
    />

    <Modal open={helpJob !== null} title={`${helpJob} · 任务说明`} onclose={() => helpJob = null}>
      {#if helpJob && JOB_HELP[helpJob]}
        <p class="text-sm font-medium mb-3">{JOB_HELP[helpJob].goal}</p>
        <ul class="space-y-2 text-sm text-muted list-disc pl-4">
          {#each JOB_HELP[helpJob].details as d}
            <li>{d}</li>
          {/each}
        </ul>
      {/if}
    </Modal>
    <p class="text-xs text-muted">改运行时间 / 开关请到「设置 · 定时任务」。</p>
  </div>
{:else}
  <div class="space-y-3">
    <select bind:value={filterTask} onchange={loadRuns} class="text-sm border border-border rounded px-2 py-1 bg-surface">
      <option value="">全部</option><option value="metrics">metrics</option>
      <option value="filings">filings</option><option value="scores">scores</option>
      <option value="event_study">event_study</option>
    </select>
    <table class="w-full text-sm">
      <thead>
        <tr class="text-muted text-left">
          <th>任务</th><th>状态</th><th>触发</th><th>运行时间</th><th>耗时</th><th>指定日期</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each reports as r}
          <tr class="border-t border-border">
            <td class="py-2 font-medium">{r.task}</td>
            <td><StatusPill status={r.status} /></td>
            <td>{r.trigger_source === 'manual' ? '手动' : '定时'}</td>
            <td>{fmtTime(r.started_at)}</td>
            <td>{fmtDuration(r)}</td>
            <td>{fmtTargetDates(r)}</td>
            <td class="text-right"><button class="text-accent text-xs" onclick={() => detailReport = r}>详情</button></td>
          </tr>
        {:else}
          <tr><td colspan="7" class="py-4 text-muted text-sm">暂无运行记录</td></tr>
        {/each}
      </tbody>
    </table>

    <Modal open={detailReport !== null} title={`${detailReport?.task ?? ''} · 运行详情`} onclose={() => detailReport = null}>
      {#if detailReport}
        <div class="text-xs text-muted mb-2 space-y-1">
          <div>run_id：{detailReport.run_id}</div>
          <div>开始：{fmtTime(detailReport.started_at)} · 结束：{fmtTime(detailReport.finished_at)}</div>
          <div>指定日期：{fmtTargetDates(detailReport)} · 触发：{detailReport.trigger_source === 'manual' ? '手动' : '定时'}</div>
        </div>
        <pre class="text-xs overflow-auto max-h-96 bg-surface-2 rounded p-2">{JSON.stringify(detailReport.summary, null, 2)}</pre>
      {/if}
    </Modal>
  </div>
{/if}
```

`SideNav.svelte` 的 tools children 改为：

```ts
    {
      id: 'tools', label: '工具', icon: '🔧', children: [
        { id: 'tasks',   label: '任务中心' },
        { id: 'runs',    label: '运行记录' },
      ],
    },
```

- [ ] **Step 4: 运行确认通过**

Run: `cd web && npx vitest run src/routes/Tools.test.ts src/app.test.ts`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/Tools.svelte web/src/lib/components/SideNav.svelte web/src/routes/Tools.test.ts
git commit -m "feat(ui): 工具模块收敛为任务中心+运行记录，全任务按日期运行，运行记录表格化"
```

---

### Task 13: 数据模块"财报"Tab

**Files:**
- Modify: `web/src/routes/Data.svelte`
- Modify: `web/src/lib/components/SideNav.svelte:17-21`（data children 加 filings）
- Test: `web/src/routes/Data.test.ts`（新建）

**Interfaces:**
- Consumes: Task 11 的 `api.getFilingRecords` / `api.filingDownloadUrl`

- [ ] **Step 1: 写失败测试**

创建 `web/src/routes/Data.test.ts`：

```ts
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Data from './Data.svelte'
import * as api from '../lib/api'

describe('Data 财报 Tab', () => {
  it('renders filing records with download link', async () => {
    vi.spyOn(api, 'getMarketSignals').mockResolvedValue({ rows: [] } as any)
    vi.spyOn(api, 'getMarketSignalsTrend').mockResolvedValue(null as any)
    vi.spyOn(api, 'getTickerTrends').mockResolvedValue({ rows: [] } as any)
    vi.spyOn(api, 'getFilingRecords').mockResolvedValue({
      records: [{
        id: 7, ticker: 'AAPL', form: '10-Q', filing_date: '2026-06-28',
        accession_number: 'acc-1', primary_document: 'q.htm',
        file_path: '/x/q.htm', downloaded_at: '2026-06-29T01:00:00+00:00',
        created_at: '2026-06-29T01:00:00+00:00',
      }],
      tickers: ['AAPL'],
      degraded: false,
    })
    render(Data, { props: { sub: 'filings' } })
    expect(await screen.findByText('AAPL')).toBeTruthy()
    expect(screen.getByText('10-Q')).toBeTruthy()
    expect(screen.getByText('2026-06-28')).toBeTruthy()
    const link = screen.getByText('下载 htm') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/api/filings/records/7/download')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npx vitest run src/routes/Data.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

`Data.svelte` 全量改为：

```svelte
<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import { fmtTime } from '../lib/format'

  let { sub }: { sub?: string } = $props()

  // Map legacy 'overview' → 'signals'; unknown subs default to 'signals'
  type Tab = 'signals' | 'trend' | 'tickers' | 'filings'
  let tab = $derived<Tab>(
    sub === 'trend' ? 'trend'
    : sub === 'tickers' ? 'tickers'
    : sub === 'filings' ? 'filings'
    : 'signals'
  )

  let signals = $state<any[]>([])
  let trend = $state<any>(null)
  let tickers = $state<any[]>([])
  let loading = $state(true)

  // 财报 Tab 状态
  let filings = $state<any[]>([])
  let filingTickers = $state<string[]>([])
  let fTicker = $state('')
  let fForm = $state('')
  let fFrom = $state('')
  let fTo = $state('')

  const cols = [
    { key: 'signal_date', label: '日期' },
    { key: 'market_status', label: '状态' },
    { key: 'spy_close', label: 'SPY' },
    { key: 'vix_close', label: 'VIX' },
  ]

  const tkCols = [
    { key: 'ticker', label: 'Ticker' },
    { key: 'trend_state', label: '趋势' },
    { key: 'attention_level', label: '关注度' },
  ]

  async function loadFilings() {
    const r = await api.getFilingRecords({
      ticker: fTicker || undefined,
      form: fForm || undefined,
      from: fFrom || undefined,
      to: fTo || undefined,
    })
    filings = r.records
    filingTickers = r.tickers
  }

  async function load() {
    loading = true
    try {
      ;[signals, trend, tickers] = await Promise.all([
        api.getMarketSignals(60).then((r: any) => r.rows ?? []),
        api.getMarketSignalsTrend(),
        api.getTickerTrends().then((r: any) => r.rows ?? []),
      ])
      await loadFilings()
    } finally { loading = false }
  }

  onMount(load)
</script>

<div>
  <div class="flex items-center gap-4 mb-4">
    <h2 class="text-lg font-semibold">数据</h2>
    <div class="flex gap-1">
      {#each (['signals', 'trend', 'tickers', 'filings'] as const) as k}
        <a
          href="#data/{k}"
          class="px-3 py-1 text-sm rounded {tab === k ? 'bg-accent text-white' : 'bg-surface-2 text-muted hover:bg-surface'}"
        >{{ signals: '信号总览', trend: '趋势分析', tickers: '技术面趋势', filings: '财报' }[k]}</a>
      {/each}
    </div>
  </div>

  {#if loading}
    <Skeleton rows={4} />
  {:else if tab === 'filings'}
    <div class="space-y-3">
      <div class="flex flex-wrap items-center gap-2">
        <select bind:value={fTicker} onchange={loadFilings} class="text-sm border border-border rounded px-2 py-1 bg-surface">
          <option value="">全部标的</option>
          {#each filingTickers as t}<option value={t}>{t}</option>{/each}
        </select>
        <select bind:value={fForm} onchange={loadFilings} class="text-sm border border-border rounded px-2 py-1 bg-surface">
          <option value="">全部类型</option><option value="10-Q">10-Q</option><option value="10-K">10-K</option>
        </select>
        <input type="date" bind:value={fFrom} onchange={loadFilings} class="text-sm border border-border rounded px-2 py-1 bg-surface" />
        <span class="text-xs text-muted">至</span>
        <input type="date" bind:value={fTo} onchange={loadFilings} class="text-sm border border-border rounded px-2 py-1 bg-surface" />
      </div>
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-muted text-left">
              <th class="px-3 py-2">标的</th><th>类型</th><th>财报日期</th><th>下载时间</th><th></th>
            </tr>
          </thead>
          <tbody>
            {#each filings as f}
              <tr class="border-t border-border">
                <td class="px-3 py-2 font-medium">{f.ticker}</td>
                <td>{f.form}</td>
                <td>{f.filing_date}</td>
                <td>{fmtTime(f.downloaded_at)}</td>
                <td class="text-right pr-3">
                  <a class="text-accent text-xs" href={api.filingDownloadUrl(f.id)} download>下载 htm</a>
                </td>
              </tr>
            {:else}
              <tr><td colspan="5" class="px-3 py-4 text-muted text-sm">暂无财报记录（可在「工具 · 任务中心」对 filings 按日期回补）</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {:else if tab === 'tickers'}
    <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
      <DataTable rows={tickers} columns={tkCols} />
    </div>
  {:else if tab === 'trend'}
    {#if trend}
      <div class="bg-surface rounded-lg p-4 shadow-elev-1">
        <div class="flex gap-4 mb-3">
          <StatusPill status={(trend as any).latest_status ?? 'unknown'} />
          <span class="text-sm text-muted">近{(trend as any).window}日 · 判断: {(trend as any).judgement ?? '—'}</span>
        </div>
        <pre class="text-xs text-muted overflow-auto">{JSON.stringify(trend, null, 2)}</pre>
      </div>
    {:else}
      <p class="text-sm text-muted">暂无趋势数据</p>
    {/if}
  {:else}
    {#if trend}
      <div class="flex gap-4 mb-4">
        <StatusPill status={(trend as any).latest_status ?? 'unknown'} />
        <span class="text-sm text-muted">近{(trend as any).window}日 · 判断: {(trend as any).judgement ?? '—'}</span>
      </div>
    {/if}
    <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
      <DataTable rows={signals} columns={cols} />
    </div>
  {/if}
</div>
```

`SideNav.svelte` 的 data children 追加一项：

```ts
    {
      id: 'data', label: '数据', icon: '📊', children: [
        { id: 'signals', label: '信号总览' },
        { id: 'trend',   label: '趋势分析' },
        { id: 'tickers', label: '技术面趋势' },
        { id: 'filings', label: '财报' },
      ],
    },
```

- [ ] **Step 4: 运行确认通过**

Run: `cd web && npx vitest run src/routes/Data.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/Data.svelte web/src/lib/components/SideNav.svelte web/src/routes/Data.test.ts
git commit -m "feat(ui): 数据模块新增财报 Tab（标的/类型/日期筛选 + 单个 htm 下载）"
```

---

### Task 14: 全量验证与收尾

**Files:**
- 无新改动（只验证；如发现遗漏在此修复）

- [ ] **Step 1: 后端全量测试**

Run: `python -m pytest tests -v`
Expected: 全部 PASS。若有本计划遗漏的引用（如某测试仍 import `job_report_metrics`、`filing_rows`、`_filings_kwargs`），按删除/改名一并修复。

- [ ] **Step 2: 前端全量测试与构建**

Run: `cd web && npm test && npm run build`
Expected: vitest 全部 PASS；svelte-check + vite build 无错误。

- [ ] **Step 3: 对照 spec 检查**

逐条核对 `docs/superpowers/specs/2026-07-04-tools-module-optimization-design.md`：
1. 工具模块只剩 任务中心/运行记录 两个子页 ✓（Task 12）
2. 4 任务支持日期/范围，API 统一校验（未来/顺序/92 天）✓（Task 4-7）
3. job_reports 记录 target_start_date/target_end_date/trigger_source ✓（Task 1/2）
4. 运行记录表格 + 详情弹窗，区分运行时间/指定日期 ✓（Task 12）
5. 通知实际日期 + 一条汇总 ✓（Task 3-5）
6. filings 表 + 财报 Tab + 单个下载 + 按标的筛选 ✓（Task 8-10/13）
7. 清理：/api/jobs/metrics 已删；/api/filings 已删；/api/market/signals/fetch 保留（operations registry 引用）✓

- [ ] **Step 4: 提交收尾（如有修复）**

```bash
git add -A
git commit -m "fix: 工具模块优化全量验证收尾"
```

- [ ] **Step 5: 部署提醒（写入交付说明，不执行）**

上线需按序执行 `python -m investment_assistant.migrate`（应用 010/011）后再滚动重启 api 与 scheduler 两个进程（Sealos 一库两进程部署）。历史财报索引回补：在任务中心对 filings 按日期范围重跑即可（已存在文件只补索引不重复下载）。
