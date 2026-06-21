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
