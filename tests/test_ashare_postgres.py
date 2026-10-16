"""Opt-in PostgreSQL verification. Every write goes to connection-local TEMP tables."""
import os
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from investment_assistant.ashare import repository as repo, service
from investment_assistant.ashare.sources import SourceError

URL = os.environ.get('INVESTMENT_ASSISTANT_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='no test database configured; temporary tables only')


@pytest.fixture
def conn():
    import psycopg
    with psycopg.connect(URL) as conn:
        conn.execute('''CREATE TEMP TABLE cn_observations(
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, security_id TEXT, dataset TEXT,
            natural_key TEXT,revision TEXT,data_date DATE,disclosed_at TIMESTAMPTZ,source TEXT,source_url TEXT,
            payload JSONB,first_seen_at TIMESTAMPTZ,last_seen_at TIMESTAMPTZ,
            UNIQUE(security_id,dataset,natural_key,revision));
            CREATE TEMP TABLE cn_collection_state(
            security_id TEXT,dataset TEXT,status TEXT,attempted_at TIMESTAMPTZ,succeeded_at TIMESTAMPTZ,
            requested_start DATE,requested_end DATE,row_count INT,error TEXT,details JSONB,
            PRIMARY KEY(security_id,dataset));
            CREATE TEMP TABLE research_observation_cards(
            security_id TEXT PRIMARY KEY,version INT,body JSONB,evidence_seen_at TIMESTAMPTZ DEFAULT now(),
            created_at TIMESTAMPTZ DEFAULT now(),updated_at TIMESTAMPTZ DEFAULT now());
            CREATE TEMP TABLE research_observation_card_versions(
            security_id TEXT,version INT,body JSONB,saved_at TIMESTAMPTZ DEFAULT now(),PRIMARY KEY(security_id,version));''')
        conn.commit()
        yield conn


SID = 'CN:stock:688008.SH'


def record(value=10):
    return {'natural_key': '2026-06-30', 'data_date': '2026-06-30',
            'disclosed_at': '2026-08-30T00:00:00+08:00', 'source': 'synthetic_test_only',
            'source_url': 'https://example.test', 'payload': {'value': value}}


def test_duplicates_revisions_reversions_and_history(conn):
    t = datetime(2026, 10, 16, 1, tzinfo=UTC)
    assert repo.store_rows(conn, SID, 'financials', [record()], now=t) == 1
    assert repo.store_rows(conn, SID, 'financials', [record()], now=t + timedelta(minutes=1)) == 0
    assert repo.read_rows(conn, SID, 'financials', as_of=t - timedelta(days=1)) == []
    assert repo.store_rows(conn, SID, 'financials', [record(20)], now=t + timedelta(minutes=2)) == 1
    assert repo.store_rows(conn, SID, 'financials', [record(10)], now=t + timedelta(minutes=3)) == 1
    assert repo.read_rows(conn, SID, 'financials')[0]['value'] == 10
    assert repo.read_rows(conn, SID, 'financials', as_of=t + timedelta(minutes=2, seconds=1))[0]['value'] == 20
    assert conn.execute('SELECT count(*) FROM cn_observations').fetchone()[0] == 3


def test_disclosed_date_is_independent_of_report_period_and_collection(conn):
    t = datetime(2026, 7, 1, tzinfo=UTC)
    repo.store_rows(conn, SID, 'financials', [record()], now=t)
    assert repo.read_rows(conn, SID, 'financials', as_of=t + timedelta(days=1)) == []
    assert len(repo.read_rows(conn, SID, 'financials', as_of=datetime(2026,10,16,tzinfo=UTC))) == 1


def test_failed_source_retains_records_then_retry_resumes(conn, monkeypatch):
    monkeypatch.setattr(service, 'connection', lambda: nullcontext(conn))
    class Source:
        def announcements(self, *args):
            raise SourceError('HTTP 429: simulated test failure')
    repo.store_rows(conn, SID, 'announcements', [record()])
    conn.commit()
    result = service.sync(['688008.SH'], start='2026-09-01', end='2026-10-15',
                          datasets=['announcements'], source=Source())
    assert result['errors'][0]['status'] == 'failed'
    assert len(repo.read_rows(conn, SID, 'announcements')) == 1
    assert repo.states(conn, SID)['announcements']['status'] == 'failed'
    class Recovered:
        def announcements(self, *args):
            return [record()]
    result = service.sync(['688008.SH'], start='2026-09-01', end='2026-10-15',
                          datasets=['announcements'], source=Recovered(), retry_failed=True)
    assert result['results'][0]['inserted_versions'] == 0
    assert repo.states(conn, SID)['announcements']['status'] == 'ready'


def test_card_conflict_preserves_versions_and_evidence_changes(conn):
    card = repo.save_card(conn, SID, {'hypothesis': 'test only'}, 0)
    conn.commit()
    assert card['version'] == 1
    with pytest.raises(repo.CardConflict):
        repo.save_card(conn, SID, {'hypothesis': 'lost update'}, 0)
    conn.rollback()
    assert repo.get_card(conn, SID)['body']['hypothesis'] == 'test only'
    repo.store_rows(conn, SID, 'financials', [record()], now=datetime.now(UTC) + timedelta(seconds=1))
    assert repo.get_card(conn, SID)['new_evidence_count'] == 1


def test_historical_view_does_not_leak_current_card_or_benchmark_status(conn, monkeypatch):
    monkeypatch.setattr(service, 'connection', lambda: nullcontext(conn))
    repo.save_card(conn, SID, {'hypothesis': 'current only'}, 0)
    conn.commit()
    v = service.view('688008.SH', start='2026-09-01', end='2026-10-15',
                     as_of='2026-01-01T00:00:00+08:00')
    assert v['card'] is None
    assert all(b['collection']['status'] == 'unavailable_at_cutoff' for b in v['comparisons'])
    assert v['pit']['strict'] is False
