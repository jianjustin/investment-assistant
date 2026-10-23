"""Offline contract for the US workbench migration text."""
import re
from pathlib import Path

SQL = Path('migrations/016_us_workbench.sql').read_text(encoding='utf-8')
CODE = re.sub(r'--[^\n]*', '', SQL)

TABLES = ['price_bars', 'news_items', 'news_item_tickers', 'signal_candidates',
          'signal_briefs', 'signal_decisions', 'trades', 'weekly_reviews']


def test_only_one_016_migration():
    assert [p.name for p in Path('migrations').glob('016_*.sql')] == ['016_us_workbench.sql']


def test_creates_all_workbench_tables():
    for table in TABLES:
        assert f'CREATE TABLE IF NOT EXISTS {table} (' in CODE, table


def test_extends_filings_without_backfill():
    assert 'ALTER TABLE filings ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ' in CODE
    assert 'ALTER TABLE filings ADD COLUMN IF NOT EXISTS items TEXT[]' in CODE


def test_never_rewrites_existing_rows():
    upper = CODE.upper()
    assert 'UPDATE ' not in upper.replace('ON CONFLICT', '')
    assert 'DELETE ' not in upper
    assert 'DROP ' not in upper
    assert 'TRUNCATE' not in upper


def test_unique_keys_for_idempotency():
    assert 'UNIQUE (ticker, price_date, revision)' in CODE
    assert 'UNIQUE (source, url)' in CODE
    assert 'UNIQUE (ticker, signal_date, rule_id, rule_version)' in CODE
    assert len(re.findall(r'request_id\s+UUID NOT NULL UNIQUE', CODE)) == 2


def test_registers_scheduled_job_after_us_close():
    assert "('workbench', '06:30', '2-6', 'Asia/Shanghai')" in CODE
    assert 'ON CONFLICT (name) DO NOTHING' in CODE
