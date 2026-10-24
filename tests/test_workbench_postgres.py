"""Real constraint behavior for the US workbench schema; disposable schema only."""
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

NOW = datetime(2026, 10, 22, 22, 30, tzinfo=UTC)


def _bar(conn, revision=1, **overrides):
    values = {'ticker': 'NVDA', 'price_date': date(2026, 10, 21), 'open': 100, 'high': 105, 'low': 99,
              'close': 104, 'volume': 1000, 'adj_close': 104, 'revision': revision, 'fetched_at': NOW}
    values.update(overrides)
    cols = ', '.join(values)
    marks = ', '.join(['%s'] * len(values))
    conn.execute(f'INSERT INTO price_bars ({cols}) VALUES ({marks})', list(values.values()))


def test_price_bar_revision_is_unique(workbench_db):
    import psycopg
    _bar(workbench_db)
    _bar(workbench_db, revision=2, close=103)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _bar(workbench_db, revision=2)


def test_split_factor_must_be_positive(workbench_db):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        _bar(workbench_db, split_factor=0)


def test_candidate_action_and_uniqueness(workbench_db):
    import psycopg
    sql = ('INSERT INTO signal_candidates (ticker, signal_date, action, rule_id, rule_version, inputs) '
           "VALUES ('NVDA', '2026-10-21', %s, 'trend_reclaim', '1', '{}')")
    workbench_db.execute(sql, ['buy'])
    with pytest.raises(psycopg.errors.UniqueViolation):
        workbench_db.execute(sql, ['buy'])


def test_candidate_rejects_unknown_action(workbench_db):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        workbench_db.execute("INSERT INTO signal_candidates (ticker, signal_date, action, rule_id, rule_version, inputs) "
                             "VALUES ('NVDA', '2026-10-21', 'short', 'x', '1', '{}')")


def _decision(conn, reason='trend intact', plan_id=None):
    return conn.execute(
        'INSERT INTO signal_decisions (request_id, request_hash, ticker, signal_date, candidate_ids, '
        "proposed_action, final_action, decision, reason, plan_id) VALUES (%s, 'h', 'NVDA', '2026-10-21', "
        "'{}', 'buy', 'buy', 'accept', %s, %s) RETURNING id", [uuid.uuid4(), reason, plan_id]).fetchone()[0]


def test_decision_requires_reason(workbench_db):
    import psycopg
    assert _decision(workbench_db)
    with pytest.raises(psycopg.errors.CheckViolation):
        _decision(workbench_db, reason='   ')


def test_trade_constraints(workbench_db):
    import psycopg
    decision_id = _decision(workbench_db)
    sql = ('INSERT INTO trades (request_id, request_hash, ticker, side, quantity, price, executed_at, decision_id) '
           "VALUES (%s, 'h', 'NVDA', 'buy', %s, 101.5, %s, %s)")
    workbench_db.execute(sql, [uuid.uuid4(), 10, NOW, decision_id])
    with pytest.raises(psycopg.errors.CheckViolation):
        workbench_db.execute(sql, [uuid.uuid4(), 0, NOW, decision_id])


def test_trade_void_needs_reason(workbench_db):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        workbench_db.execute(
            'INSERT INTO trades (request_id, request_hash, ticker, side, quantity, price, executed_at, voided_at) '
            "VALUES (%s, 'h', 'NVDA', 'sell', 1, 1, %s, %s)", [uuid.uuid4(), NOW, NOW])


def test_weekly_review_starts_on_monday(workbench_db):
    import psycopg
    sql = "INSERT INTO weekly_reviews (week_start, calc_version, stats) VALUES (%s, 'review-1', '{}')"
    workbench_db.execute(sql, [date(2026, 10, 19)])
    with pytest.raises(psycopg.errors.CheckViolation):
        workbench_db.execute(sql, [date(2026, 10, 20)])


def test_filings_columns_and_scheduled_job(workbench_db):
    workbench_db.execute(
        "INSERT INTO filings (ticker, form, filing_date, accession_number, primary_document, file_path, "
        "accepted_at, items) VALUES ('NVDA', '8-K', '2026-08-27', '0001045810-26-000001', 'a.htm', 'x', %s, %s)",
        [NOW, ['2.02', '9.01']])
    row = workbench_db.execute("SELECT time_local, weekday_mask, timezone FROM scheduled_jobs "
                               "WHERE name = 'workbench'").fetchone()
    assert row == ('06:30', '2-6', 'Asia/Shanghai')


def test_upsert_filing_keeps_first_known_acceptance(workbench_db):
    from investment_assistant import db
    args = dict(ticker='NVDA', form='8-K', filing_date=date(2026, 8, 27),
                accession_number='0001045810-26-000010', primary_document='k.htm', file_path='/x')
    db.upsert_filing(workbench_db, **args)
    db.upsert_filing(workbench_db, **args, accepted_at='2026-08-27T16:20:31-04:00', items=['2.02'])
    db.upsert_filing(workbench_db, **args, accepted_at='2026-08-28T09:00:00-04:00', items=['8.01'])
    accepted, items = workbench_db.execute('SELECT accepted_at, items FROM filings').fetchone()
    assert accepted == datetime(2026, 8, 27, 20, 20, 31, tzinfo=UTC)
    assert items == ['2.02']


def _insert(conn, table, values):
    import json
    cols, marks, params = [], [], []
    for key, value in values.items():
        cols.append(key)
        if key in ('sizing', 'inputs'):
            marks.append('%s::jsonb')
            params.append(json.dumps(value))
        else:
            marks.append('%s')
            params.append(value)
    return conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(marks)}) RETURNING id",
                        params).fetchone()[0]


def _plan(conn, kind='rule', **overrides):
    values = {'ticker': 'NVDA', 'signal_date': date(2026, 10, 21), 'kind': kind, 'plan_version': 'plan-1',
              'ref_price': 100, 'atr': 2, 'entry_low': 99, 'entry_high': 101, 'stop': 96, 'target1': 108,
              'valid_from': date(2026, 10, 22), 'valid_until': date(2026, 10, 28),
              'sizing': {}, 'status': 'ok', 'invalid_reasons': [], 'warnings': [], 'inputs': {}}
    if kind == 'own':
        values['request_id'] = overrides.pop('request_id', uuid.uuid4())
        values['request_hash'] = overrides.pop('request_hash', 'h')
    values.update(overrides)
    return _insert(conn, 'trade_plans', values)


def _flow(conn, **overrides):
    values = {'request_id': uuid.uuid4(), 'request_hash': 'h',
              'flow_date': date(2026, 10, 21), 'amount': 1000, 'note': None, 'recorded_at': NOW}
    values.update(overrides)
    return _insert(conn, 'cash_flows', values)


def _snapshot(conn, **overrides):
    values = {'request_id': uuid.uuid4(), 'request_hash': 'h', 'as_of': date(2026, 10, 21),
              'equity': 100000, 'note': None, 'recorded_at': NOW}
    values.update(overrides)
    return _insert(conn, 'account_snapshots', values)


def test_rule_plan_unique_per_version(workbench_db):
    import psycopg
    _plan(workbench_db)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _plan(workbench_db)
    workbench_db.rollback()
    _plan(workbench_db, kind='own')  # own 计划不受 (ticker, signal_date, plan_version) 唯一约束


def test_plan_levels_ordered(workbench_db):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        _plan(workbench_db, stop=99)  # stop >= entry_low


def test_cash_flow_nonzero_and_void_pair(workbench_db):
    import psycopg
    _flow(workbench_db)
    with pytest.raises(psycopg.errors.CheckViolation):
        _flow(workbench_db, amount=0)
    workbench_db.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        _flow(workbench_db, voided_at=NOW)  # voided_at 必须与 void_reason 成对


def test_snapshot_equity_positive(workbench_db):
    import psycopg
    _snapshot(workbench_db)
    with pytest.raises(psycopg.errors.CheckViolation):
        _snapshot(workbench_db, equity=0)


def test_decision_plan_fk(workbench_db):
    import psycopg
    plan_id = _plan(workbench_db)
    assert _decision(workbench_db, plan_id=plan_id)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _decision(workbench_db, plan_id=uuid.uuid4())


def test_store_earnings_dedupes(workbench_db):
    from investment_assistant.workbench import repository
    row_a = {'status': 'known', 'earnings_date': date(2026, 11, 19)}
    out1 = repository.store_earnings(workbench_db, 'NVDA', row_a, now=NOW)
    out2 = repository.store_earnings(workbench_db, 'NVDA', row_a, now=NOW + timedelta(hours=1))
    assert out1['status'] == 'inserted'
    assert out2['status'] == 'unchanged'
    assert out2['id'] == out1['id']
    assert workbench_db.execute('SELECT count(*) FROM earnings_dates').fetchone()[0] == 1
    out3 = repository.store_earnings(workbench_db, 'NVDA',
                                     {'status': 'known', 'earnings_date': date(2027, 2, 18)},
                                     now=NOW + timedelta(hours=2))
    assert out3['status'] == 'inserted'
    assert workbench_db.execute('SELECT count(*) FROM earnings_dates').fetchone()[0] == 2


def test_latest_earnings_respects_cutoff(workbench_db):
    from investment_assistant.workbench import repository
    repository.store_earnings(workbench_db, 'NVDA', {'status': 'known', 'earnings_date': date(2026, 11, 19)},
                              now=NOW)
    repository.store_earnings(workbench_db, 'NVDA', {'status': 'known', 'earnings_date': date(2027, 2, 18)},
                              now=NOW + timedelta(hours=1))
    row = repository.latest_earnings(workbench_db, 'NVDA', cutoff_at=NOW + timedelta(minutes=30))
    assert row['earnings_date'] == date(2026, 11, 19)
    assert repository.latest_earnings(workbench_db, 'NVDA', cutoff_at=NOW + timedelta(hours=2))[
        'earnings_date'] == date(2027, 2, 18)
    assert repository.latest_earnings(workbench_db, 'MU', cutoff_at=NOW) is None


def _plan_row(**overrides):
    values = {'ticker': 'NVDA', 'signal_date': date(2026, 10, 21), 'kind': 'rule', 'based_on_id': None,
              'plan_version': 'plan-1', 'ref_price': 100, 'atr': 2, 'entry_low': 99, 'entry_high': 101,
              'stop': 96, 'target1': 108, 'trail_atr_multiple': 3, 'valid_from': date(2026, 10, 22),
              'valid_until': date(2026, 10, 28), 'sizing': {'status': 'no_equity', 'per_share_risk': '4'},
              'status': 'ok', 'invalid_reasons': [], 'warnings': [], 'inputs': {'bar_ids': [1, 2]},
              'request_id': None, 'request_hash': None}
    values.update(overrides)
    return values


def test_store_plan_rule_dedup_conflict_and_reads(workbench_db):
    from investment_assistant.workbench import repository
    plan = _plan_row()
    out1 = repository.store_plan(workbench_db, plan)
    assert out1['status'] == 'inserted'
    assert repository.store_plan(workbench_db, _plan_row())['status'] == 'existing'
    out3 = repository.store_plan(workbench_db, _plan_row(entry_low=98))
    assert out3['status'] == 'conflict' and out3['record']['id'] == out1['record']['id']
    assert workbench_db.execute('SELECT count(*) FROM trade_plans').fetchone()[0] == 1
    head = repository.rule_plan(workbench_db, 'NVDA', date(2026, 10, 21))
    assert head['id'] == out1['record']['id'] and head['stop'] == 96
    assert repository.rule_plan(workbench_db, 'NVDA', date(2026, 10, 21), plan_version='plan-2') is None
    assert repository.plan_by_id(workbench_db, head['id'])['target1'] == 108
    assert len(repository.plans_since(workbench_db, date(2026, 10, 1))) == 1
    assert repository.plans_since(workbench_db, date(2026, 11, 1)) == []


def test_old_weekly_snapshot_unchanged(workbench_db, monkeypatch):
    from contextlib import contextmanager

    from investment_assistant.workbench import repository, review, service

    @contextmanager
    def connection():
        yield workbench_db

    monkeypatch.setattr(service, 'connection', connection)
    old = repository.insert_weekly_review(workbench_db, date(2026, 10, 19), 'review-1', {'units': 3}, '',
                                          None)
    assert old['calc_version'] == 'review-1'
    assert repository.weekly_head(workbench_db, date(2026, 10, 19))['stats'] == {'units': 3}


def test_monthly_frozen_and_supersede(workbench_db, monkeypatch):
    import uuid as _uuid
    from contextlib import contextmanager
    from datetime import UTC, datetime

    from investment_assistant.workbench import ledger, service

    @contextmanager
    def connection():
        yield workbench_db

    monkeypatch.setattr(service, 'connection', connection)
    now = datetime(2026, 11, 1, 22, 30, tzinfo=UTC)
    first = service.generate_monthly(date(2026, 10, 1), notes='初版', now=now)
    assert first['stats']['calc_version'] == 'monthly-1'
    assert first['stats']['return']['status'] == 'missing_snapshot'
    with pytest.raises(ledger.Conflict):
        service.generate_monthly(date(2026, 10, 1), notes='重复生成', now=now)
    fix = service.generate_monthly(date(2026, 10, 1), notes='更正', supersedes_id=first['id'], now=now)
    assert fix['supersedes_id'] == first['id'] and fix['notes'] == '更正'
    listed = service.list_monthly()
    assert [r['id'] for r in listed] == [fix['id']]
    assert workbench_db.execute('SELECT count(*) FROM monthly_reviews').fetchone()[0] == 2


def test_monthly_ignores_stop_events_outside_the_month(workbench_db, monkeypatch):
    from contextlib import contextmanager
    from datetime import UTC, date, datetime
    from decimal import Decimal as D

    from investment_assistant.workbench import repository, rules, service

    @contextmanager
    def connection():
        yield workbench_db

    monkeypatch.setattr(service, 'connection', connection)
    unit_day = date(2026, 10, 21)
    plan = repository.insert_plan(workbench_db, {
        'ticker': 'NVDA', 'signal_date': unit_day, 'kind': 'rule', 'based_on_id': None, 'plan_version': 'plan-1',
        'ref_price': D('100'), 'atr': D('2'), 'entry_low': D('99'), 'entry_high': D('101'), 'stop': D('94'),
        'target1': D('108'), 'trail_atr_multiple': D('3'), 'valid_from': date(2026, 10, 22),
        'valid_until': date(2026, 10, 27), 'sizing': {}, 'status': 'ok', 'invalid_reasons': [], 'warnings': [],
        'inputs': {}, 'request_id': None, 'request_hash': None})
    decision = repository.insert_decision(workbench_db, {
        'request_id': uuid.uuid4(), 'ticker': 'NVDA', 'signal_date': unit_day,
        'candidate_ids': [], 'brief_id': None, 'proposed_action': 'buy', 'final_action': 'buy',
        'decision': 'accept', 'reason': '合成', 'supersedes_id': None, 'plan_id': plan['id']},
        'h', decided_at=datetime(2026, 10, 22, tzinfo=UTC))
    repository.insert_trade(workbench_db, {
        'request_id': uuid.uuid4(), 'ticker': 'NVDA', 'side': 'buy', 'quantity': D('10'), 'price': D('100'),
        'fee': D('0'), 'executed_at': datetime(2026, 10, 22, 15, tzinfo=UTC), 'decision_id': decision['id'],
        'note': None}, 'h', recorded_at=datetime(2026, 10, 22, 16, tzinfo=UTC))
    repository.store_candidate(workbench_db, 'NVDA', date(2026, 11, 10),
                               rules.Candidate('plan_stop', 'sell', {'signal_date': '2026-11-10'}), run_id='r')

    review = service.generate_monthly(date(2026, 10, 1), now=datetime(2026, 11, 20, 22, 30, tzinfo=UTC))
    assert review['stats']['discipline']['counts']['held_loser'] == 0  # 11 月的止损事件不算 10 月


def test_pool_tier_check(workbench_db):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        workbench_db.execute("INSERT INTO pool_tiers (ticker, tier, effective_session, recorded_at) "
                             "VALUES ('NVDA', 'x', '2026-10-21', %s)", [NOW])


def test_regime_unique_per_session_version(workbench_db):
    import psycopg
    sql = ("INSERT INTO market_regimes (session, calc_version, label, breadth, sectors, macro, inputs) "
           "VALUES ('2026-10-21', 'regime-1', 'neutral', '{}', '{}', '{}', '{}')")
    workbench_db.execute(sql)
    with pytest.raises(psycopg.errors.UniqueViolation):
        workbench_db.execute(sql)


def test_regime_label_check(workbench_db):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        workbench_db.execute("INSERT INTO market_regimes (session, calc_version, label, breadth, sectors, macro, inputs) "
                             "VALUES ('2026-10-21', 'regime-1', 'risky', '{}', '{}', '{}', '{}')")


def test_macro_value_required(workbench_db):
    import psycopg
    with pytest.raises(psycopg.errors.NotNullViolation):
        workbench_db.execute("INSERT INTO macro_observations (series_id, obs_date, value, fetched_at) "
                             "VALUES ('BAMLH0A0HYM2', '2026-10-21', NULL, %s)", [NOW])


def test_missing_tables_lists_018(workbench_db):
    from investment_assistant.workbench import repository
    assert repository.missing_tables(workbench_db) == []
    workbench_db.execute('DROP TABLE market_regimes')
    assert 'market_regimes' in repository.missing_tables(workbench_db)
