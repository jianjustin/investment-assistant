"""The ``daily`` task shell (v2.8 §4.7, §5.9): one ``job_reports`` row per execution, the status mapping, the
``daily:run`` lock, the node table CLI and the manual-only ``sec_backfill``. SQL tests on the disposable database."""
from datetime import date

import pytest

from _daily_db import (NotifyCfg, clock, daily_config, daily_db, job_reports, notices, shared_saver)   # noqa: F401
from test_daily_workflow import RUN_ID, effective, fake_sec, flaky, no_fetch_backoff, rows, world   # noqa: F401
from test_workbench_service import NOW, SESSION, seed_watchlist

from investment_assistant.tasks import daily, filings
from investment_assistant.workbench import workflow


def run_daily(clock, factory=None, **kwargs):
    kwargs.setdefault('trigger_source', 'manual')
    return daily.run(daily_config(), now=NOW, deps=world(clk=clock), run_id=RUN_ID,
                     checkpointer_factory=factory or shared_saver()[1], sleep=clock.sleep, notify_cfg=NotifyCfg(),
                     **kwargs)


def test_job_report_row_per_execution(daily_db, clock, notices, job_reports, monkeypatch):
    seed_watchlist(daily_db, [('NVDA', ['core'])])
    flaky('regime', monkeypatch, fail_times=2)
    saver, factory = shared_saver()
    run_daily(clock, factory)
    assert len(job_reports.rows()) == 1
    daily.resume(RUN_ID, 'regime', now=NOW, deps=world(clk=clock), config=daily_config(),
                 checkpointer_factory=factory, sleep=clock.sleep, notify_cfg=NotifyCfg())
    reports = job_reports.rows()
    assert [(r['task'], r['run_id']) for r in reports] == [('daily', RUN_ID)] * 2
    assert [r['trigger_source'] for r in reports] == ['manual', 'resume']
    assert all(r['target_start_date'] == SESSION for r in reports)
    assert reports[0]['summary']['graph_version'] == 'daily-1' and reports[0]['summary']['failed_node'] == 'regime'
    assert reports[0]['summary']['stage_status']['written'] == 10


def test_status_mapping_success_degraded_error(daily_db, clock, notices, job_reports, monkeypatch):
    assert daily.JOB_STATUS == {'success': 'success', 'degraded': 'degraded', 'failed': 'error'}
    for run_status, expected in (('success', 'success'), ('degraded', 'degraded'), ('failed', 'error')):
        out = daily._report({'run_id': f'daily-2026102200000{len(job_reports.rows())}-aaaaaaa{len(job_reports.rows())}',
                             'status': run_status, 'summary': {'run_status': run_status}, 'session': '2026-10-22',
                             'failed_node': 'collect' if run_status == 'failed' else None, 'failure': None},
                            started_at=clock.wall(), trigger_source='manual', config=daily_config(),
                            notify_cfg=NotifyCfg())
        assert out['status'] == expected
    assert [r['status'] for r in job_reports.rows()] == ['success', 'degraded', 'error']
    assert len([t for t in notices.titles('workbench') if '每日工作流失败' in t]) == 1       # only the failed one


def test_a_real_degraded_run_maps_to_degraded(daily_db, clock, notices, job_reports):
    seed_watchlist(daily_db, [('NVDA', ['core'])])
    out = run_daily(clock)
    assert out['run_status'] == 'degraded' and out['status'] == 'degraded' and notices.calls == []   # degraded: no notice


def test_daily_running_lock(daily_db, clock, notices, job_reports):
    seed_watchlist(daily_db, [('NVDA', ['core'])])
    with daily.exclusive():
        with pytest.raises(daily.DailyBusy):
            run_daily(clock, trigger_source='manual')
        with pytest.raises(daily.DailyBusy):
            daily.resume(RUN_ID, 'collect', now=NOW, config=daily_config())
        out = run_daily(clock, trigger_source='scheduled')                      # a scheduled tick records and goes on
    assert out['status'] == 'error' and out['summary']['error'] == 'daily_running'
    assert [(r['status'], r['summary']['error']) for r in job_reports.rows()] == [('error', 'daily_running')]
    assert daily_db.execute('SELECT count(*) FROM stage_runs').fetchone()[0] == 0
    assert notices.calls == []


def test_checkpoint_tables_missing_refuses(daily_db, clock, notices, job_reports):
    import psycopg.errors
    from contextlib import contextmanager

    @contextmanager
    def no_tables():
        raise psycopg.errors.UndefinedTable('relation "checkpoints" does not exist')
        yield

    seed_watchlist(daily_db, [('NVDA', ['core'])])
    out = run_daily(clock, no_tables)
    assert out['status'] == 'error' and out['summary']['error'] == 'checkpoint_unavailable'


def test_cli_show_has_no_raw_summary(daily_db, clock, notices, job_reports, capsys):
    seed_watchlist(daily_db, [('NVDA', ['core'])])
    run_daily(clock)
    assert daily.main(['show', '--run-id', RUN_ID]) == 0
    out = capsys.readouterr().out
    for node in workflow.NODES:
        assert node in out
    assert 'attempt 1' in out and '失败目标' in out
    assert '{' not in out and 'cutoff_at' not in out and 'summary' not in out          # the node table, not the raw JSON
    assert daily.main(['show', '--run-id', 'daily-20260101000000-00000000']) == 2


def test_cli_resume_reports_rejections(daily_db, clock, notices, capsys):
    assert daily.main(['resume', '--run-id', 'daily-20260101000000-00000000', '--node', 'collect']) == 2
    assert capsys.readouterr().err


def test_sec_backfill_job_report_task(daily_db, clock, notices, job_reports, fake_sec):
    fake_sec.result = {'tickers': ['NVDA'], 'filings': [], 'errors': {}, 'downloaded_count': 0, 'event_ids': []}
    out = filings.backfill(daily_config(), start_date=date(2026, 10, 1), end_date=date(2026, 10, 5))
    assert out['task'] == 'sec_backfill' and out['status'] == 'success'
    assert [(r['task'], r['trigger_source']) for r in job_reports.rows()] == [('sec_backfill', 'manual')]
    assert job_reports.rows()[0]['target_start_date'] == date(2026, 10, 1)
    fetch = daily_db.execute("SELECT job, trigger, run_id, family FROM data_fetch_runs").fetchall()
    assert fetch == [('sec_backfill', 'manual_family', out['run_id'], 'sec_filings')]
    assert daily_db.execute('SELECT count(*) FROM stage_runs').fetchone()[0] == 0           # outside the graph
    with daily.exclusive():                                                                  # and under the daily lock
        with pytest.raises(daily.DailyBusy):
            filings.backfill(daily_config(), start_date=date(2026, 10, 1))


from langgraph.checkpoint.memory import InMemorySaver


class _BrokenSaver(InMemorySaver):
    """An in-memory saver whose Nth checkpoint write fails like a dropped database connection."""

    def __init__(self, fail_on):
        super().__init__()
        self.fail_on, self.puts = fail_on, 0

    def put(self, *args, **kwargs):
        import psycopg

        self.puts += 1
        if self.puts == self.fail_on:
            raise psycopg.OperationalError('server closed the connection unexpectedly')
        return super().put(*args, **kwargs)


def test_other_exceptions_still_get_a_report_rows_and_one_notice(daily_db, clock, notices, job_reports):
    from contextlib import nullcontext

    seed_watchlist(daily_db, [('NVDA', ['core'])])
    saver = _BrokenSaver(fail_on=4)                                   # after a few nodes the connection drops
    out = run_daily(clock, lambda: nullcontext(saver))
    assert out['status'] == 'error' and 'aborted' in out['summary']['error'] and 'closed the connection' in out['summary']['error']
    assert [r['status'] for r in job_reports.rows()] == ['error']                       # the execution has its row
    eff = workflow.effective_rows(rows(daily_db))
    assert list(eff) == list(workflow.NODES)                                              # still ten effective rows
    assert [n for n in workflow.NODES if eff[n]['status'] == 'failed'] and eff['retro']['reason'] == 'upstream_failed'
    assert len([t for t in notices.titles('workbench') if '每日工作流失败' in t]) == 1


def test_a_failure_before_the_graph_starts_is_reported_too(daily_db, clock, notices, job_reports, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('config unreadable')

    monkeypatch.setattr(workflow, '_make_context', boom)
    out = run_daily(clock)
    assert out['status'] == 'error' and out['summary']['error'] == 'aborted: config unreadable'
    assert [r['status'] for r in job_reports.rows()] == ['error']
    assert len(notices.titles('workbench')) == 1 and daily_db.execute('SELECT count(*) FROM stage_runs').fetchone()[0] == 0


def test_resume_aborting_outside_a_node_is_reported(daily_db, clock, notices, job_reports, monkeypatch):
    from contextlib import nullcontext

    seed_watchlist(daily_db, [('NVDA', ['core'])])
    flaky('regime', monkeypatch, fail_times=2)
    saver = _BrokenSaver(fail_on=10 ** 9)
    run_daily(clock, lambda: nullcontext(saver))
    saver.fail_on = saver.puts + 2
    out = daily.resume(RUN_ID, 'regime', now=NOW, deps=world(clk=clock), config=daily_config(),
                       checkpointer_factory=lambda: nullcontext(saver), sleep=clock.sleep, notify_cfg=NotifyCfg())
    assert out['status'] == 'error' and 'aborted' in out['summary']['error']
    assert [r['trigger_source'] for r in job_reports.rows()] == ['manual', 'resume']
    assert len([t for t in notices.titles('workbench') if '每日工作流失败' in t]) == 2     # one per failed execution


def test_failure_notice_names_the_booked_failed_stage(daily_db, clock, notices, job_reports, monkeypatch):
    """M1: a stage that books ``failed`` without stopping the chain (retro cards) still names itself in the notice."""
    from investment_assistant.workbench import retro_cards

    def boom(*args, **kwargs):
        raise RuntimeError('retro exploded')

    monkeypatch.setattr(retro_cards, 'run_stage', boom)
    seed_watchlist(daily_db, [('NVDA', ['core'])])
    out = run_daily(clock, trigger_source='scheduled')
    assert out['status'] == 'error' and out['summary']['failed_node'] == 'retro'
    [notice] = [n for t, items in notices.calls if t == 'workbench' for n in items if '每日工作流失败' in n.title]
    fields = {f.name: f.value for f in notice.fields}
    assert fields['失败节点'] == '复盘' and 'retro exploded' in fields['原因'] and fields['未执行'] == '其后 0 个节点'


def test_is_running_only_looks_at_the_lock(daily_db):
    assert daily.is_running() is False
    with daily.exclusive():
        assert daily.is_running() is True
        assert daily.is_running() is True                         # probing never takes or releases it
    assert daily.is_running() is False
    with daily.exclusive():                                       # and a probe leaves nothing behind
        pass
