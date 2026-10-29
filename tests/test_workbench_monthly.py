"""Monthly return, tier, review flag and sensitivity table (design §8.2)."""
from datetime import UTC, date, datetime
from decimal import Decimal as D
from uuid import uuid4

import pytest

from investment_assistant.config import WorkbenchConfig
from investment_assistant.workbench import monthly

TIERS = WorkbenchConfig().return_tiers


def snap(as_of, equity, supersedes_id=None, recorded_at=None):
    return {'id': uuid4(), 'as_of': as_of, 'equity': D(equity), 'supersedes_id': supersedes_id,
            'recorded_at': recorded_at or datetime(2026, 11, 1, tzinfo=UTC)}


def flow(day, amount, voided=False):
    return {'flow_date': day, 'amount': D(amount), 'voided_at': date(2026, 11, 1) if voided else None}


def test_month_return_with_flows():
    out = monthly.month_return(date(2026, 10, 1),
                               [snap(date(2026, 9, 30), 100000), snap(date(2026, 10, 31), 112000)],
                               [flow(date(2026, 10, 15), 5000), flow(date(2026, 11, 2), 999)])
    assert out['status'] == 'ok'
    assert out['return'] == pytest.approx(0.07)
    assert out['net_flow'] == pytest.approx(5000)  # 11 月的出入金不算本月


def test_month_missing_snapshot():
    out = monthly.month_return(date(2026, 10, 1), [snap(date(2026, 10, 31), 112000)], [])
    assert out['status'] == 'missing_snapshot' and out['return'] is None


def test_voided_flow_ignored():
    out = monthly.month_return(date(2026, 10, 1),
                               [snap(date(2026, 9, 30), 100000), snap(date(2026, 10, 31), 112000)],
                               [flow(date(2026, 10, 15), 5000, voided=True)])
    assert out['return'] == pytest.approx(0.12)


def test_superseded_snapshot_ignored():
    old_end = snap(date(2026, 10, 31), 112000)
    out = monthly.month_return(date(2026, 10, 1),
                               [snap(date(2026, 9, 30), 100000), old_end,
                                snap(date(2026, 10, 31), 110000, supersedes_id=old_end['id'])],
                               [])
    assert out['return'] == pytest.approx(0.10)


def test_tier_boundaries():
    assert monthly.tier(0.2001, TIERS) == 'excellent_plus'
    assert monthly.tier(0.20, TIERS) == 'excellent'
    assert monthly.tier(0.10, TIERS) == 'excellent'
    assert monthly.tier(0.0999, TIERS) == 'viable'
    assert monthly.tier(0.0, TIERS) == 'viable'
    assert monthly.tier(-0.0001, TIERS) == 'attention'


def test_review_flag_requires_loss_and_underperform():
    losing = [{'return': r, 'spy_return': s} for r, s in zip((-0.05, -0.02, -0.01), (0.01, 0.01, 0.01))]
    assert monthly.review_flag(losing) == 'review'
    beating = [{'return': r, 'spy_return': s} for r, s in zip((-0.05, -0.02, -0.01), (-0.10, -0.10, -0.10))]
    assert monthly.review_flag(beating) == 'ok'
    gaining = [{'return': r, 'spy_return': s} for r, s in zip((0.02, -0.01, 0.03), (0.01, 0.01, 0.01))]
    assert monthly.review_flag(gaining) == 'ok'


def test_review_flag_insufficient():
    assert monthly.review_flag([{'return': 0.01, 'spy_return': 0.0}]) == 'insufficient'
    assert monthly.review_flag([{'return': 0.01, 'spy_return': 0.0}] * 2) == 'insufficient'
    assert monthly.review_flag([{'return': 0.01, 'spy_return': 0.0}, {'return': None, 'spy_return': 0.0},
                                {'return': 0.02, 'spy_return': 0.0}]) == 'insufficient'


def test_sensitivity_drawdown():
    rows = monthly.sensitivity([2, -1, -1, 3])
    assert [r['risk_pct'] for r in rows] == [0.005, 0.01, 0.015, 0.02]
    assert rows[1]['return'] == pytest.approx(0.03)
    assert rows[1]['max_drawdown'] == pytest.approx(0.02)


def test_month_without_snapshot_inside_it_is_missing():
    # 只录了 10 月快照：11 月的期末不能沿用 10 月那条，否则会算成 0% 并评为「可行」
    out = monthly.month_return(date(2026, 11, 1), [snap(date(2026, 10, 30), 100000)], [])
    assert out['status'] == 'missing_snapshot' and out['return'] is None


def test_month_start_must_be_previous_month():
    # 10 月没有快照：期初不能拿 7 月的快照顶替，否则会把四个月的收益当成单月收益
    out = monthly.month_return(date(2026, 11, 1),
                               [snap(date(2026, 7, 31), 100000), snap(date(2026, 11, 30), 130000)], [])
    assert out['status'] == 'missing_snapshot' and out['return'] is None


# --- review detail (P4 §5) ---

def test_review_detail_compounds():
    import pytest
    last_three = [{'month': '2026-08-01', 'return': 0.02, 'spy_return': 0.01},
                  {'month': '2026-09-01', 'return': -0.05, 'spy_return': 0.01},
                  {'month': '2026-10-01', 'return': 0.01, 'spy_return': 0.01}]
    detail = monthly.review_detail(last_three)
    assert detail['compound'] == pytest.approx(1.02 * 0.95 * 1.01 - 1)
    assert detail['spy_compound'] == pytest.approx(1.01 ** 3 - 1)
    assert detail['flag'] == 'review'
    assert [m['month'] for m in detail['months']] == ['2026-08-01', '2026-09-01', '2026-10-01']
    assert all(set(m) == {'month', 'return', 'spy_return'} for m in detail['months'])


def test_review_detail_missing_month_nulls():
    detail = monthly.review_detail([{'month': '2026-09-01', 'return': None, 'spy_return': None}])
    assert detail['compound'] is None and detail['spy_compound'] is None
    assert detail['flag'] == 'insufficient'
    assert monthly.month_end_snapshot([{'id': 1, 'as_of': date(2026, 10, 31), 'recorded_at': datetime(2026, 11, 1, tzinfo=UTC),
                                        'supersedes_id': None}], date(2026, 10, 1))['id'] == 1


# --- v2.5 D17: monthly-3 counts each chain's first version in plans.agent, its head in agent_latest ---

def test_monthly_version_is_monthly_3():
    assert monthly.MONTHLY_VERSION == 'monthly-3'


def test_generate_monthly_counts_first_and_latest(workbench_db, monkeypatch):
    from contextlib import contextmanager
    from datetime import timedelta

    from investment_assistant.workbench import repository, service

    @contextmanager
    def connection():
        yield workbench_db
    monkeypatch.setattr(service, 'connection', connection)
    now = datetime(2026, 11, 20, 22, 30, tzinfo=UTC)
    day = date(2026, 10, 21)
    previous = None
    for version_no in range(3):
        plan = repository.insert_plan(workbench_db, {
            'ticker': 'NVDA', 'signal_date': day, 'kind': 'agent', 'based_on_id': None, 'plan_version': 'agent-2',
            'ref_price': D('100'), 'atr': D('2'), 'entry_low': D('99'), 'entry_high': D('101'), 'stop': D('94'),
            'target1': D('108'), 'trail_atr_multiple': D('3'), 'valid_from': date(2026, 10, 22),
            'valid_until': date(2026, 10, 26), 'sizing': {'status': 'no_equity'}, 'status': 'ok',
            'invalid_reasons': [], 'warnings': [], 'inputs': {'bar_ids': [1]}, 'request_id': None,
            'request_hash': None})
        run_id, at = uuid4(), datetime(2026, 10, 22, 1, tzinfo=UTC) + timedelta(days=version_no)
        repository.insert_agent_run(workbench_db, {
            'id': run_id, 'ticker': 'NVDA', 'signal_date': day, 'pool': 'main', 'attempt': 1,
            'mode': 'propose' if version_no == 0 else 'revise', 'agent_version': 'agent-2', 'provider': 'chatgpt',
            'model': 'gpt-test', 'cutoff_at': at, 'status': 'ok', 'reason': None, 'output': {'action': 'buy'},
            'counter': None, 'plan_id': plan['id'], 'input_tokens': 0, 'output_tokens': 0,
            'started_at': at, 'finished_at': at}, [])
        repository.insert_plan_version(workbench_db, {
            'plan_id': plan['id'], 'ticker': 'NVDA', 'signal_date': day, 'version_no': version_no,
            'supersedes_plan_id': previous, 'origin': 'signal' if version_no == 0 else 'review',
            'agent_run_id': run_id, 'cutoff_at': at, 'as_of_session': day,
            'diff': None if version_no == 0 else [{'field': 'stop', 'before': '94', 'after': '95'}],
            'schema_version': 'agent-2'})
        previous = plan['id']
    stats = service.generate_monthly(date(2026, 10, 1), now=now)['stats']
    assert stats['calc_version'] == 'monthly-3'
    assert stats['plans']['agent']['count'] == 1
    assert stats['plans']['agent_latest']['count'] == 1
    assert stats['tracks']['units'][0]['agent']['version_basis'] == 'first'
