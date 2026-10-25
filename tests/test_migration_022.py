import os
import re
import uuid
from pathlib import Path

import pytest

MIGRATION = Path('migrations/022_drop_v1_legacy.sql')
LEGACY_TABLES = ('strategy_scores', 'ticker_signal_snapshots', 'market_signals', 'event_studies',
                 'research_observation_card_versions', 'research_observation_cards')


@pytest.fixture
def legacy_db():
    """Migrations < 022 in a throwaway schema, dropped afterwards; explicit test URL only."""
    url = os.environ.get('INVESTMENT_ASSISTANT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('explicit test database URL required; disposable schema only')
    import psycopg
    schema = f'm022_test_{uuid.uuid4().hex[:12]}'
    with psycopg.connect(url) as conn:
        conn.execute(f'CREATE SCHEMA {schema}')
        conn.execute(f'SET search_path TO {schema}')
        for path in sorted(Path('migrations').glob('0*.sql')):
            if path.name < '022':
                conn.execute(path.read_text(encoding='utf-8'))
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            conn.execute(f'DROP SCHEMA {schema} CASCADE')
            conn.commit()


def _exists(conn, table):
    return conn.execute('SELECT to_regclass(%s)', (table,)).fetchone()[0] is not None


def test_only_one_022_migration():
    assert [p.name for p in Path('migrations').glob('022_*.sql')] == ['022_drop_v1_legacy.sql']


def test_022_only_touches_legacy_objects():
    code = re.sub(r'--[^\n]*', '', MIGRATION.read_text(encoding='utf-8'))
    assert set(re.findall(r'DROP TABLE IF EXISTS (\w+)', code)) == set(LEGACY_TABLES)
    assert set(re.findall(r'DELETE FROM (\w+)', code)) == {'scheduled_jobs'}
    assert 'CASCADE' not in code and 'job_reports' not in code and 'us_research' not in code


def test_022_drops_legacy_and_keeps_mainline(legacy_db):
    conn = legacy_db
    conn.execute("INSERT INTO job_reports(task, run_id, status, summary, started_at, finished_at)"
                 " VALUES ('metrics', 'r1', 'success', '{}', now(), now())")
    conn.commit()
    conn.execute(MIGRATION.read_text(encoding='utf-8'))
    conn.commit()
    for table in LEGACY_TABLES:
        assert not _exists(conn, table), table
    assert conn.execute("SELECT count(*) FROM scheduled_jobs WHERE name IN ('metrics', 'scores', 'event_study')").fetchone()[0] == 0
    kept = {row[0] for row in conn.execute('SELECT name FROM scheduled_jobs').fetchall()}
    assert {'workbench', 'workbench_review', 'filings'} <= kept
    assert _exists(conn, 'us_research_observations') and _exists(conn, 'us_research_collection_state')
    assert conn.execute("SELECT count(*) FROM job_reports WHERE task = 'metrics'").fetchone()[0] == 1


def test_022_is_rerunnable(legacy_db):
    conn = legacy_db
    sql = MIGRATION.read_text(encoding='utf-8')
    conn.execute(sql)
    conn.commit()
    conn.execute(sql)
    conn.commit()
    for table in LEGACY_TABLES:
        assert not _exists(conn, table), table
