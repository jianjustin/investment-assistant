from pathlib import Path


def test_market_signals_migration_defines_required_table_and_unique_date():
    sql = Path("migrations/001_market_signals.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS market_signals" in sql
    assert "signal_date DATE NOT NULL UNIQUE" in sql
    assert "market_status TEXT NOT NULL" in sql
    assert "spy_close NUMERIC" in sql
    assert "vix_close NUMERIC" in sql
    assert "details JSONB" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_market_signals_signal_date" in sql


def test_watchlist_items_migration_defines_manageable_watchlist_table():
    sql = Path("migrations/002_watchlist_items.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS watchlist_items" in sql
    assert "ticker TEXT NOT NULL UNIQUE" in sql
    assert "status TEXT NOT NULL" in sql
    assert "thesis TEXT" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_watchlist_items_status" in sql


def test_ticker_signal_snapshots_migration_defines_required_table():
    sql = Path("migrations/003_ticker_signal_snapshots.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS ticker_signal_snapshots" in sql
    assert "ticker TEXT NOT NULL" in sql
    assert "signal_date DATE NOT NULL" in sql
    assert "trend_state TEXT NOT NULL" in sql
    assert "attention_level TEXT NOT NULL" in sql
    assert "trigger_reason JSONB NOT NULL" in sql
    assert "UNIQUE (ticker, signal_date)" in sql


def test_strategy_scores_migration_defines_required_table():
    sql = Path("migrations/004_strategy_scores.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS strategy_scores" in sql
    assert "ticker TEXT NOT NULL" in sql
    assert "strategy TEXT NOT NULL" in sql
    assert "score INTEGER NOT NULL" in sql
    assert "evidence JSONB NOT NULL" in sql
    assert "limits JSONB NOT NULL" in sql


def test_strategy_scores_fk_migration_adds_constraint():
    sql = Path("migrations/005_strategy_scores_fk.sql").read_text()
    assert "fk_strategy_scores_snapshot" in sql
    assert "REFERENCES ticker_signal_snapshots (id)" in sql
    assert "ON DELETE SET NULL" in sql
    # must clean up orphans before adding constraint
    assert "UPDATE strategy_scores" in sql
    # idempotent guard
    assert "pg_constraint" in sql


def test_job_reports_migration():
    sql = Path("migrations/006_job_reports.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS job_reports" in sql
    assert "task        TEXT NOT NULL" in sql or "task TEXT NOT NULL" in sql
    assert "run_id" in sql and "status" in sql
    assert "summary     JSONB" in sql or "summary JSONB" in sql
    assert "created_at  TIMESTAMPTZ" in sql or "created_at TIMESTAMPTZ" in sql


def test_scheduled_jobs_migration():
    sql = Path("migrations/007_scheduled_jobs.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS scheduled_jobs" in sql
    assert "name         TEXT NOT NULL UNIQUE" in sql or "name TEXT NOT NULL UNIQUE" in sql
    assert "time_local" in sql and "weekday_mask" in sql and "timezone" in sql
    assert "next_run_at" in sql
    assert "'metrics'" in sql and "'filings'" in sql and "'scores'" in sql  # seed
    assert "ON CONFLICT (name) DO NOTHING" in sql


def test_notify_settings_migration():
    sql = Path("migrations/008_notify_settings.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS notify_settings" in sql
    assert "id" in sql and "CHECK (id = 1)" in sql
    assert "webhooks" in sql and "task_channels" in sql and "task_enabled" in sql
    assert "JSONB" in sql
    assert "ON CONFLICT (id) DO NOTHING" in sql


def test_event_studies_migration():
    sql = Path("migrations/009_event_studies.sql").read_text()  # 用实测编号
    assert "CREATE TABLE IF NOT EXISTS event_studies" in sql
    assert "kind" in sql and "params_hash" in sql
    assert "result" in sql and "JSONB" in sql
    assert "UNIQUE (kind, params_hash)" in sql


def test_job_reports_target_dates_migration():
    sql = Path("migrations/010_job_reports_target_dates.sql").read_text()
    assert "ALTER TABLE job_reports" in sql
    assert "target_start_date DATE" in sql
    assert "target_end_date DATE" in sql
    assert "trigger_source TEXT NOT NULL DEFAULT 'scheduled'" in sql


def test_filings_migration_defines_index_table():
    sql = Path("migrations/011_filings.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS filings" in sql
    assert "ticker TEXT NOT NULL" in sql
    assert "form TEXT NOT NULL" in sql
    assert "filing_date DATE NOT NULL" in sql
    assert "accession_number TEXT NOT NULL" in sql
    assert "UNIQUE (accession_number, primary_document)" in sql
    assert "idx_filings_ticker_date" in sql


def test_notify_channel_migration():
    sql = Path("migrations/012_notify_channel.sql").read_text()
    assert "ALTER TABLE notify_settings" in sql
    assert "channel TEXT NOT NULL DEFAULT 'discord'" in sql
    assert "email" in sql and "JSONB" in sql and "'{}'::jsonb" in sql


def test_signal_provenance_migration_is_nullable_idempotent_and_never_relabels_old_rows():
    import re

    sql = Path("migrations/015_signal_provenance.sql").read_text()
    statements = [s.strip() for s in re.sub(r"--[^\n]*", "", sql).split(";") if s.strip()]
    normalized = [" ".join(s.split()).upper() for s in statements]
    assert normalized == [
        "ALTER TABLE TICKER_SIGNAL_SNAPSHOTS ADD COLUMN IF NOT EXISTS PRICE_DATE DATE",
        "ALTER TABLE TICKER_SIGNAL_SNAPSHOTS ADD COLUMN IF NOT EXISTS CALCULATION_VERSION TEXT",
        "ALTER TABLE STRATEGY_SCORES ADD COLUMN IF NOT EXISTS CALCULATION_VERSION TEXT",
    ]
    assert not re.search(r"\b(DEFAULT|UPDATE|DELETE|DROP|INSERT)\b", " ".join(normalized))

