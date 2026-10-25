import os
import uuid
from pathlib import Path

import pytest

MIGRATION = Path('migrations/023_screen_and_beijing_jobs.sql')


@pytest.fixture
def migrated_db():
    """Migrations < 023 in a throwaway schema, dropped afterwards; explicit test URL only."""
    url = os.environ.get('INVESTMENT_ASSISTANT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('explicit test database URL required; disposable schema only')
    import psycopg
    schema = f'm023_test_{uuid.uuid4().hex[:12]}'
    with psycopg.connect(url) as conn:
        conn.execute(f'CREATE SCHEMA {schema}')
        conn.execute(f'SET search_path TO {schema}')
        for path in sorted(Path('migrations').glob('0*.sql')):
            if path.name < '023':
                conn.execute(path.read_text(encoding='utf-8'))
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            conn.execute(f'DROP SCHEMA {schema} CASCADE')
            conn.commit()


def _filings(conn):
    return conn.execute(
        "SELECT timezone, time_local, next_run_at FROM scheduled_jobs WHERE name = 'filings'"
    ).fetchone()


def test_023_moves_filings_to_beijing(migrated_db):
    conn = migrated_db
    conn.execute(MIGRATION.read_text(encoding='utf-8'))
    conn.commit()
    timezone, time_local, _ = _filings(conn)
    assert (timezone, time_local) == ('Asia/Shanghai', '09:30')
    row = conn.execute(
        "SELECT (next_run_at AT TIME ZONE 'Asia/Shanghai')::time AS at, "
        "extract(isodow FROM next_run_at AT TIME ZONE 'Asia/Shanghai') AS isodow, "
        "next_run_at > now() AS later, "
        "next_run_at <= now() + interval '4 days' AS soon "
        "FROM scheduled_jobs WHERE name = 'filings'"
    ).fetchone()
    at, isodow, later, soon = row
    assert str(at) == '09:30:00'
    assert 1 <= isodow <= 5
    assert later is True
    assert soon is True


def test_023_keeps_user_changed_timezone(migrated_db):
    conn = migrated_db
    conn.execute("UPDATE scheduled_jobs SET timezone = 'Asia/Shanghai', time_local = '10:00'"
                 " WHERE name = 'filings'")
    conn.commit()
    conn.execute(MIGRATION.read_text(encoding='utf-8'))
    conn.commit()
    assert _filings(conn)[:2] == ('Asia/Shanghai', '10:00')


def test_023_is_rerunnable(migrated_db):
    conn = migrated_db
    sql = MIGRATION.read_text(encoding='utf-8')
    conn.execute(sql)
    conn.commit()
    conn.execute(sql)
    conn.commit()
    assert _filings(conn)[:2] == ('Asia/Shanghai', '09:30')
