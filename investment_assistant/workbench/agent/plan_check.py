"""agent-2 plan, counter and review checks (v2.5 spec §4.1, §4.3). Pure functions.

check_plan runs citations.check_proposal unchanged (refs = this run's calls plus
the user inputs given to it), then the agent-2 gates in order: thesis count,
invalidation conditions, review conditions, and `changes` against the host
diff. The first failing gate names the reason; nothing is salvaged.

Two deliberate readings of the spec:
- Thesis count runs before check_proposal, because check_proposal folds an
  empty thesis list into 'malformed' and §4.4 names 'thesis_count' for it.
- A 'pass' is not an executable plan: only its thesis (count, refs) is checked;
  invalidation / review_when / changes are ignored and come back empty with
  diff None. In a revision the caller turns a pass into an invalidation (D11).

diff is the one host diff (the timeline module reuses it). It accepts both the
check_plan output (Decimal / date) and the same dict read back from JSON
(strings), and its output is JSON-serializable: prices as '95.00', entry as
'94.00–96.00', thesis as the text sequence, conditions as [{kind, params}] with
every param a canonical string. Condition text and refs are never compared.
"""
from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from investment_assistant.workbench.agent import conditions
from investment_assistant.workbench.agent.citations import Rejected, _loads, check_proposal

THESIS_RANGE = (1, 3)
INVALIDATION_RANGE = (1, 5)
REVIEW_WHEN_MAX = 3
CHANGE_FIELDS = ('action', 'entry', 'stop', 'target1', 'thesis', 'invalidation', 'review_when')
REVIEW_OUTCOMES = ('maintain', 'revise', 'invalidate')
_CENT = Decimal('0.01')
_THESIS_REF = re.compile(r'^T?([1-9])$')


def _payload(text: str) -> Any:
    try:
        return _loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _cited(item_refs: Any, allowed: set[str]) -> bool:
    """A non-empty list whose every entry is a known ref."""
    return (isinstance(item_refs, list) and bool(item_refs)
            and all(isinstance(ref, str) and ref in allowed for ref in item_refs))


# ---------------------------------------------------------------- plan

def _invalidation(raw: Any, *, allowed: set[str], last_close: Decimal, as_of_session: date) -> list[dict]:
    if not isinstance(raw, list) or not INVALIDATION_RANGE[0] <= len(raw) <= INVALIDATION_RANGE[1]:
        raise Rejected('invalid_condition')
    out = []
    for item in raw:
        cond = conditions.validate(item, use='invalidation', last_close=last_close, as_of_session=as_of_session)
        if not _cited(cond.get('refs'), allowed):
            raise Rejected('invalid_condition')
        out.append(cond)
    return out


def _review_when(raw: Any, *, last_close: Decimal, as_of_session: date) -> list[dict]:
    if raw is None or raw == []:
        raw = [{'kind': 'next_session', 'params': {}}]
    if not isinstance(raw, list) or len(raw) > REVIEW_WHEN_MAX:
        raise Rejected('invalid_condition')
    out = []
    for item in raw:
        cond = conditions.validate(item, use='review', last_close=last_close, as_of_session=as_of_session)
        cond.pop('refs', None)          # review conditions carry no citations; unchecked refs are not kept
        out.append(cond)
    return out


def _changes(raw: Any, *, allowed: set[str]) -> list[dict]:
    """Shape and citations of a revision's `changes`; the field-set match is the caller's."""
    if raw is None or raw == []:
        raise Rejected('changes_mismatch')
    if not isinstance(raw, list):
        raise Rejected('malformed')
    out = []
    for item in raw:
        if (not isinstance(item, dict) or not isinstance(item.get('field'), str)
                or not isinstance(item.get('text'), str)
                or not isinstance(item.get('refs'), list) or not item['refs']):
            raise Rejected('malformed')
        out.append({'field': item['field'], 'text': item['text'], 'refs': item['refs']})
    if any(not _cited(item['refs'], allowed) for item in out):
        raise Rejected('invalid_citation')
    return out


def check_plan(text: str, *, refs: set[str], price_refs: set[str], user_refs: set[str],
               last_close: Decimal, as_of_session: date, previous: dict | None) -> dict:
    """§4.1 in full; previous is the prior version's check_plan output (None = first version)."""
    allowed = set(refs) | set(user_refs)
    payload = _payload(text)
    if isinstance(payload, dict) and isinstance(payload.get('thesis'), list) \
            and not THESIS_RANGE[0] <= len(payload['thesis']) <= THESIS_RANGE[1]:
        raise Rejected('thesis_count')
    base = check_proposal(text, refs=allowed, price_refs=price_refs, last_close=last_close)
    if not isinstance(payload, dict):   # unreachable: check_proposal accepted it, so it parsed to an object
        raise Rejected('malformed')

    out: dict[str, Any] = {
        'action': base['action'],
        'summary': base['summary'],
        'levels': base['levels'],
        'thesis': [{'id': f'T{i}', 'text': item['text'], 'refs': item['refs']}
                   for i, item in enumerate(base['thesis'], start=1)],
        'invalidation': [],
        'review_when': [],
        'changes': [],
        'diff': None,
    }
    if out['action'] == 'pass':
        return out

    out['invalidation'] = _invalidation(payload.get('invalidation'), allowed=allowed,
                                        last_close=last_close, as_of_session=as_of_session)
    out['review_when'] = _review_when(payload.get('review_when'), last_close=last_close,
                                      as_of_session=as_of_session)

    raw_changes = payload.get('changes')
    if previous is None:
        if raw_changes is not None and raw_changes != []:
            raise Rejected('malformed')
        return out

    host_diff = diff(previous, out)
    if not host_diff:
        raise Rejected('no_change')
    changes = _changes(raw_changes, allowed=allowed)
    if {item['field'] for item in changes} != {item['field'] for item in host_diff}:
        raise Rejected('changes_mismatch')
    out['changes'] = changes
    out['diff'] = host_diff
    return out


# ---------------------------------------------------------------- diff

def _money(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return f'{number.quantize(_CENT, rounding="ROUND_HALF_UP"):.2f}'


def _level(plan: dict, key: str) -> str | None:
    levels = plan.get('levels')
    if not isinstance(levels, dict) or not isinstance(levels.get(key), dict):
        return None
    return _money(levels[key].get('value'))


def _entry(plan: dict) -> str | None:
    low, high = _level(plan, 'entry_low'), _level(plan, 'entry_high')
    return None if low is None and high is None else f'{low}–{high}'


def _canon_param(name: str, value: Any) -> str:
    if name == 'price':
        return _money(value) or str(value)
    if name == 'date':
        if isinstance(value, date):
            return value.isoformat()
        return str(value)[:10] if isinstance(value, str) else str(value)
    if name == 'value' and not isinstance(value, bool) and isinstance(value, (int, float, Decimal, str)):
        try:
            return repr(float(value))
        except ValueError:
            return str(value)
    return str(value)


def _conditions(plan: dict, key: str) -> list[dict]:
    items = plan.get(key) or []
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        params = item.get('params') or {}
        out.append({'kind': item.get('kind'),
                    'params': {name: _canon_param(name, params[name]) for name in sorted(params)}})
    return out


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _thesis_texts(plan: dict) -> list[str]:
    return [item.get('text') for item in plan.get('thesis') or [] if isinstance(item, dict)]


def diff(previous: dict, new: dict) -> list[dict]:
    """[{field, before, after}] for each changed field, in CHANGE_FIELDS order (§4.1)."""
    extract = {
        'action': lambda plan: plan.get('action'),
        'entry': _entry,
        'stop': lambda plan: _level(plan, 'stop'),
        'target1': lambda plan: _level(plan, 'target1'),
        'thesis': _thesis_texts,
        'invalidation': lambda plan: _conditions(plan, 'invalidation'),
        'review_when': lambda plan: _conditions(plan, 'review_when'),
    }
    out = []
    for field in CHANGE_FIELDS:
        before, after = extract[field](previous), extract[field](new)
        if _canon(before) != _canon(after):
            out.append({'field': field, 'before': before, 'after': after})
    return out


# ---------------------------------------------------------------- counter

def _thesis_no(value: Any, thesis_count: int) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and (match := _THESIS_REF.match(value.strip())):
        value = int(match.group(1))
    if isinstance(value, int) and 1 <= value <= thesis_count:
        return value
    return None


def filter_counter_v2(text: str, *, refs: set[str], thesis_count: int) -> dict:
    """Per-thesis counters and risks; bad entries drop out and count, prices and actions are ignored."""
    every = list(range(1, thesis_count + 1))
    payload = _payload(text)
    if (not isinstance(payload, dict) or not isinstance(payload.get('counter'), list)
            or not isinstance(payload.get('risks', []), list)):
        return {'status': 'malformed', 'counter': [], 'risks': [], 'dropped': 0, 'uncountered': every}
    counter: list[dict] = []
    risks: list[dict] = []
    dropped = 0
    for item in payload['counter']:
        number = _thesis_no(item.get('thesis'), thesis_count) if isinstance(item, dict) else None
        if number is not None and isinstance(item.get('text'), str) and _cited(item.get('refs'), refs):
            counter.append({'thesis': number, 'text': item['text'], 'refs': item['refs']})
        else:
            dropped += 1
    for item in payload.get('risks', []):
        if isinstance(item, dict) and isinstance(item.get('text'), str) and _cited(item.get('refs'), refs):
            risks.append({'text': item['text'], 'refs': item['refs']})
        else:
            dropped += 1
    countered = {item['thesis'] for item in counter}
    return {'status': 'ok', 'counter': counter, 'risks': risks, 'dropped': dropped,
            'uncountered': [n for n in every if n not in countered]}


# ---------------------------------------------------------------- review verdict

def check_review(text: str, *, refs: set[str]) -> dict:
    """agent-review-1's single verdict; revise / invalidate must cite, maintain may not."""
    payload = _payload(text)
    if not isinstance(payload, dict) or payload.get('outcome') not in REVIEW_OUTCOMES:
        raise Rejected('review_malformed')
    reason = payload.get('reason')
    if not isinstance(reason, str) or not reason.strip():
        raise Rejected('review_malformed')
    cited = payload.get('refs', [])
    if not isinstance(cited, list):
        raise Rejected('review_malformed')
    if cited and not _cited(cited, refs):
        raise Rejected('invalid_citation')
    if payload['outcome'] != 'maintain' and not cited:
        raise Rejected('invalid_citation')
    return {'outcome': payload['outcome'], 'reason': reason, 'refs': cited}
