from investment_assistant.services import watchlist as wl


def test_invalid_market_returns_400(client):
    assert client.get('/api/watchlist?market=UK').status_code == 400


def test_watchlist_forwards_filter_enrichment(client, monkeypatch):
    def rows(market=None, *, enriched=False):
        assert (market, enriched) == ('CN', True)
        return [{'ticker': '600519.SH', 'market': 'CN'}]
    monkeypatch.setattr(wl, 'watchlist_rows', rows)
    response = client.get('/api/watchlist?market=CN&enriched=true')
    assert response.json() == {'rows': [{'ticker': '600519.SH', 'market': 'CN'}], 'count': 1}


def test_watchlist_resolve_endpoint(client, monkeypatch):
    monkeypatch.setattr(wl, 'resolve_candidates', lambda s: [{'symbol': '600519.SH'}], raising=False)
    assert client.get('/api/watchlist/resolve?symbol=600519').json() == {'candidates': [{'symbol': '600519.SH'}]}


def test_edit_conflict_returns_409(client, monkeypatch):
    from investment_assistant.db import WatchlistConflict
    def conflict(_): raise WatchlistConflict('record changed or removed')
    monkeypatch.setattr(wl, 'add_watchlist_item', conflict)
    assert client.post('/api/watchlist', json={'ticker': 'MU', 'expected_updated_at': '2026-10-16T00:00:00Z'}).status_code == 409
