import json
from pathlib import Path

from investment_assistant.config import load_config


def test_load_config_uses_runtime_defaults_when_file_missing(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    monkeypatch.delenv("INVESTMENT_ASSISTANT_CONFIG", raising=False)

    cfg = load_config(missing)

    assert cfg.watchlist == ["CRDO", "MU", "RKLB", "NVDA"]
    assert cfg.market.spy_ticker == "SPY"
    assert cfg.market.vix_ticker == "^VIX"
    assert cfg.market.ma_days == 200
    assert cfg.filings.forms == ["10-Q", "10-K"]
    assert cfg.filings.output_dir == Path("/srv/investment-assistant/filings")


def test_load_config_applies_json_overrides(tmp_path):
    path = tmp_path / "investment-assistant.json"
    path.write_text(json.dumps({
        "watchlist": ["AAPL"],
        "filings": {"forms": ["10-Q"], "lookback_years": 1, "output_dir": str(tmp_path / "filings")},
        "market": {"red_vix": 35},
        "max_daily_focus_items": 2,
    }))

    cfg = load_config(path)

    assert cfg.watchlist == ["AAPL"]
    assert cfg.filings.forms == ["10-Q"]
