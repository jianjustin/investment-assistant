"""Data family catalog: order, purposes, classify, sanitize, lagging, coverage (pure)."""
from datetime import date, datetime, UTC

from investment_assistant.workbench import families
from investment_assistant.tasks import catalog

S = date(2026, 10, 22)

def test_six_families_in_order_and_described():
    assert [f.id for f in families.FAMILIES] == ['bars', 'sec_filings', 'news', 'atr', 'fred', 'universe']
    for f in families.FAMILIES:
        assert f.title and f.purpose and f.kind in ('fetched', 'derived', 'manual')
        assert catalog.describe(f.job) is not None
    assert families.get('atr').fetch_via == 'bars' and families.get('atr').kind == 'derived'
    assert families.get('universe').kind == 'manual'
    assert {f.id for f in families.FAMILIES if f.per_ticker} == {'bars', 'news', 'sec_filings'}

def test_classify():
    assert families.classify(2, 0, 'FRED_API_KEY 未配置') == 'skipped'
    assert families.classify(3, 3) == 'success'
    assert families.classify(3, 0) == 'failed'
    assert families.classify(3, 1) == 'partial'

def test_sanitize_reason_redacts_and_truncates(monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'sekret123')
    out = families.sanitize_reason('url?api_key=sekret123 ' + 'x' * 400)
    assert 'sekret123' not in out and '***' in out and len(out) == 300

def test_lagging_edges():
    assert families.lagging('bars', S, session=S) is False
    assert families.lagging('bars', date(2026, 10, 21), session=S) is True
    assert families.lagging('atr', S, session=S, bar_count=15) is False
    assert families.lagging('atr', S, session=S, bar_count=14) is True
    assert families.lagging('fred', date(2026, 10, 15), session=S) is False   # 第 7 天
    assert families.lagging('fred', date(2026, 10, 14), session=S) is True    # 第 8 天
    assert families.lagging('sec_filings', date(2026, 6, 24), session=S) is False  # 120 天
    assert families.lagging('news', datetime(2026, 10, 15, 12, tzinfo=UTC), session=S) is False
    assert families.lagging('bars', None, session=S) is True

def test_coverage_counts_missing_as_lagging():
    cov = families.coverage('bars', ['A', 'B', 'C'], {'A': S, 'B': date(2026, 10, 20)}, session=S)
    assert cov == {'targets': 3, 'covered': 1, 'lagging': ['B', 'C']}
