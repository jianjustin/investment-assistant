"""Checks for the v2.7 growth-loop agent outputs (spec §4.4, §6.2, §8.4). Pure functions.

``check_draft`` validates a retro card draft (``agent-retro-1``), ``check_lesson`` one lesson (also the
knowledge draft of a discussion answer), ``check_answer`` a discussion answer (``agent-discuss-1``).
Like ``plan_check`` they stop at the first failing gate and salvage nothing, except the one case the spec
spells out: a bad knowledge draft inside an otherwise valid answer is dropped, the answer stays.

``knowledge_citations`` reads the ``know:`` references out of a checked plan / counter / review output for
the ``knowledge_citations`` table. The allowed reference sets are assembled by the caller (``graph``): this
module only compares against what it is given, plus the fixed ``fact:`` keys of the frozen card facts.
"""
from __future__ import annotations

import json
from typing import Any

from investment_assistant.data.identity import stock_id
from investment_assistant.workbench.agent.citations import Rejected, _loads
from investment_assistant.workbench.retro import FACT_KEYS, LESSONS_MAX

HEADLINE_MAX = 60
NARRATIVE_RANGE = (1, 4)
SENTENCE_MAX = 300
LESSON_LIMITS = {'title': 60, 'body': 1500, 'scope': 300, 'counter_examples': 500}
ANSWER_MAX = 3000
CONTEXT_REF = 'fact:context'
FIELDS = ('thesis', 'invalidation', 'changes', 'counter', 'risks', 'review')

# ``knowledge`` and ``knowledge_items`` are imported inside the functions: knowledge -> stages -> ... -> service
# -> agent.graph -> this module, so a module-level import here would be a cycle.


def _text(value: Any, limit: int, *, required: bool = True) -> str:
    """A string within ``limit`` characters (after stripping); anything else is a shape problem."""
    if not isinstance(value, str):
        raise Rejected('retro_malformed')
    value = value.strip()
    if (required and not value) or len(value) > limit:
        raise Rejected('retro_malformed')
    return value


def _ref_list(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(ref, str) for ref in value):
        raise Rejected('retro_malformed')
    return list(value)


def _loads_object(text: str) -> dict:
    try:
        payload = _loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        raise Rejected('retro_malformed') from None
    if not isinstance(payload, dict):
        raise Rejected('retro_malformed')
    return payload


def _check_refs(item_refs: list[str], allowed: set[str]) -> None:
    if not item_refs or any(ref not in allowed for ref in item_refs):
        raise Rejected('invalid_citation')


# ---------------------------------------------------------------- lessons

def _lesson_shape(item: Any) -> dict:
    """Types and upper length bounds of one lesson; blank scope / counter-examples are the next gate."""
    if not isinstance(item, dict):
        raise Rejected('retro_malformed')
    out: dict[str, Any] = {'title': _text(item.get('title'), LESSON_LIMITS['title']),
                           'body': _text(item.get('body'), LESSON_LIMITS['body'])}
    for key in ('scope', 'counter_examples'):
        value = item.get(key)
        if value is None:
            out[key] = ''
        elif isinstance(value, str) and len(value.strip()) <= LESSON_LIMITS[key]:
            out[key] = value.strip()
        else:
            raise Rejected('retro_malformed')
    for key in ('concepts', 'tickers'):
        value = item.get(key)
        if value is not None and not isinstance(value, list):
            raise Rejected('retro_malformed')
        out[key] = list(value or [])
    out['refs'] = _ref_list(item.get('refs'))
    return out


def _lesson_links(shaped: dict, *, concept_ids: set[str], default_ticker: str) -> dict:
    """The ``lesson_invalid`` gate: scope and counter-examples present, attachments valid (≤ 10 together)."""
    from investment_assistant.workbench import knowledge, knowledge_items

    if not shaped['scope'] or not shaped['counter_examples']:
        raise Rejected('lesson_invalid')
    concepts: list[str] = []
    for entry in shaped['concepts']:
        match = knowledge.REF_RE.fullmatch(entry.strip()) if isinstance(entry, str) else None
        if match is None or match.group(1) not in concept_ids:
            raise Rejected('lesson_invalid')
        if match.group(1) not in concepts:
            concepts.append(match.group(1))
    tickers: list[str] = []
    for entry in shaped['tickers']:
        try:
            stock_id(entry)
        except (ValueError, AttributeError):
            raise Rejected('lesson_invalid') from None
        upper = entry.strip().upper()
        if upper not in tickers:
            tickers.append(upper)
    if len(concepts) + len(tickers) > knowledge_items.LINKS_MAX:
        raise Rejected('lesson_invalid')
    if not concepts and not tickers:
        tickers = [default_ticker]             # nothing attached: the card's ticker (not an error)
    return {**shaped, 'concepts': concepts, 'tickers': tickers}


def check_lesson(item: dict, *, refs: set[str], concept_ids: set[str], default_ticker: str) -> dict:
    """One lesson / knowledge draft: shape (``retro_malformed``), citations (``invalid_citation``), then
    scope, counter-examples and attachments (``lesson_invalid``)."""
    shaped = _lesson_shape(item)
    _check_refs(shaped['refs'], refs)
    return _lesson_links(shaped, concept_ids=concept_ids, default_ticker=default_ticker)


# ---------------------------------------------------------------- retro card draft

def _sentence(item: Any) -> dict:
    if not isinstance(item, dict):
        raise Rejected('retro_malformed')
    return {'text': _text(item.get('text'), SENTENCE_MAX), 'refs': _ref_list(item.get('refs'))}


def check_draft(text: str, *, refs: set[str], concept_ids: set[str], default_ticker: str) -> dict:
    """§4.4 in full. ``refs`` = this run's ``call:N``, the ``concept:`` / ``know:`` refs its tools returned;
    the ten ``fact:<key>`` refs of the frozen facts are always allowed."""
    payload = _loads_object(text)
    allowed = set(refs) | {f'fact:{key}' for key in FACT_KEYS}
    headline = _text(payload.get('headline'), HEADLINE_MAX)
    narrative_raw = payload.get('expected_vs_actual')
    if (not isinstance(narrative_raw, list)
            or not NARRATIVE_RANGE[0] <= len(narrative_raw) <= NARRATIVE_RANGE[1]):
        raise Rejected('retro_malformed')
    narrative = [_sentence(item) for item in narrative_raw]
    review = _sentence(payload.get('decision_review'))
    lessons_raw = payload.get('lessons')
    if lessons_raw is None:
        lessons_raw = []
    if not isinstance(lessons_raw, list) or len(lessons_raw) > LESSONS_MAX:
        raise Rejected('retro_malformed')
    shaped = [_lesson_shape(item) for item in lessons_raw]
    for sentence in (*narrative, review):
        _check_refs(sentence['refs'], allowed)
    for lesson in shaped:
        _check_refs(lesson['refs'], allowed)
    lessons = [_lesson_links(lesson, concept_ids=concept_ids, default_ticker=default_ticker) for lesson in shaped]
    return {'headline': headline, 'expected_vs_actual': narrative, 'decision_review': review, 'lessons': lessons}


# ---------------------------------------------------------------- discussion answer

def check_answer(text: str, *, refs: set[str], concept_ids: set[str], default_ticker: str,
                 targets: set[str]) -> tuple[dict, str | None]:
    """§8.4: ``(checked, draft_dropped)``. ``refs`` = this run's ``call:N``, the ``concept:`` / ``know:`` refs
    its tools returned and the ``user:<id>`` the context showed; ``fact:context`` is always allowed.
    ``targets`` = the ``know:`` refs a knowledge draft may rewrite (the attachment's and the returned ones).
    A bad draft is dropped (the second item names why) and the answer stays."""
    try:
        payload = _loads_object(text)
    except Rejected:
        raise Rejected('answer_malformed') from None
    answer = payload.get('answer')
    if not isinstance(answer, str) or not 1 <= len(answer.strip()) <= ANSWER_MAX:
        raise Rejected('answer_malformed')
    answer_refs = payload.get('refs')
    if not isinstance(answer_refs, list) or any(not isinstance(ref, str) for ref in answer_refs):
        raise Rejected('answer_malformed')
    allowed = set(refs) | {CONTEXT_REF}
    _check_refs(answer_refs, allowed)
    draft, dropped = None, None
    raw = payload.get('knowledge_draft')
    if raw is not None:
        try:
            draft = _answer_draft(raw, allowed=allowed, concept_ids=concept_ids,
                                  default_ticker=default_ticker, targets=targets)
        except Rejected as exc:
            dropped = 'lesson_invalid' if exc.reason == 'retro_malformed' else exc.reason
    return {'answer': answer.strip(), 'refs': list(answer_refs), 'knowledge_draft': draft}, dropped


def _answer_draft(raw: Any, *, allowed: set[str], concept_ids: set[str], default_ticker: str,
                  targets: set[str]) -> dict:
    from investment_assistant.workbench import knowledge_items

    lesson = check_lesson(raw, refs=allowed, concept_ids=concept_ids, default_ticker=default_ticker)
    target = raw.get('target')
    if target is not None:
        try:
            if not isinstance(target, str) or knowledge_items.parse_ref(target)[1] is None or target not in targets:
                raise Rejected('lesson_invalid')
        except ValueError:
            raise Rejected('lesson_invalid') from None
    return {**lesson, 'target': target}


# ---------------------------------------------------------------- knowledge citations

def concept_refs(calls: list[dict], phase: str | None = None) -> set[str]:
    """The ``concept:<id>@<version>`` refs the successful ``get_concept`` calls of this run returned."""
    found: set[str] = set()
    for c in calls:
        if c['tool'] != 'get_concept' or 'error' in c['result'] or (phase is not None and c['phase'] != phase):
            continue
        data = c['result'].get('data')
        if isinstance(data, dict) and isinstance(data.get('concept_ref'), str):
            found.add(data['concept_ref'])
    return found


def _first_calls(calls: list[dict]) -> dict[str, int]:
    """``know:`` ref -> seq of the first successful ``get_knowledge`` call that returned it."""
    first: dict[str, int] = {}
    for c in calls:
        if c['tool'] != 'get_knowledge' or 'error' in c['result']:
            continue
        data = c['result'].get('data')
        for entry in (data.get('entries') if isinstance(data, dict) else None) or []:
            if isinstance(entry, dict) and isinstance(entry.get('ref'), str):
                first.setdefault(entry['ref'], c['seq'])
    return first


def _field_refs(output: dict | None, counter: dict | None, mode: str) -> list[tuple[str, list]]:
    """(field, refs) pairs of the parts of a checked output that may carry a ``know:`` ref (spec §6.2)."""
    pairs: list[tuple[str, list]] = []
    if mode == 'review':
        pairs.append(('review', (output or {}).get('refs') or []))
        return pairs
    for field, key in (('thesis', 'thesis'), ('invalidation', 'invalidation'), ('changes', 'changes')):
        for item in (output or {}).get(key) or []:
            if isinstance(item, dict):
                pairs.append((field, item.get('refs') or []))
    for field, key in (('counter', 'counter'), ('risks', 'risks')):
        for item in (counter or {}).get(key) or []:
            if isinstance(item, dict):
                pairs.append((field, item.get('refs') or []))
    return pairs


def knowledge_citations(*, output: dict | None, counter: dict | None, mode: str, calls: list[dict]) -> list[dict]:
    """``[{knowledge_id, version, field, call_seq}]`` for a run that passed its checks (spec §6.2).

    ``output`` / ``counter`` are the checked ones, so a counter entry the filter dropped is not in them and
    is not cited. ``mode`` is ``'review'`` (the verdict's refs, field ``review``) or a plan run
    (``'propose'`` / ``'revise'``: thesis, invalidation, changes, and from the counter: counter, risks).
    ``call_seq`` is the first ``get_knowledge`` call of the run that returned the ref; a ref no call returned
    cannot have passed the checks and is skipped. One row per (knowledge id, version, field)."""
    from investment_assistant.workbench import knowledge_items

    first = _first_calls(calls)
    rows: list[dict] = []
    seen: set[tuple[int, int, str]] = set()
    for field, item_refs in _field_refs(output, counter, mode):
        for ref in item_refs:
            if not isinstance(ref, str) or ref not in first:
                continue
            try:
                knowledge_id, version = knowledge_items.parse_ref(ref)
            except ValueError:
                continue
            if version is None or (knowledge_id, version, field) in seen:
                continue
            seen.add((knowledge_id, version, field))
            rows.append({'knowledge_id': knowledge_id, 'version': version, 'field': field,
                         'call_seq': first[ref]})
    return rows
