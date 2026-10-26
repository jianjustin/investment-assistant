"""Offline tests for collect.py's tally and fetch-run writing (v2.3 Task 5, design §6.2)."""
from datetime import UTC, date, datetime

from investment_assistant.workbench import collect, service

SESSION = date(2026, 10, 22)
NOW = datetime(2026, 10, 22, 22, 30, tzinfo=UTC)


def _row(tally, **overrides):
    kwargs = dict(trigger='scheduled', run_id=None, session=SESSION, started_at=NOW, finished_at=NOW)
    kwargs.update(overrides)
    return tally.row(**kwargs)


def test_tally_last_outcome_wins_and_row_shape():
    tally = collect.Tally('bars', 'workbench', ('A', 'B', 'C'))
    tally.fail('B', 'x')
    tally.ok('B')
    tally.fail('C', 'y')
    tally.ok('A')
    row = _row(tally)
    assert row['status'] == 'partial'
    assert row['target_count'] == 3 and row['ok_count'] == 2
    assert row['failures'] == [{'target': 'C', 'reason': 'y'}]
    assert row['family'] == 'bars' and row['job'] == 'workbench'
    assert row['scope'] == 'family' and row['ticker'] is None
    assert 'failed_targets' not in row['detail']


def test_tally_skip():
    tally = collect.Tally('fred', 'workbench')
    tally.skip('FRED_API_KEY 未配置')
    row = _row(tally)
    assert row['status'] == 'skipped'
    assert row['detail']['reason'] == 'FRED_API_KEY 未配置'


def test_tally_wildcard_is_not_a_target():
    """'*' is the whole-call failure sentinel: the denominator stays the real
    target set frozen beforehand, no N+1th target appears (I04)."""
    tally = collect.Tally('sec_filings', 'workbench', ('MU', 'NVDA'))
    tally.ok('MU')
    tally.fail('*', 'edgar down')
    row = _row(tally)
    assert row['status'] == 'partial'                       # NVDA never completed collection
    assert row['target_count'] == 2 and row['ok_count'] == 1
    assert row['failures'] == [{'target': '*', 'reason': 'edgar down'}]
    assert row['detail']['failed_targets'] == ['MU', 'NVDA']   # I05: the call's own scope


def test_tally_whole_call_failure_all_targets_failed():
    tally = collect.Tally('sec_filings', 'workbench', ('MU', 'NVDA'))
    tally.fail('*', 'edgar down')
    row = _row(tally)
    assert row['status'] == 'failed'
    assert row['target_count'] == 2 and row['ok_count'] == 0
    assert row['failures'] == [{'target': '*', 'reason': 'edgar down'}]


def test_tally_whole_call_failure_without_targets_is_failed_not_success():
    """Empty real targets plus a call failure must not be a 0==0 success (I04)."""
    tally = collect.Tally('sec_filings', 'workbench')
    tally.fail('*', 'benchmark missing')
    row = _row(tally)
    assert row['status'] == 'failed'
    assert row['target_count'] == 0 and row['ok_count'] == 0
    assert row['failures'] == [{'target': '*', 'reason': 'benchmark missing'}]


def test_write_runs_never_raises(monkeypatch):
    def connection():
        raise RuntimeError('boom')

    monkeypatch.setattr(service, 'connection', connection)
    out = collect.write_runs([_row(collect.Tally('bars', 'workbench', ('A',)))])
    assert out == {'written': 0, 'error': 'boom'}


def test_wall_clock_is_real_utc_now():
    from datetime import UTC

    before = datetime.now(UTC)
    got = collect.wall_clock()
    after = datetime.now(UTC)
    assert before <= got <= after
