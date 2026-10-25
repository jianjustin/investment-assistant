import json
from pathlib import Path

import pytest

from investment_assistant.config import load_config


def test_load_config_uses_runtime_defaults_when_file_missing(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    monkeypatch.delenv("INVESTMENT_ASSISTANT_CONFIG", raising=False)

    cfg = load_config(missing)

    assert cfg.watchlist == ["CRDO", "MU", "RKLB", "NVDA"]
    assert cfg.filings.forms == ["10-Q", "10-K"]
    assert cfg.filings.output_dir == Path("/srv/investment-assistant/filings")


def test_load_config_applies_json_overrides(tmp_path):
    path = tmp_path / "investment-assistant.json"
    path.write_text(json.dumps({
        "watchlist": ["AAPL"],
        "filings": {"forms": ["10-Q"], "lookback_years": 1, "output_dir": str(tmp_path / "filings")},
        "max_daily_focus_items": 2,
    }))

    cfg = load_config(path)

    assert cfg.watchlist == ["AAPL"]
    assert cfg.filings.forms == ["10-Q"]


def test_workbench_defaults(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    monkeypatch.delenv("INVESTMENT_ASSISTANT_CONFIG", raising=False)

    cfg = load_config(missing)

    assert cfg.workbench.risk_pct == 0.01
    assert cfg.workbench.single_cap == 0.25
    assert cfg.workbench.total_cap == 1.0
    assert cfg.workbench.public_url == "http://localhost:8787"
    assert cfg.workbench.return_tiers == (0.20, 0.10, 0.0)


def test_workbench_section_overrides(tmp_path):
    path = tmp_path / "investment-assistant.json"
    path.write_text(json.dumps({"workbench": {"risk_pct": 0.015}}))

    cfg = load_config(path)

    assert cfg.workbench.risk_pct == 0.015
    assert cfg.workbench.single_cap == 0.25
    assert cfg.workbench.public_url == "http://localhost:8787"
    assert cfg.workbench.return_tiers == (0.20, 0.10, 0.0)


def test_workbench_rejects_bad_values(tmp_path):
    def load_with(workbench):
        path = tmp_path / "investment-assistant.json"
        path.write_text(json.dumps({"workbench": workbench}))
        return load_config(path)

    for bad in ({"risk_pct": 0}, {"risk_pct": 0.06}, {"single_cap": 0}, {"single_cap": 1.5},
                {"total_cap": 0}, {"total_cap": -1}, {"return_tiers": [0.10, 0.20, 0.0]}):
        with pytest.raises(ValueError):
            load_with(bad)
