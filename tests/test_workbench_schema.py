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


SQL_017 = Path('migrations/017_trade_plans.sql').read_text(encoding='utf-8')
CODE_017 = re.sub(r'--[^\n]*', '', SQL_017)
FLAT_017 = re.sub(r'\s+', ' ', CODE_017)

TABLES_017 = ['trade_plans', 'earnings_dates', 'account_snapshots', 'cash_flows', 'monthly_reviews']


def test_only_one_017_migration():
    assert [p.name for p in Path('migrations').glob('017_*.sql')] == ['017_trade_plans.sql']


def test_017_is_additive():
    for table in TABLES_017:
        assert f'CREATE TABLE IF NOT EXISTS {table} (' in CODE_017, table
    assert 'ALTER TABLE signal_decisions ADD COLUMN IF NOT EXISTS plan_id' in CODE_017
    upper = CODE_017.upper()
    assert 'UPDATE ' not in upper.replace('ON CONFLICT', '')
    assert 'DELETE ' not in upper
    assert 'DROP ' not in upper
    assert 'TRUNCATE' not in upper


def test_017_plan_uniqueness():
    assert "ON trade_plans (ticker, signal_date, plan_version) WHERE kind = 'rule'" in FLAT_017
    assert 'UNIQUE (request_id)' in FLAT_017
