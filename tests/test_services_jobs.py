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


def test_patch_scheduled_job_passthrough(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    seen = {}
    monkeypatch.setattr(jobs, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(jobs.db, "update_scheduled_job",
                        lambda conn, name, **kw: seen.update({"name": name, **kw}))
    out = jobs.patch_scheduled_job("metrics", time_local="09:30")
    assert out["updated"] is True and seen == {"name": "metrics", "enabled": None, "time_local": "09:30"}
