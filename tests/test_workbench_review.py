"""Review math on synthetic bars (fabricated numbers)."""
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import review

T = date(2026, 10, 1)  # Thursday
NOW = datetime(2026, 11, 20, tzinfo=UTC)


def bars_from(start, closes, opens=None, factor=1.0):
    days = [add_trading_days(start, i) for i in range(len(closes))]
    opens = opens or closes
    return [{'price_date': d, 'open': float(o), 'close': float(c), 'adj_close': float(c) * factor}
            for d, o, c in zip(days, opens, closes)]


def unit(action='buy', decision='accept', final=None, rules=('trend_reclaim',), signal_date=T):
    return {'id': uuid.uuid4(), 'ticker': 'NVDA', 'signal_date': signal_date, 'proposed_action': action,
            'decision': decision, 'final_action': final or action, 'rule_ids': list(rules),
            'decided_at': datetime(2026, 10, 2, 1, tzinfo=UTC)}


# T at 100, then entry day opens at 100 and rises 1 per session.
STOCK = bars_from(T, [100] + [100 + i for i in range(1, 30)], opens=[100, 100] + [100 + i for i in range(2, 30)])
SPY = bars_from(T, [500] * 30)


def test_buy_shadow_enters_next_open_and_measures_windows():
    out = review.shadow_outcome(unit(), STOCK, SPY)
    assert out['entry_date'] == add_trading_days(T, 1) and out['entry_price'] == 100.0
    w5 = out['windows']['5']
    # exit at close of the 5th session counting the entry session: close 105
    assert w5 == {'status': 'mature', 'exit_date': add_trading_days(T, 5).isoformat(),
                  'return': pytest.approx(0.05), 'spy_return': pytest.approx(0.0), 'excess': pytest.approx(0.05)}


def test_sell_shadow_reports_avoided_move_with_sign_flipped():
    w5 = review.shadow_outcome(unit('sell'), STOCK, SPY)['windows']['5']
    assert w5['return'] == pytest.approx(-0.05) and w5['excess'] == pytest.approx(-0.05)


def test_watch_shadow_records_move_without_pnl():
    w5 = review.shadow_outcome(unit('watch'), STOCK, SPY)['windows']['5']
    assert w5['move'] == pytest.approx(0.05) and 'return' not in w5 and 'excess' not in w5


def test_windows_not_yet_complete_are_immature():
    short = STOCK[:8]
    out = review.shadow_outcome(unit(), short, SPY)
    assert out['windows']['5']['status'] == 'mature'
    assert out['windows']['10'] == {'status': 'immature'} and out['windows']['20'] == {'status': 'immature'}


def test_missing_entry_bar_is_pending():
    assert review.shadow_outcome(unit(), STOCK[:1], SPY) == {'status': 'pending_entry', 'windows': {}}


def test_returns_use_adjusted_prices_including_dividends():
    # adj_close 1% below close on every day before a dividend paid after the window: no effect on ratios.
    stock = bars_from(T, [100] * 10, factor=0.99)
    w5 = review.shadow_outcome(unit(), stock, SPY)['windows']['5']
    assert w5['return'] == pytest.approx(0.0)


def test_trade_review_for_closed_segment():
    segment = {'buy_trade_id': 'b', 'sell_trade_id': 's', 'quantity': D('10'), 'entry_cost_per_share': D('100.1'),
               'exit_price': D('105'), 'realized_pnl': D('48'),
               'opened_at': datetime(2026, 10, 2, 14, tzinfo=UTC), 'closed_at': datetime(2026, 10, 8, 19, tzinfo=UTC)}
    out = review.trade_segment_review(segment, STOCK, SPY)
    assert out['holding_sessions'] == 5
    assert out['return'] == pytest.approx(48 / 1001)
    assert out['spy_return'] == pytest.approx(0.0)
    assert out['max_favorable'] == pytest.approx(0.05) and out['max_adverse'] == pytest.approx(0.0)


def test_open_position_mark_to_latest_close():
    pos = {'quantity': D('10'), 'avg_cost': D('100'), 'opened_at': datetime(2026, 10, 2, 14, tzinfo=UTC)}
    out = review.open_position_review('NVDA', pos, STOCK)
    assert out['last_close'] == 129.0 and out['unrealized_pnl'] == pytest.approx(290.0)
    assert out['as_of'] == STOCK[-1]['price_date'].isoformat()


def test_weekly_stats_groups_and_never_claims_significance():
    week = date(2026, 9, 28)
    accepted = unit(rules=('trend_reclaim', 'new_filing'))
    rejected = unit(decision='reject', final='ignore')
    outcomes = {accepted['id']: review.shadow_outcome(accepted, STOCK, SPY),
                rejected['id']: review.shadow_outcome(rejected, STOCK[:3], SPY)}
    trades = [
        {'id': 't1', 'ticker': 'NVDA', 'side': 'buy', 'price': D('101'), 'executed_at': datetime(2026, 10, 2, 14, tzinfo=UTC),
         'decision_id': accepted['id'], 'voided_at': None},
        {'id': 't2', 'ticker': 'MU', 'side': 'buy', 'price': D('50'), 'executed_at': datetime(2026, 10, 2, 15, tzinfo=UTC),
         'decision_id': None, 'voided_at': None},
        {'id': 't3', 'ticker': 'MU', 'side': 'buy', 'price': D('50'), 'executed_at': datetime(2026, 10, 2, 16, tzinfo=UTC),
         'decision_id': None, 'voided_at': datetime(2026, 10, 3, tzinfo=UTC)},
    ]
    stats = review.weekly_stats(week, [accepted, rejected], outcomes, trades, segments=[], undecided=2,
                                entry_opens={accepted['id']: 100.0})
    assert stats['calc_version'] == review.CALC_VERSION
    assert stats['week'] == {'start': '2026-09-28', 'end': '2026-10-04'}
    assert stats['units'] == {'decided': 2, 'undecided': 2}
    tr = stats['by_rule']['trend_reclaim']['5']
    assert tr['count'] == 2 and tr['mature'] == 1 and tr['mean'] == pytest.approx(0.05)
    assert stats['by_rule']['new_filing']['5']['count'] == 1
    assert stats['by_decision']['reject']['5'] == {'count': 1, 'mature': 0, 'mean': None, 'median': None, 'values': []}
    assert stats['execution'] == [{'trade_id': 't1', 'decision_id': str(accepted['id']), 'ticker': 'NVDA',
                                   'slippage': pytest.approx(0.01), 'delay_hours': pytest.approx(13.0)}]
    assert stats['unsignaled_trades'] == ['t2']
    assert 'significant' not in str(stats) and 'p_value' not in str(stats)


# --- weekly snapshot persistence (disposable schema) ---

def test_weekly_reviews_are_frozen_and_corrected_by_superseding(workbench_db):
    from investment_assistant.workbench import ledger
    week = date(2026, 10, 19)
    first = review.save_weekly(workbench_db, week, {'units': {'decided': 1}}, notes='初稿', supersedes_id=None)
    with pytest.raises(ledger.Conflict):
        review.save_weekly(workbench_db, week, {'units': {'decided': 2}}, notes='', supersedes_id=None)
    second = review.save_weekly(workbench_db, week, first['stats'], notes='补充笔记', supersedes_id=first['id'])
    assert second['supersedes_id'] == first['id'] and second['stats'] == {'units': {'decided': 1}}
    heads = review.list_weekly(workbench_db)
    assert [h['id'] for h in heads] == [second['id']]
    assert workbench_db.execute('SELECT count(*) FROM weekly_reviews').fetchone() == (2,)


def test_weekly_review_week_must_start_monday(workbench_db):
    from investment_assistant.workbench import ledger
    with pytest.raises(ledger.LedgerError):
        review.save_weekly(workbench_db, date(2026, 10, 20), {}, notes='', supersedes_id=None)


def test_weekly_review2_has_plans_and_discipline():
    week = date(2026, 9, 28)
    in_week = lambda d: week <= d <= week + timedelta(days=6)
    plan_outcomes = [
        {'kind': 'rule', 'signal_date': date(2026, 9, 29), 'outcome': {'status': 'open', 'r': 2.0}},
        {'kind': 'rule', 'signal_date': date(2026, 10, 1), 'outcome': {'status': 'expired', 'r': None}},
        {'kind': 'own', 'signal_date': date(2026, 9, 30), 'outcome': {'status': 'closed', 'r': 1.0}},
        {'kind': 'rule', 'signal_date': date(2026, 10, 10), 'outcome': {'status': 'closed', 'r': 9.0}},  # 周外
    ]
    disc = {'trades': [], 'counts': {'chase': 0, 'early_take': 0, 'held_loser': 0, 'unplanned': 0},
            'immature': {'early_take': 0, 'held_loser': 0}, 'planned_buys': 1, 'compliance_rate': 1.0}
    stats = review.weekly_stats(week, [], {}, [], segments=[], undecided=0, entry_opens={},
                                plan_outcomes=plan_outcomes, discipline=disc)
    assert stats['calc_version'] == 'review-3'
    assert stats['plans']['rule'] == {'count': 2, 'expired': 1, 'r_mean': 2.0, 'r_median': 2.0}
    assert stats['plans']['own'] == {'count': 1, 'expired': 0, 'r_mean': 1.0, 'r_median': 1.0}
    assert stats['discipline'] == disc


# --- P2: by-pool view (review-3) ---

def test_pool_of_prefers_context():
    assert review.pool_of('extended', {'tier': 'core'}) == 'extended'
    assert review.pool_of('core', {'tier': 'extended'}) == 'core'
    assert review.pool_of(None, {'tier': 'extended'}) == 'extended'
    assert review.pool_of(None, {'tier': 'core'}) == 'core'


def test_legacy_plan_without_context_counts_core():
    assert review.pool_of(None, None) == 'core'
    assert review.pool_of('unknown', None) == 'core'


def test_pool_summary_splits_by_pool_and_rule():
    triggers = [{'pool': 'core', 'rule_id': 'trend_reclaim'}, {'pool': 'core', 'rule_id': 'trend_reclaim'},
                {'pool': 'extended', 'rule_id': 'trend_reclaim'}, {'pool': 'core', 'rule_id': 'volume_breakout'}]
    plan_outcomes = [{'pool': 'core', 'rule_ids': ['trend_reclaim', 'volume_breakout'],
                      'outcome': {'status': 'expired', 'r': None}},
                     {'pool': 'extended', 'rule_ids': ['trend_reclaim'], 'outcome': {'status': 'open', 'r': 2.0}}]
    out = review.pool_summary(triggers, plan_outcomes)
    assert out['core']['trend_reclaim'] == {'triggers': 2, 'plans': 1, 'expired': 1, 'filled': 0,
                                            'r_mean': None, 'r_median': None}
    assert out['core']['volume_breakout']['triggers'] == 1 and out['core']['volume_breakout']['plans'] == 1
    assert out['extended']['trend_reclaim'] == {'triggers': 1, 'plans': 1, 'expired': 0, 'filled': 1,
                                                'r_mean': 2.0, 'r_median': 2.0}


def test_pool_summary_counts_expired_and_filled():
    plan_outcomes = [{'pool': 'core', 'rule_ids': ['earnings_gap_up'], 'outcome': {'status': 'expired', 'r': None}},
                     {'pool': 'core', 'rule_ids': ['earnings_gap_up'], 'outcome': {'status': 'open', 'r': 1.0}},
                     {'pool': 'core', 'rule_ids': ['earnings_gap_up'], 'outcome': {'status': 'closed', 'r': 3.0}},
                     {'pool': 'core', 'rule_ids': ['earnings_gap_up'], 'outcome': {'status': 'pending', 'r': None}}]
    out = review.pool_summary([], plan_outcomes)['core']['earnings_gap_up']
    assert (out['plans'], out['expired'], out['filled']) == (4, 1, 2)
    assert out['r_mean'] == 2.0 and out['r_median'] == 2.0


def test_pool_summary_counts_only_rule_plans():
    # An own plan on the same unit must not double the rule plan's counts (spec §9: rule plans only).
    plan_outcomes = [{'pool': 'core', 'kind': 'rule', 'rule_ids': ['trend_reclaim'],
                      'outcome': {'status': 'closed', 'r': 1.0}},
                     {'pool': 'core', 'kind': 'own', 'rule_ids': ['trend_reclaim'],
                      'outcome': {'status': 'closed', 'r': 3.0}}]
    out = review.pool_summary([], plan_outcomes)['core']['trend_reclaim']
    assert (out['plans'], out['filled'], out['r_mean']) == (1, 1, 1.0)


def test_weekly_stats_carries_by_pool():
    stats = review.weekly_stats(date(2026, 10, 19), [], {}, [], segments=[], undecided=0, entry_opens={},
                                by_pool={'core': {'trend_reclaim': {'triggers': 1}}})
    assert stats['by_pool'] == {'core': {'trend_reclaim': {'triggers': 1}}}
    assert review.weekly_stats(date(2026, 10, 19), [], {}, [], segments=[], undecided=0, entry_opens={})['by_pool'] == {}
