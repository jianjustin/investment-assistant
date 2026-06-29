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
