import pytest

from investment_assistant.services import jobs


def test_scheduled_jobs_degraded_without_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = jobs.scheduled_jobs()
    assert out["degraded"] is True and out["jobs"] == []
    assert out["scheduler"]["meta"]["enabled"] is False


def test_scheduled_jobs_exposes_global_disable_despite_enabled_job(client, monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    monkeypatch.setattr(jobs, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(jobs.db, "list_scheduled_jobs",
                        lambda conn: [{"name": "metrics", "enabled": True}])
    response = client.get("/api/jobs/scheduled")
    assert response.status_code == 200
    out = response.json()
    assert out["jobs"][0]["enabled"] is True
    assert out["degraded"] is False  # 数据库可用与调度开关独立
    assert out["scheduler"]["meta"]["enabled"] is False
    assert "SCHEDULER_ENABLED=0" in out["scheduler"]["detail"]


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
    monkeypatch.setattr(jobs, "REGISTRY", {"metrics": lambda config, **kw: {"ok": True}})
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    monkeypatch.setattr(jobs.runner, "submit", lambda kind, fn: captured.update({"kind": kind}) or "run-1")
    out = jobs.trigger_job("metrics")
    assert out["run_id"] == "run-1" and out["status"] == "pending" and captured["kind"] == "metrics"


def test_trigger_job_filings_passes_date_range(monkeypatch):
    from datetime import date

    seen = {}
    monkeypatch.setattr(jobs, "REGISTRY", {"filings": lambda config, **kw: seen.update(kw) or {"ok": True}})
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    submitted = {}
    monkeypatch.setattr(jobs.runner, "submit", lambda kind, fn: submitted.update({"fn": fn}) or "run-2")

    out = jobs.trigger_job("filings", {"from": "2026-06-01", "to": "2026-06-30"})
    submitted["fn"]()  # 同步执行以观察参数
    assert out["run_id"] == "run-2"
    assert seen == {"start_date": date(2026, 6, 1), "end_date": date(2026, 6, 30),
                    "trigger_source": "manual"}


def test_trigger_job_filings_single_date(monkeypatch):
    from datetime import date

    seen = {}
    monkeypatch.setattr(jobs, "REGISTRY", {"filings": lambda config, **kw: seen.update(kw) or {"ok": True}})
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    submitted = {}
    monkeypatch.setattr(jobs.runner, "submit", lambda kind, fn: submitted.update({"fn": fn}) or "run-3")

    jobs.trigger_job("filings", {"date": "2026-06-15"})
    submitted["fn"]()
    assert seen == {"start_date": date(2026, 6, 15), "end_date": date(2026, 6, 15),
                    "trigger_source": "manual"}


def test_trigger_job_filings_rejects_bad_range(monkeypatch):
    monkeypatch.setattr(jobs, "REGISTRY", {"filings": lambda config, **kw: {"ok": True}})
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    with pytest.raises(ValueError):
        jobs.trigger_job("filings", {"from": "2026-06-30", "to": "2026-06-01"})
    with pytest.raises(ValueError):
        jobs.trigger_job("filings", {"from": "2025-01-01", "to": "2026-01-01"})  # 超过范围上限


def test_trigger_job_unknown_is_distinct_error(monkeypatch):
    monkeypatch.setattr(jobs, "REGISTRY", {})
    with pytest.raises(jobs.UnknownJobError):
        jobs.trigger_job("ghost")


def test_patch_scheduled_job_passthrough(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    seen = {}
    monkeypatch.setattr(jobs, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(jobs.db, "update_scheduled_job",
                        lambda conn, name, **kw: seen.update({"name": name, **kw}))
    out = jobs.patch_scheduled_job("metrics", time_local="09:30")
    assert out["updated"] is True and seen == {"name": "metrics", "enabled": None, "time_local": "09:30"}


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


def test_scheduled_jobs_carry_description(monkeypatch):
    from investment_assistant.tasks import catalog

    monkeypatch.setattr(jobs, "_has_db", lambda: True)
    monkeypatch.setattr(jobs, "_with_conn", lambda fn: [
        {"name": "daily", "enabled": True},
        {"name": "ghost", "enabled": True},
    ])
    out = jobs.scheduled_jobs()
    assert out["degraded"] is False
    assert out["jobs"][0]["description"]["title"] == catalog.JOB_INFO["daily"]["title"]
    assert out["jobs"][1]["description"] is None


def test_scheduled_jobs_list_manual_only_registry_jobs(monkeypatch):
    """``sec_backfill`` has no scheduled_jobs row; the task center still gets a row for it (only 按日期运行)."""
    from investment_assistant.tasks import catalog

    monkeypatch.setattr(jobs, "_has_db", lambda: True)
    monkeypatch.setattr(jobs, "_with_conn", lambda fn: [{"name": "daily", "enabled": True}])
    out = jobs.scheduled_jobs()["jobs"]
    assert out[0] == {"name": "daily", "enabled": True, "description": catalog.describe("daily")}   # normal rows as before
    assert out[1] == {"name": "sec_backfill", "manual_only": True, "enabled": False, "next_run_at": None,
                      "time_local": None, "weekday_mask": None, "timezone": None,
                      "description": catalog.describe("sec_backfill")}
    assert len(out) == 2
    monkeypatch.setattr(jobs, "_with_conn", lambda fn: [{"name": "sec_backfill", "enabled": True}])    # a real row wins
    assert [j.get("manual_only") for j in jobs.scheduled_jobs()["jobs"]] == [None]


def test_old_job_names_404(client, monkeypatch):
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    for old in ("workbench", "workbench_review", "filings"):
        with pytest.raises(jobs.UnknownJobError):
            jobs.trigger_job(old)
        response = client.post(f"/api/jobs/{old}/run", json={})
        assert response.status_code == 404 and response.json() == {"error": f"unknown job: {old}"}


def test_sec_backfill_requires_dates(client, monkeypatch):
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    submitted = {}
    monkeypatch.setattr(jobs.runner, "submit", lambda kind, fn: submitted.update({"kind": kind, "fn": fn}) or "run-9")
    with pytest.raises(ValueError):
        jobs.trigger_job("sec_backfill", {})
    assert client.post("/api/jobs/sec_backfill/run", json={}).status_code == 400
    assert submitted == {}
    out = jobs.trigger_job("sec_backfill", {"date": "2026-10-01"})
    assert out == {"run_id": "run-9", "status": "pending"} and submitted["kind"] == "sec_backfill"


def test_daily_job_ignores_dates(monkeypatch):
    seen = {}
    monkeypatch.setattr(jobs, "REGISTRY", {"daily": lambda config, **kw: seen.update(kw) or {"ok": True}})
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    monkeypatch.setattr(jobs.runner, "submit", lambda kind, fn: fn() and "run-3")
    jobs.trigger_job("daily", {"date": "2026-10-01"})
    assert seen == {"trigger_source": "manual"}
