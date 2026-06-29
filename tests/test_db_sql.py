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
