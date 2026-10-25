import os
from pathlib import Path

import pytest

DB_URL = os.environ.get("INVESTMENT_ASSISTANT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="no test database configured")


def test_fk_rejects_bogus_snapshot_id():
    """Migration 005's FK holds on the chain up to 005 (022 later drops both tables)."""
    import psycopg

    with psycopg.connect(DB_URL) as conn:
        schema_sqls = []
        # Apply 001..005 only: run() would replay through 022 and drop the legacy tables.
        for path in sorted(Path("migrations").glob("0*.sql")):
            if path.name <= "005_strategy_scores_fk.sql":
                schema_sqls.append(path.read_text(encoding="utf-8"))
        with conn.cursor() as cur:
            for sql in schema_sqls:
                cur.execute(sql)
        conn.commit()
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cur.execute(
                    "INSERT INTO strategy_scores (ticker, score_date, strategy, score, source_snapshot_id)"
                    " VALUES ('ZZZ', CURRENT_DATE, 'trend_relative_strength', 50, 999999999)"
                )
        conn.rollback()
        # The disposable test database is shared: drop what only this test created.
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS strategy_scores, ticker_signal_snapshots, market_signals, job_reports, watchlist_items, scheduled_jobs, notify_settings, research_observation_cards, research_observation_card_versions CASCADE")
        conn.commit()
