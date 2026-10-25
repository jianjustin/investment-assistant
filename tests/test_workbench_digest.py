"""Digest content and Discord templates for the daily workbench push (design §7.2)."""
import json
from datetime import date
from decimal import Decimal as D

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.notify import templates
from investment_assistant.workbench import digest

SESSION = date(2026, 10, 22)
URL = 'http://localhost:8787'


def plan_row(signal_date=SESSION, ticker='NVDA', **over):
    row = {'ticker': ticker, 'signal_date': signal_date, 'kind': 'rule', 'plan_version': 'plan-1', 'status': 'ok',
           'entry_low': D('98.5'), 'entry_high': D('101.5'), 'stop': D('94'), 'target1': D('112'),
           'valid_from': date(2026, 10, 23), 'valid_until': date(2026, 10, 27),
           'sizing': {'status': 'sized', 'shares': 166, 'risk_amount': D('1000'),
                      'snapshot_as_of': date(2026, 10, 20)},
           'invalid_reasons': [], 'warnings': []}
    row.update(over)
    return row


def unit(ticker='NVDA', plan=None, brief_summary='解读：量价配合。', signal_date=SESSION, agent=None):
    return {'ticker': ticker, 'signal_date': signal_date, 'proposed_action': 'buy', 'rule_ids': ['trend_reclaim'],
            'labels': [],
            'plan': plan,
            'agent': agent,
            'brief': ({'status': 'fallback', 'output': {'summary': brief_summary}} if brief_summary else None)}


def holding(ticker='NVDA', **over):
    row = {'ticker': ticker, 'quantity': 10, 'avg_cost': 100, 'plan_id': 'p1', 'stop': 94, 'mode': 'initial',
           't1_reached': False, 'target1': 112, 'last_close': 100.0, 'to_stop_pct': -0.06,
           'to_target_pct': 0.12, 'next_earnings': None}
    row.update(over)
    return row


def build(units=(), holdings=(), summary=None, last_push_failed=False, extended_plans=0, market=None,
          agent_summary=None):
    return digest.build(session=SESSION, units=list(units), holdings=list(holdings),
                        summary=summary or {'errors': [], 'earnings': {}},
                        last_push_failed=last_push_failed, public_url=URL,
                        extended_plans=extended_plans, market=market, agent_summary=agent_summary)


def agent_ok(ticker='NVDA', summary='回踩修复放量', first_risk='财报临近'):
    plan = plan_row(ticker=ticker, kind='agent', plan_version='agent-1')
    return {'id': 'r1', 'status': 'ok', 'model': 'glm-5.3', 'agent_version': 'agent-1',
            'output': {'action': 'buy', 'summary': summary,
                       'levels': {k: {'value': str(plan[k]), 'refs': ['call:1']}
                                  for k in ('entry_low', 'entry_high', 'stop', 'target1')},
                       'thesis': [{'text': 't', 'refs': ['call:1']}]},
            'counter': ({'status': 'ok', 'risks': [{'text': first_risk, 'refs': ['call:1']}], 'dropped': 0}
                        if first_risk else None),
            'plan': plan, 'input_tokens': 10, 'output_tokens': 5, 'created_at': '2026-10-22T23:00:00+00:00'}


def all_text(messages):
    return '\n'.join(f.value for m in messages for f in m.fields)


def test_digest_plan_carries_action_rules_funding_and_contra():
    u = unit(plan=plan_row())
    u['brief']['output']['contra'] = [{'text': '反证：量能不足'}]
    dg = build(units=[u])
    entry = dg['plans'][0]
    assert entry['action'] == 'buy' and entry['rule_ids'] == ['trend_reclaim']
    assert entry['plan_version'] == 'plan-1' and entry['snapshot_as_of'] == '2026-10-20'
    assert '反证：量能不足' in entry['contra']
    text = all_text(templates.workbench_digest(dg))
    for needle in ('买入', 'trend_reclaim · plan-1', '资金日 2026-10-20', '反证：量能不足'):
        assert needle in text, needle


def test_holding_alerts_today():
    summary = {'errors': [], 'earnings': {},
               'tickers': {'NVDA': {'candidates': ['plan_stop']}}}
    dg = build(holdings=[holding()], summary=summary)
    assert dg['holdings'][0]['plan_alerts'] == ['plan_stop']
    text = all_text(templates.workbench_digest(dg))
    assert 'plan_stop' in text and '核对券商止损单' in text
    target = build(holdings=[holding()],
                   summary={'errors': [], 'earnings': {}, 'tickers': {'NVDA': {'candidates': ['plan_target']}}})
    assert target['holdings'][0]['plan_alerts'] == ['plan_target']
    assert '卖出一半' in all_text(templates.workbench_digest(target))


def test_digest_sections():
    dg = build(units=[unit(plan=plan_row())], holdings=[holding()])
    assert {'session', 'overview', 'plans', 'holdings', 'pending', 'errors'} <= set(dg)
    assert dg['overview']['new_plans'] == 1 and dg['overview']['holdings'] == 1
    assert dg['plans'][0]['ticker'] == 'NVDA' and dg['plans'][0]['shares'] == 166
    assert dg['holdings'][0]['ticker'] == 'NVDA'


def test_digest_no_plans_still_sends():
    dg = build()
    assert dg['plans'] == []
    assert '今日无新计划' in all_text(templates.workbench_digest(dg))


def test_digest_marks_last_push_failed():
    dg = build(last_push_failed=True)
    assert dg['overview']['last_push_failed'] is True
    assert '上次推送失败' in all_text(templates.workbench_digest(dg))


def test_plan_field_text():
    dg = build(units=[unit(plan=plan_row())])
    text = all_text(templates.workbench_digest(dg))
    for needle in ('区间', '止损', 'T1', '证据：未验证', URL):
        assert needle in text, needle


def test_field_truncated_to_1024_and_message_under_6000():
    units = [unit(ticker=f'T{i:03d}', plan=plan_row(ticker=f'T{i:03d}'), brief_summary='长' * 5000)
             for i in range(30)]
    for message in templates.workbench_digest(build(units=units)):
        for field in message.fields:
            assert len(field.value) <= 1024
        total = len(message.title) + sum(len(f.name) + len(f.value) for f in message.fields) + len(message.footer)
        assert total <= 6000


def test_overflow_says_rest_in_system():
    units = [unit(ticker=f'T{i:03d}', plan=plan_row(ticker=f'T{i:03d}'),
                  brief_summary='很长的解读摘要' * 20) for i in range(80)]
    text = all_text(templates.workbench_digest(build(units=units)))
    assert '其余' in text and '见系统' in text


def test_holding_earnings_eve_reminder():
    eve = add_trading_days(SESSION, 1).isoformat()
    dg = build(holdings=[holding(next_earnings=eve)])
    assert dg['holdings'][0]['earnings_eve'] is True
    assert '财报' in all_text(templates.workbench_digest(dg))


def test_expiring_plan_listed_in_pending():
    expiring = plan_row(valid_until=add_trading_days(SESSION, 1))
    dg = build(units=[unit(plan=expiring)])
    assert dg['pending']['expiring'][0]['ticker'] == 'NVDA'


def test_digest_collects_errors():
    dg = build(summary={'errors': ['NVDA bars: provider down'], 'earnings': {'MU': 'error: boom'}})
    assert any('provider down' in e for e in dg['errors'])
    assert any('MU' in e for e in dg['errors'])


def test_closed_day_message():
    messages = templates.workbench_closed(date(2026, 10, 24))
    assert len(messages) == 1
    assert '纽约休市，未运行' in messages[0].title


# --- P2: market context, extended count, errors by source ---

def market_row(**over):
    row = {'id': 'r1', 'session': SESSION, 'calc_version': 'regime-1', 'label': 'risk_off',
           'breadth': {'tickers': 40, 'eligible_50': 40, 'above_50': 20, 'pct_50': 0.5,
                       'eligible_200': 40, 'above_200': 12, 'pct_200': 0.3,
                       'eligible_52w': 38, 'new_highs': 3, 'new_lows': 1},
           'sectors': {'SMH': {'rs20': -0.12, 'rs60': -0.2, 'state': 'weak'},
                       'XLK': {'rs20': 0.03, 'rs60': -0.01, 'state': 'mixed'},
                       'QQQ': None},
           'macro': {'BAMLH0A0HYM2': {'value': D('3.2'), 'obs_date': SESSION, 'change': D('0.1'),
                                     'change_from': SESSION},
                     'T10Y2Y': {'value': D('-0.1'), 'obs_date': SESSION, 'change': D('-0.05'),
                                'change_from': SESSION}},
           'inputs': {}, 'created_at': None}
    row.update(over)
    return row


def ctx(**over):
    context = {'context_version': 'context-1', 'pool_tier': 'core',
               'regime': {'id': 'r1', 'label': 'risk_off'},
               'sector': {'etf': 'SMH', 'rs20': -0.12, 'rs60': -0.2, 'state': 'weak'},
               'next_earnings': date(2026, 11, 20)}
    context.update(over)
    return context


def test_digest_market_field_text():
    dg = build(market=market_row())
    assert dg['overview']['market']['label'] == 'risk_off'
    text = all_text(templates.workbench_digest(dg))
    for needle in ('区制 防守', '站上 MA50 50.0%', 'MA200 30.0%', '新高 3 / 新低 1',
                   'SMH -12.0% 弱', 'XLK +3.0% 分化', 'QQQ 数据不足',
                   'HY OAS 3.2（20 期 +0.1）', '2s10s -0.1（20 期 -0.05）'):
        assert needle in text, needle


def test_digest_fred_not_configured_text():
    market = market_row(macro={'BAMLH0A0HYM2': None, 'T10Y2Y': None},
                        inputs={'macro_status': {'BAMLH0A0HYM2': 'not_configured', 'T10Y2Y': 'not_configured'}})
    assert 'FRED 未配置' in all_text(templates.workbench_digest(build(market=market)))
    assert '市场环境未生成' in all_text(templates.workbench_digest(build(market=None)))


def test_digest_fred_failed_is_not_called_unconfigured():
    market = market_row(macro={'BAMLH0A0HYM2': None, 'T10Y2Y': None},
                        inputs={'macro_status': {'BAMLH0A0HYM2': 'error', 'T10Y2Y': 'error'}})
    text = all_text(templates.workbench_digest(build(market=market)))
    assert 'FRED 采集失败' in text and 'FRED 未配置' not in text
    # A snapshot without recorded status (or with no stored rows) says only that there is no data.
    for inputs in ({}, {'macro_status': {'BAMLH0A0HYM2': 'ok', 'T10Y2Y': 'ok'}}):
        text = all_text(templates.workbench_digest(build(market=market_row(
            macro={'BAMLH0A0HYM2': None, 'T10Y2Y': None}, inputs=inputs))))
        assert 'FRED 无数据' in text and 'FRED 未配置' not in text


def test_plan_line_has_regime_earnings_sector():
    plan = plan_row()
    plan['inputs'] = {'context': ctx()}
    dg = build(units=[unit(plan=plan)])
    assert dg['plans'][0]['regime_label'] == 'risk_off'
    assert dg['plans'][0]['next_earnings'] == '2026-11-20'
    text = all_text(templates.workbench_digest(dg))
    assert '区制 防守' in text and '下次财报 2026-11-20' in text and '行业 SMH 弱' in text

    bare = build(units=[unit(plan=plan_row())])
    bare_text = all_text(templates.workbench_digest(bare))
    assert '下次财报 未知' in bare_text and '行业 未映射' in bare_text


def test_extended_count_in_overview():
    dg = build(extended_plans=3)
    assert dg['overview']['extended_plans'] == 3
    assert '扩展池新计划 3 份（不推送）' in all_text(templates.workbench_digest(dg))
    silent = build()
    assert '扩展池新计划' not in all_text(templates.workbench_digest(silent))


def test_core_empty_overview_text():
    dg = build(summary={'errors': ['core_empty'], 'earnings': {}})
    assert dg['overview']['core_empty'] is True
    assert '核心池为空，只推送持仓' in all_text(templates.workbench_digest(dg))


def test_errors_grouped_by_source():
    summary = {'errors': ['MU bars: down', 'batch_over_budget: 2100.0'], 'earnings': {},
               'sources': {'bars': ['MU'], 'news': [], 'earnings': [], 'sec': [], 'etf_bars': [], 'fred': [],
                           'regime': []}}
    dg = build(summary=summary)
    assert dg['errors_by_source']['bars'] == ['MU']
    assert dg['errors_by_source']['budget'] == ['batch_over_budget: 2100.0']
    messages = templates.workbench_digest(dg)
    names = {f.name for m in messages for f in m.fields}
    assert '日线' in names and '耗时' in names and '资讯' not in names
    text = all_text(messages)
    assert 'MU' in text and 'batch_over_budget: 2100.0' in text


def test_digest_limits_with_100_ticker_summary():
    failed = [f'T{i:03d}' for i in range(100)]
    summary = {'errors': [f'{t} bars: down' for t in failed], 'earnings': {},
               'sources': {'bars': failed, 'news': failed, 'earnings': failed, 'sec': ['all'],
                           'etf_bars': ['XLK'], 'fred': ['T10Y2Y'], 'regime': []}}
    dg = build(summary=summary)
    for message in templates.workbench_digest(dg):
        for field in message.fields:
            assert len(field.value) <= 1024
        total = len(message.title) + sum(len(f.name) + len(f.value) for f in message.fields) + len(message.footer)
        assert total <= 6000


# --- agent lines in the daily push (P3 §10.2) ---

def test_agent_line_ok():
    u = unit(plan=plan_row(), agent=agent_ok())
    text = all_text(templates.workbench_digest(build(units=[u])))
    assert 'Agent（glm-5.3）买入 · 区间 98.5–101.5 · 止损 94 · T1 112 · 166 股；回踩修复放量' in text
    assert '反方：财报临近' in text


def test_agent_line_pass():
    agent = {'id': 'r2', 'status': 'pass', 'model': 'glm-5.3', 'agent_version': 'agent-1',
             'output': {'action': 'pass', 'summary': '趋势不明'}, 'counter': None, 'plan': None,
             'input_tokens': 5, 'output_tokens': 5, 'created_at': '2026-10-22T23:00:00+00:00'}
    text = all_text(templates.workbench_digest(build(units=[unit(plan=plan_row(), agent=agent)])))
    assert 'Agent（glm-5.3）不建议买入；趋势不明' in text


def test_agent_line_missing_reason():
    agent = {'id': 'r3', 'status': 'skipped', 'reason': 'quota_exhausted',
             'created_at': '2026-10-22T23:00:00+00:00'}
    text = all_text(templates.workbench_digest(build(units=[unit(plan=plan_row(), agent=agent)])))
    assert 'Agent 未给出建议（额度用尽）' in text


def test_agent_only_unit_listed():
    u = unit(plan=None, agent=agent_ok())
    dg = build(units=[u])
    assert len(dg['plans']) == 1
    item = dg['plans'][0]
    assert item['kind'] == 'agent' and item['entry_low'] is None and item['shares'] is None
    text = all_text(templates.workbench_digest(dg))
    assert 'Agent（glm-5.3）买入 · 区间 98.5–101.5' in text
    assert text.count('区间') == 1          # 规则区间行不写，只有 Agent 行里的区间


def test_overview_agent_counts_and_quota_warning():
    units = [unit(plan=plan_row(), agent=agent_ok()),
             unit(ticker='MU', plan=plan_row(ticker='MU'),
                  agent={'id': 'r', 'status': 'pass', 'model': 'glm-5.3', 'output': {'summary': 's'},
                         'counter': None, 'plan': None, 'input_tokens': 0, 'output_tokens': 0,
                         'created_at': 'c'}),
             unit(ticker='AMD', plan=plan_row(ticker='AMD'), agent=None)]
    dg = build(units=units, agent_summary={'quota_exhausted': True})
    assert dg['overview']['agent'] == {'ok': 1, 'pass': 1, 'missing': 1}
    assert dg['overview']['agent_quota_exhausted'] is True
    text = all_text(templates.workbench_digest(dg))
    assert 'Agent 建议 1 · 不建议 1 · 未给出 1' in text
    assert '⚠️ Agent 额度用尽，其余单元未运行' in text


def test_overview_agent_counts_only_session_buy_units():
    """Sell/watch, conflict and earlier still-open units never enter the agent stage: not 'missing'."""
    units = [unit(plan=plan_row(), agent=agent_ok()),
             {**unit(ticker='AAPL'), 'proposed_action': 'sell'},
             {**unit(ticker='MSFT'), 'proposed_action': 'watch'},
             {**unit(ticker='MU'), 'labels': ['conflict']},
             unit(ticker='AMD', signal_date=date(2026, 10, 21), plan=plan_row(ticker='AMD')),
             unit(ticker='TSM', plan=plan_row(ticker='TSM'), agent=None)]
    assert build(units=units)['overview']['agent'] == {'ok': 1, 'pass': 0, 'missing': 1}


def test_digest_limits_with_agent_lines():
    long_text = '风' * 900
    units = [unit(ticker=f'T{i:02d}', plan=plan_row(ticker=f'T{i:02d}'),
                  agent=agent_ok(ticker=f'T{i:02d}', summary=long_text, first_risk=long_text))
             for i in range(15)]
    for message in templates.workbench_digest(build(units=units)):
        for field in message.fields:
            assert len(field.value) <= 1024
        total = len(message.title) + sum(len(f.name) + len(f.value) for f in message.fields) + len(message.footer)
        assert total <= 6000


def test_agent_line_without_snapshot_omits_shares():
    no_equity = plan_row(kind='agent', plan_version='agent-1',
                         sizing={'status': 'no_equity', 'shares': None, 'risk_amount': None,
                                 'snapshot_as_of': None})
    agent = {**agent_ok(), 'plan': no_equity}
    text = all_text(templates.workbench_digest(build(units=[unit(plan=plan_row(), agent=agent)])))
    assert 'None' not in text
    assert '缺资金快照，无法计算' in text
