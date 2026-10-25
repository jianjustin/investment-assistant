"""Watchlist boundaries: no implicit defaults, identity guessing, or ingestion on listing."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from investment_assistant.services import watchlist as wl
from investment_assistant.ashare import service


def test_paused_us_symbols_do_not_return_from_config(monkeypatch):
    monkeypatch.setattr(wl, 'watchlist_rows', lambda: [{'ticker': 'MU', 'status': 'paused'}])
    assert wl.current_watchlist() == []


def test_configured_empty_list_stays_empty(monkeypatch):
    monkeypatch.setenv('INVESTMENT_ASSISTANT_DATABASE_URL', 'test-only')
    monkeypatch.setattr(wl, 'connect', lambda _: nullcontext(object()))
    monkeypatch.setattr(wl, 'list_watchlist_items', lambda _: [])
    assert wl.watchlist_rows() == []
    assert wl.current_watchlist() == []


def test_market_filter_preserves_legacy_shape_and_isolates_markets(monkeypatch):
    rows = [{'ticker': 'MU', 'status': 'active'}, {'ticker': '600519.SH', 'status': 'active'}]
    monkeypatch.setenv('INVESTMENT_ASSISTANT_DATABASE_URL', 'test-only')
    monkeypatch.setattr(wl, 'connect', lambda _: nullcontext(object()))
    monkeypatch.setattr(wl, 'list_watchlist_items', lambda _: rows)
    assert wl.watchlist_rows() == rows
    assert wl.watchlist_rows('CN') == [rows[1]]
    assert wl.watchlist_rows('US') == [rows[0]]
    assert wl.current_watchlist() == ['MU']


@pytest.mark.parametrize('ticker', ['000300.SH', '600519.SZ', '123456', 'CN:index:000300.SH', 'garbage value', None, True])
def test_invalid_or_ambiguous_identity_cannot_be_saved(monkeypatch, ticker):
    monkeypatch.setenv('INVESTMENT_ASSISTANT_DATABASE_URL', 'test-only')
    monkeypatch.setattr(wl, 'connect', lambda _: nullcontext(object()))
    with pytest.raises(ValueError):
        wl.add_watchlist_item({'ticker': ticker})


def test_resolve_numeric_returns_candidates_without_persisting(monkeypatch):
    monkeypatch.setattr(service, 'resolve', lambda symbol: {'symbol': symbol, 'name': '贵州茅台', 'market': 'CN', 'asset_type': 'stock'})
    assert wl.resolve_candidates('600519') == [{'symbol': '600519.SH', 'name': '贵州茅台', 'market': 'CN', 'asset_type': 'stock'}]


def test_enrichment_reads_only_local_profiles_states_and_events(monkeypatch):
    monkeypatch.setenv('INVESTMENT_ASSISTANT_DATABASE_URL', 'test-only')
    monkeypatch.setattr(wl, 'connect', lambda _: nullcontext(object()))
    monkeypatch.setattr(wl, 'list_watchlist_items', lambda _: [{'ticker': '600519.SH', 'status': 'active'}])
    def rows(conn, sid, dataset):
        return {'profile': [{'name': '贵州茅台', 'board': '主板'}],
                'financials': [{'period_end': '2026-06-30'}],
                'disclosure': [{'scheduled_date': '2099-10-30', 'period_end': '2026-09-30'}]}.get(dataset, [])
    monkeypatch.setattr(service.repo, 'read_rows', rows)
    monkeypatch.setattr(service.repo, 'states', lambda *args: {'profile': {'status': 'ready'}})
    monkeypatch.setattr(service, 'sync', lambda *a, **kw: pytest.fail('listing initiated ingestion'))
    result = wl.watchlist_rows('CN', enriched=True)[0]
    assert (result['market'], result['name'], result['board'], result['latest_period']) == ('CN', '贵州茅台', '主板', '2026-06-30')
    assert result['datasets']['profile']['status'] == 'ready'
    assert result['next_event']['date'] == '2099-10-30'


def test_sync_processes_more_than_ten_and_continues_after_stock_failure(monkeypatch):
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchone(self): return (True,)
    conn = SimpleNamespace(cursor=Cursor, commit=lambda: None, rollback=lambda: None)
    monkeypatch.setattr(service, 'connection', lambda: nullcontext(conn))
    symbols = [f'600{i:03}.SH' for i in range(12)]
    monkeypatch.setattr(service, 'list_watchlist_items', lambda _: [{'ticker': s, 'status': 'active'} for s in symbols] + [{'ticker': symbols[0], 'status': 'active'}, {'ticker': 'MU', 'status': 'active'}])
    monkeypatch.setattr(service.repo, 'states', lambda *a: {})
    monkeypatch.setattr(service.repo, 'store_rows', lambda *a, **kw: 0)
    monkeypatch.setattr(service.repo, 'collection_state', lambda *a, **kw: None)
    class Source:
        def profile(self, sid, *args):
            if sid.endswith('600000.SH'): raise ValueError('test stock failure')
            return []
    result = service.sync(start='2026-09-01', end='2026-10-15', datasets=['profile'], source=Source())
    assert len(result['results']) == 12
    assert len(result['errors']) == 1
    assert result['results'][-1]['security_id'] == 'CN:stock:600011.SH'


def test_us_enrichment_retains_success_identity_and_uses_duration_end_not_later_instant(monkeypatch):
    from investment_assistant.us_research import repository as repo
    monkeypatch.setenv('INVESTMENT_ASSISTANT_DATABASE_URL', 'test-only')
    monkeypatch.setattr(wl, 'connect', lambda _: nullcontext(object()))
    monkeypatch.setattr(wl, 'list_watchlist_items', lambda _: [{'ticker': 'MU', 'status': 'active'}])
    monkeypatch.setattr(repo, 'read_rows', lambda *a, **kw: [
        {'period_kind': 'duration', 'start': '2026-05-30', 'end': '2026-09-03', 'metric': 'revenue'},
        {'period_kind': 'instant', 'end': '2026-10-01', 'metric': 'shares_outstanding'}])
    monkeypatch.setattr(repo, 'states', lambda *a: {'financials': {'status': 'failed', 'last_success_details': {'identity': {'name': 'Micron Technology'}}}})
    from investment_assistant.research import card_repository
    monkeypatch.setattr(card_repository, 'get_card', lambda *a: None)
    result = wl.watchlist_rows('US', enriched=True)[0]
    assert result['name'] == 'Micron Technology'
    assert result['latest_period'] == '2026-09-03'
    assert result['datasets']['financials']['status'] == 'failed'
    assert result['next_event'] is None


@pytest.mark.parametrize('ticker', ['AAPL.US', 'TSLA.SH', 'ABC.DEF'])
def test_unsupported_us_identity_rejected_before_write_and_resolve(monkeypatch, ticker):
    monkeypatch.setenv('INVESTMENT_ASSISTANT_DATABASE_URL', 'test-only')
    monkeypatch.setattr(wl, 'connect', lambda _: pytest.fail('invalid identity opened write connection'))
    with pytest.raises(ValueError): wl.add_watchlist_item({'ticker': ticker})
    with pytest.raises(ValueError): wl.resolve_candidates(ticker)


def test_valid_share_class_and_cn_fullcodes_remain_supported():
    assert wl.validated_symbol('brk.b') == 'BRK.B'
    assert wl.validated_symbol('600519.SH') == '600519.SH'


def test_legacy_invalid_rows_remain_listed_and_deletable_but_not_active_jobs(monkeypatch):
    rows = [{'ticker': ticker, 'status': 'active'} for ticker in ['MU', 'AAPL.US', 'TSLA.SH', 'ABC.DEF', '600519.SH']]
    monkeypatch.setenv('INVESTMENT_ASSISTANT_DATABASE_URL', 'test-only')
    monkeypatch.setattr(wl, 'connect', lambda _: nullcontext(None))
    monkeypatch.setattr(wl, 'list_watchlist_items', lambda _: rows)
    listed = wl.watchlist_rows(enriched=True)
    assert len(listed) == 5
    assert [r['ticker'] for r in listed if r.get('identity_error')] == ['AAPL.US', 'TSLA.SH', 'ABC.DEF']
    assert wl.current_watchlist() == ['MU']
    deleted = []
    monkeypatch.setattr(wl, 'db_delete_watchlist_item', lambda conn, ticker: deleted.append(ticker) or {'ticker': ticker})
    assert wl.delete_watchlist_item('AAPL.US') == {'ticker': 'AAPL.US'}
    assert deleted == ['AAPL.US']
