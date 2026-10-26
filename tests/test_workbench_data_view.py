"""Read-only use cases behind the Data menu (v2.3 Task 8, design §8): overview,
family detail and raw browse. All market data below is synthetic. The reads never
collect: a never-collected ticker is an empty 200, not an error and not a fetch
(test_browse_unknown_ticker_is_empty_not_error), and every GET leaves the business
tables untouched (test_reads_are_read_only)."""
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import bars as bars_module
from investment_assistant.workbench import collect, data_view, families, plans, repository, service
from investment_assistant.workbench import macro as macro_module
from investment_assistant.workbench import news as news_module
from investment_assistant.workbench import universe as universe_module

SESSION = date(2026, 10, 22)                         # Thursday
NOW = datetime(2026, 10, 22, 22, 30, tzinfo=UTC)     # 18:30 New York

CARD_KEYS = {'id', 'title', 'purpose', 'kind', 'fetch_via', 'per_ticker', 'job', 'coverage',
             'latest_at', 'last_run', 'last_success_at', 'evidence', 'notes'}
BUSINESS_TABLES = repository.WORKBENCH_TABLES + ('data_fetch_runs',)


@pytest.fixture
def db(workbench_db, monkeypatch):
    @contextmanager
    def connection():
        yield workbench_db
    monkeypatch.setattr(service, 'connection', connection)
    return workbench_db


def _bar(conn, **overrides):
    values = {'ticker': 'NVDA', 'price_date': SESSION, 'open': 100, 'high': 105, 'low': 99,
              'close': 104, 'volume': 1000, 'adj_close': 104, 'revision': 1, 'fetched_at': NOW}
    values.update(overrides)
    cols = ', '.join(values)
    conn.execute(f"INSERT INTO price_bars ({cols}) VALUES ({', '.join(['%s'] * len(values))})",
                 list(values.values()))


def _run(db, **overrides):
    row = {'family': 'bars', 'job': 'workbench', 'trigger': 'manual_family', 'run_id': 'r1',
           'scope': 'family', 'ticker': None, 'session': SESSION, 'status': 'success',
           'target_count': 2, 'ok_count': 2, 'failures': [], 'detail': {},
           'started_at': NOW, 'finished_at': NOW}
    row.update(overrides)
    repository.insert_fetch_run(db, row)


def test_overview_has_six_cards_and_evidence(db):
    _bar(db)   # scheduled_jobs 里 workbench/filings 两行来自迁移 016/007
    _run(db, run_id='r-ov', finished_at=NOW + timedelta(hours=1))
    db.commit()

    out = data_view.overview(now=NOW)
    cards = {card['id']: card for card in out['families']}
    assert [card['id'] for card in out['families']] == \
        ['bars', 'sec_filings', 'news', 'atr', 'fred', 'universe']
    assert out['evidence'] == families.EVIDENCE
    assert out['session'] == SESSION and out['fetch_runs_ready'] is True

    bars_card = cards['bars']
    assert set(bars_card) == CARD_KEYS
    assert bars_card['coverage']['targets'] == len(families.targets(db, 'bars')[0])
    assert bars_card['coverage']['covered'] == 1 and 'NVDA' not in bars_card['coverage']['lagging']
    assert bars_card['job'] == {'name': 'workbench', 'enabled': True, 'next_run_at': None}
    assert bars_card['last_run'] == {'status': 'success', 'trigger': 'manual_family', 'scope': 'family',
                                     'ticker': None, 'finished_at': NOW + timedelta(hours=1),
                                     'ok_count': 2, 'target_count': 2, 'failures': []}
    assert bars_card['last_success_at'] == NOW + timedelta(hours=1)

    assert cards['sec_filings']['job']['name'] == 'filings'
    assert 'no_filing_is_not_missing' in cards['sec_filings']['notes']
    assert 'pool_empty' in cards['news']['notes']

    assert cards['atr']['evidence'] == families.EVIDENCE + ' ' + families.ATR_EVIDENCE
    assert cards['atr']['last_run'] == bars_card['last_run']      # ATR 取 bars 的拉取记录
    assert cards['atr']['last_success_at'] == bars_card['last_success_at']
    assert cards['news']['last_run'] is None

    loaded = universe_module.load()
    assert cards['universe']['coverage'] == {'targets': len(loaded.tickers),
                                             'covered': len(loaded.tickers), 'lagging': []}
    assert cards['universe']['latest_at'] == loaded.as_of
    assert 'universe_stale' not in cards['universe']['notes']


def test_card_uses_latest_run(db):
    success_at, failed_at = NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    _run(db, run_id='ok', finished_at=success_at)
    _run(db, run_id='bad', status='failed', ok_count=0, finished_at=failed_at,
         failures=[{'target': f'T{i}', 'reason': f'boom {i}'} for i in range(8)])
    db.commit()

    card = data_view.overview(now=NOW)['families'][0]
    assert card['last_run']['status'] == 'failed' and card['last_run']['finished_at'] == failed_at
    assert [f['target'] for f in card['last_run']['failures']] == ['T0', 'T1', 'T2', 'T3', 'T4']
    assert card['last_success_at'] == success_at


def test_overview_without_fetch_runs_table(db):
    _bar(db)
    db.execute('DROP TABLE data_fetch_runs')
    db.commit()

    out = data_view.overview(now=NOW)
    assert out['fetch_runs_ready'] is False
    for card in out['families']:
        assert card['last_run'] is None and card['last_success_at'] is None
    bars_card = next(card for card in out['families'] if card['id'] == 'bars')
    assert bars_card['coverage']['targets'] == len(families.targets(db, 'bars')[0])
    assert bars_card['coverage']['covered'] == 1


def test_detail_rows_and_last_failure(db):
    _bar(db)
    _run(db, status='failed', ok_count=0, failures=[{'target': '*', 'reason': 'whole family down'}])
    db.commit()

    detail = data_view.family_detail('bars', now=NOW)
    assert detail['card']['id'] == 'bars' and detail['card']['coverage']['targets'] > 0
    assert [run['status'] for run in detail['runs']] == ['failed']
    assert detail['rows']
    for row in detail['rows']:
        assert set(row) == {'target', 'latest_at', 'lagging', 'last_failure'}
        assert row['last_failure'] == 'whole family down'   # '*' 对每个 target 都算
    nvda = next(row for row in detail['rows'] if row['target'] == 'NVDA')
    assert nvda['latest_at'] == SESSION and nvda['lagging'] is False

    atr = data_view.family_detail('atr', now=NOW)          # ATR 详情取 bars 的记录
    assert atr['card']['id'] == 'atr' and [run['family'] for run in atr['runs']] == ['bars']
    assert data_view.family_detail('universe', now=NOW)['rows'] == []


def test_browse_bars_latest_revision_and_counts(db):
    _bar(db, price_date=add_trading_days(SESSION, -1), close=100)
    _bar(db, close=100, fetched_at=NOW - timedelta(hours=2))
    _bar(db, close=101, revision=2, fetched_at=NOW - timedelta(hours=1))
    db.commit()

    out = data_view.browse('bars', now=NOW, ticker='NVDA')
    assert out['family'] == 'bars' and out['key'] == 'NVDA' and out['has_data'] is True
    rows = out['rows']
    assert rows == sorted(rows, key=lambda row: row['price_date'], reverse=True)   # 新到旧
    day = next(row for row in rows if row['price_date'] == SESSION)                # 同日两修订 → 一行
    assert day['close'] == 101.0 and day['revisions'] == 2
    assert day['fetched_at'] == NOW - timedelta(hours=1) and day['note']
    assert rows[1]['revisions'] == 1


def test_browse_atr_matches_plans_atr14(db):
    for i in range(60 + plans.MIN_BARS):
        day = add_trading_days(SESSION, -(74 - i))
        close = 100 + (i % 9)
        _bar(db, price_date=day, open=close - 1, high=close + 2, low=close - 2,
             close=close, adj_close=close)
    db.commit()

    out = data_view.browse('atr', now=NOW, ticker='NVDA')
    assert len(out['rows']) == 60
    window = repository.read_bars(db, 'NVDA', SESSION, cutoff_at=NOW, limit=60 + plans.MIN_BARS)
    last = out['rows'][-1]
    assert set(last) == {'price_date', 'close', 'atr', 'atr_pct'}
    assert last['price_date'] == SESSION
    assert last['atr'] == float(plans.atr14(window))
    assert last['atr_pct'] == last['atr'] / last['close']


def test_browse_unknown_ticker_is_empty_not_error(db, monkeypatch):
    calls = []

    def recorder(name):
        def fn(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f'browse 不应调用外部数据源：{name}')
        return fn

    monkeypatch.setattr(bars_module, 'fetch_history', recorder('bars'))
    monkeypatch.setattr(news_module, 'fetch_yfinance', recorder('news'))
    monkeypatch.setattr(macro_module, 'fetch_series', recorder('fred'))
    monkeypatch.setattr(collect, 'sec_listing', recorder('sec'))
    db.commit()

    out = data_view.browse('bars', now=NOW, ticker='ZZZZ')
    assert out == {'family': 'bars', 'key': 'ZZZZ', 'has_data': False, 'rows': []}
    assert calls == []


def test_browse_validation():
    with pytest.raises(ValueError, match='ticker'):
        data_view.browse('bars', now=NOW)
    with pytest.raises(ValueError):
        data_view.browse('sec_filings', now=NOW)
    with pytest.raises(ValueError):
        data_view.browse('fred', now=NOW)
    with pytest.raises(ValueError, match='未知序列'):
        data_view.browse('fred', now=NOW, series='DGS10')
    with pytest.raises(LookupError):
        data_view.browse('nope', now=NOW)
    with pytest.raises(LookupError):
        data_view.family_detail('nope', now=NOW)


def test_reads_are_read_only(db):
    _bar(db, close=104)
    _bar(db, close=105, revision=2, fetched_at=NOW - timedelta(hours=1))
    repository.store_news(db, [({'source': 'sec_8k', 'title': 'NVDA 8-K',
                                 'url': 'https://sec.example/x', 'publisher': 'SEC EDGAR',
                                 'published_at': datetime(2026, 10, 20, 14, tzinfo=UTC)}, ['NVDA'])],
                          now=NOW)
    db.execute('INSERT INTO filings (ticker, form, filing_date, accession_number, primary_document, '
               'file_path, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)',
               ['NVDA', '10-Q', SESSION, '0001045810-26-000001', 'd.htm', '/x', NOW])
    repository.store_macro(db, 'BAMLH0A0HYM2',
                           [{'obs_date': date(2026, 10, 21), 'value': Decimal('3.2')}], now=NOW)
    _run(db)
    db.commit()

    def counts():
        out = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
               for table in BUSINESS_TABLES}
        db.commit()
        return out

    before = counts()
    data_view.overview(now=NOW)
    data_view.family_detail('bars', now=NOW)
    data_view.family_detail('universe', now=NOW)
    data_view.browse('bars', now=NOW, ticker='NVDA')
    data_view.browse('atr', now=NOW, ticker='NVDA')
    data_view.browse('news', now=NOW, ticker='NVDA')
    data_view.browse('sec_filings', now=NOW, ticker='NVDA')
    data_view.browse('fred', now=NOW, series='BAMLH0A0HYM2')
    data_view.browse('universe', now=NOW)
    assert counts() == before

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with data_view._read_tx() as conn:
            conn.execute('INSERT INTO data_fetch_runs (family, job, trigger, scope, status, '
                         'target_count, ok_count, started_at, finished_at) '
                         "VALUES ('bars', 'workbench', 'manual_family', 'family', 'failed', 1, 0, %s, %s)",
                         [NOW, NOW])
