"""The agent-1 graph: propose with tools, code check, counter with tools (P3 design §6.1).

Each phase allows at most MAX_TOOL_ROUNDS tool-bearing model replies; a
proposal that overruns is rejected, a counter that overruns keeps the
proposal and marks the counter. Model exceptions propagate untouched — the
batch classifies them.
"""
from __future__ import annotations

import inspect
import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Callable, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph, add_messages
from langgraph.prebuilt import ToolNode

from investment_assistant.workbench.agent.citations import Rejected, check_proposal, filter_counter
from investment_assistant.workbench.agent.tools import TOOL_DESCRIPTIONS, TOOLS, Recorder, ToolContext, call
from investment_assistant.workbench.plans import AGENT_VERSION   # re-exported here (plan §graph.py)

MAX_TOOL_ROUNDS = 8

PROPOSE_PROMPT = """你是美股波段交易研究员，为一个已触发规则的买入候选独立给出交易建议。
只能通过工具获取数据；工具只返回截止时间之前的数据，你不能指定日期。
每个工具结果带有 ref（如 call:3）。你写出的每个价位和每条理由都必须引用支撑它的 ref，只能引用本次真实返回过的 ref；引用不存在的 ref 会使整条建议作废。每个价位至少引用一次 get_price_bars 或 get_indicators 的结果。
计划在信号日后第 1 到第 3 个交易日内有效；到达 T1 后卖出一半，剩余按 3 倍 ATR 移动止损。不要考虑仓位大小。
完成后只输出一个 JSON 对象，不要输出其他文字：
{"action": "buy" 或 "pass", "summary": 一句话, "levels": {"entry_low": {"value": 数字, "refs": [...]}, "entry_high": {...}, "stop": {...}, "target1": {...}}, "thesis": [{"text": 字符串, "refs": [...]}]}
action 为 pass 时省略 levels。价位须满足 stop < entry_low <= entry_high < target1。"""

COUNTER_PROMPT = """你是反方审查员。下面是一条买入建议及其引用。请找出反对这笔交易的证据，并核对建议中的引用和数字是否与工具结果一致。
可以调用工具补充数据；每条结论必须引用 ref，只能引用真实返回过的 ref。你不能修改价位或动作。
只输出一个 JSON 对象：{"risks": [{"text": 字符串, "refs": [...]}]}"""


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    counter_messages: Annotated[list, add_messages]
    rounds: int
    counter_rounds: int
    status: str
    reason: str | None
    output: dict | None
    counter: dict | None
    input_tokens: int
    output_tokens: int


def _wrapped_tools(ctx: ToolContext, recorder: Recorder, *, now: Callable[[], datetime]) -> list:
    """The eight tools wrapped for the model: args schema from the real signature,
    the call envelope serialized to JSON, failures still recorded."""
    from pydantic import create_model
    from langchain_core.tools import StructuredTool

    tools = []
    for name, fn in TOOLS.items():
        params = [p for p in inspect.signature(fn).parameters.values()][1:]   # drop ctx
        fields = {p.name: (p.annotation, ... if p.default is inspect.Parameter.empty else p.default)
                  for p in params}
        schema = create_model(f'{name}_args', **fields)

        def runner(_name=name, **kwargs):
            return json.dumps(call(ctx, recorder, _name, kwargs, now=now()), ensure_ascii=False)

        tools.append(StructuredTool.from_function(func=runner, name=name, description=TOOL_DESCRIPTIONS[name],
                                                 args_schema=schema))
    return tools


def _build_graph(*, ctx: ToolContext, recorder: Recorder, model: BaseChatModel, tools: list,
                 last_close: Decimal, checkpointer) -> Any:
    def usage_delta(message):
        meta = getattr(message, 'usage_metadata', None) or {}
        return meta.get('input_tokens', 0), meta.get('output_tokens', 0)

    def propose_node(state: AgentState):
        message = model.bind_tools(tools).invoke(state['messages'])
        tin, tout = usage_delta(message)
        update = {'messages': [message], 'input_tokens': state['input_tokens'] + tin,
                  'output_tokens': state['output_tokens'] + tout}
        if message.tool_calls:
            rounds = state['rounds'] + 1
            update['rounds'] = rounds
            if rounds > MAX_TOOL_ROUNDS:
                update['status'] = 'rejected'
                update['reason'] = 'tool_rounds_exceeded'
        return update

    def route_propose(state: AgentState):
        if state['status'] == 'rejected':
            return 'end'
        return 'tools' if state['messages'][-1].tool_calls else 'check'

    def check_node(state: AgentState):
        try:
            output = check_proposal(state['messages'][-1].content, refs=recorder.refs('propose'),
                                    price_refs=recorder.price_refs(), last_close=last_close)
        except Rejected as exc:
            return {'status': 'rejected', 'reason': exc.reason}
        return {'status': 'ok' if output['action'] == 'buy' else 'pass', 'output': output}

    def route_check(state: AgentState):
        return 'end' if state['status'] == 'rejected' else 'counter'

    def counter_node(state: AgentState):
        first = not state['counter_messages']
        if first:
            recorder.phase = 'counter'
            base = [SystemMessage(content=COUNTER_PROMPT),
                    HumanMessage(content=state['messages'][-1].content)]
        else:
            base = state['counter_messages']
        message = model.bind_tools(tools).invoke(base)
        tin, tout = usage_delta(message)
        update = {'counter_messages': [*base, message] if first else [message],
                  'input_tokens': state['input_tokens'] + tin,
                  'output_tokens': state['output_tokens'] + tout}
        if message.tool_calls:
            rounds = state['counter_rounds'] + 1
            update['counter_rounds'] = rounds
            if rounds > MAX_TOOL_ROUNDS:
                update['counter'] = {'status': 'tool_rounds_exceeded', 'risks': [], 'dropped': 0}
        return update

    def route_counter(state: AgentState):
        if state['counter'] is not None:
            return 'end'
        return 'tools' if state['counter_messages'][-1].tool_calls else 'finish'

    def finish_node(state: AgentState):
        return {'counter': filter_counter(state['counter_messages'][-1].content, refs=recorder.refs())}

    builder = StateGraph(AgentState)
    builder.add_node('propose', propose_node)
    builder.add_node('propose_tools', ToolNode(tools))
    builder.add_node('check', check_node)
    builder.add_node('counter', counter_node)
    builder.add_node('counter_tools', ToolNode(tools, messages_key='counter_messages'))
    builder.add_node('finish', finish_node)
    builder.set_entry_point('propose')
    builder.add_conditional_edges('propose', route_propose,
                                  {'tools': 'propose_tools', 'check': 'check', 'end': END})
    builder.add_edge('propose_tools', 'propose')
    builder.add_conditional_edges('check', route_check, {'counter': 'counter', 'end': END})
    builder.add_conditional_edges('counter', route_counter,
                                  {'tools': 'counter_tools', 'finish': 'finish', 'end': END})
    builder.add_edge('counter_tools', 'counter')
    builder.add_edge('finish', END)
    return builder.compile(checkpointer=checkpointer)


def _string_levels(output: dict) -> dict:
    """Levels as strings, ready for JSONB (brief: prices become strings)."""
    if output.get('levels') is None:
        return output
    return {**output, 'levels': {key: {**item, 'value': str(item['value'])}
                                 for key, item in output['levels'].items()}}


def run_unit(*, unit: dict, ctx: ToolContext, model: BaseChatModel, checkpointer, run_id: str,
             last_close: Decimal, now: Callable[[], datetime]) -> dict:
    """One agent run of a unit. Model exceptions propagate for the batch to classify."""
    recorder = Recorder()
    tools = _wrapped_tools(ctx, recorder, now=now)
    graph = _build_graph(ctx=ctx, recorder=recorder, model=model, tools=tools,
                         last_close=last_close, checkpointer=checkpointer)
    initial = {'messages': [SystemMessage(content=PROPOSE_PROMPT),
                            HumanMessage(content=f"标的 {unit['ticker']} · 信号日 {unit['signal_date']} · "
                                                 f"分层 {unit['pool_tier']} · 数据截至信号日收盘")],
               'counter_messages': [], 'rounds': 0, 'counter_rounds': 0, 'status': 'pending',
               'reason': None, 'output': None, 'counter': None, 'input_tokens': 0, 'output_tokens': 0}
    config = {'configurable': {'thread_id': run_id}, 'recursion_limit': 4 * MAX_TOOL_ROUNDS + 10}
    final = graph.invoke(initial, config=config)
    return {'status': final['status'], 'reason': final['reason'],
            'output': _string_levels(final['output']) if final['output'] else None,
            'counter': final['counter'], 'calls': recorder.calls,
            'input_tokens': final['input_tokens'], 'output_tokens': final['output_tokens']}
