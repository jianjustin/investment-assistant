import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

MIGRATION = Path('migrations/024_data_fetch_runs.sql')

NOW = datetime(2026, 10, 26, 22, 30, tzinfo=UTC)


@pytest.fixture
def migrated_db():
    """Migrations < 024 in a throwaway schema, dropped afterwards; explicit test URL only."""
    url = os.environ.get('INVESTMENT_ASSISTANT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('explicit test database URL required; disposable schema only')
    import psycopg
    schema = f'm024_test_{uuid.uuid4().hex[:12]}'
    with psycopg.connect(url) as conn:
        conn.execute(f'CREATE SCHEMA {schema}')
        conn.execute(f'SET search_path TO {schema}')
        for path in sorted(Path('migrations').glob('0*.sql')):
            if path.name < '024':
                conn.execute(path.read_text(encoding='utf-8'))
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            conn.execute(f'DROP SCHEMA {schema} CASCADE')
            conn.commit()


def _apply(conn):
    conn.execute(MIGRATION.read_text(encoding='utf-8'))
    conn.commit()


def _insert(conn, **overrides):
    """Insert one run with savepoint isolation; failures/detail stay out so DB defaults apply."""
    values = {'family': 'bars', 'job': 'workbench', 'trigger': 'scheduled', 'scope': 'family',
              'status': 'success', 'target_count': 10, 'ok_count': 10,
              'started_at': NOW, 'finished_at': NOW}
    values.update(overrides)
    cols = ', '.join(values)
    marks = ', '.join(['%s'] * len(values))
    with conn.transaction():
        conn.execute(f'INSERT INTO data_fetch_runs ({cols}) VALUES ({marks})', list(values.values()))


def test_024_creates_table_and_is_rerunnable(migrated_db):
    conn = migrated_db
    sql = MIGRATION.read_text(encoding='utf-8')
    conn.execute(sql)
    conn.commit()
    conn.execute(sql)
    conn.commit()
    assert conn.execute("SELECT to_regclass('data_fetch_runs')").fetchone()[0] is not None
    assert conn.execute("SELECT to_regclass('idx_data_fetch_runs_family')").fetchone()[0] is not None


def test_024_check_constraints(migrated_db):
    import psycopg
    conn = migrated_db
    _apply(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(conn, family='atr')
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(conn, trigger='cron')
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(conn, scope='ticker', ticker=None)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(conn, scope='family', ticker='MU')
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(conn, target_count=2, ok_count=3)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(conn, status='ok')
    _insert(conn)  # the base row is legal
    row = conn.execute('SELECT failures, detail, ticker FROM data_fetch_runs ORDER BY id DESC LIMIT 1').fetchone()
    assert row[0] == [] and row[1] == {} and row[2] is None


def _columns(conn):
    return set(conn.execute('SELECT table_name, column_name FROM information_schema.columns '
                            'WHERE table_schema = current_schema()').fetchall())


def test_024_touches_no_existing_table(migrated_db):
    conn = migrated_db
    before = _columns(conn)
    _apply(conn)
    after = _columns(conn)
    assert {table for table, _ in after - before} == {'data_fetch_runs'}
    assert before - after == set()
