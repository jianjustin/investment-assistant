import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from investment_assistant.api.app import create_app


@pytest.fixture(autouse=True)
def isolate_unit_tests_from_local_database(monkeypatch):
    """Individual DB tests opt in explicitly; a local .env must not make mocks use production."""
    monkeypatch.delenv('INVESTMENT_ASSISTANT_DATABASE_URL', raising=False)
    monkeypatch.setenv('SCHEDULER_ENABLED', '0')
    monkeypatch.setenv('WORKBENCH_LLM_PROVIDER', 'off')  # tests never call a real model


@pytest.fixture()
def client():
    return TestClient(create_app())


WORKBENCH_MIGRATIONS = ('007_scheduled_jobs.sql', '011_filings.sql', '016_us_workbench.sql',
                        '017_trade_plans.sql')


@pytest.fixture
def workbench_db():
    """Workbench schema in a throwaway Postgres schema, dropped afterwards; explicit test URL only."""
    url = os.environ.get('INVESTMENT_ASSISTANT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('explicit test database URL required; disposable schema only')
    import psycopg
    schema = f'wb_test_{uuid.uuid4().hex[:12]}'
    with psycopg.connect(url) as conn:
        conn.execute(f'CREATE SCHEMA {schema}')
        conn.execute(f'SET search_path TO {schema}')
        for name in WORKBENCH_MIGRATIONS:
            conn.execute(Path('migrations', name).read_text(encoding='utf-8'))
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            conn.execute(f'DROP SCHEMA {schema} CASCADE')
            conn.commit()
