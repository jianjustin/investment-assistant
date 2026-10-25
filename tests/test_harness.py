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


def test_record_keeps_db_row_when_run_log_is_not_writable(monkeypatch):
    from datetime import datetime, UTC

    saved = {}

    def boom(record):
        raise PermissionError("denied")

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(_harness, "append_run", boom)
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgresql://example")
    monkeypatch.setattr("investment_assistant.db.connect", lambda url: Conn())
    monkeypatch.setattr("investment_assistant.db.insert_job_report", lambda conn, **kw: saved.update(kw))

    _harness._record(
        task="filings", run_id="filings-test", status="success",
        started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
        summary={"downloaded_count": 0}, trigger_source="manual",
    )

    assert saved["status"] == "success"
    assert saved["summary"]["downloaded_count"] == 0
    assert "denied" in saved["summary"]["run_log_error"]


def test_harness_imports_run_log_from_tasks():
    from investment_assistant.tasks import run_log

    assert _harness.append_run is run_log.append_run
