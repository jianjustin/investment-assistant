"""Cited LLM briefs for decision units (design §8). The model explains; it never sets the action."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from investment_assistant.hermes.deepseek_client import DEFAULT_MODEL, request_json_completion_verbose
from investment_assistant.workbench import codex_client

PROMPT_VERSION = 'workbench-brief-1'
NY = ZoneInfo('America/New_York')
SECTIONS = ('support', 'contra', 'conflicts')

SYSTEM_PROMPT = """你是美股波段研究助手，只负责解读，不给出买卖动作。
输入包含规则候选、SEC 财报元数据和资讯标题链接，每项都有 ref 编号。
输出 JSON：{"summary": 字符串, "support": [...], "contra": [...], "conflicts": [...]}，
三个数组的每一项为 {"text": 字符串, "refs": [ref 编号]}，refs 至少一个且只能使用输入中出现的 ref。
support 写支持候选方向的证据，contra 写反证，conflicts 写互相矛盾或信息不足之处。
资讯只有标题与链接，未核验原文；发布时间未知的资讯要在文字中说明。不要输出 action 或任何交易指令。"""

# (system_prompt, user_payload, model) -> (result or None, status with 'error')
BriefClient = Callable[..., tuple[dict[str, Any] | None, dict[str, Any]]]


def _deepseek_client(*, system_prompt: str, user_payload: dict[str, Any], model: str):
    return request_json_completion_verbose(system_prompt=system_prompt, user_payload=user_payload, model=model)


def _disabled_client(**_):
    return None, {'ok': False, 'error': 'LLM 已关闭（WORKBENCH_LLM_PROVIDER=off）'}


def provider_client() -> tuple[BriefClient, str]:
    """WORKBENCH_LLM_PROVIDER: codex (default, ChatGPT plan via Codex CLI) | deepseek | off."""
    provider = os.environ.get('WORKBENCH_LLM_PROVIDER', 'codex').strip().lower()
    if provider == 'deepseek':
        return _deepseek_client, DEFAULT_MODEL
    if provider == 'off':
        return _disabled_client, 'none'
    return codex_client.request, codex_client.MODEL_LABEL


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else '发布时间未知'


def _known_filings(filings: list[dict[str, Any]], cutoff_at: datetime) -> list[dict[str, Any]]:
    cutoff_day = cutoff_at.astimezone(NY).date()
    return [f for f in filings if (f['accepted_at'] <= cutoff_at if f.get('accepted_at') else f['filing_date'] <= cutoff_day)]


def _known_news(news: list[dict[str, Any]], cutoff_at: datetime) -> list[dict[str, Any]]:
    return [n for n in news if n['fetched_at'] <= cutoff_at and (n['published_at'] is None or n['published_at'] <= cutoff_at)]


def build_payload(unit, candidates, filings, news, cutoff_at) -> tuple[dict[str, Any], list[str]]:
    payload = {
        'ticker': unit['ticker'], 'signal_date': unit['signal_date'].isoformat(),
        'proposed_action': unit['proposed_action'], 'labels': unit.get('labels', []),
        'candidates': [{'ref': f"candidate:{c['id']}", 'rule_id': c['rule_id'], 'action': c['action'],
                        'inputs': c['inputs']} for c in candidates],
        'filings': [{'ref': f"filing:{f['id']}", 'form': f['form'], 'items': f.get('items'),
                     'filing_date': f['filing_date'].isoformat(), 'accepted_at': _iso(f.get('accepted_at'))}
                    for f in _known_filings(filings, cutoff_at)],
        'news': [{'ref': f"news:{n['id']}", 'source': n['source'], 'title': n['title'], 'url': n['url'],
                  'publisher': n.get('publisher'), 'published_at': _iso(n['published_at'])}
                 for n in _known_news(news, cutoff_at)],
    }
    refs = [item['ref'] for key in ('candidates', 'filings', 'news') for item in payload[key]]
    return payload, refs


def _validate(raw: Any, allowed: set[str]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict) or not isinstance(raw.get('summary'), str):
        return None, 'malformed output: summary missing'
    output: dict[str, Any] = {'summary': raw['summary']}
    unknown: set[str] = set()
    for section in SECTIONS:
        items = raw.get(section, [])
        if not isinstance(items, list):
            return None, f'malformed output: {section} is not a list'
        for item in items:
            if (not isinstance(item, dict) or not isinstance(item.get('text'), str)
                    or not isinstance(item.get('refs'), list) or not item['refs']):
                return None, f'malformed output: uncited {section} item'
            unknown.update(str(r) for r in item['refs'] if r not in allowed)
        output[section] = [{'text': i['text'], 'refs': list(i['refs'])} for i in items]
    if unknown:
        return None, 'unknown refs: ' + ', '.join(sorted(unknown))
    return output, None


def _fallback_summary(unit, candidates) -> dict[str, Any]:
    rules = '、'.join(f"{c['rule_id']}({c['action']})" for c in candidates)
    labels = f"；标签：{'、'.join(unit['labels'])}" if unit.get('labels') else ''
    return {'summary': f"规则候选：{rules}；建议动作 {unit['proposed_action']}{labels}。LLM 未参与。",
            'support': [], 'contra': [], 'conflicts': []}


def generate(unit, candidates, filings, news, *, cutoff_at: datetime, client: BriefClient | None = None,
             model: str | None = None) -> dict[str, Any]:
    if client is None:
        client, label = provider_client()
        model = model or label
    payload, refs = build_payload(unit, candidates, filings, news, cutoff_at)
    brief = {'ticker': unit['ticker'], 'signal_date': unit['signal_date'], 'model': model,
             'prompt_version': PROMPT_VERSION, 'cutoff_at': cutoff_at, 'input_refs': refs}
    try:
        call_model = None if model == codex_client.MODEL_LABEL else model
        raw, status = client(system_prompt=SYSTEM_PROMPT, user_payload=payload, model=call_model)
    except Exception as exc:  # optional enhancement: any failure keeps the rule-only brief
        raw, status = None, {'error': f'client failed: {type(exc).__name__}'}
    if raw is None:
        return {**brief, 'output': _fallback_summary(unit, candidates), 'status': 'fallback',
                'error': status.get('error') or 'model unavailable'}
    output, error = _validate(raw, set(refs))
    if error:
        return {**brief, 'output': {}, 'status': 'error', 'error': error}
    return {**brief, 'output': output, 'status': 'ok', 'error': None}
