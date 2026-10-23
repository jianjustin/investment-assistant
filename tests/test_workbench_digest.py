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


def unit(ticker='NVDA', plan=None, brief_summary='解读：量价配合。', signal_date=SESSION):
    return {'ticker': ticker, 'signal_date': signal_date, 'proposed_action': 'buy', 'rule_ids': ['trend_reclaim'],
            'labels': [],
            'plan': plan,
            'brief': ({'status': 'fallback', 'output': {'summary': brief_summary}} if brief_summary else None)}


def holding(ticker='NVDA', **over):
    row = {'ticker': ticker, 'quantity': 10, 'avg_cost': 100, 'plan_id': 'p1', 'stop': 94, 'mode': 'initial',
           't1_reached': False, 'target1': 112, 'last_close': 100.0, 'to_stop_pct': -0.06,
           'to_target_pct': 0.12, 'next_earnings': None}
    row.update(over)
    return row


def build(units=(), holdings=(), summary=None, last_push_failed=False):
    return digest.build(session=SESSION, units=list(units), holdings=list(holdings),
                        summary=summary or {'errors': [], 'earnings': {}},
                        last_push_failed=last_push_failed, public_url=URL)


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
