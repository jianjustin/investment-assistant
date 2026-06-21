# Hermes Investment Assistant Redesign

## Decision

Adopt 方案 A: `investment-assistant` becomes the source repository for the Hermes investment assistant. The repository stores runtime logic, business rules, database schema, deployment templates, tests, and documentation. It does not store business output data.

`/opt/hermes-investment-assistant` remains the production deployment directory. Files under `/opt`, `/srv`, and Postgres are runtime state, not source of truth.

## Current State

The remote host currently has two partially overlapping systems:

- `/home/jianjustin/workspaces/investment-assistant`: Git repository cloned from GitHub. It is still shaped as the older `earnings-agent` project.
- `/opt/hermes-investment-assistant`: live Hermes MVP installation. It contains `scripts/investment_assistant.py`, `dashboard/dashboard_server.py`, config, systemd services, run logs, Hermes home, and draft output paths.

The repository already has reusable investment modules:

- `data/price.py`: yfinance OHLCV fetcher.
- `signals/market.py`: SPY 200MA plus VIX market gate.
- `data/sec.py`: SEC EDGAR downloader with ticker to CIK lookup, recent filings, historical paged filings, and batch download support.
- `ops/daily_scan.py`: old daily scan entrypoint that writes `data/daily_scan.json` inside the repository.
- `ops/earnings_monitor.py`: old earnings monitor that writes `data/earnings_today.json` and SEC files inside the repository.

The live Hermes MVP currently has useful runtime behavior but is not source-controlled in this repository:

- Reads vault context from `/srv/vault-ro`.
- Writes draft notes only to `/srv/vault-staging/06-收集箱/AI草稿`.
- Calls DeepSeek/OpenAI-compatible APIs.
- Records run logs under `/opt/hermes-investment-assistant/logs` and task index under `/opt/hermes-investment-assistant/data`.
- Exposes a LAN dashboard through `hermes-investment-dashboard.service`.
- Runs `hermes-investment-daily.timer` at 08:30 local time.

## Goals

1. Redesign the repository around Hermes, not the old standalone `earnings-agent` identity.
2. Store all Hermes investment assistant logic and business rules in the repository.
3. Keep business output data out of the repository.
4. Create a Postgres service and a table for daily broad-market signals.
5. Make the Hermes daily scheduled task fetch and persist market signals.
6. Make the Hermes daily scheduled task download quarterly and annual SEC filings for configured US stocks.
7. Store downloaded filing files as HTML/PDF-compatible original documents in a custom runtime directory that can be synced by Syncthing.
8. Simplify unclear old code so the repository has a small number of obvious entrypoints.

## Non-Goals

- No trading API integration.
- No automatic buy/sell decision.
- No silent writes to existing vault notes.
- No storage of generated market signals, SEC filings, daily JSON outputs, or run logs inside Git-tracked repository paths.
- No large rewrite of the Hermes agent implementation under `/opt/hermes-investment-assistant/hermes-agent`.
- No mandatory HTML-to-PDF conversion in the first implementation. SEC original `.htm`, `.html`, and `.pdf` documents are preserved. PDF conversion remains a separate follow-up if a downstream reader needs it.

## Target Repository Shape

The repository should move from scattered top-level scripts toward one clear package:

```text
investment-assistant/
├── investment_assistant/
│   ├── __init__.py
│   ├── config.py
│   ├── runtime_paths.py
│   ├── db.py
│   ├── market/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── service.py
│   ├── filings/
│   │   ├── __init__.py
│   │   ├── sec_downloader.py
│   │   └── service.py
│   ├── hermes/
│   │   ├── __init__.py
│   │   ├── daily.py
│   │   ├── assistant.py
│   │   └── run_log.py
│   ├── dashboard/
│   │   ├── __init__.py
│   │   └── server.py
│   └── ops/
│       ├── __init__.py
│       └── hermes_daily.py
├── deploy/
│   ├── docker-compose.postgres.yml
│   ├── systemd/
│   │   ├── hermes-investment-daily.service
│   │   ├── hermes-investment-daily.timer
│   │   ├── hermes-investment-dashboard.service
│   │   └── investment-assistant-postgres.service
│   └── install.sh
├── migrations/
│   └── 001_market_signals.sql
├── config/
│   └── investment-assistant.example.json
├── tests/
├── docs/
└── README.md
```

The old directories and scripts are handled as follows:

- Reuse code from `data/price.py`, `signals/market.py`, and `data/sec.py` inside the new package.
- Retire duplicate top-level shims after the new entrypoints pass tests: `earnings_calendar.py`, `earnings_monitor.py`, `sec_downloader.py`, `vault_writer.py`, and `diagnose_edgar.py`.
- Replace `ops/daily_scan.py` and `ops/earnings_monitor.py` with compatibility wrappers only if needed; otherwise document the new `python -m investment_assistant.ops.hermes_daily` entrypoint.
- Remove repository-local business output writes such as `data/daily_scan.json`, `data/earnings_today.json`, and `data/earnings_reports/` from the main path.
- Keep tests focused on the new package. Old tests can be migrated or removed when they only cover retired entrypoints.

## Runtime Data Boundaries

The repository may contain:

- Python source code.
- SQL migrations.
- systemd and Docker Compose templates.
- example config files without secrets.
- tests and docs.

The repository must not contain:

- downloaded filings.
- generated signal JSON.
- Postgres data directories.
- Hermes state database.
- API keys or service passwords.
- vault drafts or generated investment notes.

Runtime paths:

```text
/opt/hermes-investment-assistant/          deployed app, config, virtualenv, logs
/opt/hermes-investment-assistant/.env      secrets and runtime env, chmod 600
/srv/investment-assistant/filings/         SEC filing document storage, Syncthing candidate
/var/lib/investment-assistant/postgres/    Postgres persistent volume when using Docker bind mount
/srv/vault-ro                              read-only vault source
/srv/vault-staging/06-收集箱/AI草稿          only writable vault draft target
```

## Configuration

Runtime config lives at `/opt/hermes-investment-assistant/config/investment-assistant.json`. The repository contains `config/investment-assistant.example.json`.

Required config fields:

```json
{
  "watchlist": ["CRDO", "MU", "RKLB", "NVDA"],
  "market": {
    "spy_ticker": "SPY",
    "vix_ticker": "^VIX",
    "ma_days": 200,
    "history_days": 300,
    "yellow_vix": 20,
    "red_vix": 30
  },
  "filings": {
    "forms": ["10-Q", "10-K"],
    "lookback_years": 3,
    "output_dir": "/srv/investment-assistant/filings"
  },
  "vault_ro": "/srv/vault-ro",
  "draft_dir": "/srv/vault-staging/06-收集箱/AI草稿",
  "brief_time_local": "08:30",
  "max_daily_focus_items": 3,
  "model_default": "deepseek-v4-pro"
}
```

Required environment variables in `/opt/hermes-investment-assistant/.env`:

- `INVESTMENT_ASSISTANT_DATABASE_URL`
- `SEC_USER_AGENT`
- `DEEPSEEK_API_KEY` or `OPENAI_API_KEY`
- `SERVER_PWD` or `HERMES_DASHBOARD_PASSWORD`

## Postgres Service

Use Docker-managed Postgres because Docker is already present on the host and keeps the database service isolated from the OS package lifecycle.

Repository artifacts:

- `deploy/docker-compose.postgres.yml`: defines a single `postgres` service.
- `deploy/systemd/investment-assistant-postgres.service`: starts the compose service at boot.
- `migrations/001_market_signals.sql`: creates the required signal table.

The service name should be `investment-assistant-postgres.service`.

The database name should be `investment_assistant`.

## Market Signals Table

`migrations/001_market_signals.sql` creates this table:

```sql
CREATE TABLE IF NOT EXISTS market_signals (
  id BIGSERIAL PRIMARY KEY,
  signal_date DATE NOT NULL UNIQUE,
  market_status TEXT NOT NULL CHECK (market_status IN ('green', 'yellow', 'red')),
  spy_ticker TEXT NOT NULL DEFAULT 'SPY',
  spy_close NUMERIC(18,6) NOT NULL,
  spy_ma200 NUMERIC(18,6) NOT NULL,
  spy_above_200ma BOOLEAN NOT NULL,
  vix_ticker TEXT NOT NULL DEFAULT '^VIX',
  vix_close NUMERIC(18,6) NOT NULL,
  source TEXT NOT NULL DEFAULT 'yfinance',
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  run_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

