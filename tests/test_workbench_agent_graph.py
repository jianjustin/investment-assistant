"""The agent-1 graph with a scripted model: calls, citations, round limits, tokens. No network."""
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage

from investment_assistant.workbench.agent import graph
from investment_assistant.workbench.agent.tools import ToolContext

S = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 22, 30, tzinfo=UTC)
LAST_CLOSE = Decimal('100')
UNIT = {'ticker': 'AMD', 'signal_date': S, 'pool_tier': 'core'}


def _fake_bars(n=60, close=100.0):
    days = [S - timedelta(days=i) for i in range(n)]
    return [{'price_date': d, 'open': close, 'high': close * 1.02, 'low': close * 0.98, 'close': close,
             'adj_close': close, 'volume': 1000, 'split_factor': 1.0} for d in days]


def _ctx(monkeypatch, *, candidates=None, news=None):
    """Tool context over monkeypatched repository reads; the connection is never touched."""
    from investment_assistant.workbench import repository
    monkeypatch.setattr(repository, 'read_bars', lambda conn, ticker, end_date, **kw: _fake_bars())
    monkeypatch.setattr(repository, 'read_news', lambda conn, ticker, **kw: news or [])
    if candidates is not None:
        monkeypatch.setattr(repository, 'unit_candidates', lambda conn, ticker, signal_date: candidates)
    return ToolContext(ticker='AMD', session=S, cutoff_at=NOW, read=lambda fn: fn(object()))


def _tool_call(name, args, call_id):
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': call_id}])


def _buy_json(ref='call:1'):
    return json.dumps({'action': 'buy', 'summary': '回踩修复放量',
                       'levels': {'entry_low': {'value': 98.5, 'refs': [ref]},
                                  'entry_high': {'value': 101.5, 'refs': [ref]},
                                  'stop': {'value': 96.0, 'refs': [ref]},
                                  'target1': {'value': 108.0, 'refs': [ref]}},
                       'thesis': [{'text': '突破 20 日线', 'refs': [ref]}]}, ensure_ascii=False)


def run(monkeypatch, make, responses, *, candidates=None, run_id='run-1', last_close=LAST_CLOSE):
    from langgraph.checkpoint.memory import InMemorySaver
    saver = InMemorySaver()
    model = make(responses)
    result = graph.run_unit(unit=UNIT, ctx=_ctx(monkeypatch, candidates=candidates), model=model,
                            checkpointer=saver, run_id=run_id, last_close=last_close, now=lambda: NOW)
    return result, saver, model


def test_constants_match_spec():
    assert graph.AGENT_VERSION == 'agent-1'
    assert graph.MAX_TOOL_ROUNDS == 8
    assert '只能通过工具获取数据' in graph.PROPOSE_PROMPT and 'JSON' in graph.PROPOSE_PROMPT
    assert '反方审查员' in graph.COUNTER_PROMPT


def test_ok_run_records_calls_and_tokens(monkeypatch, scripted_model):
    result, _, _ = run(monkeypatch, scripted_model, [
        _tool_call('get_indicators', {'ticker': 'AMD'}, 't1'),
        AIMessage(content=_buy_json('call:1')),
        _tool_call('get_news', {'days': 7}, 't2'),
        AIMessage(content=json.dumps({'risks': [{'text': '财报临近', 'refs': ['call:2']}]})),
    ])
    assert result['status'] == 'ok' and result['reason'] is None
    assert [(c['phase'], c['tool']) for c in result['calls']] == \
        [('propose', 'get_indicators'), ('counter', 'get_news')]
    assert result['input_tokens'] == 40 and result['output_tokens'] == 20   # 4 条回复之和
    assert result['output']['levels']['entry_low']['value'] == '98.50'      # 价位转字符串写 JSONB
    assert result['counter']['status'] == 'ok'
    assert result['counter']['risks'] == [{'text': '财报临近', 'refs': ['call:2']}]


def test_pass_run(monkeypatch, scripted_model):
    result, _, _ = run(monkeypatch, scripted_model, [
        _tool_call('get_indicators', {'ticker': 'AMD'}, 't1'),
        AIMessage(content=json.dumps({'action': 'pass', 'summary': '趋势不明',
                                      'thesis': [{'text': '量能不足', 'refs': ['call:1']}]})),
        AIMessage(content=json.dumps({'risks': []})),
    ])
    assert result['status'] == 'pass' and result['output']['levels'] is None
    assert result['counter']['status'] == 'ok' and result['counter']['dropped'] == 0


def test_unknown_ref_rejected_and_counter_not_called(monkeypatch, scripted_model):
    result, _, _ = run(monkeypatch, scripted_model, [
        _tool_call('get_indicators', {'ticker': 'AMD'}, 't1'),
        AIMessage(content=_buy_json('call:99')),
    ])
    assert result['status'] == 'rejected' and result['reason'] == 'invalid_citation'
    assert result['counter'] is None and result['output'] is None


def test_tool_rounds_exceeded(monkeypatch, scripted_model):
    result, _, _ = run(monkeypatch, scripted_model,
                       [_tool_call('get_news', {'days': 7}, f't{i}') for i in range(9)])
    assert result['status'] == 'rejected' and result['reason'] == 'tool_rounds_exceeded'
    assert len(result['calls']) == 8   # 第 9 轮不再执行


def test_counter_rounds_exceeded_keeps_proposal(monkeypatch, scripted_model):
    result, _, _ = run(monkeypatch, scripted_model, [
        _tool_call('get_indicators', {'ticker': 'AMD'}, 't0'),
        AIMessage(content=_buy_json('call:1')),
        *[_tool_call('get_news', {'days': 7}, f'c{i}') for i in range(9)],
    ])
    assert result['status'] == 'ok'
    assert result['counter'] == {'status': 'tool_rounds_exceeded', 'risks': [], 'dropped': 0}


def test_counter_malformed_keeps_proposal(monkeypatch, scripted_model):
    result, _, _ = run(monkeypatch, scripted_model, [
        _tool_call('get_indicators', {'ticker': 'AMD'}, 't0'),
        AIMessage(content=_buy_json('call:1')),
        AIMessage(content='我认为没有明显风险'),
    ])
    assert result['status'] == 'ok'
    assert result['counter'] == {'status': 'malformed', 'risks': [], 'dropped': 0}


def test_counter_cites_propose_call(monkeypatch, scripted_model):
    result, _, _ = run(monkeypatch, scripted_model, [
        _tool_call('get_indicators', {'ticker': 'AMD'}, 't0'),
        AIMessage(content=_buy_json('call:1')),
        AIMessage(content=json.dumps({'risks': [{'text': '高位滞涨', 'refs': ['call:1']}]})),
    ])
    assert result['counter']['risks'] == [{'text': '高位滞涨', 'refs': ['call:1']}]
    assert result['counter']['dropped'] == 0


def test_model_messages_have_no_rule_levels(monkeypatch, scripted_model):
    candidates = [{'id': 1, 'ticker': 'AMD', 'signal_date': S, 'action': 'buy', 'rule_id': 'trend_reclaim',
                   'rule_version': '1', 'inputs': {'close': 110}, 'run_id': None, 'created_at': NOW,
                   'entry_low': '123.45', 'entry_high': '125.45', 'stop': '119.45', 'target1': '135.45'}]
    _, _, model = run(monkeypatch, scripted_model, [
        _tool_call('get_trigger', {}, 't0'),
        _tool_call('get_indicators', {'ticker': 'AMD'}, 't1'),
        AIMessage(content=_buy_json('call:2')),
        AIMessage(content=json.dumps({'risks': []})),
    ], candidates=candidates)
    for messages in model.seen:
        for message in messages:
            assert '123.45' not in str(message.content)


def test_thread_id_is_run_id(monkeypatch, scripted_model):
    _, saver, _ = run(monkeypatch, scripted_model, [
        _tool_call('get_indicators', {'ticker': 'AMD'}, 't1'),
        AIMessage(content=_buy_json('call:1')),
        AIMessage(content=json.dumps({'risks': []})),
    ], run_id='run-42')
    assert saver.get({'configurable': {'thread_id': 'run-42'}}) is not None


def test_model_exception_propagates(monkeypatch, scripted_model):
    with pytest.raises(AssertionError):   # scripted model exhausted on first call
        run(monkeypatch, scripted_model, [])


def test_wrapped_tools_expose_schemas(monkeypatch):
    from investment_assistant.workbench.agent.tools import Recorder
    ctx = _ctx(monkeypatch)
    tools = graph._wrapped_tools(ctx, Recorder(), now=lambda: NOW)
    by_name = {t.name: t for t in tools}
    assert set(by_name) == set(graph.TOOL_DESCRIPTIONS)
    props = by_name['get_price_bars'].args_schema.model_json_schema()['properties']
    assert 'ticker' in props and 'lookback' in props
    assert json.loads(by_name['get_price_bars'].invoke({'ticker': 'AMD', 'lookback': 30}))['ref'] == 'call:1'
