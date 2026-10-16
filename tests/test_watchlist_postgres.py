"""Opt-in atomic edit tests; all writes are connection-local TEMP tables."""
import os
import pytest
from investment_assistant import db

URL = os.environ.get('INVESTMENT_ASSISTANT_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='no explicit test database URL; TEMP tables only')

@pytest.fixture
def conn():
    import psycopg
    with psycopg.connect(URL) as conn:
        conn.execute('''CREATE TEMP TABLE watchlist_items(ticker TEXT PRIMARY KEY,status TEXT,
          thesis TEXT,tags TEXT[],created_at TIMESTAMPTZ DEFAULT now(),updated_at TIMESTAMPTZ DEFAULT now())''')
        conn.commit()
        yield conn


def test_omitted_fields_survive_status_edit(conn):
    initial = db.upsert_watchlist_item(conn, ticker='MU', thesis='my thesis', tags=['memory'])
    edited = db.upsert_watchlist_item(conn, ticker='MU', status='paused', expected_updated_at=initial['updated_at'])
    assert (edited['status'], edited['thesis'], edited['tags']) == ('paused', 'my thesis', ['memory'])
    with pytest.raises(db.WatchlistConflict):
        db.upsert_watchlist_item(conn, ticker='MU', thesis='lost update', expected_updated_at=initial['updated_at'])
    conn.rollback()
    assert db.list_watchlist_items(conn)[0]['thesis'] == 'my thesis'


def test_deleted_edit_does_not_resurrect_record(conn):
    initial = db.upsert_watchlist_item(conn, ticker='MU', thesis='original')
    db.delete_watchlist_item(conn, 'MU')
    with pytest.raises(db.WatchlistConflict):
        db.upsert_watchlist_item(conn, ticker='MU', status='paused', expected_updated_at=initial['updated_at'])
    conn.rollback()
    assert db.list_watchlist_items(conn) == []
