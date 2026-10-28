"""agent-2 plan, counter and review checks (v2.5 spec §4.1, §4.3): pure functions, no database."""
import copy
import json
from datetime import date
from decimal import Decimal

import pytest

from investment_assistant.workbench.agent.citations import Rejected
from investment_assistant.workbench.agent.plan_check import check_plan, check_review, diff, filter_counter_v2

REFS = {'call:1', 'call:2', 'call:3'}
PRICE_REFS = {'call:1'}
USER_REFS = {'user:7'}
LAST_CLOSE = Decimal('100')
AS_OF = date(2026, 10, 21)


def lv(value):
    return {'value': value, 'refs': ['call:1']}


def payload(**over) -> dict:
    base = {
        'action': 'buy',
        'summary': '回踩 50 日线企稳',
        'levels': {'entry_low': lv(98), 'entry_high': lv(100), 'stop': lv(95), 'target1': lv(110)},
        'thesis': [{'text': '放量突破', 'refs': ['call:2']}, {'text': '用户提到的订单', 'refs': ['user:7']}],
        'invalidation': [{'kind': 'close_below', 'params': {'price': 94}, 'text': '跌破 94', 'refs': ['call:1']}],
        'review_when': [],
    }
    base.update(over)
    return base


def run(p: dict, previous=None) -> dict:
    return check_plan(json.dumps(p), refs=REFS, price_refs=PRICE_REFS, user_refs=USER_REFS,
                      last_close=LAST_CLOSE, as_of_session=AS_OF, previous=previous)


# ---------------------------------------------------------------- check_plan, first version

def test_first_version_ok():
    out = run(payload())
    assert out['action'] == 'buy'
    assert out['summary'] == '回踩 50 日线企稳'
    assert [t['id'] for t in out['thesis']] == ['T1', 'T2']
    assert out['thesis'][1] == {'id': 'T2', 'text': '用户提到的订单', 'refs': ['user:7']}
    assert out['levels']['stop']['value'] == Decimal('95.00')
    assert out['invalidation'] == [{'kind': 'close_below', 'params': {'price': Decimal('94.00')},
                                    'text': '收盘跌破 94.00', 'refs': ['call:1']}]
    assert out['review_when'] == [{'kind': 'next_session', 'params': {}, 'text': '下一交易日'}]
    assert out['changes'] == []
    assert out['diff'] is None


def test_first_version_missing_review_when_defaults_to_next_session():
    p = payload()
    del p['review_when']
    assert run(p)['review_when'] == [{'kind': 'next_session', 'params': {}, 'text': '下一交易日'}]


def test_review_when_kept_and_refs_dropped():
    out = run(payload(review_when=[{'kind': 'date_reached', 'params': {'date': '2026-11-02'}, 'refs': ['call:9']}]))
    assert out['review_when'] == [{'kind': 'date_reached', 'params': {'date': date(2026, 11, 2)},
                                   'text': '到 2026-11-02 再看'}]


def test_pass_skips_condition_checks():
    p = payload(action='pass', invalidation=[], review_when='junk')
    del p['levels']
    out = run(p)
    assert out['action'] == 'pass' and out['levels'] is None
    assert out['invalidation'] == [] and out['review_when'] == [] and out['changes'] == []
    assert out['diff'] is None
    with pytest.raises(Rejected) as exc:          # thesis count still applies to a pass
        run({**p, 'thesis': []})
    assert exc.value.reason == 'thesis_count'


def _thesis(n):
    return [{'text': f't{i}', 'refs': ['call:2']} for i in range(n)]


def _inv(n):
    return [{'kind': 'close_below', 'params': {'price': 90 + i}, 'refs': ['call:1']} for i in range(n)]


@pytest.mark.parametrize('over, reason', [
    ({'thesis': []}, 'thesis_count'),
    ({'thesis': _thesis(4)}, 'thesis_count'),
    ({'invalidation': []}, 'invalid_condition'),
    ({'invalidation': _inv(6)}, 'invalid_condition'),
    ({'invalidation': None}, 'invalid_condition'),
    ({'invalidation': [{'kind': 'date_reached', 'params': {'date': '2026-11-02'}, 'refs': ['call:1']}]},
     'invalid_condition'),                                                      # review-only kind
    ({'invalidation': [{'kind': 'close_below', 'params': {'price': 10}, 'refs': ['call:1']}]},
     'invalid_condition'),                                                      # outside ±50 %
    ({'invalidation': [{'kind': 'close_below', 'params': {'price': 94}}]}, 'invalid_condition'),
    ({'invalidation': [{'kind': 'close_below', 'params': {'price': 94}, 'refs': []}]}, 'invalid_condition'),
    ({'invalidation': [{'kind': 'close_below', 'params': {'price': 94}, 'refs': ['call:9']}]},
     'invalid_condition'),
    ({'review_when': [{'kind': 'next_session'}] * 4}, 'invalid_condition'),
    ({'review_when': [{'kind': 'no_entry_by', 'params': {'date': '2026-11-02'}}]}, 'invalid_condition'),
    ({'review_when': 'next_session'}, 'invalid_condition'),
    ({'thesis': [{'text': 'x', 'refs': ['user:99']}]}, 'invalid_citation'),
    ({'changes': [{'field': 'stop', 'text': 'x', 'refs': ['call:1']}]}, 'malformed'),
    ({'changes': 'none'}, 'malformed'),
    ({'levels': {'entry_low': lv(98), 'entry_high': lv(100), 'stop': lv(99), 'target1': lv(110)}}, 'level_check'),
    ({'action': 'sell'}, 'malformed'),
])
def test_rejections(over, reason):
    with pytest.raises(Rejected) as exc:
        run(payload(**over))
    assert exc.value.reason == reason


def test_not_json_is_malformed():
    with pytest.raises(Rejected) as exc:
        check_plan('not json', refs=REFS, price_refs=PRICE_REFS, user_refs=USER_REFS,
                   last_close=LAST_CLOSE, as_of_session=AS_OF, previous=None)
    assert exc.value.reason == 'malformed'


def test_first_version_empty_changes_ok():
    assert run(payload(changes=[]))['changes'] == []
    assert run(payload(changes=None))['changes'] == []


# ---------------------------------------------------------------- check_plan, revision

def _stop_96(**over):
    levels = {'entry_low': lv(98), 'entry_high': lv(100), 'stop': lv(96), 'target1': lv(110)}
    return payload(levels=levels, **over)


STOP_CHANGE = [{'field': 'stop', 'text': '上移止损', 'refs': ['call:1']}]


def test_revision_changes_must_match_diff():
    previous = run(payload())
    out = run(_stop_96(changes=STOP_CHANGE), previous=previous)
    assert out['diff'] == [{'field': 'stop', 'before': '95.00', 'after': '96.00'}]
    assert out['changes'] == STOP_CHANGE

    with pytest.raises(Rejected) as exc:
        run(_stop_96(changes=STOP_CHANGE + [{'field': 'thesis', 'text': '论点', 'refs': ['call:2']}]),
            previous=previous)
    assert exc.value.reason == 'changes_mismatch'

    with pytest.raises(Rejected) as exc:
        run(payload(changes=STOP_CHANGE), previous=previous)
    assert exc.value.reason == 'no_change'

    with pytest.raises(Rejected) as exc:
        run(_stop_96(), previous=previous)
    assert exc.value.reason == 'changes_mismatch'

    with pytest.raises(Rejected) as exc:
        run(_stop_96(changes=[]), previous=previous)
    assert exc.value.reason == 'changes_mismatch'


def test_revision_no_change_checked_before_missing_changes():
    previous = run(payload())
    with pytest.raises(Rejected) as exc:
        run(payload(), previous=previous)
    assert exc.value.reason == 'no_change'


@pytest.mark.parametrize('changes, reason', [
    ([{'field': 'stop', 'text': '上移止损', 'refs': ['call:9']}], 'invalid_citation'),
    ([{'field': 'stop', 'text': '上移止损', 'refs': ['user:99']}], 'invalid_citation'),
    ([{'field': 'stop', 'text': '上移止损', 'refs': []}], 'malformed'),
    ([{'field': 'stop', 'refs': ['call:1']}], 'malformed'),
    (['stop'], 'malformed'),
    ([{'field': 'levels', 'text': '上移止损', 'refs': ['call:1']}], 'changes_mismatch'),
])
def test_revision_change_items_checked(changes, reason):
    previous = run(payload())
    with pytest.raises(Rejected) as exc:
        run(_stop_96(changes=changes), previous=previous)
    assert exc.value.reason == reason


def test_revision_change_may_cite_user_input():
    previous = run(payload())
    out = run(_stop_96(changes=[{'field': 'stop', 'text': '用户提醒', 'refs': ['user:7']}]), previous=previous)
    assert [d['field'] for d in out['diff']] == ['stop']


def test_revision_against_previous_read_back_from_json():
    previous = json.loads(json.dumps(run(payload()), default=str))
    out = run(_stop_96(changes=STOP_CHANGE), previous=previous)
    assert out['diff'] == [{'field': 'stop', 'before': '95.00', 'after': '96.00'}]
    with pytest.raises(Rejected) as exc:
        run(payload(changes=STOP_CHANGE), previous=previous)
    assert exc.value.reason == 'no_change'


def test_revision_pass_is_returned_unchecked():
    previous = run(payload())
    p = payload(action='pass')
    del p['levels']
    out = run(p, previous=previous)
    assert out['action'] == 'pass' and out['changes'] == [] and out['diff'] is None


def test_revision_multi_field_diff():
    previous = run(payload())
    new = payload(
        levels={'entry_low': lv(97), 'entry_high': lv(100), 'stop': lv(95), 'target1': lv(112)},
        thesis=[{'text': '放量突破', 'refs': ['call:2']}],
        invalidation=[{'kind': 'close_below', 'params': {'price': 93}, 'refs': ['call:1']}],
        review_when=[{'kind': 'earnings_within', 'params': {'sessions': 3}}],
        changes=[{'field': f, 'text': 'x', 'refs': ['call:3']}
                 for f in ('entry', 'target1', 'thesis', 'invalidation', 'review_when')])
    out = run(new, previous=previous)
    by_field = {d['field']: d for d in out['diff']}
    assert list(by_field) == ['entry', 'target1', 'thesis', 'invalidation', 'review_when']
    assert by_field['entry'] == {'field': 'entry', 'before': '98.00–100.00', 'after': '97.00–100.00'}
    assert by_field['target1'] == {'field': 'target1', 'before': '110.00', 'after': '112.00'}
    assert by_field['thesis'] == {'field': 'thesis', 'before': ['放量突破', '用户提到的订单'], 'after': ['放量突破']}
    assert by_field['invalidation'] == {'field': 'invalidation',
                                        'before': [{'kind': 'close_below', 'params': {'price': '94.00'}}],
                                        'after': [{'kind': 'close_below', 'params': {'price': '93.00'}}]}
    assert by_field['review_when']['before'] == [{'kind': 'next_session', 'params': {}}]
    assert by_field['review_when']['after'] == [{'kind': 'earnings_within', 'params': {'sessions': '3'}}]
    json.dumps(out['diff'])                                   # JSON-serializable as is


# ---------------------------------------------------------------- diff

def test_condition_text_only_change_is_not_a_diff():
    previous = run(payload())
    new = copy.deepcopy(previous)
    new['invalidation'][0]['text'] = '换个说法：收盘低于 94'
    new['invalidation'][0]['refs'] = ['call:3']
    new['review_when'][0]['text'] = '明天'
    assert diff(previous, new) == []
    # same params in another representation (JSON read-back, a number instead of a string) still equal
    as_json = json.loads(json.dumps(previous, default=str))
    as_json['invalidation'][0]['params']['price'] = 94
    assert diff(as_json, new) == []
    # a changed param is a change
    new['invalidation'][0]['params']['price'] = Decimal('94.50')
    assert [d['field'] for d in diff(previous, new)] == ['invalidation']


def test_diff_action_and_thesis_text():
    previous = run(payload())
    new = copy.deepcopy(previous)
    new['thesis'][0]['text'] = '放量突破！'
    new['thesis'][0]['refs'] = ['call:3']                      # refs alone are not compared
    assert [d['field'] for d in diff(previous, new)] == ['thesis']
    new['action'] = 'pass'
    new['levels'] = None
    fields = {d['field']: d for d in diff(previous, new)}
    assert fields['action'] == {'field': 'action', 'before': 'buy', 'after': 'pass'}
    assert fields['stop'] == {'field': 'stop', 'before': '95.00', 'after': None}


# ---------------------------------------------------------------- counter

def test_counter_v2():
    text = json.dumps({
        'action': 'pass',
        'levels': {'stop': lv(50)},
        'counter': [{'thesis': 1, 'text': '量能不可持续', 'refs': ['call:1']},
                    {'thesis': 3, 'text': '不存在的论点', 'refs': ['call:1']}],
        'risks': [{'text': '大盘走弱', 'refs': ['call:2']}],
    })
    out = filter_counter_v2(text, refs=REFS, thesis_count=2)
    assert out == {'status': 'ok', 'counter': [{'thesis': 1, 'text': '量能不可持续', 'refs': ['call:1']}],
                   'risks': [{'text': '大盘走弱', 'refs': ['call:2']}], 'dropped': 1, 'uncountered': [2]}


def test_counter_v2_drops_bad_items_and_counts():
    text = json.dumps({
        'counter': [{'thesis': 'T2', 'text': 'ok', 'refs': ['user:7']},
                    {'thesis': 1, 'text': 'bad ref', 'refs': ['call:9']},
                    {'thesis': 1, 'text': 'no refs', 'refs': []},
                    {'thesis': True, 'text': 'bool', 'refs': ['call:1']},
                    {'thesis': 0, 'text': 'zero', 'refs': ['call:1']},
                    'junk'],
        'risks': [{'text': 'bad', 'refs': ['call:9']}],
    })
    out = filter_counter_v2(text, refs=REFS | USER_REFS, thesis_count=3)
    assert out['counter'] == [{'thesis': 2, 'text': 'ok', 'refs': ['user:7']}]
    assert out['risks'] == [] and out['dropped'] == 6 and out['uncountered'] == [1, 3]


@pytest.mark.parametrize('text', ['not json', '[]', json.dumps({'risks': []}),
                                  json.dumps({'counter': [], 'risks': 'x'})])
def test_counter_v2_malformed(text):
    out = filter_counter_v2(text, refs=REFS, thesis_count=2)
    assert out == {'status': 'malformed', 'counter': [], 'risks': [], 'dropped': 0, 'uncountered': [1, 2]}


def test_counter_v2_risks_optional():
    out = filter_counter_v2(json.dumps({'counter': []}), refs=REFS, thesis_count=1)
    assert out == {'status': 'ok', 'counter': [], 'risks': [], 'dropped': 0, 'uncountered': [1]}


# ---------------------------------------------------------------- review verdict

def test_check_review():
    assert check_review(json.dumps({'outcome': 'maintain', 'reason': '没有新变化', 'refs': []}), refs=REFS) == \
        {'outcome': 'maintain', 'reason': '没有新变化', 'refs': []}
    assert check_review(json.dumps({'outcome': 'maintain', 'reason': '没有新变化'}), refs=REFS)['refs'] == []
    assert check_review('```json\n{"outcome": "revise", "reason": "止损应上移", "refs": ["call:1"]}\n```',
                        refs=REFS) == {'outcome': 'revise', 'reason': '止损应上移', 'refs': ['call:1']}
    out = check_review(json.dumps({'outcome': 'invalidate', 'reason': '论点被证伪', 'refs': ['call:2'],
                                   'levels': {}}), refs=REFS)
    assert out == {'outcome': 'invalidate', 'reason': '论点被证伪', 'refs': ['call:2']}


@pytest.mark.parametrize('text, reason', [
    (json.dumps({'outcome': 'revise', 'reason': '止损应上移', 'refs': []}), 'invalid_citation'),
    (json.dumps({'outcome': 'revise', 'reason': '止损应上移'}), 'invalid_citation'),
    (json.dumps({'outcome': 'invalidate', 'reason': '证伪', 'refs': ['call:9']}), 'invalid_citation'),
    (json.dumps({'outcome': 'maintain', 'reason': '照旧', 'refs': ['call:9']}), 'invalid_citation'),
    (json.dumps({'outcome': 'hold', 'reason': '照旧', 'refs': []}), 'review_malformed'),
    (json.dumps({'outcome': 'maintain', 'refs': []}), 'review_malformed'),
    (json.dumps({'outcome': 'maintain', 'reason': '  ', 'refs': []}), 'review_malformed'),
    (json.dumps({'outcome': 'maintain', 'reason': '照旧', 'refs': 'call:1'}), 'review_malformed'),
    (json.dumps(['maintain']), 'review_malformed'),
    ('not json', 'review_malformed'),
])
def test_check_review_rejections(text, reason):
    with pytest.raises(Rejected) as exc:
        check_review(text, refs=REFS)
    assert exc.value.reason == reason
