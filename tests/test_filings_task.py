from datetime import date

from investment_assistant.config import AssistantConfig, FilingsConfig, SecMonitorConfig
from investment_assistant.tasks import filings


def test_core_summarizes_downloads(monkeypatch, tmp_path):
    def fake_download(tickers, cfg, *, downloader=None, start_date=None, end_date=None):
        return {"downloaded_count": 1, "filings": [{"ticker": "NVDA", "form": "10-Q", "filing_date": "2026-06-28", "path": "/x/NVDA/10-Q/a.htm", "downloaded": True}], "errors": {}}

    monkeypatch.setattr(filings, "download_configured_filings", fake_download)
    cfg = AssistantConfig(filings=FilingsConfig(output_dir=tmp_path))
    summary = filings._core(cfg)
    assert summary["downloaded_count"] == 1
    assert summary["filings"][0]["ticker"] == "NVDA"
    assert summary["filings"][0]["filing_date"] == "2026-06-28"


def test_core_passes_date_range(monkeypatch, tmp_path):
    seen = {}

    def fake_download(tickers, cfg, *, downloader=None, start_date=None, end_date=None):
        seen.update({"start_date": start_date, "end_date": end_date})
        return {"downloaded_count": 0, "filings": [], "errors": {}}

    monkeypatch.setattr(filings, "download_configured_filings", fake_download)
    cfg = AssistantConfig(filings=FilingsConfig(output_dir=tmp_path))
    filings._core(cfg, start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))
    assert seen == {"start_date": date(2026, 6, 1), "end_date": date(2026, 6, 30)}


def test_run_goes_through_harness(monkeypatch):
    monkeypatch.setattr(filings, "_core", lambda config, **kw: {"downloaded_count": 0, "filings": []})
    captured = {}

    def fake_run_task(task, fn, *, config, **kw):
        captured["task"] = task
        return {"task": task, "status": "success", "summary": fn()}

    monkeypatch.setattr(filings, "run_task", fake_run_task)
    out = filings.run(AssistantConfig())
    assert captured["task"] == "filings" and out["summary"]["downloaded_count"] == 0


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


def _collecting_write_runs(monkeypatch, rows):
    from investment_assistant.workbench import collect

    def fake_write_runs(new_rows):
        rows.extend(new_rows)
        return {"written": len(new_rows), "error": None}

    monkeypatch.setattr(collect, "write_runs", fake_write_runs)


def test_downloader_records_partial_by_ticker(monkeypatch):
    rows = []
    _collecting_write_runs(monkeypatch, rows)
    monkeypatch.setattr(filings, "_core", lambda config, **kw: {
        "downloaded_count": 0, "filings": [], "errors": {"MU": "timeout"}})

    def fake_run_task(task, fn, *, config, **kw):
        return {"run_id": "filings-r9", "task": task, "status": "error", "summary": fn()}

    monkeypatch.setattr(filings, "run_task", fake_run_task)
    out = filings.run(AssistantConfig(watchlist=["MU", "NVDA"]))
    assert out["run_id"] == "filings-r9"
    assert len(rows) == 1
    assert rows[0]["family"] == "sec_filings" and rows[0]["job"] == "filings"
    assert rows[0]["status"] == "partial"
    assert rows[0]["failures"] == [{"target": "MU", "reason": "timeout"}]
    assert rows[0]["trigger"] == "scheduled"
    assert rows[0]["run_id"] == "filings-r9"
    assert rows[0]["target_count"] == 2 and rows[0]["ok_count"] == 1
    assert rows[0]["detail"] == {"targets_source": "config.watchlist", "mode": "downloader"}
    assert out["data_status"] == {"written": 1, "error": None}


def test_monitor_records_failure(monkeypatch):
    from investment_assistant.filings import monitor

    rows = []
    _collecting_write_runs(monkeypatch, rows)
    monkeypatch.setattr(monitor, "run_monitor", lambda config, **kw: {
        "run_id": "r1", "task": "filings", "status": "error", "summary": {"error": "edgar down"}})
    cfg = AssistantConfig(watchlist=["MU", "NVDA"],
                          sec_monitor=SecMonitorConfig(enabled=True, start_date="2026-10-01"))
    out = filings.run(cfg)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["failures"] == [{"target": "*", "reason": "edgar down"}]
    assert rows[0]["detail"] == {"targets_source": "config.watchlist", "mode": "monitor"}
    assert rows[0]["run_id"] == "r1" and rows[0]["trigger"] == "scheduled"
    assert out["data_status"] == {"written": 1, "error": None}


def test_manual_trigger_maps_to_manual_batch(monkeypatch):
    rows = []
    _collecting_write_runs(monkeypatch, rows)
    monkeypatch.setattr(filings, "_core", lambda config, **kw: {
        "downloaded_count": 0, "filings": [], "errors": {}})
    monkeypatch.setattr(filings, "run_task",
                        lambda task, fn, *, config, **kw: {"run_id": "f1", "task": task,
                                                           "status": "success", "summary": fn()})
    filings.run(AssistantConfig(watchlist=["NVDA"]), trigger_source="manual")
    assert len(rows) == 1 and rows[0]["trigger"] == "manual_batch"


def test_record_failure_does_not_change_result(monkeypatch):
    from investment_assistant.workbench import collect

    monkeypatch.setattr(collect, "write_runs",
                        lambda new_rows: {"written": 0, "error": "migration 024 未执行"})
    summary = {"downloaded_count": 1, "filings": [], "errors": {}}
    monkeypatch.setattr(filings, "_core", lambda config, **kw: dict(summary))
    monkeypatch.setattr(filings, "run_task",
                        lambda task, fn, *, config, **kw: {"run_id": "f2", "task": task,
                                                           "status": "success", "summary": fn()})
    out = filings.run(AssistantConfig(watchlist=["NVDA"]))
    assert out["status"] == "success"
    assert out["summary"] == summary
    assert out["data_status"] == {"written": 0, "error": "migration 024 未执行"}
