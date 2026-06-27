import os

import pytest

DB_URL = os.environ.get("INVESTMENT_ASSISTANT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="no test database configured")


def test_fk_rejects_bogus_snapshot_id():
    import psycopg

    from investment_assistant.migrate import run

    run(DB_URL)  # apply 001..005
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cur.execute(
                    "INSERT INTO strategy_scores (ticker, score_date, strategy, score, source_snapshot_id)"
                    " VALUES ('ZZZ', CURRENT_DATE, 'trend_relative_strength', 50, 999999999)"
                )
        conn.rollback()
