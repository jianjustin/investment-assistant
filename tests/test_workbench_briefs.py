import uuid
from datetime import UTC, date, datetime, timedelta

from investment_assistant.workbench import briefs, repository

T = date(2026, 10, 22)
CUTOFF = datetime(2026, 10, 22, 22, 30, tzinfo=UTC)
CID = uuid.UUID('00000000-0000-0000-0000-000000000001')

UNIT = {'ticker': 'NVDA', 'signal_date': T, 'proposed_action': 'buy', 'labels': [], 'candidate_ids': [CID]}
CANDS = [{'id': CID, 'rule_id': 'trend_reclaim', 'action': 'buy', 'inputs': {'values': {'close': 101.0}}}]
FILINGS = [
    {'id': 5, 'form': '8-K', 'items': ['2.02'], 'filing_date': date(2026, 10, 21),
     'accepted_at': CUTOFF - timedelta(days=1)},
    {'id': 6, 'form': '10-Q', 'items': [], 'filing_date': date(2026, 10, 23), 'accepted_at': CUTOFF + timedelta(hours=1)},
]
NEWS = [
    {'id': 11, 'source': 'yfinance', 'title': 'Beat', 'url': 'https://a', 'publisher': 'W',
     'published_at': CUTOFF - timedelta(hours=5), 'fetched_at': CUTOFF - timedelta(hours=4)},
    {'id': 12, 'source': 'yfinance', 'title': 'Undated', 'url': 'https://b', 'publisher': None,
     'published_at': None, 'fetched_at': CUTOFF - timedelta(hours=4)},
    {'id': 13, 'source': 'yfinance', 'title': 'Too late', 'url': 'https://c', 'publisher': None,
     'published_at': CUTOFF - timedelta(hours=1), 'fetched_at': CUTOFF + timedelta(minutes=5)},
]


def fake(result, status=None):
    calls = []

    def client(*, system_prompt, user_payload, model):
        calls.append(user_payload)
        return result, status or {'ok': result is not None, 'error': None if result else 'boom'}
    client.calls = calls
    return client


def gen(client):
    return briefs.generate(UNIT, CANDS, FILINGS, NEWS, cutoff_at=CUTOFF, client=client)


def test_inputs_only_include_material_known_by_cutoff():
    client = fake({'summary': 's', 'support': [], 'contra': [], 'conflicts': []})
    brief = gen(client)
    assert brief['input_refs'] == [f'candidate:{CID}', 'filing:5', 'news:11', 'news:12']
    payload = client.calls[0]
    assert [n['ref'] for n in payload['news']] == ['news:11', 'news:12']
    assert payload['news'][1]['published_at'] == '发布时间未知'
    assert 'filing:6' not in str(payload)


def test_valid_output_is_kept_with_citations():
    out = {'summary': '趋势修复', 'support': [{'text': '财报超预期', 'refs': ['filing:5', 'news:11']}],
           'contra': [{'text': '估值偏高', 'refs': [f'candidate:{CID}']}], 'conflicts': []}
    brief = gen(fake(out))
    assert brief['status'] == 'ok' and brief['output'] == out
    assert brief['prompt_version'] == briefs.PROMPT_VERSION


def test_unknown_reference_marks_brief_as_error_and_hides_output():
    out = {'summary': 's', 'support': [{'text': 'x', 'refs': ['news:13']}], 'contra': [], 'conflicts': []}
    brief = gen(fake(out))
    assert brief['status'] == 'error' and 'news:13' in brief['error']
    assert brief['output'] == {}


def test_item_without_citation_is_invalid():
    out = {'summary': 's', 'support': [{'text': 'uncited', 'refs': []}], 'contra': [], 'conflicts': []}
    assert gen(fake(out))['status'] == 'error'


def test_malformed_output_is_error():
    assert gen(fake({'summary': 3}))['status'] == 'error'


def test_action_fields_from_the_model_are_dropped():
    out = {'summary': 's', 'support': [], 'contra': [], 'conflicts': [], 'action': 'sell', 'final_action': 'sell'}
    brief = gen(fake(out))
    assert brief['status'] == 'ok' and 'action' not in brief['output'] and 'final_action' not in brief['output']


def test_unavailable_model_falls_back_to_rule_summary():
    brief = gen(fake(None, {'ok': False, 'error': 'DEEPSEEK_API_KEY not configured'}))
    assert brief['status'] == 'fallback' and brief['error'] == 'DEEPSEEK_API_KEY not configured'
    assert 'trend_reclaim' in brief['output']['summary']
    assert brief['output']['support'] == [] and brief['output']['contra'] == []


def test_client_exception_falls_back():
    def boom(**_):
        raise RuntimeError('network down')
    assert gen(boom)['status'] == 'fallback'


# --- persistence (disposable schema) ---

def test_store_and_read_latest_brief(workbench_db):
    first = gen(fake(None))
    second = gen(fake({'summary': 'later', 'support': [], 'contra': [], 'conflicts': []}))
    id1 = repository.store_brief(workbench_db, first)
    id2 = repository.store_brief(workbench_db, second)
    assert id1 != id2
    latest = repository.latest_brief(workbench_db, 'NVDA', T)
    assert latest['id'] == id2 and latest['output']['summary'] == 'later' and latest['status'] == 'ok'
    assert repository.latest_brief(workbench_db, 'MU', T) is None
