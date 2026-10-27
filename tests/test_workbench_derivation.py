"""Plan-1 rule plan derivation: independent recomputation from substituted values (offline, pure)."""
import copy
import json
import uuid
from datetime import date
from decimal import Decimal

import pytest

from investment_assistant.config import WorkbenchConfig
from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import derivation, plans, repository

SIGNAL = date(2026, 10, 21)


def _bars(n=15, close=100):
    """Bars with constant TR=2 and the given close, ids 1..n."""
    out = []
    start = date(2026, 10, 1)
    for i in range(n):
        d = add_trading_days(start, i) if i else start
        out.append({'id': i + 1, 'price_date': d, 'open': close, 'high': close + 2, 'low': close,
                    'close': close, 'adj_close': close, 'volume': 1000, 'split_factor': 1.0, 'revision': 1})
    return out


def _snapshot(equity='100000'):
    return {'id': uuid.uuid4(), 'as_of': date(2026, 10, 20), 'equity': Decimal(equity)}


def _exposure(ticker_value='0', total_value='0'):
    return {'ticker_value': Decimal(ticker_value), 'total_value': Decimal(total_value)}


def _earnings(d, status='known'):
    return {'id': uuid.uuid4(), 'status': status, 'earnings_date': d}


def _rows(bars, earnings=None, snapshot=None, regime=None):
    dec_bars = [{**b, **{k: Decimal(str(b[k])) for k in ('open', 'high', 'low', 'close')}} for b in bars]
    return derivation.Rows(bars=dec_bars, earnings=earnings, snapshot=snapshot, regime=regime,
                           agent_run=None, rule_plan=None, candidates=[], missing=[])


def _make(*, bars=None, earnings=None, snapshot='default', exposure=None, params=None, context=None,
          regime=None):
    bars = bars or _bars()
    snapshot = _snapshot() if snapshot == 'default' else snapshot
    plan = plans.build_rule_plan(
        ticker='AAA', signal_date=SIGNAL, bars=bars, earnings_row=earnings, snapshot=snapshot,
        exposure=exposure or _exposure(), params=params or WorkbenchConfig(), context=context)
    plan['id'] = uuid.uuid4()
    return plan, _rows(bars, earnings, snapshot, regime)


def _step(result, key):
    return next(s for s in result['steps'] if s['key'] == key)


def _keys(result):
    return [s['key'] for s in result['steps']]


def test_constants_match_plans():
    for name in ('ENTRY_ATR', 'STOP_ATR', 'TARGET_ATR', 'TRAIL_ATR_MULTIPLE', 'VALID_SESSIONS',
                 'EARNINGS_WARN_SESSIONS', 'ATR_PERIOD', 'MIN_BARS'):
        assert getattr(derivation, name) == getattr(plans, name), name
    assert derivation.DERIVATION_VERSION == 'derivation-1'
    assert plans.PLAN_VERSION in derivation.REGISTERED_VERSIONS
    assert plans.AGENT_VERSION in derivation.REGISTERED_VERSIONS


def test_fixed_texts_verbatim():
    assert derivation.EVIDENCE_TEXT == (
        '规则 v1 与 `plan-1` 都未经验证（Phase 0 Gate HOLD）。推导一致只说明算术正确，不说明规则有效。')
    assert derivation.TRIGGER_NOTE == '触发段只复核候选冻结的取值是否满足阈值，不从原始日线重算均线。'


def test_rule_plan_worked_example():
    plan, rows = _make()
    result = derivation.derive_plan(plan, rows)
    expected = {'atr': '2', 'ref_price': '100', 'entry_low': '99', 'entry_high': '101', 'stop': '96',
                'target1': '108', 'per_share_risk': '4', 'risk_amount': '1000', 'cap_risk': '250',
                'cap_single': '247', 'cap_total': '990', 'shares': '247'}
    for key, value in expected.items():
        assert Decimal(_step(result, key)['result']) == Decimal(value), key
    assert _step(result, 'atr')['result'] == '2.000000'
    assert _step(result, 'entry_low')['result'] == '99.00'
    assert _step(result, 'applied_cap')['result'] == 'single'
    assert _step(result, 'sizing.status')['result'] == 'capped'
    assert _step(result, 'status')['result'] == 'ok'
    assert all(s['consistent'] is not False for s in result['steps'])
    assert result['consistency'] == {'status': 'consistent', 'mismatches': [], 'missing': []}
    assert result['trigger'] == []
    assert result['derivation_version'] == 'derivation-1'
    assert result['evidence'] == derivation.EVIDENCE_TEXT
    assert result['plan'] == {'id': str(plan['id']), 'ticker': 'AAA', 'signal_date': '2026-10-21',
                              'kind': 'rule', 'plan_version': 'plan-1', 'status': 'ok'}
    assert _step(result, 'valid_from')['result'] == add_trading_days(SIGNAL, 1).isoformat()
    assert _step(result, 'valid_until')['result'] == add_trading_days(SIGNAL, 3).isoformat()
    assert _step(result, 'trail_atr_multiple')['result'] == '3'
    # Every step carries the documented shape and string substitutions.
    for s in result['steps']:
        assert set(s) == {'key', 'label', 'formula', 'substitutions', 'result', 'stored', 'source', 'consistent'}
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in s['substitutions'].items())
    assert _step(result, 'stop')['substitutions'] == {'ref_price': '100.000000', 'STOP_ATR': '2', 'atr': '2.000000'}
    assert result['checks'][0]['key'] == 'levels_ordered' and result['checks'][0]['holds'] is True


CONTEXT_BASE = {'context_version': 'context-2', 'pool_tier': 'core', 'source': 'manual', 'screen': None,
                'regime': {'id': str(uuid.uuid4()), 'label': 'risk_on'}, 'sector': None, 'next_earnings': None}

VARIANTS = {
    'sized': dict(params=WorkbenchConfig(single_cap=0.9)),
    'capped_total': dict(exposure=_exposure('0', '99000')),
    'no_room': dict(exposure=_exposure('30000', '30000')),
    'no_equity': dict(snapshot=None),
    'earnings_in_validity': dict(earnings=_earnings(date(2026, 10, 23))),
    'earnings_within_10d': dict(earnings=_earnings(date(2026, 11, 2))),
    'earnings_far': dict(earnings=_earnings(date(2026, 12, 15))),
    'earnings_past': dict(earnings=_earnings(date(2026, 10, 1))),
    'earnings_unknown_row': dict(earnings=_earnings(None, status='unknown')),
    'earnings_missing': dict(earnings=None),
    'risk_off': dict(context={**CONTEXT_BASE, 'regime': {'id': str(uuid.uuid4()), 'label': 'risk_off'}}),
    'regime_unavailable': dict(context={**CONTEXT_BASE, 'regime': None}),
    'sector_weak': dict(context={**CONTEXT_BASE, 'sector': {'etf': 'XLK', 'rs20': -0.1, 'rs60': -0.2,
                                                           'state': 'weak'}}),
    'screen_source': dict(context={**CONTEXT_BASE, 'source': 'screen',
                                   'screen': {'screen_run_id': str(uuid.uuid4()), 'group': 'growth',
                                              'rs': 0.4, 'rank': 3}}),
    'everything': dict(earnings=_earnings(date(2026, 10, 23)), exposure=_exposure('30000', '30000'),
                       context={**CONTEXT_BASE, 'regime': {'id': 'x', 'label': 'risk_off'},
                                'sector': {'etf': 'XLK', 'rs20': -0.1, 'rs60': -0.2, 'state': 'weak'}}),
}


@pytest.mark.parametrize('name', sorted(VARIANTS))
def test_rule_plan_variants_consistent(name):
    plan, rows = _make(**VARIANTS[name])
    result = derivation.derive_plan(plan, rows)
    assert result['consistency'] == {'status': 'consistent', 'mismatches': [], 'missing': []}, result['consistency']
    assert _step(result, 'status')['result'] == plan['status']
    assert _step(result, 'invalid_reasons')['result'] == sorted(plan['invalid_reasons'])
    assert _step(result, 'warnings')['result'] == sorted(plan['warnings'])
    assert _step(result, 'status')['consistent'] is True
    assert _step(result, 'invalid_reasons')['consistent'] is True
    assert _step(result, 'warnings')['consistent'] is True


def test_variant_outcomes_are_what_they_claim():
    def run(name):
        plan, rows = _make(**VARIANTS[name])
        return plan, derivation.derive_plan(plan, rows)

    plan, result = run('sized')
    assert plan['sizing']['status'] == 'sized' and _step(result, 'applied_cap')['result'] == 'risk'
    assert _step(result, 'sizing.status')['result'] == 'sized'
    plan, result = run('capped_total')
    assert _step(result, 'applied_cap')['result'] == 'total' and _step(result, 'shares')['result'] == '9'
    plan, result = run('no_room')
    assert plan['status'] == 'invalid' and 'no_room' in plan['invalid_reasons']
    assert _step(result, 'sizing.status')['result'] == 'no_room'
    assert _step(result, 'invalid_reasons')['result'] == ['no_room']
    plan, result = run('no_equity')
    assert plan['sizing']['status'] == 'no_equity' and plan['sizing']['shares'] is None
    assert _step(result, 'shares')['result'] is None and _step(result, 'sizing.status')['result'] == 'no_equity'
    assert _step(result, 'per_share_risk')['consistent'] is True
    assert 'cap_risk' not in _keys(result)
    plan, result = run('earnings_in_validity')
    assert _step(result, 'invalid_reasons')['result'] == ['earnings_in_validity']
    assert _step(result, 'status')['result'] == 'invalid'
    plan, result = run('earnings_within_10d')
    assert _step(result, 'warnings')['result'] == ['earnings_within_10d']
    plan, result = run('earnings_missing')
    assert _step(result, 'warnings')['result'] == ['earnings_unknown']
    plan, result = run('risk_off')
    assert _step(result, 'warnings')['result'] == ['earnings_unknown', 'regime_risk_off']
    plan, result = run('regime_unavailable')
    assert 'regime_unavailable' in _step(result, 'warnings')['result']
    plan, result = run('sector_weak')
    assert 'sector_weak' in _step(result, 'warnings')['result']


def test_json_roundtripped_plan_is_consistent():
    """A plan read back from the database has JSON sizing/inputs (strings, floats, iso dates)."""
    plan, rows = _make(earnings=_earnings(date(2026, 10, 23)),
                       context={**CONTEXT_BASE, 'next_earnings': date(2026, 10, 23)})
    stored = copy.deepcopy(plan)
    stored['sizing'] = json.loads(repository._plan_json(plan['sizing']))
    stored['inputs'] = json.loads(repository._plan_json(plan['inputs']))
    result = derivation.derive_plan(stored, rows)
    assert result['consistency']['status'] == 'consistent', result['consistency']


def _tamper_stop(p):
    p['stop'] += Decimal('0.01')


def _tamper_atr(p):
    p['atr'] += Decimal('0.000001')


def _tamper_shares(p):
    p['sizing']['shares'] += 1


def _tamper_warnings(p):
    p['warnings'] = [*p['warnings'], 'regime_risk_off']


@pytest.mark.parametrize('key,tamper', [('stop', _tamper_stop), ('atr', _tamper_atr),
                                        ('shares', _tamper_shares), ('warnings', _tamper_warnings)])
def test_tampered_value_is_mismatch(key, tamper):
    plan, rows = _make()
    tamper(plan)
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'mismatch'
    assert result['consistency']['mismatches'][0]['key'] == key
    assert len(result['consistency']['mismatches']) == 1
    step = _step(result, key)
    assert step['consistent'] is False
    assert result['consistency']['mismatches'][0] == {'key': key, 'result': step['result'], 'stored': step['stored']}


def test_tampered_frozen_equity_and_status_are_mismatch():
    plan, rows = _make()
    plan['sizing']['equity'] = Decimal('100001')
    assert derivation.derive_plan(plan, rows)['consistency']['mismatches'][0]['key'] == 'equity'
    plan, rows = _make()
    plan['status'] = 'invalid'
    assert derivation.derive_plan(plan, rows)['consistency']['mismatches'][0]['key'] == 'status'
    plan, rows = _make()
    plan['valid_until'] = add_trading_days(SIGNAL, 4)
    assert derivation.derive_plan(plan, rows)['consistency']['mismatches'][0]['key'] == 'valid_until'


def test_altered_input_row_is_mismatch():
    """If the frozen bar row read back differs from what the plan used, the recomputation disagrees."""
    plan, rows = _make()
    rows.bars[-1]['close'] += Decimal('1')
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'mismatch'
    assert result['consistency']['mismatches'][0]['key'] == 'ref_price'


def test_missing_rows_incomplete():
    plan, rows = _make()
    rows.missing = ['price_bars:42']
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'incomplete'
    assert result['consistency']['missing'] == ['price_bars:42']

    plan, rows = _make()
    rows.bars = rows.bars[:14]
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'incomplete' and 'bar_ids' in result['consistency']['missing']

    plan, rows = _make()
    rows.bars = None
    assert 'bar_ids' in derivation.derive_plan(plan, rows)['consistency']['missing']

    plan, rows = _make()
    plan['plan_version'] = 'plan-9'
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'incomplete'
    assert 'unknown_plan_version' in result['consistency']['missing']
    assert result['steps'] == []


def test_missing_snapshot_or_earnings_row_is_incomplete():
    plan, rows = _make()
    rows.snapshot = None   # inputs.snapshot_id still points at a row that was not read back
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'incomplete'
    assert result['consistency']['missing'] == [f"account_snapshots:{plan['inputs']['snapshot_id']}"]

    plan, rows = _make(earnings=_earnings(date(2026, 10, 23)))
    rows.earnings = None
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'incomplete'
    assert result['consistency']['missing'] == [f"earnings_dates:{plan['inputs']['earnings_date_id']}"]


def test_incomplete_outranks_mismatch():
    plan, rows = _make()
    plan['stop'] += Decimal('1')
    rows.missing = ['price_bars:42']
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'incomplete'
    assert result['consistency']['mismatches'] != []


def test_unimplemented_kind_is_incomplete_not_a_crash():
    plan, rows = _make()
    plan['kind'] = 'own'
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'incomplete'


def test_atr_step_shows_fourteen_true_ranges():
    plan, rows = _make()
    result = derivation.derive_plan(plan, rows)
    trs = [s for s in result['steps'] if s['key'].startswith('tr_')]
    assert [s['key'] for s in trs] == [f'tr_{i}' for i in range(1, 15)]
    assert all('max(H − L, |H − C前|, |L − C前|)' in s['formula'] for s in trs)
    assert all(s['result'] == '2' for s in trs)
    assert trs[0]['substitutions'] == {'H': '102', 'L': '100', 'C前': '100'}
    assert _step(result, 'atr')['substitutions']['tr_14'] == '2'
    assert len(_step(result, 'atr')['substitutions']) == 14


def test_true_range_uses_previous_close_gap():
    bars = _bars()
    bars[5]['high'] = bars[5]['low'] = bars[5]['close'] = 110   # gap up: |H − C前| = 10 dominates
    plan, rows = _make(bars=bars)
    result = derivation.derive_plan(plan, rows)
    assert _step(result, 'tr_5')['result'] == '10'
    assert result['consistency']['status'] == 'consistent'


def test_derivation_does_not_call_plans_math(monkeypatch):
    plan, rows = _make()

    def boom(*a, **k):
        raise AssertionError('derivation must not call plans math')

    for name in ('rule_levels', 'size', 'atr14', 'earnings_flags', 'validity', 'context_flags', 'levels_ordered',
                 '_cent', '_freeze', '_floor'):
        monkeypatch.setattr(plans, name, boom)
    result = derivation.derive_plan(plan, rows)
    assert result['consistency']['status'] == 'consistent'


def test_derivation_is_deterministic_and_does_not_mutate_inputs():
    plan, rows = _make(earnings=_earnings(date(2026, 10, 23)))
    plan_before, rows_before = copy.deepcopy(plan), copy.deepcopy(rows)
    first = derivation.derive_plan(plan, rows)
    second = derivation.derive_plan(plan, rows)
    assert first == second
    assert plan == plan_before and rows == rows_before
    json.dumps(first)   # everything is JSON-ready (strings, lists, bools)


def test_inputs_section_shows_frozen_rows():
    snap = _snapshot()
    plan, rows = _make(snapshot=snap, earnings=_earnings(date(2026, 10, 23)),
                       exposure=_exposure('10', '20'), regime={'id': 'r', 'label': 'risk_on', 'calc_version': 'regime-1'},
                       context={**CONTEXT_BASE, 'regime': {'id': 'r', 'label': 'risk_on'}})
    inputs = derivation.derive_plan(plan, rows)['inputs']
    assert len(inputs['bars']) == 15 and inputs['bars'][0]['id'] == '1'
    assert inputs['bars'][-1]['close'] == '100'
    assert inputs['snapshot']['equity'] == '100000'
    assert inputs['earnings']['earnings_date'] == '2026-10-23'
    assert inputs['exposure']['ticker_value'] == '10'
    assert inputs['sizing_params']['risk_pct'] == '0.01'
    assert inputs['regime']['label'] == 'risk_on'
    no_snap, rows2 = _make(snapshot=None)
    assert derivation.derive_plan(no_snap, rows2)['inputs']['snapshot'] is None
