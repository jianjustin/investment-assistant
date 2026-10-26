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


def test_tally_skip():
    tally = collect.Tally('fred', 'workbench')
    tally.skip('FRED_API_KEY 未配置')
    row = _row(tally)
    assert row['status'] == 'skipped'
    assert row['detail']['reason'] == 'FRED_API_KEY 未配置'


def test_write_runs_never_raises(monkeypatch):
    def connection():
        raise RuntimeError('boom')

    monkeypatch.setattr(service, 'connection', connection)
    out = collect.write_runs([_row(collect.Tally('bars', 'workbench', ('A',)))])
    assert out == {'written': 0, 'error': 'boom'}
