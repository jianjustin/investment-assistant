"""Agent reasoning reading view: one agent run laid out as reading steps (v2.6 spec §8).

``build`` is pure. It takes the stored rows of one run (the ``agent_runs`` row, its ``agent_tool_calls``, the
version row it produced, the review it belongs to, the later reviews of its plan, the generated plan's
state) and returns ``{run, legacy, version, review, steps, notes}``. Nothing is inferred beyond what was
stored: a rejected run keeps only what was recorded, and the checks the validator ran are listed without
guessing which passed (D13). ``reasoning`` is the read-only use case (one read-only transaction, the plan
derivation reuses ``derivation_view`` on the same connection).

``fields`` of a ``read`` call maps a name shown in the result to the concept card that explains it:
a top-level key (``atr14``), a dotted path for the macro series (``macro.BAMLH0A0HYM2``), the rule id
*value* for ``get_trigger`` (``trend_reclaim``), and ``id`` for ``get_concept`` (the card it returned).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from investment_assistant.workbench import labels
from investment_assistant.workbench.agent import REASON_TEXT
from investment_assistant.workbench.agent import conditions as condition_registry

AGENT_V1 = 'agent-1'
CUTOFF_EXEMPT_TOOLS = frozenset({'get_concept'})
CUTOFF_EXEMPT_TEXT = '概念卡随代码版本走，不受截止时间约束'
LEGACY_NOTE = 'agent-1（旧版）：没有失效条件、下次复查条件与逐条对应的反证，也不参与复查；以下按原样显示'
NO_TIMELINE_NOTE = '迁移 026 未执行，没有版本与复查记录'
NO_CALLS_NOTE = '没有记录到工具调用'
RESPONSE_EMPTY_TITLE = '回应：本版之后还没有复查'
RESPONSE_TITLE = '回应：本版之后的复查'
IMPLICATED_NOTE = '未通过的检查在这几项之中：{items}；校验器遇到第一处失败就停，不记录是哪一项'

TOOL_TEXT: dict[str, str] = {
    'get_trigger': '触发规则', 'get_price_bars': '日线', 'get_indicators': '技术指标', 'get_filings': 'SEC 文件',
    'get_news': '资讯', 'get_earnings': '财报日', 'get_market_context': '市场环境', 'get_position': '持仓',
    'get_concept': '概念卡',
}

# Tool -> the concept card of the tool's result, and result field -> concept (spec §8.3). Every tool in
# agent.tools.TOOLS has a row (a test pins it).
TOOL_CONCEPTS: dict[str, dict] = {
    'get_trigger': {'concept': 'system.decision_unit',
                    'fields': {rule_id: f'rule.{rule_id}' for rule_id in labels.RULE_TEXT}},
    'get_price_bars': {'concept': 'family.bars', 'fields': {}},
    'get_indicators': {'concept': 'indicator.atr14', 'fields': {
        'last_close': 'family.bars', 'atr14': 'indicator.atr14',
        'ma20': 'indicator.moving_average', 'ma50': 'indicator.moving_average', 'ma200': 'indicator.moving_average',
        'high_20': 'indicator.high_low', 'low_20': 'indicator.high_low',
        'high_252': 'indicator.high_low', 'low_252': 'indicator.high_low',
        'avg_volume_20': 'indicator.volume_ratio', 'volume_ratio': 'indicator.volume_ratio',
        'rs20': 'indicator.relative_strength', 'rs60': 'indicator.relative_strength'}},
    'get_filings': {'concept': 'family.sec_filings', 'fields': {}},
    'get_news': {'concept': 'family.news', 'fields': {}},
    'get_earnings': {'concept': 'plan.earnings', 'fields': {}},
    'get_market_context': {'concept': 'indicator.regime', 'fields': {
        'label': 'indicator.regime', 'breadth': 'indicator.breadth', 'sectors': 'indicator.sector_strength',
        'macro.BAMLH0A0HYM2': 'indicator.hy_oas', 'macro.T10Y2Y': 'indicator.t10y2y'}},
    'get_position': {'concept': 'review.position', 'fields': {}},
    'get_concept': {'concept': 'system.concept_card', 'fields': {}},
}

# Validator checks per run kind: (id, text, the reject reasons that can come from it). The validator stops
# at the first failure and records only the reason, so a rejected run implicates every check whose reason
# set contains the stored reason (spec §8.4).
_COMMON = (
    ('json', '输出是合法 JSON 且字段齐全', ('malformed',)),
    ('refs', '引用都存在', ('invalid_citation',)),
    ('price_refs', '每个价位至少引用一次价格类工具', ('invalid_citation',)),
    ('level_order', '价位顺序 stop < entry_low ≤ entry_high < target1', ('level_check',)),
    ('level_range', '价位在最近收盘 ±50% 内', ('level_check',)),
)
_THESIS = (
    ('thesis_count', '论点 1–3 条', ('thesis_count',)),
    ('conditions', '失效与复查条件合法', ('invalid_condition',)),
)
_ROUNDS = ('tool_rounds', '工具轮数不超过 8', ('tool_rounds_exceeded',))
CHECKS: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    'agent-2-propose': (*_COMMON, *_THESIS, _ROUNDS),
    'agent-2-revise': (*_COMMON, *_THESIS,
                       ('changes', '变化说明与宿主差异一致',
                        ('changes_mismatch', 'no_change', 'malformed', 'invalid_citation')),
                       ('plan_status', '入场期修订的新计划行必须有效', ('plan_invalid',)), _ROUNDS),
    'agent-1': (*_COMMON, _ROUNDS),
    'review': (('json', '复查输出格式', ('review_malformed',)),
               ('refs', '修订 / 作废必须有引用且都存在', ('invalid_citation',)), _ROUNDS),
    'interpret': (('json', '输出是合法 JSON 且字段齐全', ('malformed',)),
                  ('refs', '引用都存在', ('invalid_citation',)), _ROUNDS),
}

LEVEL_CONCEPTS = (('entry_low', '入场下沿', 'plan.entry_zone'), ('entry_high', '入场上沿', 'plan.entry_zone'),
                  ('stop', '止损', 'plan.stop'), ('target1', 'T1 目标', 'plan.target1'))
ACTION_TEXT = {'buy': '买入', 'pass': '不买入'}
OUTCOME_TEXT = {'maintain': '维持', 'revise': '修订', 'invalidate': '作废', 'skipped': '跳过', 'error': '出错'}


def _plain(value: Any) -> Any:
    """JSON-safe copy: dates and datetimes as ISO strings, Decimal and UUID as strings, tuples as lists."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    return value


def _reason_text(reason: Any) -> str | None:
    return None if reason in (None, '') else REASON_TEXT.get(reason, str(reason))


# ---------------------------------------------------------------- read step

def _call_fields(tool: str, data: Any) -> dict[str, str]:
    """The result names present in this call that have a concept card (see the module docstring)."""
    table = TOOL_CONCEPTS.get(tool, {}).get('fields', {})
    if tool == 'get_trigger':
        seen = [item.get('rule_id') for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        return {rid: table[rid] for rid in dict.fromkeys(seen) if rid in table}
    if tool == 'get_concept':
        return {'id': data['id']} if isinstance(data, dict) and isinstance(data.get('id'), str) else {}
    if not isinstance(data, dict):
        return {}
    macro = data.get('macro') if tool == 'get_market_context' else None
    macro = macro if isinstance(macro, dict) else {}
    return {key: concept for key, concept in table.items()
            if key in data or (key.startswith('macro.') and key.removeprefix('macro.') in macro)}


def _call_view(call: dict) -> dict:
    envelope = call.get('result') or {}
    data = envelope.get('data')
    error = envelope.get('error')
    tool = call['tool']
    exempt = tool in CUTOFF_EXEMPT_TOOLS
    return {
        'seq': call['seq'], 'ref': envelope.get('ref') or f"call:{call['seq']}", 'phase': call.get('phase'),
        'tool': tool, 'tool_text': TOOL_TEXT.get(tool, tool), 'args': call.get('args') or {},
        'result': data, 'error': error, 'result_sha256_8': str(call.get('result_sha256') or '')[:8],
        'called_at': call.get('called_at'),
        'concept': TOOL_CONCEPTS.get(tool, {}).get('concept'),
        'fields': {} if error else _call_fields(tool, data),
        'cutoff_exempt': exempt, 'cutoff_note': CUTOFF_EXEMPT_TEXT if exempt else None,
    }


def _read(calls: list[dict], phase: str, title: str, empty_note: str) -> dict:
    selected = [_call_view(c) for c in calls if c.get('phase') == phase]
    return {'kind': 'read', 'title': title, 'concept': 'agent.tool_calls', 'phase': phase, 'calls': selected,
            'note': None if selected else empty_note}


# ---------------------------------------------------------------- other steps

def _void_text(run: dict) -> str:
    return f"这次运行作废：{_reason_text(run.get('reason')) or '未记录原因'}，只保留工具调用"


def _unavailable(kind: str, title: str, concept: str, run: dict) -> dict:
    return {'kind': kind, 'title': title, 'concept': concept, 'available': False, 'text': _void_text(run)}


def _condition_view(item: dict) -> dict:
    try:
        text = condition_registry.describe(item)
    except Exception:    # noqa: BLE001 - display only: fall back to what was stored
        text = item.get('text') or str(item.get('kind'))
    return {'kind': item.get('kind'), 'params': item.get('params') or {}, 'text': text,
            'refs': list(item.get('refs') or [])}


def _evidence(review: dict | None) -> dict:
    base = {'kind': 'evidence', 'title': '触发这次运行的复查', 'concept': 'agent.signals'}
    if review is None:
        return {**base, 'review_id': None, 'text': '没有找到触发这次运行的复查记录'}
    return {**base, 'review_id': review['id'], 'session': review.get('session'), 'trigger': review.get('trigger'),
            'signals': review.get('signals') or [], 'conditions': review.get('conditions') or [],
            'user_input_ids': list(review.get('user_input_ids') or []),
            'review_agent_run_id': review.get('review_agent_run_id'),
            'revision_agent_run_id': review.get('revision_agent_run_id'),
            'outcome': review.get('outcome'), 'decided_by': review.get('decided_by'), 'reason': review.get('reason')}


def _proposal(run: dict, *, revise: bool, legacy: bool) -> dict:
    base = {'kind': 'proposal', 'title': '提议', 'concept': 'agent.legacy' if legacy else 'agent.action_levels'}
    out = run.get('output')
    if not isinstance(out, dict):
        return {**base, 'available': False, 'text': _void_text(run)}
    levels = out.get('levels') or {}
    step = {**base, 'available': True, 'action': out.get('action'),
            'action_text': ACTION_TEXT.get(out.get('action'), out.get('action')), 'summary': out.get('summary'),
            'levels': [{'key': key, 'label': label, 'value': levels[key].get('value'),
                        'refs': list(levels[key].get('refs') or []), 'concept': concept}
                       for key, label, concept in LEVEL_CONCEPTS if isinstance(levels.get(key), dict)]}
    thesis = [t for t in out.get('thesis') or [] if isinstance(t, dict)]
    if legacy:
        step['reasons'] = [{'text': t.get('text'), 'refs': list(t.get('refs') or [])} for t in thesis]
        return step
    step['thesis'] = [{'id': t.get('id') or f'T{i}', 'text': t.get('text'), 'refs': list(t.get('refs') or [])}
                      for i, t in enumerate(thesis, start=1)]
    step['invalidation'] = [_condition_view(c) for c in out.get('invalidation') or [] if isinstance(c, dict)]
    step['review_when'] = [_condition_view(c) for c in out.get('review_when') or [] if isinstance(c, dict)]
    if revise:
        step['changes'] = list(out.get('changes') or [])
        step['diff'] = list(out.get('diff') or [])
    return step


def _check(run: dict, key: str) -> dict:
    status, reason = run['status'], run.get('reason')
    items, implicated = [], []
    for item_id, text, reasons in CHECKS[key]:
        if status in ('ok', 'pass'):
            result = 'pass'
        elif status == 'rejected':
            result = 'implicated' if reason in reasons else 'not_recorded'
        else:
            result = 'not_run'
        if result == 'implicated':
            implicated.append(text)
        items.append({'id': item_id, 'text': text, 'result': result})
    return {'kind': 'check', 'title': '校验结果', 'concept': 'agent.reject_reasons', 'items': items,
            'note': IMPLICATED_NOTE.format(items='、'.join(implicated)) if implicated else None,
            'reason': reason, 'reason_text': _reason_text(reason)}


def _thesis_label(value: Any) -> Any:
    return f'T{value}' if isinstance(value, int) and not isinstance(value, bool) else value


def _counter(run: dict) -> dict:
    counter = run.get('counter')
    if not isinstance(counter, dict):
        return _unavailable('counter', '反方审查', 'agent.counter', run)
    return {'kind': 'counter', 'title': '反方审查', 'concept': 'agent.counter', 'available': True,
            'status': counter.get('status'),
            'items': [{'thesis': _thesis_label(c.get('thesis')), 'text': c.get('text'), 'refs': list(c.get('refs') or [])}
                      for c in counter.get('counter') or [] if isinstance(c, dict)],
            'risks': [{'text': r.get('text'), 'refs': list(r.get('refs') or [])}
                      for r in counter.get('risks') or [] if isinstance(r, dict)],
            'dropped': counter.get('dropped', 0),
            'uncountered': [_thesis_label(n) for n in counter.get('uncountered') or []]}


def _response(later_reviews: list[dict]) -> dict:
    items = []
    for review in later_reviews:
        new_version = review.get('new_version') or {}
        items.append({
            'review_id': review['id'], 'session': review.get('session'), 'trigger': review.get('trigger'),
            'outcome': review.get('outcome'), 'decided_by': review.get('decided_by'), 'reason': review.get('reason'),
            'signals_fired': [s.get('kind') for s in review.get('signals') or [] if isinstance(s, dict) and s.get('fired')],
            'new_plan_id': review.get('new_plan_id'),
            'new_version_no': new_version.get('version_no') if review.get('new_plan_id') else None,
            'changes': list(new_version.get('diff') or []) if review.get('new_plan_id') else []})
    return {'kind': 'response', 'title': RESPONSE_TITLE if items else RESPONSE_EMPTY_TITLE,
            'concept': 'agent.review_outcome', 'items': items}


def _outcome(plan_state: dict) -> dict:
    plan = plan_state['plan']
    return {'kind': 'outcome', 'title': '生成的计划', 'concept': 'plan.status', 'plan_id': plan['id'],
            'status': plan.get('status'), 'invalid_reasons': list(plan.get('invalid_reasons') or []),
            'warnings': list(plan.get('warnings') or []), 'valid_from': plan.get('valid_from'),
            'valid_until': plan.get('valid_until'), 'consistency': plan_state.get('consistency'),
            'consistency_error': plan_state.get('consistency_error')}


def _verdict(run: dict) -> dict:
    out = run.get('output')
    if not isinstance(out, dict):
        return _unavailable('verdict', '复查结论', 'agent.review_outcome', run)
    return {'kind': 'verdict', 'title': '复查结论', 'concept': 'agent.review_outcome', 'available': True,
            'outcome': out.get('outcome'), 'outcome_text': OUTCOME_TEXT.get(out.get('outcome'), out.get('outcome')),
            'reason': out.get('reason'), 'refs': list(out.get('refs') or [])}


def _interpretation(run: dict) -> dict:
    out = run.get('output')
    if not isinstance(out, dict):
        return _unavailable('interpretation', '解读', 'agent.brief', run)
    return {'kind': 'interpretation', 'title': '解读', 'concept': 'agent.brief', 'available': True,
            'summary': out.get('summary'), 'support': out.get('support') or [], 'contra': out.get('contra') or [],
            'conflicts': out.get('conflicts') or []}


# ---------------------------------------------------------------- assembly

def _run_view(run: dict) -> dict:
    return {'id': str(run['id']), 'ticker': run['ticker'], 'signal_date': run['signal_date'], 'mode': run['mode'],
            'agent_version': run['agent_version'], 'status': run['status'], 'reason': run.get('reason'),
            'reason_text': _reason_text(run.get('reason')), 'detail': run.get('detail'), 'model': run.get('model'),
            'cutoff_at': run.get('cutoff_at'), 'started_at': run.get('started_at'),
            'finished_at': run.get('finished_at'), 'input_tokens': run.get('input_tokens'),
            'output_tokens': run.get('output_tokens'),
            'plan_id': str(run['plan_id']) if run.get('plan_id') else None}


def _check_key(run: dict, legacy: bool) -> str:
    mode = run['mode']
    if mode == 'interpret':
        return 'interpret'
    if mode == 'review':
        return 'review'
    if mode == 'revise':
        return 'agent-2-revise'
    return 'agent-1' if legacy else 'agent-2-propose'


def build(*, run: dict, calls: list[dict], version: dict | None, trigger_review: dict | None,
          later_reviews: list[dict], plan_state: dict | None, timeline_ready: bool) -> dict:
    """The §8.1 payload of one run. Pure; see the module docstring for what each input is."""
    mode = run['mode']
    legacy = run.get('agent_version') == AGENT_V1
    counter_ran = isinstance(run.get('counter'), dict)
    steps: list[dict] = []

    if mode in ('revise', 'review') and timeline_ready:
        steps.append(_evidence(trigger_review))
    if mode == 'review':
        steps.append(_read(calls, 'review', '复查员读了什么', NO_CALLS_NOTE))
        steps.append(_verdict(run))
        steps.append(_check(run, _check_key(run, legacy)))
    elif mode == 'interpret':
        steps.append(_read(calls, 'propose', '解读读了什么', NO_CALLS_NOTE))
        steps.append(_interpretation(run))
        steps.append(_check(run, _check_key(run, legacy)))
    else:
        steps.append(_read(calls, 'propose', '提议者读了什么', NO_CALLS_NOTE))
        steps.append(_proposal(run, revise=mode == 'revise', legacy=legacy))
        steps.append(_check(run, _check_key(run, legacy)))
        steps.append(_read(calls, 'counter', '反方读了什么', '反方没有调用工具' if counter_ran else '反方没有运行'))
        steps.append(_counter(run))
        if timeline_ready and not legacy and run.get('plan_id'):
            steps.append(_response(later_reviews))
        if plan_state is not None:
            steps.append(_outcome(plan_state))

    notes = []
    if legacy:
        notes.append(LEGACY_NOTE)
    if not timeline_ready:
        notes.append(NO_TIMELINE_NOTE)
    if plan_state is not None and plan_state.get('consistency_error'):
        notes.append(f"推导一致性没能读出（consistency_error）：{plan_state['consistency_error']}")
    review = None
    if trigger_review is not None and timeline_ready:
        review = {key: trigger_review.get(key) for key in ('id', 'session', 'trigger', 'outcome', 'decided_by', 'reason')}
    return _plain({
        'run': _run_view(run), 'legacy': legacy,
        'version': ({'plan_id': version['plan_id'], 'version_no': version['version_no'], 'origin': version['origin']}
                    if version is not None and timeline_ready else None),
        'review': review, 'steps': steps, 'notes': notes})


# ---------------------------------------------------------------- use case

def _uuid(value: Any) -> str:
    try:
        return str(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f'运行 id 不是合法的 UUID：{value}') from None


def reasoning(run_id: str) -> dict:
    """Read-only use case behind ``GET /api/workbench/agent-runs/{run_id}/reasoning``.

    ValueError for a non-UUID id, LookupError for an unknown run, ``service.Unavailable`` without a database."""
    from investment_assistant.workbench import derivation, derivation_view, repository, service

    key = _uuid(run_id)
    with service.read_only_tx() as conn:
        run = repository.agent_run_by_id(conn, key)
        if run is None:
            raise LookupError(f'运行不存在：{key}')
        calls = repository.agent_tool_calls(conn, key)
        ready = repository.timeline_ready(conn)
        version = trigger_review = None
        later: list[dict] = []
        if ready:
            version = repository.version_by_run(conn, key)
            if run['mode'] in ('revise', 'review'):
                trigger_review = repository.review_by_run(conn, key)
            if run.get('plan_id'):
                later = repository.reviews_of_head(conn, run['plan_id'])
                for review in later:
                    if review.get('new_plan_id'):
                        review['new_version'] = repository.version_by_plan(conn, review['new_plan_id'])
        plan_state = None
        plan = repository.plan_by_id(conn, run['plan_id']) if run.get('plan_id') else None
        if plan is not None:
            plan_state = {'plan': plan, 'consistency': None, 'consistency_error': None}
            try:
                with conn.transaction():      # a savepoint: a failed read must not poison the rest of the view
                    plan_state['consistency'] = derivation.derive_plan(
                        plan, derivation_view.load_rows(conn, plan))['consistency']
            except Exception as exc:    # noqa: BLE001 - side panel: the reading view must still load, with the reason
                plan_state['consistency_error'] = (str(exc).splitlines() or [''])[0][:200] or type(exc).__name__
    return build(run=run, calls=calls, version=version, trigger_review=trigger_review, later_reviews=later,
                 plan_state=plan_state, timeline_ready=ready)
