"""My knowledge (v2.7 spec §5, ``my-knowledge-1``): field validation, ``know:`` references and the
cutoff-time visibility of append-only versions. Pure: no database, no clock, no agent or service imports.

An item is a row plus numbered versions; archiving is a status record, never a new version. ``visible``
is the one function every reader (``get_knowledge``, the pages, the cutoff check) goes through, so what
a plan generated at ``cutoff`` could see is decided in exactly one place.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from investment_assistant.data.identity import stock_id
from investment_assistant.workbench.knowledge import ID_BODY

MY_KNOWLEDGE_VERSION = 'my-knowledge-1'
KNOWLEDGE_RESULT_MAX = 10          # items one get_knowledge call returns (spec §6.1)
INDEX_MAX = 50                     # entries of the get_knowledge index
LINKS_MAX = 10                     # concepts + tickers attached to one version
LIMITS = {'title': 60, 'body': 4000, 'scope': 500, 'counter_examples': 1000}
FIELDS = ('title', 'body', 'scope', 'counter_examples', 'concepts', 'tickers')

REF_RE = re.compile(r'^know:([1-9][0-9]*)(?:@([1-9][0-9]*))?$')
_CONCEPT_RE = re.compile(rf'^(?:concept:)?({ID_BODY})(?:@[1-9][0-9]*)?$')


def parse_ref(text: str) -> tuple[int, int | None]:
    """``know:<id>[@<version>]`` -> ``(id, version | None)``; anything else raises ``ValueError``.
    The version-less form is accepted in page addresses only; agent citations must carry one."""
    match = REF_RE.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError(f'不是知识引用：{text!r}')
    return int(match.group(1)), int(match.group(2)) if match.group(2) else None


def ref(knowledge_id: int, version: int) -> str:
    return f'know:{knowledge_id}@{version}'


def _text(payload: dict[str, Any], field: str, *, required: bool) -> str:
    value = payload.get(field)
    if value is None and not required:
        value = ''
    if not isinstance(value, str):
        raise ValueError(f'{field} 必须是文字')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{field} 不能为空')
    if len(value) > LIMITS[field]:
        raise ValueError(f'{field} 最多 {LIMITS[field]} 字')
    return value


def _list(payload: dict[str, Any], field: str) -> list[Any]:
    value = payload.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f'{field} 必须是列表')
    return value


def validate(payload: dict[str, Any], *, concept_versions: dict[str, int] | None,
             require_counter: bool) -> dict[str, Any]:
    """Normalised fields of one knowledge version.

    ``concept_versions`` maps concept id -> current card version; each ``concepts`` entry (``plan.stop``,
    ``concept:plan.stop`` or a pinned ``concept:plan.stop@2``) comes back as ``concept:<id>@<current>``.
    ``None`` means the card catalog could not be loaded: asking to attach a concept then raises
    ``LookupError``; tickers alone never need it. ``require_counter`` is set for agent-drafted lessons."""
    out: dict[str, Any] = {
        'title': _text(payload, 'title', required=True),
        'body': _text(payload, 'body', required=True),
        'scope': _text(payload, 'scope', required=True),
        'counter_examples': _text(payload, 'counter_examples', required=require_counter),
    }
    concept_ids: list[str] = []
    for item in _list(payload, 'concepts'):
        match = _CONCEPT_RE.fullmatch(item.strip()) if isinstance(item, str) else None
        if match is None:
            raise ValueError(f'不是概念卡 id：{item!r}')
        if match.group(1) not in concept_ids:
            concept_ids.append(match.group(1))
    tickers: list[str] = []
    for item in _list(payload, 'tickers'):
        try:
            stock_id(item)
        except (ValueError, AttributeError):
            raise ValueError(f'不是有效的美股代码：{item!r}') from None
        ticker = item.strip().upper()
        if ticker not in tickers:
            tickers.append(ticker)
    if len(concept_ids) + len(tickers) > LINKS_MAX:
        raise ValueError(f'挂靠最多 {LINKS_MAX} 处')
    if not concept_ids and not tickers:
        raise ValueError('至少挂靠一张概念卡或一个标的')
    if concept_ids and concept_versions is None:
        raise LookupError('概念卡不可用')
    for concept_id in concept_ids:
        if concept_id not in (concept_versions or {}):
            raise ValueError(f'概念卡不存在：{concept_id}')
    out['concepts'] = [f'concept:{concept_id}@{concept_versions[concept_id]}' for concept_id in concept_ids]
    out['tickers'] = tickers
    return out


def _order(row: dict[str, Any]) -> tuple:
    return row['created_at'], row.get('id') or 0


def status_at(statuses: list[dict[str, Any]], cutoff: datetime | None) -> str:
    """One item's state at ``cutoff`` (None = now): the last record written at or before it, else ``active``."""
    seen = [row for row in statuses if cutoff is None or row['created_at'] <= cutoff]
    return max(seen, key=_order)['status'] if seen else 'active'


def visible(versions: list[dict[str, Any]], statuses: list[dict[str, Any]], *,
            cutoff: datetime | None) -> list[dict[str, Any]]:
    """The version of each item a reader at ``cutoff`` (None = now) may see (spec §5.3, D15): the highest
    version written at or before it, unless the item was archived at that moment. Items with no version
    yet at the cutoff are absent; later versions and later archivals are invisible. Ordered by item id."""
    top: dict[Any, dict[str, Any]] = {}
    for row in versions:
        if cutoff is not None and row['created_at'] > cutoff:
            continue
        current = top.get(row['knowledge_id'])
        if current is None or row['version'] > current['version']:
            top[row['knowledge_id']] = row
    by_item: dict[Any, list[dict[str, Any]]] = {}
    for row in statuses:
        by_item.setdefault(row['knowledge_id'], []).append(row)
    return [top[key] for key in sorted(top) if status_at(by_item.get(key, []), cutoff) != 'archived']


def changed_fields(prev: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Which of the version fields differ between two versions, in field order."""
    return [field for field in FIELDS if prev.get(field) != new.get(field)]
