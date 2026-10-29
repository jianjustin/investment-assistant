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


def _monitor_watchlist_file(tmp_path, tickers):
    """A real monitor watchlist table: only 采集=是 rows are in scope."""
    path = tmp_path / "watchlist.md"
    lines = ["| Ticker | 采集 |", "| --- | --- |"]
    for ticker, collect_it in tickers:
        lines.append(f"| {ticker} | {collect_it} |")
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


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
    detail = rows[0]["detail"]      # v2.8: the legacy Tally.ok/fail also write detail.policy / detail.targets
    assert {k: detail[k] for k in ("targets_source", "mode")} == {"targets_source": "config.watchlist", "mode": "downloader"}
    assert detail["policy"] == "fetch-1" and [t["target"] for t in detail["targets"]] == ["MU", "NVDA"]
    assert out["data_status"] == {"written": 1, "error": None}


def test_downloader_whole_failure_is_call_sentinel(monkeypatch, tmp_path):
    """A whole-run downloader failure keeps config.watchlist as the denominator;
    '*' is the sentinel, never an N+1th target (I02/I04)."""
    rows = []
    _collecting_write_runs(monkeypatch, rows)
    monkeypatch.setattr(filings, "_core", lambda config, **kw: {
        "downloaded_count": 0, "filings": [], "errors": {}, "error": "downloader down"})

    def fake_run_task(task, fn, *, config, **kw):
        return {"run_id": "f3", "task": task, "status": "error", "summary": {"error": "downloader down"}}

    monkeypatch.setattr(filings, "run_task", fake_run_task)
    filings.run(AssistantConfig(watchlist=["MU", "NVDA"], filings=__import__(
        "investment_assistant.config", fromlist=["FilingsConfig"]).FilingsConfig(output_dir=tmp_path)))
    assert rows[0]["status"] == "failed"
    assert rows[0]["target_count"] == 2 and rows[0]["ok_count"] == 0
    assert rows[0]["failures"] == [{"target": "*", "reason": "downloader down"}]
    assert rows[0]["detail"]["failed_targets"] == ["MU", "NVDA"]


def _monitor_run(monkeypatch, summary, cfg):
    from investment_assistant.filings import monitor

    monkeypatch.setattr(monitor, "run_monitor",
                        lambda config, **kw: {"run_id": "r1", "task": "filings",
                                              "status": "error" if summary.get("errors") or
                                              summary.get("error") else "success",
                                              "summary": summary})
    return filings.run(cfg)


def test_monitor_failure_uses_real_watchlist_targets(monkeypatch, tmp_path):
    """The monitor's real failure shape: coverage unavailable, errors.collection.
    Targets are the monitor's own watchlist file, never config.watchlist (I02/I03)."""
    rows = []
    _collecting_write_runs(monkeypatch, rows)
    cfg = AssistantConfig(
        watchlist=["MU", "NVDA"],
        sec_monitor=SecMonitorConfig(enabled=True, start_date="2026-10-01",
                                      watchlist_path=_monitor_watchlist_file(
                                          tmp_path, [("AAPL", "是"), ("TSLA", "否")])))
    out = _monitor_run(monkeypatch, {"start_date": "2026-10-01", "end_date": "2026-10-22",
                                     "coverage": "unavailable",
                                     "errors": {"collection": "edgar down"},
                                     "filings": [], "downloaded_count": 0}, cfg)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["target_count"] == 1 and rows[0]["ok_count"] == 0   # 只有 AAPL；MU/NVDA 没被采集
    assert rows[0]["failures"] == [{"target": "*", "reason": "edgar down"}]
    assert rows[0]["detail"] == {"targets_source": "sec_monitor.watchlist_path", "mode": "monitor",
                                 "failed_targets": ["AAPL"]}
    assert rows[0]["trigger"] == "scheduled" and rows[0]["run_id"] == "r1"
    assert out["data_status"] == {"written": 1, "error": None}


def test_monitor_success_uses_summary_tickers(monkeypatch, tmp_path):
    rows = []
    _collecting_write_runs(monkeypatch, rows)
    cfg = AssistantConfig(watchlist=["MU", "NVDA"],
                          sec_monitor=SecMonitorConfig(enabled=True, start_date="2026-10-01",
                                                        watchlist_path=_monitor_watchlist_file(
                                                            tmp_path, [("AAPL", "是")])))
    _monitor_run(monkeypatch, {"start_date": "2026-10-01", "end_date": "2026-10-22",
                               "coverage": "complete_for_declared_universe", "tickers": ["AAPL"],
                               "errors": {}, "filings": [], "downloaded_count": 0}, cfg)
    assert rows[0]["status"] == "success"
    assert rows[0]["target_count"] == 1 and rows[0]["ok_count"] == 1
    assert rows[0]["failures"] == []
    assert {k: v for k, v in rows[0]["detail"].items() if k not in ("policy", "targets")} == {
        "targets_source": "sec_monitor.watchlist_path", "mode": "monitor"}
    assert [t["target"] for t in rows[0]["detail"]["targets"]] == ["AAPL"]


def test_monitor_delivery_failure_is_not_a_target(monkeypatch, tmp_path):
    """Discord delivery failed after a complete collection: not a ticker, not ok'd
    away — reported separately in detail.non_target_errors (I02)."""
    rows = []
    _collecting_write_runs(monkeypatch, rows)
    cfg = AssistantConfig(watchlist=["MU", "NVDA"],
                          sec_monitor=SecMonitorConfig(enabled=True, start_date="2026-10-01",
                                                        watchlist_path=_monitor_watchlist_file(
                                                            tmp_path, [("AAPL", "是")])))
    _monitor_run(monkeypatch, {"start_date": "2026-10-01", "end_date": "2026-10-22",
                               "coverage": "complete_for_declared_universe", "tickers": ["AAPL"],
                               "errors": {"delivery": "Discord 投递失败或待核验；详见 delivery.receipts"},
                               "filings": [], "downloaded_count": 0}, cfg)
    assert rows[0]["status"] == "success"
    assert rows[0]["failures"] == [] and rows[0]["target_count"] == 1 and rows[0]["ok_count"] == 1
    assert rows[0]["detail"]["non_target_errors"] == {
        "delivery": "Discord 投递失败或待核验；详见 delivery.receipts"}


def test_monitor_failure_with_unreadable_watchlist_is_unknown_targets(monkeypatch, tmp_path):
    rows = []
    _collecting_write_runs(monkeypatch, rows)
    cfg = AssistantConfig(watchlist=["MU", "NVDA"],
                          sec_monitor=SecMonitorConfig(enabled=True, start_date="2026-10-01",
                                                        watchlist_path=str(tmp_path / "missing.md")))
    _monitor_run(monkeypatch, {"coverage": "unavailable",
                               "errors": {"collection": "edgar down"},
                               "filings": [], "downloaded_count": 0}, cfg)
    assert rows[0]["status"] == "failed"
    assert rows[0]["target_count"] == 0 and rows[0]["ok_count"] == 0   # 目标未知，不伪造分母
    assert rows[0]["failures"] == [{"target": "*", "reason": "edgar down"}]
    assert rows[0]["detail"]["targets_error"]


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


def test_record_failure_prints_searchable_stderr_line(monkeypatch, capsys):
    """The scheduled path drops data_status, so the write failure needs a
    searchable trail on stderr (I08); the task result itself is unchanged."""
    from investment_assistant.workbench import collect

    monkeypatch.setattr(collect, "write_runs",
                        lambda new_rows: {"written": 0, "error": "permission denied"})
    monkeypatch.setattr(filings, "_core", lambda config, **kw: {
        "downloaded_count": 0, "filings": [], "errors": {}})
    monkeypatch.setattr(filings, "run_task",
                        lambda task, fn, *, config, **kw: {"run_id": "f4", "task": task,
                                                           "status": "success", "summary": fn()})
    out = filings.run(AssistantConfig(watchlist=["NVDA"]))
    assert out["status"] == "success"
    err = capsys.readouterr().err
    assert ("family=sec_filings job=filings trigger=scheduled error=permission denied" in err)
