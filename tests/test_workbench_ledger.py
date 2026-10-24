import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from investment_assistant.workbench import ledger, repository
from investment_assistant.workbench.rules import Candidate

T = date(2026, 10, 22)
NOW = datetime(2026, 10, 23, 1, 0, tzinfo=UTC)


def decision_payload(cids, **overrides):
    payload = {'request_id': str(uuid.uuid4()), 'ticker': 'NVDA', 'signal_date': T.isoformat(),
               'candidate_ids': [str(c) for c in cids], 'proposed_action': 'buy', 'final_action': 'buy',
               'decision': 'accept', 'reason': '趋势修复且财报支持'}
    payload.update(overrides)
    return payload


def trade_payload(**overrides):
    payload = {'request_id': str(uuid.uuid4()), 'ticker': 'NVDA', 'side': 'buy', 'quantity': '10',
               'price': '101.5', 'fee': '1', 'executed_at': '2026-10-23T14:00:00+00:00'}
    payload.update(overrides)
    return payload


# --- validation (pure) ---

@pytest.mark.parametrize('overrides', [
    {'reason': '  '},
    {'decision': 'accept', 'final_action': 'sell'},
    {'decision': 'reject', 'final_action': 'buy'},
    {'decision': 'downgrade', 'final_action': 'buy'},
    {'candidate_ids': []},
    {'signal_date': '2026-13-01'},
    {'request_id': 'not-a-uuid'},
])
def test_invalid_decisions(overrides):
    with pytest.raises(ledger.LedgerError):
        ledger.validate_decision(decision_payload([uuid.uuid4()], **overrides))


def test_decision_consistency_matrix():
    ok = [('accept', 'buy', 'buy'), ('reject', 'buy', 'ignore'), ('downgrade', 'buy', 'watch'),
          ('accept', 'watch', 'watch'), ('reject', 'watch', 'ignore')]
    for decision, proposed, final in ok:
        ledger.validate_decision(decision_payload([uuid.uuid4()], decision=decision, proposed_action=proposed,
                                                  final_action=final))


@pytest.mark.parametrize('overrides', [
    {'quantity': '0'}, {'price': '-1'}, {'fee': '-0.1'}, {'side': 'short'},
    {'executed_at': '2026-10-23T14:00:00'},          # naive time
    {'executed_at': '2026-10-24T14:00:00+00:00'},    # in the future relative to NOW
])
def test_invalid_trades(overrides):
    with pytest.raises(ledger.LedgerError):
        ledger.validate_trade(trade_payload(**overrides), now=NOW)


def test_request_hash_ignores_request_id_only():
    a = trade_payload()
    assert ledger.request_hash(a) == ledger.request_hash({**a, 'request_id': str(uuid.uuid4())})
    assert ledger.request_hash(a) != ledger.request_hash({**a, 'price': '101.6'})


# --- persistence (disposable schema) ---

@pytest.fixture
def cids(workbench_db):
    c = Candidate('trend_reclaim', 'buy', {'signal_date': T.isoformat()})
    return [repository.store_candidate(workbench_db, 'NVDA', T, c, run_id='r')['id']]


def test_decision_is_idempotent_per_request(workbench_db, cids):
    payload = decision_payload(cids)
    first = ledger.record_decision(workbench_db, payload, now=NOW)
    again = ledger.record_decision(workbench_db, payload, now=NOW + timedelta(minutes=1))
    assert first['status'] == 'created' and again['status'] == 'existing'
    assert again['record']['id'] == first['record']['id']
    assert first['record']['decided_at'] == NOW


def test_same_request_with_other_content_conflicts(workbench_db, cids):
    payload = decision_payload(cids)
    ledger.record_decision(workbench_db, payload, now=NOW)
    with pytest.raises(ledger.Conflict):
        ledger.record_decision(workbench_db, {**payload, 'reason': 'changed'}, now=NOW)


def test_second_decision_must_supersede_the_latest(workbench_db, cids):
    first = ledger.record_decision(workbench_db, decision_payload(cids), now=NOW)['record']
    with pytest.raises(ledger.Conflict):
        ledger.record_decision(workbench_db, decision_payload(cids, decision='reject', final_action='ignore'), now=NOW)
    fix = ledger.record_decision(workbench_db, decision_payload(
        cids, decision='reject', final_action='ignore', supersedes_id=str(first['id'])), now=NOW)
    assert fix['record']['supersedes_id'] == first['id']
    with pytest.raises(ledger.Conflict):  # stale: superseding a decision that is no longer the latest
        ledger.record_decision(workbench_db, decision_payload(cids, supersedes_id=str(first['id'])), now=NOW)


def test_decision_candidates_must_belong_to_the_unit(workbench_db, cids):
    with pytest.raises(ledger.LedgerError):
        ledger.record_decision(workbench_db, decision_payload([uuid.uuid4()]), now=NOW)
    with pytest.raises(ledger.LedgerError):
        ledger.record_decision(workbench_db, decision_payload(cids, ticker='MU'), now=NOW)


def test_trade_links_decision_and_is_idempotent(workbench_db, cids):
    decision = ledger.record_decision(workbench_db, decision_payload(cids), now=NOW)['record']
    payload = trade_payload(decision_id=str(decision['id']))
    first = ledger.record_trade(workbench_db, payload, now=NOW + timedelta(days=1))
    again = ledger.record_trade(workbench_db, payload, now=NOW + timedelta(days=1))
    assert first['status'] == 'created' and again['status'] == 'existing'
    assert first['record']['decision_id'] == decision['id']
    with pytest.raises(ledger.Conflict):
        ledger.record_trade(workbench_db, {**payload, 'quantity': '11'}, now=NOW + timedelta(days=1))


def test_trade_without_signal_is_allowed(workbench_db):
    out = ledger.record_trade(workbench_db, trade_payload(), now=NOW + timedelta(days=1))
    assert out['record']['decision_id'] is None


def test_trade_decision_must_match_ticker(workbench_db, cids):
    decision = ledger.record_decision(workbench_db, decision_payload(cids), now=NOW)['record']
    with pytest.raises(ledger.LedgerError):
        ledger.record_trade(workbench_db, trade_payload(ticker='MU', decision_id=str(decision['id'])),
                            now=NOW + timedelta(days=1))


def test_cannot_sell_more_than_held(workbench_db):
    later = NOW + timedelta(days=1)
    ledger.record_trade(workbench_db, trade_payload(quantity='5'), now=later)
    with pytest.raises(ledger.LedgerError):
        ledger.record_trade(workbench_db, trade_payload(side='sell', quantity='6',
                                                        executed_at='2026-10-23T15:00:00+00:00'), now=later)


def test_void_requires_reason_once_and_keeps_row(workbench_db):
    later = NOW + timedelta(days=1)
    t = ledger.record_trade(workbench_db, trade_payload(), now=later)['record']
    with pytest.raises(ledger.LedgerError):
        ledger.void_trade(workbench_db, t['id'], ' ', now=later)
    voided = ledger.void_trade(workbench_db, t['id'], '价格录错', now=later)
    assert voided['voided_at'] == later and voided['void_reason'] == '价格录错'
    with pytest.raises(ledger.Conflict):
        ledger.void_trade(workbench_db, t['id'], 'again', now=later)
    with pytest.raises(ledger.NotFound):
        ledger.void_trade(workbench_db, uuid.uuid4(), 'x', now=later)
    assert workbench_db.execute('SELECT count(*) FROM trades').fetchone() == (1,)


def test_void_refused_when_it_would_leave_a_sell_uncovered(workbench_db):
    later = NOW + timedelta(days=1)
    buy = ledger.record_trade(workbench_db, trade_payload(quantity='5'), now=later)['record']
    ledger.record_trade(workbench_db, trade_payload(side='sell', quantity='5',
                                                    executed_at='2026-10-23T15:00:00+00:00'), now=later)
    with pytest.raises(ledger.LedgerError):
        ledger.void_trade(workbench_db, buy['id'], '录错', now=later)


# --- plans linked to decisions (spec §5.3) ---

def rule_plan_row(conn, **overrides):
    plan = {'ticker': 'NVDA', 'signal_date': T, 'kind': 'rule', 'based_on_id': None, 'plan_version': 'plan-1',
            'ref_price': Decimal('100'), 'atr': Decimal('2'), 'entry_low': Decimal('99'),
            'entry_high': Decimal('101'), 'stop': Decimal('94'), 'target1': Decimal('108'),
            'trail_atr_multiple': Decimal('3'), 'valid_from': date(2026, 10, 23), 'valid_until': date(2026, 10, 27),
            'sizing': {'status': 'no_equity'}, 'status': 'ok', 'invalid_reasons': [], 'warnings': [],
            'inputs': {'bar_ids': [1]}, 'request_id': None, 'request_hash': None}
    plan.update(overrides)
    return repository.insert_plan(conn, plan)


def _unit_bar(conn):
    conn.execute("INSERT INTO price_bars (ticker, price_date, open, high, low, close, volume, adj_close, "
                 "revision, fetched_at) VALUES ('NVDA', %s, 100, 102, 99, 100, 1000, 100, 1, %s)", [T, NOW])


def own_levels(**overrides):
    levels = {'entry_low': '98.5', 'entry_high': '101.5', 'stop': '94', 'target1': '112'}
    levels.update(overrides)
    return levels


def test_accept_buy_requires_plan(workbench_db, cids):
    rule_plan_row(workbench_db)
    with pytest.raises(ledger.LedgerError):
        ledger.record_decision(workbench_db, decision_payload(cids), now=NOW)


def test_accept_with_wrong_plan_id_rejected(workbench_db, cids):
    plan = rule_plan_row(workbench_db)
    with pytest.raises(ledger.LedgerError):
        ledger.record_decision(workbench_db, decision_payload(cids, plan_id=str(uuid.uuid4())), now=NOW)
    out = ledger.record_decision(workbench_db, decision_payload(cids, plan_id=str(plan['id'])), now=NOW)
    assert out['record']['plan_id'] == plan['id']


def test_invalid_rule_plan_requires_own(workbench_db, cids):
    plan = rule_plan_row(workbench_db, status='invalid', invalid_reasons=['earnings_in_validity'])
    _unit_bar(workbench_db)
    with pytest.raises(ledger.LedgerError):
        ledger.record_decision(workbench_db, decision_payload(cids, plan_id=str(plan['id'])), now=NOW)
    out = ledger.record_decision(workbench_db, decision_payload(
        cids, own_plan={'request_id': str(uuid.uuid4()), **own_levels()}), now=NOW)
    assert out['record']['plan_id'] != plan['id']  # 指向新建的 own 计划


def test_own_plan_written_with_decision(workbench_db, cids):
    rule = rule_plan_row(workbench_db)
    _unit_bar(workbench_db)
    own_request = str(uuid.uuid4())
    out = ledger.record_decision(workbench_db, decision_payload(
        cids, own_plan={'request_id': own_request, **own_levels()}), now=NOW)
    plan = repository.plan_by_id(workbench_db, out['record']['plan_id'])
    assert plan['kind'] == 'own' and str(plan['request_id']) == own_request
    assert plan['based_on_id'] == rule['id']
    assert Decimal(plan['stop']) == Decimal('94')


def test_own_plan_replay_same_request(workbench_db, cids):
    rule_plan_row(workbench_db)
    _unit_bar(workbench_db)
    payload = decision_payload(cids, own_plan={'request_id': str(uuid.uuid4()), **own_levels()})
    first = ledger.record_decision(workbench_db, payload, now=NOW)
    again = ledger.record_decision(workbench_db, payload, now=NOW + timedelta(minutes=1))
    assert first['status'] == 'created' and again['status'] == 'existing'
    assert again['record']['id'] == first['record']['id']
    assert workbench_db.execute("SELECT count(*) FROM trade_plans WHERE kind = 'own'").fetchone()[0] == 1


def test_reject_with_plan_rejected(workbench_db, cids):
    rule_plan_row(workbench_db)
    with pytest.raises(ledger.LedgerError):
        ledger.record_decision(workbench_db, decision_payload(cids, decision='reject', final_action='ignore',
                                                              plan_id=str(uuid.uuid4())), now=NOW)
    with pytest.raises(ledger.LedgerError):
        ledger.record_decision(workbench_db, decision_payload(cids, decision='reject', final_action='ignore',
                                                              own_plan={'request_id': str(uuid.uuid4()),
                                                                        **own_levels()}), now=NOW)


def test_plan_id_must_belong_to_the_unit(workbench_db, cids):
    other = rule_plan_row(workbench_db, ticker='MU')
    with pytest.raises(ledger.LedgerError):
        ledger.record_decision(workbench_db, decision_payload(cids, plan_id=str(other['id'])), now=NOW)


def test_own_plan_gets_context(workbench_db, cids):
    rule_plan_row(workbench_db)
    _unit_bar(workbench_db)
    out = ledger.record_decision(workbench_db, decision_payload(
        cids, own_plan={'request_id': str(uuid.uuid4()), **own_levels()}), now=NOW)
    plan = repository.plan_by_id(workbench_db, out['record']['plan_id'])
    ctx = plan['inputs']['context']
    assert ctx['context_version'] == 'context-1'
    assert ctx['pool_tier'] == 'unknown'      # no pool_tiers rows in this schema
    assert ctx['regime'] is None and ctx['sector'] is None
    assert 'regime_unavailable' in plan['warnings']
