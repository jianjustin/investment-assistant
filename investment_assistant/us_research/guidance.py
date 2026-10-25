"""Source-backed company guidance, immutable revisions and exact-basis comparisons."""
from __future__ import annotations

import math
from datetime import UTC, date, datetime
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from . import repository as repo
from .domain import StrictModel, stock_id, valid_source_link
from .service import connection


class Guidance(StrictModel):
    metric: str = Field(min_length=1, max_length=200)
    target_start: date
    target_end: date
    basis: str = Field(min_length=1, max_length=300)
    unit: str = Field(min_length=1, max_length=100)
    low: float
    high: float
    issued_at: datetime
    source_url: str = Field(min_length=1, max_length=2000)
    source_locator: str = Field(min_length=1, max_length=2000)
    note: str = Field(default='', max_length=5000)
    supersedes_id: int | None = Field(default=None, ge=1)

    _valid_link = field_validator('source_url')(valid_source_link)

    @field_validator('low', 'high', mode='before')
    @classmethod
    def numeric_amount(cls, value):
        if isinstance(value, bool):
            raise ValueError('指引金额须为有限数值')
        return value

    @model_validator(mode='after')
    def coherent(self):
        if self.target_start > self.target_end or self.low > self.high or self.issued_at.date() > self.target_end:
            raise ValueError('指引期间或上下限不连贯')
        if self.issued_at.tzinfo is None:
            raise ValueError('发布时间须含时区')
        if self.issued_at > datetime.now(UTC):
            raise ValueError('发布时间不可在未来')
        # Use explicit normalized bases; the word GAAP alone loses attribution.
        if ':' not in self.basis or self.basis.split(':', 1)[0] not in {'us-gaap', 'non-gaap', 'company'}:
            raise ValueError('须指定完整会计口径，例如us-gaap:consolidated')
        if not self.metric.strip() or not self.unit.strip() or not self.source_locator.strip():
            raise ValueError('指标、单位与原文定位不可空白')
        return self


def append(ticker, payload):
    sid = stock_id(ticker)
    model = Guidance.model_validate(payload)
    data = model.model_dump(mode='json')
    with connection() as conn:
        natural_key = 'manual:' + str(uuid4())
        if model.supersedes_id is not None:
            with conn.cursor() as cur:
                cur.execute('''SELECT natural_key,payload FROM us_research_observations
                    WHERE id=%s AND security_id=%s AND dataset='guidance' ''', (model.supersedes_id, sid))
                original = cur.fetchone()
            if not original:
                raise ValueError('被修订指引不属于当前证券的指引记录')
            prior = original[1]
            if any(data[k] != prior.get(k) for k in ('metric', 'target_start', 'target_end')):
                raise ValueError('修订须属于同一指标与目标期间')
            if prior.get('issued_at') and model.issued_at < datetime.fromisoformat(prior['issued_at'].replace('Z', '+00:00')):
                raise ValueError('修订发布时间不可早于原指引')
            natural_key = original[0]
        result = repo.store_rows(conn, sid, 'guidance', [{'natural_key': natural_key, 'payload': data,
            'disclosed_at': model.issued_at, 'source_url': model.source_url}])[0]
        conn.commit()
    return result


def list_records(ticker, *, as_of=None):
    from .service import _cutoff
    with connection() as conn:
        return repo.read_history(conn, stock_id(ticker), 'guidance', as_of=_cutoff(as_of))


def _eligible(record, cutoff):
    if cutoff is None:
        return True
    for field in ('first_seen_at', 'disclosed_at', 'issued_at', 'filed'):
        value = record.get(field)
        if value:
            try:
                parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                if field == 'filed' and len(str(value)) == 10:
                    parsed = parsed.replace(tzinfo=UTC)
                if parsed.tzinfo is None or parsed > cutoff:
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def comparisons(records, financials, *, as_of=None):
    """Never combine accounting/share bases or periods to manufacture a beat."""
    from .service import _cutoff
    cutoff = _cutoff(as_of)
    results = []
    for record in records:
        if not _eligible(record, cutoff):
            continue
        low, high = record.get('low'), record.get('high')
        result = {'guidance_id': record.get('id'), 'metric': record.get('metric'),
            'target_start': record.get('target_start'), 'target_end': record.get('target_end'),
            'basis': record.get('basis'), 'unit': record.get('unit'), 'actual': None,
            'low': low, 'high': high, 'midpoint': (low / 2 + high / 2) if _finite(low) and _finite(high) else None,
            'status': 'not_comparable', 'input_ids': [], 'reason': '缺少同指标、期间、单位及已核实口径的实际结果'}
        basis = record.get('basis', '')
        # Identical unknown share-basis strings still do not prove split comparability.
        verified = basis in {'us-gaap:consolidated', 'us-gaap:parent', 'us-gaap:common'}
        candidates = []
        if verified and _finite(low) and _finite(high) and low <= high:
            for period in financials:
                if (period.get('start'), period.get('end')) != (str(record.get('target_start')), str(record.get('target_end'))):
                    continue
                actual = period.get('metrics', {}).get(record.get('metric'), {})
                if (actual.get('unit'), actual.get('basis')) != (record.get('unit'), basis):
                    continue
                if not _finite(actual.get('value')) or not _eligible(actual, cutoff):
                    continue
                if not all(_eligible(source, cutoff) for source in actual.get('sources', [])):
                    continue
                candidates.append(actual)
        if candidates and len({r['value'] for r in candidates}) == 1:
            actual = candidates[0]
            value = actual['value']
            result.update(actual=value, status='below_range' if value < low else 'above_range' if value > high else 'in_range',
                input_ids=list(dict.fromkeys(id_ for c in candidates for id_ in c.get('input_ids', []))), reason=None)
        results.append(result)
    return results
