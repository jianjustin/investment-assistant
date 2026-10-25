"""Research card tests; database cases use only connection-local TEMP tables."""
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest


def cards():
    from investment_assistant.research import cards
    return cards


def body(**extra):
    return {'improvement': {'hypothesis':'check growth','products':'','expected_window':'','next_event':''}, **extra}


@pytest.fixture
def card_db(monkeypatch):
    url = os.environ.get('INVESTMENT_ASSISTANT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('explicit URL required; TEMP tables only')
    import psycopg
    with psycopg.connect(url) as conn:
        conn.execute('SET search_path TO pg_temp')
        for name in ('013_ashare_research.sql', '014_us_research.sql'):
            conn.execute(Path('migrations', name).read_text().split('-- Manual verification')[0].replace('CREATE TABLE IF NOT EXISTS', 'CREATE TEMP TABLE'))
        conn.execute('CREATE TEMP TABLE filings(id BIGINT,ticker TEXT,form TEXT,filing_date DATE,accession_number TEXT,primary_document TEXT,file_path TEXT,downloaded_at TIMESTAMPTZ,created_at TIMESTAMPTZ)')
        conn.execute('CREATE TEMP TABLE watchlist_items(ticker TEXT,status TEXT)')
        conn.commit()
        @contextmanager
        def connection():
            yield conn
        monkeypatch.setattr(cards(), 'connection', connection)
        from investment_assistant.us_research import guidance
        monkeypatch.setattr(guidance, 'connection', connection)
        yield conn
        conn.rollback()


@pytest.mark.parametrize('scenario', [dict(profit_cny=10,currency='CNY'),dict(profit=10),dict(profit=float('inf'),currency='USD')])
def test_legacy_cny_field_and_missing_currency_rejected(scenario):
    with pytest.raises(ValueError):
        cards().Scenario(label='',method='analyst_assumption',period='',share_basis='',**scenario)


def test_usd_scenario_and_arbitrary_us_link_roundtrip(card_db):
    value = body(scenarios=[dict(label='base',method='analyst_assumption',profit=100,currency='USD',pe=10,shares=20,period='FY26',share_basis='common')], links=[dict(ticker='SNDK',products='NAND',transmission_condition='verify',fiscal_period='FY26',currency='USD',accounting_basis='GAAP')])
    saved = cards().save('SNDK',value,0)
    assert saved['security_id'] == 'US:stock:SNDK'
    assert cards().scenario_values(saved['body'])[0]['implied_value_per_share'] == 50
    assert cards().get('SNDK')['body']['links'][0]['ticker'] == 'SNDK'


def test_wrong_security_evidence_rejected(card_db):
    from investment_assistant.us_research import repository
    record = repository.store_rows(card_db,'US:stock:MU','financials',[{'natural_key':'r','payload':{'metric':'revenue','value':100,'unit':'USD','basis':'us-gaap:consolidated','start':'2026-01-01','end':'2026-03-31'},'source_url':'https://issuer.test/result'}])[0]
    evidence = [dict(claim='growth',stance='pending',observation_id=record['id'])]
    with pytest.raises(ValueError,match='不属于'):
        cards().save('NVDA',body(evidence=evidence),0)
    saved = cards().save('MU',body(evidence=evidence),0)
    assert saved['body']['evidence'][0]['collected_at']
    assert cards().get('MU')['new_evidence_count'] == 0


def test_conflict_evidence_requires_matching_candidate_locator(card_db):
    from investment_assistant.us_research import repository
    row = repository.store_rows(card_db,'US:stock:MU','financials',[{'natural_key':'r','payload':{'value':None,'conflicts':[{'metric':'revenue','value':100,'unit':'USD','basis':'us-gaap:consolidated','source_locator':'/a'},{'metric':'revenue','value':200,'unit':'USD','basis':'us-gaap:consolidated','source_locator':'/b'}]},'source_url':'https://issuer.test/result'}])[0]
    item = dict(claim='ambiguous',stance='pending',observation_id=row['id'],metric='revenue',value=100,unit='USD',basis='us-gaap:consolidated')
    with pytest.raises(ValueError,match='定位'):
        cards().save('MU',body(evidence=[item]),0)
    item['source_locator'] = '/b'
    with pytest.raises(ValueError,match='一致'):
        cards().save('MU',body(evidence=[item]),0)
    item['source_locator'] = '/a'
    assert cards().save('MU',body(evidence=[item]),0)['version'] == 1


def test_wrong_filing_and_stale_version_return_409(card_db,client):
    card_db.execute("INSERT INTO filings(id,ticker) VALUES(8,'NVDA')")
    value = body(links=[dict(ticker='SNDK',filing_id=8,products='x',transmission_condition='x',fiscal_period='x',currency='USD',accounting_basis='GAAP')])
    assert client.put('/api/research/observation-cards/MU',json={'body':value,'expected_version':0}).status_code == 400
    assert client.put('/api/research/observation-cards/MU',json={'body':body(),'expected_version':0}).status_code == 200
    assert client.put('/api/research/observation-cards/MU',json={'body':body(),'expected_version':0}).status_code == 409
    assert card_db.execute('SELECT count(*) FROM research_observation_card_versions').fetchone()[0] == 1


def test_references_include_dynamic_watchlist_without_parsing_files(card_db):
    card_db.execute("INSERT INTO watchlist_items VALUES('RKLB','active'),('BRK.B','active'),('688008.SH','active')")
    card_db.execute("INSERT INTO filings(id,ticker,form,filing_date,file_path) VALUES(1,'RKLB','10-Q','2026-08-01','/does/not/exist')")
    rows = cards().us_references()
    assert [r['ticker'] for r in rows] == ['RKLB']
    assert rows[0]['id'] == 1


def test_us_counts_financial_revisions_without_counting_guidance(card_db):
    from investment_assistant.us_research import repository
    cards().save('MU',body(),0)
    future=datetime(2030,1,1,tzinfo=UTC)
    for dataset in ('financials','filings','guidance','market'):
        repository.store_rows(card_db,'US:stock:MU',dataset,[{'natural_key':dataset,'payload':{}}],now=future)
    assert cards().get('MU')['new_evidence_count'] == 2


@pytest.mark.parametrize('change',[{'source_url':'https://wrong.test'},{'low':999,'high':1000},{'period':'2025-01-01/2025-03-31'}])
def test_disclosed_numeric_evidence_cannot_relabel_source_or_range(card_db,change):
    from investment_assistant.us_research import repository
    row=repository.store_rows(card_db,'US:stock:MU','financials',[{'natural_key':'r','payload':{'metric':'revenue','value':100,'unit':'USD','basis':'us-gaap:consolidated','start':'2026-01-01','end':'2026-03-31'},'source_url':'https://issuer.test/result'}])[0]
    item=dict(claim='reported',stance='pending',observation_id=row['id'],value=100,**change)
    with pytest.raises(ValueError,match='一致'):
        cards().save('MU',body(evidence=[item]),0)


@pytest.mark.parametrize('change', [
    {'value':999},
    {'value':100,'unit':'EUR'},
    {'value':100,'period':'2025-01-01/2025-03-31'},
    {'value':100,'source_url':'https://wrong.test'},
])
def test_disclosed_input_ids_cannot_bypass_primary_source_validation(card_db,change):
    from investment_assistant.us_research import repository
    row=repository.store_rows(card_db,'US:stock:MU','financials',[{'natural_key':'r','payload':{'metric':'revenue','value':100,'unit':'USD','basis':'us-gaap:consolidated','start':'2026-01-01','end':'2026-03-31'},'source_url':'https://issuer.test/result'}])[0]
    item=dict(claim='reported',stance='pending',method='disclosed',input_ids=[row['id']],**change)
    with pytest.raises(ValueError,match='observation_id'):
        cards().save('MU',body(evidence=[item]),0)
    assert card_db.execute('SELECT count(*) FROM research_observation_cards').fetchone()[0] == 0
    assert card_db.execute('SELECT count(*) FROM research_observation_card_versions').fetchone()[0] == 0


def test_disclosed_input_ids_cannot_bypass_conflict_locator(card_db):
    from investment_assistant.us_research import repository
    row=repository.store_rows(card_db,'US:stock:MU','financials',[{'natural_key':'r','payload':{'value':None,'conflicts':[{'metric':'revenue','value':100,'unit':'USD','source_locator':'/a'},{'metric':'revenue','value':200,'unit':'USD','source_locator':'/b'}]},'source_url':'https://issuer.test/result'}])[0]
    item=dict(claim='reported',stance='pending',method='disclosed',input_ids=[row['id']],value=100)
    with pytest.raises(ValueError,match='observation_id'):
        cards().save('MU',body(evidence=[item]),0)
    assert card_db.execute('SELECT count(*) FROM research_observation_card_versions').fetchone()[0] == 0


def test_manual_sources_and_explicit_calculations_keep_their_authored_status(card_db):
    from investment_assistant.us_research import repository
    row=repository.store_rows(card_db,'US:stock:MU','financials',[{'natural_key':'r','payload':{'metric':'revenue','value':100},'source_url':'https://issuer.test/result'}])[0]
    items=[
        dict(claim='manual range',stance='pending',method='disclosed',value='mid-teens',source_url='https://issuer.test/manual'),
        dict(claim='manual calculation',stance='pending',method='calculated',input_ids=[row['id']],value=999),
        dict(claim='authored assumption',stance='pending',method='analyst_assumption',input_ids=[row['id']],value=999),
    ]
    result=cards().save('MU',body(evidence=items),0)
    assert result['version']==1
    assert [(e['method'],e['value'],e['observation_id']) for e in result['body']['evidence']] == [
        ('disclosed','mid-teens',None),('calculated',999,None),('analyst_assumption',999,None)]
    assert card_db.execute('SELECT count(*) FROM research_observation_card_versions').fetchone()[0] == 1


def test_card_rejects_ashare_symbol():
    with pytest.raises(ValueError):  # 688008.SH: not a valid US ticker
        cards().stock_id('688008.SH')


def test_card_storage_lives_in_research():
    from investment_assistant.research import card_repository
    assert callable(card_repository.get_card) and callable(card_repository.save_card)
    assert issubclass(card_repository.CardConflict, ValueError)
    for path in ('investment_assistant/research/cards.py', 'investment_assistant/research/card_repository.py'):
        assert 'ashare' not in Path(path).read_text(encoding='utf-8')


def test_card_routes_live_in_research_router():
    from investment_assistant.api.routes import research
    paths = {route.path for route in research.router.routes}
    assert {'/api/research/observation-cards/{symbol}', '/api/research/us-references'} <= paths
