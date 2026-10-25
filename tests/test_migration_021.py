import json
import os
import re
import uuid
from pathlib import Path

import pytest

MIGRATION = Path('migrations/021_drop_ashare.sql')


@pytest.fixture
def ashare_db():
    """Migrations 001-020 in a throwaway schema, dropped afterwards; explicit test URL only."""
    url = os.environ.get('INVESTMENT_ASSISTANT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('explicit test database URL required; disposable schema only')
    import psycopg
    schema = f'm021_test_{uuid.uuid4().hex[:12]}'
    with psycopg.connect(url) as conn:
        conn.execute(f'CREATE SCHEMA {schema}')
        conn.execute(f'SET search_path TO {schema}')
        for path in sorted(Path('migrations').glob('0*.sql')):
            if path.name < '021':
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


def _exists(conn, table):
    return conn.execute('SELECT to_regclass(%s)', (table,)).fetchone()[0] is not None


def test_only_one_021_migration():
    assert [p.name for p in Path('migrations').glob('021_*.sql')] == ['021_drop_ashare.sql']


def test_021_only_touches_ashare_objects():
    code = re.sub(r'--[^\n]*', '', MIGRATION.read_text(encoding='utf-8'))
    assert set(re.findall(r'DROP TABLE IF EXISTS (\w+)', code)) == {'cn_observations', 'cn_collection_state'}
    assert set(re.findall(r'DELETE FROM (\w+)', code)) == {
        'research_observation_card_versions', 'research_observation_cards', 'watchlist_items', 'scheduled_jobs'}
    assert 'job_reports' not in code and 'pool_tiers' not in code


def test_021_removes_cn_rows_and_keeps_us(ashare_db):
    conn = ashare_db
    body = json.dumps({'thesis': 'x'})
    for sid in ('CN:stock:688008.SH', 'US:stock:MU'):
        conn.execute('INSERT INTO research_observation_cards(security_id, version, body) VALUES (%s, 1, %s::jsonb)',
                     (sid, body))
        conn.execute('INSERT INTO research_observation_card_versions(security_id, version, body) '
                     'VALUES (%s, 1, %s::jsonb)', (sid, body))
    for ticker in ('688008.SH', '600519.SH', 'MU', 'BRK.B'):
        conn.execute("INSERT INTO watchlist_items(ticker, status) VALUES (%s, 'active')", (ticker,))
    conn.execute("INSERT INTO job_reports(task, run_id, status, started_at) VALUES ('ashares', 'r1', 'success', now())")
    conn.execute("INSERT INTO cn_observations(security_id, dataset, natural_key, revision, source, source_url, payload) "
                 "VALUES ('CN:stock:688008.SH', 'profile', 'k', 'r', 's', 'https://example.com', '{}'::jsonb)")
    assert conn.execute("SELECT count(*) FROM scheduled_jobs WHERE name = 'ashares'").fetchone()[0] == 1

    _apply(conn)
    _apply(conn)  # repeatable

    assert not _exists(conn, 'cn_observations') and not _exists(conn, 'cn_collection_state')
    assert [r[0] for r in conn.execute('SELECT security_id FROM research_observation_cards')] == ['US:stock:MU']
    assert [r[0] for r in conn.execute('SELECT security_id FROM research_observation_card_versions')] == ['US:stock:MU']
    assert {r[0] for r in conn.execute('SELECT ticker FROM watchlist_items')} == {'MU', 'BRK.B'}
    jobs = {r[0] for r in conn.execute('SELECT name FROM scheduled_jobs')}
    assert 'workbench' in jobs and 'ashares' not in jobs
    assert conn.execute("SELECT count(*) FROM job_reports WHERE task = 'ashares'").fetchone()[0] == 1


def test_021_on_fresh_install(ashare_db):
    _apply(ashare_db)
    assert _exists(ashare_db, 'research_observation_cards')
    assert _exists(ashare_db, 'research_observation_card_versions')
    assert not _exists(ashare_db, 'cn_observations')
