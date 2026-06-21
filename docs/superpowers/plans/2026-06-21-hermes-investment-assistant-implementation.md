# Hermes Investment Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `investment-assistant` into the source repository for the Hermes investment assistant, with runtime data stored outside Git, Postgres-backed market signals, and scheduled SEC filing downloads.

**Architecture:** Create a focused `investment_assistant` package and migrate reusable price, market, SEC, Hermes run-log, and dashboard behavior into it. Runtime outputs go to Postgres, `/srv/investment-assistant/filings`, and `/opt/hermes-investment-assistant`, while the repository keeps only code, tests, SQL, deployment templates, and docs.

**Tech Stack:** Python 3.14 on codex-lan, pytest, requests, python-dotenv, yfinance, psycopg 3, Docker-managed Postgres, systemd timers/services.

---

## File Structure

- Create `investment_assistant/config.py`: dataclass-based config loading, env loading, default runtime paths.
- Create `investment_assistant/runtime_paths.py`: path constants for `/opt`, `/srv`, logs, task index, and filings.
- Create `investment_assistant/db.py`: psycopg connection and `market_signals` upsert/read helpers.
- Create `investment_assistant/market/models.py`: `MarketSignal` dataclass.
- Create `investment_assistant/market/service.py`: compute SPY/VIX market signal using injected price fetcher.
- Create `investment_assistant/filings/sec_downloader.py`: migrated SEC downloader logic, focused on generic forms.
- Create `investment_assistant/filings/service.py`: configured `10-Q`/`10-K` download orchestration and skip-existing policy.
- Create `investment_assistant/hermes/run_log.py`: append run records and task index outside the repo.
- Create `investment_assistant/hermes/assistant.py`: migrated daily brief/research/challenge behavior from `/opt` MVP.
- Create `investment_assistant/hermes/daily.py`: orchestrates market signal, filings, and optional daily brief.
- Create `investment_assistant/dashboard/server.py`: repository-backed dashboard server with PG and filing status.
- Create `investment_assistant/ops/hermes_daily.py`: canonical CLI entrypoint.
- Create `migrations/001_market_signals.sql`: Postgres schema.
- Create `config/investment-assistant.example.json`: non-secret config example.
- Create `deploy/docker-compose.postgres.yml`: Postgres service template.
- Create `deploy/systemd/*.service|*.timer`: deployable systemd units.
- Create `deploy/install.sh`: idempotent install/deploy script.
- Modify `requirements.txt`: add `psycopg[binary]` and `pytest`.
- Modify `.gitignore`: ignore runtime output directories and local env files.
- Modify `README.md` and docs to make Hermes the primary product.
- Retire or simplify old unclear entrypoints after new tests pass.

## Task 1: Config, Paths, and Data Boundary Foundation

**Files:**
- Create: `investment_assistant/__init__.py`
- Create: `investment_assistant/config.py`
- Create: `investment_assistant/runtime_paths.py`
- Test: `tests/test_config.py`
- Modify: `.gitignore`

- [ ] **Step 1.1: Write failing config tests**

Create `tests/test_config.py` with tests proving defaults, JSON overrides, and env loading:

```python
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
    assert cfg.filings.forms == ["10-Q", "10-K"]
    assert cfg.filings.output_dir == Path("/srv/investment-assistant/filings")


def test_load_config_applies_json_overrides(tmp_path):
    path = tmp_path / "investment-assistant.json"
    path.write_text(json.dumps({
        "watchlist": ["AAPL"],
        "filings": {"forms": ["10-Q"], "lookback_years": 1, "output_dir": str(tmp_path / "filings")},
        "market": {"red_vix": 35}
    }))

    cfg = load_config(path)

    assert cfg.watchlist == ["AAPL"]
    assert cfg.filings.forms == ["10-Q"]
    assert cfg.filings.lookback_years == 1
    assert cfg.market.red_vix == 35
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'investment_assistant'`.

- [ ] **Step 1.3: Implement config and runtime paths**

Implement `MarketConfig`, `FilingsConfig`, `AssistantConfig`, and `load_config(path=None)`. Defaults must match the approved spec. Convert path-like fields to `Path`.

- [ ] **Step 1.4: Update `.gitignore`**

Add ignores for runtime-only outputs:

```gitignore
.env
.venv/
data/*.json
data/earnings_reports/
filings/
postgres-data/
logs/
```

- [ ] **Step 1.5: Run config tests**

Run: `python3 -m pytest tests/test_config.py -q`

Expected: PASS.

## Task 2: Postgres Schema and DB Helpers

**Files:**
- Create: `migrations/001_market_signals.sql`
- Create: `investment_assistant/db.py`
- Test: `tests/test_db_sql.py`

- [ ] **Step 2.1: Write failing SQL tests**

Create `tests/test_db_sql.py`:

```python
from pathlib import Path


def test_market_signals_migration_defines_required_table_and_unique_date():
    sql = Path("migrations/001_market_signals.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS market_signals" in sql
    assert "signal_date DATE NOT NULL UNIQUE" in sql
    assert "market_status TEXT NOT NULL" in sql
    assert "spy_close NUMERIC" in sql
    assert "vix_close NUMERIC" in sql
    assert "details JSONB" in sql
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_db_sql.py -q`

Expected: FAIL because migration file is missing.

- [ ] **Step 2.3: Implement migration and db helper**

Create the SQL from the approved spec. Implement `connect(database_url)`, `apply_migration(conn, sql_path)`, `upsert_market_signal(conn, signal)`, and `get_latest_market_signal(conn)`.

- [ ] **Step 2.4: Run SQL tests**

Run: `python3 -m pytest tests/test_db_sql.py -q`

Expected: PASS.

## Task 3: Market Signal Service

**Files:**
- Create: `investment_assistant/market/__init__.py`
- Create: `investment_assistant/market/models.py`
- Create: `investment_assistant/market/service.py`
- Test: `tests/test_market_signal_service.py`

- [ ] **Step 3.1: Write failing market signal tests**

Create `tests/test_market_signal_service.py`:

```python
import pandas as pd

from investment_assistant.config import MarketConfig
from investment_assistant.market.service import compute_market_signal


def _df(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes, "Open": closes, "High": closes, "Low": closes, "Volume": [1] * len(closes)}, index=idx)


def test_compute_market_signal_green_when_spy_above_ma_and_vix_low():
    def fetcher(ticker, days):
        if ticker == "SPY":
            return _df([100.0] * 100 + [120.0] * 220)
        return _df([15.0])

    signal = compute_market_signal(MarketConfig(), price_fetcher=fetcher, run_id="run-1")

    assert signal.market_status == "green"
    assert signal.spy_above_200ma is True
    assert signal.spy_close == 120.0
    assert signal.vix_close == 15.0
    assert signal.run_id == "run-1"


def test_compute_market_signal_red_when_vix_above_threshold():
    def fetcher(ticker, days):
        if ticker == "SPY":
            return _df([100.0] * 100 + [120.0] * 220)
        return _df([35.0])

    signal = compute_market_signal(MarketConfig(), price_fetcher=fetcher)

    assert signal.market_status == "red"
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_market_signal_service.py -q`

Expected: FAIL because `investment_assistant.market` is missing.

- [ ] **Step 3.3: Implement market signal service**

Use the old `signals.market` rules but return a row-ready `MarketSignal` dataclass containing `signal_date`, tickers, closes, MA200, status, details, and run id.

- [ ] **Step 3.4: Run market tests**

Run: `python3 -m pytest tests/test_market_signal_service.py -q`

Expected: PASS.

## Task 4: SEC Filing Service

**Files:**
- Create: `investment_assistant/filings/__init__.py`
- Create: `investment_assistant/filings/sec_downloader.py`
- Create: `investment_assistant/filings/service.py`
- Test: `tests/test_filing_service.py`

- [ ] **Step 4.1: Write failing filing tests**

Create `tests/test_filing_service.py`:

```python
from pathlib import Path

from investment_assistant.config import FilingsConfig
from investment_assistant.filings.service import download_configured_filings


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download_filings_batch(self, ticker, form_types, since_date, output_base):
        self.calls.append((ticker, form_types, since_date, output_base))
        path = Path(output_base) / ticker / form_types[0] / "000-test.htm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html>ok</html>")
        return [path]


def test_download_configured_filings_uses_runtime_output_dir(tmp_path):
    cfg = FilingsConfig(forms=["10-Q", "10-K"], lookback_years=1, output_dir=tmp_path / "filings")
    downloader = FakeDownloader()

    result = download_configured_filings(["NVDA"], cfg, downloader=downloader)

    assert downloader.calls[0][0] == "NVDA"
    assert downloader.calls[0][1] == ["10-Q", "10-K"]
    assert result["downloaded_count"] == 1
    assert str(result["files"][0]).startswith(str(tmp_path / "filings"))
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_filing_service.py -q`

Expected: FAIL because filing service is missing.

- [ ] **Step 4.3: Implement filing service**

Migrate `data/sec.py` to `investment_assistant/filings/sec_downloader.py`, add skip-existing behavior for nonzero local files, and implement `download_configured_filings`.

- [ ] **Step 4.4: Run filing tests**

Run: `python3 -m pytest tests/test_filing_service.py -q`

Expected: PASS.

## Task 5: Hermes Daily Orchestration and Run Logs

**Files:**
- Create: `investment_assistant/hermes/__init__.py`
- Create: `investment_assistant/hermes/run_log.py`
- Create: `investment_assistant/hermes/assistant.py`
- Create: `investment_assistant/hermes/daily.py`
- Create: `investment_assistant/ops/__init__.py`
- Create: `investment_assistant/ops/hermes_daily.py`
- Test: `tests/test_hermes_daily.py`

- [ ] **Step 5.1: Write failing orchestration tests**

Create `tests/test_hermes_daily.py` with injected fakes:

```python
from investment_assistant.config import AssistantConfig
from investment_assistant.hermes.daily import run_daily


def test_run_daily_orchestrates_market_filings_and_brief(tmp_path):
    calls = []
    cfg = AssistantConfig()
    cfg.filings.output_dir = tmp_path / "filings"

    def market_step(config, run_id):
        calls.append(("market", run_id))
        return {"market_status": "green"}

    def filing_step(watchlist, filings_config):
        calls.append(("filings", tuple(watchlist)))
        return {"downloaded_count": 0, "files": []}

    def brief_step(context):
        calls.append(("brief", context["market"]["market_status"]))
        return {"output_file": None}

    result = run_daily(cfg, market_step=market_step, filing_step=filing_step, brief_step=brief_step, dry_run=False)

    assert [c[0] for c in calls] == ["market", "filings", "brief"]
    assert result["status"] == "success"
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hermes_daily.py -q`

Expected: FAIL because `investment_assistant.hermes.daily` is missing.

- [ ] **Step 5.3: Implement orchestration**

Implement `run_daily(config, dry_run=False, skip_brief=False, ...)` with injectable steps for tests. The real market step must compute and upsert to PG unless `dry_run=True`. The real filing step must write to `/srv/investment-assistant/filings`. The CLI must expose `--dry-run` and `--skip-brief`.

- [ ] **Step 5.4: Run orchestration tests**

Run: `python3 -m pytest tests/test_hermes_daily.py -q`

Expected: PASS.

## Task 6: Deployment, Dashboard, Docs, and Verification

**Files:**
