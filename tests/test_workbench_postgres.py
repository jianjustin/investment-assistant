"""Real constraint behavior for the US workbench schema; disposable schema only."""
import uuid
from datetime import UTC, date, datetime

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


def _decision(conn, reason='trend intact'):
    return conn.execute(
        'INSERT INTO signal_decisions (request_id, request_hash, ticker, signal_date, candidate_ids, '
        "proposed_action, final_action, decision, reason) VALUES (%s, 'h', 'NVDA', '2026-10-21', "
        "'{}', 'buy', 'buy', 'accept', %s) RETURNING id", [uuid.uuid4(), reason]).fetchone()[0]


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
