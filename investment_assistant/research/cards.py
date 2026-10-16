"""Editable evidence cards; hypotheses and scenario arithmetic are never advice."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from investment_assistant import db
from investment_assistant.ashare import repository as repo
from investment_assistant.ashare.domain import stock_id as cn_stock_id
from investment_assistant.us_research.domain import stock_id as us_stock_id
from investment_assistant.ashare.service import connection


def stock_id(symbol):
    if isinstance(symbol, str) and symbol.strip().upper().endswith(('.SH', '.SZ', '.BJ')):
        return cn_stock_id(symbol)
    return us_stock_id(symbol)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Improvement(StrictModel):
    hypothesis: str = Field(max_length=5000)
    products: str = Field(max_length=2000)
    expected_window: str = Field(max_length=500)
    next_event: str = Field(max_length=1000)
    next_event_date: date | None = None


class Evidence(StrictModel):
    claim: str = Field(min_length=1, max_length=3000)
    stance: Literal['supports', 'opposes', 'pending']
    source_url: str = Field(default='', max_length=2000)
    observation_id: int | None = Field(default=None, ge=1)
    occurred_at: str | None = Field(default=None, max_length=100)
    disclosed_at: str | None = Field(default=None, max_length=100)
    collected_at: str | None = Field(default=None, max_length=100)
    method: Literal['disclosed', 'calculated', 'analyst_assumption'] = 'disclosed'
    metric: str | None = Field(default=None, max_length=200)
    value: float | str | None = None
    low: float | None = None
    high: float | None = None
    unit: str | None = Field(default=None, max_length=100)
    period: str | None = Field(default=None, max_length=300)
    source_locator: str | None = Field(default=None, max_length=2000)
    basis: str | None = Field(default=None, max_length=300)
    input_ids: list[int] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def valid_range(self):
        if (self.method == 'disclosed' and self.input_ids and self.observation_id is None
                and any(value is not None for value in (self.value, self.low, self.high))):
            raise ValueError('披露数值须指定主记录observation_id；仅input_ids的计算或假设须明确标记性质')
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError('证据范围下限不可大于上限')
        if any(isinstance(x, bool) or x < 1 for x in self.input_ids):
            raise ValueError('输入记录编号须为正整数')
        return self

    @field_validator('source_url')
    @classmethod
    def valid_link(cls, value):
        if value and (urlparse(value).scheme not in {'http', 'https'} or not urlparse(value).netloc):
            raise ValueError('来源链接须为http/https原文链接')
        return value


class Scenario(StrictModel):
    label: str = Field(max_length=200)
    method: Literal['analyst_assumption', 'mechanical_annualization', 'company_guidance']
    profit_cny: float | None = None
    profit: float | None = None
    currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')

    pe: float | None = Field(default=None, gt=0, le=1000)
    shares: float | None = Field(default=None, gt=0)
    period: str = Field(max_length=200)
    share_basis: str = Field(max_length=500)
    source_url: str = Field(default='', max_length=2000)
    note: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def currency_coherent(self):
        if self.profit_cny is not None:
            if self.currency not in (None, 'CNY') or (self.profit is not None and self.profit != self.profit_cny):
                raise ValueError('profit_cny只能是CNY且须与profit一致')
            self.profit = self.profit_cny
            self.currency = 'CNY'
        if self.profit is not None and self.currency is None:
            raise ValueError('利润须指定币种')
        return self

    _valid_link = field_validator('source_url')(Evidence.valid_link.__func__)


class Invalidation(StrictModel):
    condition: str = Field(max_length=2000)
    indicator: str = Field(max_length=1000)
    review_date: date | None = None
    result: Literal['pending', 'triggered', 'not_triggered', 'unknown'] = 'pending'
    checked_at: date | None = None
    note: str = Field(default='', max_length=2000)


class ResearchLink(StrictModel):
    ticker: str

    filing_id: int | None = Field(default=None, ge=1)
    products: str = Field(min_length=1, max_length=1000)
    transmission_condition: str = Field(min_length=1, max_length=2000)
    fiscal_period: str = Field(min_length=1, max_length=300)
    currency: str = Field(min_length=1, max_length=50)
    accounting_basis: str = Field(min_length=1, max_length=300)
    status: Literal['pending', 'supported', 'opposed'] = 'pending'

    @field_validator('ticker')
    @classmethod
    def valid_ticker(cls, value):
        return us_stock_id(value).rsplit(':', 1)[-1]


class CardBody(StrictModel):
    improvement: Improvement
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    scenarios: list[Scenario] = Field(default_factory=list, max_length=20)
    invalidations: list[Invalidation] = Field(default_factory=list, max_length=50)
    links: list[ResearchLink] = Field(default_factory=list, max_length=30)


def _observation(conn, sid, id_):
    table = 'cn_observations' if sid.startswith('CN:') else 'us_research_observations'
    with conn.cursor() as cur:
        cur.execute(f'SELECT payload,first_seen_at,disclosed_at,source_url FROM {table} WHERE id=%s AND security_id=%s', (id_, sid))
        row = cur.fetchone()
    if not row:
        raise ValueError('证据数据记录不属于当前证券或不存在')
    return row


def _check_values(e, payload):
    candidates = payload.get('conflicts')
    quantitative = any(e.get(k) is not None for k in ('value', 'low', 'high'))
    if candidates and quantitative:
        if not e.get('source_locator'):
            raise ValueError('冲突数据须指定原文定位，不能任取一个数值')
        candidates = [c for c in candidates if c.get('source_locator') == e['source_locator']]
        if not candidates:
            raise ValueError('原文定位与证据记录不一致')
    elif candidates:
        return  # qualitative discussion can explicitly retain the ambiguous group
    else:
        candidates = [payload]
    # Calculations retain several input IDs; their calculated value is not a raw scalar.
    if e['method'] != 'disclosed':
        return
    fields = ('metric', 'value', 'low', 'high', 'unit', 'basis', 'source_locator', 'period', 'source_url')
    normalized = [{**c, 'period': c.get('period') or (f"{c['start']}/{c['end']}" if c.get('start') and c.get('end') else c.get('end'))} for c in candidates]
    def same(key, candidate):
        value = e.get(key)
        if value is None or (key == 'source_url' and not value):
            return True
        # Text entry preserves ranges/qualitative wording; an edited numeric string
        # must still describe the actual scalar, rather than invent another value.
        if key == 'value' and isinstance(value, str) and isinstance(candidate.get(key), (int, float)):
            try:
                return float(value) == candidate[key]
            except ValueError:
                return False
        return value == candidate.get(key)
    matching = [c for c in normalized if all(same(k, c) for k in fields)]
    if quantitative and not matching:
        raise ValueError('数值、单位、口径、期间或来源定位与所关联的原始记录不一致')
    return matching[0] if matching else None


def save(symbol, body, expected_version):
    sid = stock_id(symbol)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
        raise ValueError('expected_version须为非负整数')
    model = CardBody.model_validate(body)
    payload = model.model_dump(mode='json')
    now = datetime.now(UTC).isoformat()
    with connection() as conn:
        for e in payload['evidence']:
            if not e['source_url'] and not e['observation_id'] and not e['input_ids']:
                raise ValueError('每条证据必须关联数据记录或来源链接；未知事实应标尚待验证')
            for id_ in set(e['input_ids'] + ([e['observation_id']] if e['observation_id'] else [])):
                record = _observation(conn, sid, id_)
                if id_ == e['observation_id']:
                    verified = _check_values(e, {**record[0], 'source_url': record[3] or record[0].get('source_url')})
                    e['collected_at'] = record[1].isoformat()
                    e['disclosed_at'] = record[2].isoformat() if record[2] else e['disclosed_at']
                    e['source_url'] = e['source_url'] or (verified or {}).get('source_url') or record[3] or ''
            e['collected_at'] = e['collected_at'] or now
        for s in payload['scenarios']:
            if s['method'] == 'company_guidance' and not s['source_url']:
                raise ValueError('公司指引情景必须有原文链接')
        for link in payload['links']:
            if link['filing_id']:
                f = db.get_filing(conn, link['filing_id'])
                if not f or f['ticker'] != link['ticker']:
                    raise ValueError('关联SEC原文不属于所选美股')
        result = repo.save_card(conn, sid, payload, expected_version)
        conn.commit()
    return _mapped(result)


def _mapped(card):
    if card is None:
        return None
    import copy
    card = copy.deepcopy(card)
    for scenario in card['body'].get('scenarios', []):
        if scenario.get('profit_cny') is not None:
            scenario.setdefault('profit', scenario['profit_cny'])
            scenario.setdefault('currency', 'CNY')
    return card


def get(symbol):
    with connection() as conn:
        return _mapped(repo.get_card(conn, stock_id(symbol)))


def scenario_values(body):
    result = []
    for original in body.get('scenarios', []):
        s = dict(original)
        profit = s.get('profit', s.get('profit_cny'))
        currency = s.get('currency') or ('CNY' if s.get('profit_cny') is not None else None)
        value = profit * s['pe'] / s['shares'] if profit and profit > 0 and s.get('pe') and s.get('shares') else None
        result.append({**s, 'currency': currency, 'implied_value_per_share': value,
            'formula': f'情景每股价值=假设年度利润({currency or "币种待填"})×假设PE/假设股数；非目标价或买卖建议'})
    return result


def us_references():
    """Read bounded existing filing indices; GET never parses or acquires source files."""
    results = []
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT ticker FROM watchlist_items ORDER BY ticker')
            tickers = [r[0] for r in cur.fetchall()]
        for ticker in tickers:
            try:
                us_stock_id(ticker)
            except ValueError:
                continue
            for f in db.list_filings(conn, ticker=ticker, limit=6):
                results.append({'id': f['id'], 'ticker': ticker, 'form': f['form'],
                    'filing_date': str(f['filing_date']), 'url': f'/api/filings/records/{f["id"]}/download',
                    'facts': {}, 'limitation': '请核对既有SEC原文；本接口不触发解析或采集',
                    'basis_note': '按各原文实际财年、期间、币种和GAAP/non-GAAP显示；产品传导另行核实。'})
    return results
