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
    assert seen == {"start_date": date(2026, 6, 1), "end_date": date(2026, 6, 30)}


def test_trigger_job_filings_single_date(monkeypatch):
    from datetime import date

    seen = {}
    monkeypatch.setattr(jobs, "REGISTRY", {"filings": lambda config, **kw: seen.update(kw) or {"ok": True}})
    monkeypatch.setattr(jobs, "load_config", lambda: object())
    submitted = {}
    monkeypatch.setattr(jobs.runner, "submit", lambda kind, fn: submitted.update({"fn": fn}) or "run-3")

    jobs.trigger_job("filings", {"date": "2026-06-15"})
    submitted["fn"]()
    assert seen == {"start_date": date(2026, 6, 15), "end_date": date(2026, 6, 15)}


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
