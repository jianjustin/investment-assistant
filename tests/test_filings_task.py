from datetime import date
from pathlib import Path

from investment_assistant.config import AssistantConfig, FilingsConfig
from investment_assistant.tasks import filings


def test_core_summarizes_downloads(monkeypatch, tmp_path):
    def fake_download(tickers, cfg, *, downloader=None, start_date=None, end_date=None):
        return {"downloaded_count": 1, "files": [tmp_path / "NVDA/10-Q/acc.htm"], "errors": {}}

    monkeypatch.setattr(filings, "download_configured_filings", fake_download)
    cfg = AssistantConfig(filings=FilingsConfig(output_dir=tmp_path))
    summary = filings._core(cfg)
    assert summary["downloaded_count"] == 1
    assert summary["filings"][0]["ticker"] == "NVDA"


def test_core_passes_date_range(monkeypatch, tmp_path):
    seen = {}

    def fake_download(tickers, cfg, *, downloader=None, start_date=None, end_date=None):
        seen.update({"start_date": start_date, "end_date": end_date})
        return {"downloaded_count": 0, "files": [], "errors": {}}

    monkeypatch.setattr(filings, "download_configured_filings", fake_download)
    cfg = AssistantConfig(filings=FilingsConfig(output_dir=tmp_path))
    filings._core(cfg, start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))
    assert seen == {"start_date": date(2026, 6, 1), "end_date": date(2026, 6, 30)}


def test_run_goes_through_harness(monkeypatch):
    monkeypatch.setattr(filings, "_core", lambda config, **kw: {"downloaded_count": 0, "filings": []})
    captured = {}

    def fake_run_task(task, fn, *, config):
        captured["task"] = task
        return {"task": task, "status": "success", "summary": fn()}

    monkeypatch.setattr(filings, "run_task", fake_run_task)
    out = filings.run(AssistantConfig())
    assert captured["task"] == "filings" and out["summary"]["downloaded_count"] == 0
