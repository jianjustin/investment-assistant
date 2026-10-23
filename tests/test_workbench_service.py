"""Batch + read model against a disposable schema; all market data below is synthetic."""
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import service

SESSION = date(2026, 10, 22)                         # Thursday
NOW = datetime(2026, 10, 22, 22, 30, tzinfo=UTC)     # 18:30 New York


def closes_for(ticker):
    if ticker == 'SPY':
        return [500.0] * 300
    base = [50 + i * 0.25 for i in range(296)]
    return base + [base[-1] - 6] * 3 + [base[-1] + 1]   # trend_reclaim on SESSION


def frame(ticker, end):
    closes = closes_for(ticker)
    days = [add_trading_days(SESSION, -(len(closes) - 1 - i)) for i in range(len(closes))]
    rows = [(d, c) for d, c in zip(days, closes) if d <= end]
    index = pd.DatetimeIndex([pd.Timestamp(d, tz='America/New_York') for d, _ in rows])
    return pd.DataFrame({'Open': [c for _, c in rows], 'High': [c for _, c in rows], 'Low': [c for _, c in rows],
                         'Close': [c for _, c in rows], 'Adj Close': [c for _, c in rows],
                         'Volume': [1000] * len(rows), 'Stock Splits': [0.0] * len(rows)}, index=index)


class Sources:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.calls = []

    def bars(self, ticker, start, end_exclusive):
        self.calls.append(('bars', ticker))
        if ticker in self.fail:
            raise RuntimeError('provider down')
        return frame(ticker, end_exclusive - timedelta(days=1))

    def news(self, ticker):
        return [{'content': {'title': f'{ticker} headline', 'pubDate': '2026-10-22T12:00:00Z',
                             'canonicalUrl': {'url': f'https://news.example.com/{ticker}'}}}]

    def discover(self, tickers, start, end):
        return [{'ticker': 'NVDA', 'form': '8-K', 'filing_date': '2026-10-22', 'items': ['8.01'],
                 'accepted_at': '2026-10-22T08:00:00-04:00', 'edgar_url': 'https://www.sec.gov/Archives/x.htm'}]


@pytest.fixture
def db(workbench_db, monkeypatch):
    @contextmanager
    def connection():
        yield workbench_db
    monkeypatch.setattr(service, 'connection', connection)
    return workbench_db


def deps(sources, brief_client=None):
    return service.Deps(bar_fetcher=sources.bars, news_fetcher=sources.news, filing_source=sources,
                        brief_client=brief_client or (lambda **_: (None, {'error': 'no key'})))


def test_batch_collects_evaluates_and_briefs(db):
    summary = service.run_batch(tickers=['NVDA', 'MU'], now=NOW, deps=deps(Sources()))
    assert summary['session'] == SESSION.isoformat()
    nvda = summary['tickers']['NVDA']
    assert nvda['bars']['inserted'] > 0 and nvda['error'] is None
    assert set(nvda['candidates']) >= {'trend_reclaim', 'new_filing'}
    assert summary['briefs'] == {'NVDA': 'fallback', 'MU': 'fallback'}
    assert summary['benchmark']['error'] is None
    stored = db.execute('SELECT count(*) FROM news_items WHERE source = %s', ['sec_8k']).fetchone()
    assert stored == (1,)


def test_batch_rerun_is_idempotent(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    again = service.run_batch(tickers=['NVDA'], now=NOW + timedelta(minutes=5), deps=deps(Sources()))
    assert again['tickers']['NVDA']['bars']['inserted'] == 0
    assert again['conflicts'] == []
    assert db.execute('SELECT count(*) FROM signal_candidates').fetchone()[0] == len(again['tickers']['NVDA']['candidates'])


def test_one_ticker_failure_does_not_block_others(db):
    summary = service.run_batch(tickers=['NVDA', 'MU'], now=NOW, deps=deps(Sources(fail={'MU'})))
    assert 'provider down' in summary['tickers']['MU']['error']
    assert summary['tickers']['NVDA']['error'] is None
    assert any('MU' in e for e in summary['errors'])


def test_too_many_tickers_is_an_error_not_a_truncation(db):
    with pytest.raises(ValueError):
        service.run_batch(tickers=[f'T{i}' for i in range(11)], now=NOW, deps=deps(Sources()))


def test_scheduled_run_skips_when_new_york_day_was_not_a_session(db):
    saturday = datetime(2026, 10, 24, 22, 30, tzinfo=UTC)
    sources = Sources()
    out = service.run_batch(tickers=['NVDA'], now=saturday, deps=deps(sources), skip_non_trading=True)
    assert out == {'status': 'skipped', 'reason': 'not a trading day in New York', 'ny_date': '2026-10-24'}
    assert sources.calls == []


def test_today_lists_open_units_with_brief_and_context(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    view = service.today(now=NOW)
    unit = view['units'][0]
    assert unit['ticker'] == 'NVDA' and unit['signal_date'] == SESSION
    assert unit['proposed_action'] == 'buy' and unit['entry_passed'] is False
    assert unit['brief']['status'] == 'fallback'
    assert {c['rule_id'] for c in unit['candidates']} >= {'trend_reclaim', 'new_filing'}
    assert unit['news'][0]['source'] == 'sec_8k' or unit['news'][0]['source'] == 'yfinance'


def test_decide_then_unit_leaves_today(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    unit = service.today(now=NOW)['units'][0]
    out = service.decide({'request_id': '6f1d1c1e-1111-4444-8888-000000000001', 'ticker': 'NVDA',
                          'signal_date': SESSION.isoformat(), 'candidate_ids': [str(c['id']) for c in unit['candidates']],
                          'brief_id': str(unit['brief']['id']), 'proposed_action': 'buy', 'final_action': 'buy',
                          'decision': 'accept', 'reason': '合成样例：趋势修复'}, now=NOW)
    assert out['status'] == 'created'
    assert service.today(now=NOW)['units'] == []


def test_unavailable_database_is_reported(monkeypatch):
    monkeypatch.delenv('INVESTMENT_ASSISTANT_DATABASE_URL', raising=False)
    with pytest.raises(service.Unavailable):
        service.today(now=NOW)


def test_missing_schema_is_unavailable_not_empty(workbench_db, monkeypatch):
    workbench_db.execute('DROP TABLE signal_candidates CASCADE')

    @contextmanager
    def connection():
        yield workbench_db
    monkeypatch.setattr(service, 'connection', connection)
    with pytest.raises(service.Unavailable):
        service.today(now=NOW)
