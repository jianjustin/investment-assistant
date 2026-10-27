"""run_batch 的七个阶段记账（v2.4 §4）：计数与四族 fetch 行、筛选与区制的产出引用对得上；
非交易日六个阶段整段跳过；信号、计划、Agent、推送的计数与产出引用；每次运行恰好 7 行。
复用 characterization 的假 fetcher，recorder 用默认写入，行落在一次性库的 stage_runs 里再读回。"""
from datetime import UTC, date, datetime, timedelta

import pytest

from test_workbench_batch_characterization import UNIVERSE, batch_deps
from test_workbench_service import (NOW, SESSION, Sources, _agent_settings, _ok_responses, _task_run,
                                    agent_deps, db, deps, seed_watchlist)
from investment_assistant.workbench import regime as regime_module
from investment_assistant.workbench import repository, service
from investment_assistant.workbench import stages as stages_module
from investment_assistant.workbench import universe as universe_module

SATURDAY = datetime(2026, 10, 24, 22, 30, tzinfo=UTC)   # 纽约周六，非交易日


def _recorder(run_id: str, *, trigger: str = 'scheduled') -> stages_module.StageRecorder:
    return stages_module.StageRecorder(run_id, trigger, SESSION, wall_now=lambda: NOW)


def _stage(db, run_id: str, stage_id: str) -> dict:
    rows = [row for row in repository.stage_runs_for_run(db, run_id) if row['stage'] == stage_id]
    assert len(rows) == 1
    return rows[0]


def test_collect_counts_match_fetch_runs(db):
    """collect 的计数等于本次四族 data_fetch_runs 之和；失败与降级挨着采集记。"""
    summary = service.run_batch(tickers=['NVDA', 'MU'], now=NOW,
                                deps=batch_deps(fail={'MU'}, fail_news=()),
                                record_trigger='scheduled', run_id='run-collect',
                                stages=_recorder('run-collect'))
    fam = dict(db.execute("SELECT family, id FROM data_fetch_runs "
                          "WHERE run_id = 'run-collect'").fetchall())
    assert set(fam) == {'bars', 'news', 'sec_filings', 'fred'}
    totals = db.execute("SELECT sum(target_count), sum(ok_count) FROM data_fetch_runs "
                        "WHERE run_id = 'run-collect'").fetchone()
    row = _stage(db, 'run-collect', 'collect')
    assert row['run_id'] == 'run-collect' and row['session'] == SESSION
    assert row['input_count'] == totals[0] and row['output_count'] == totals[1]
    assert row['outputs']['data_fetch_runs'] == [fam[f] for f in
                                                 ('bars', 'news', 'sec_filings', 'fred')]
    assert row['status'] == 'partial'
    assert {'target': 'bars:MU', 'reason': 'provider down'} in row['failures']
    assert {'target': 'sec_filings:*', 'reason': 'edgar down'} in row['failures']
    assert any(d['kind'] == 'fred_not_configured' for d in row['degradations'])
    assert row['detail']['earnings'] == {'targets': 2, 'ok': 2, 'failed': 0}


def test_screen_stage(db):
    seed_watchlist(db, [('AAA', ['core']), ('BBB', []), ('CCC', [])])
    summary = service.run_batch(now=NOW, deps=batch_deps(), stages=_recorder('run-screen'))
    row = _stage(db, 'run-screen', 'screen')
    assert row['status'] == 'success'
    assert row['input_count'] == len(UNIVERSE)                     # 范围成员数
    assert row['output_count'] == len(summary['screen']['selected'])
    assert row['outputs']['screen_run_id'] == db.execute(
        'SELECT id FROM screen_runs WHERE session = %s', [SESSION]).fetchone()[0]

    service.run_batch(tickers=['NVDA'], now=NOW, deps=batch_deps(), stages=_recorder('run-explicit'))
    row = _stage(db, 'run-explicit', 'screen')
    assert row['status'] == 'skipped' and row['reason'] == 'explicit_pool'

    broken = batch_deps()
    broken.universe = None

    def boom():
        raise universe_module.UniverseError('文件不可读')

    broken.universe_loader = boom
    service.run_batch(now=NOW, deps=broken, stages=_recorder('run-nouniverse'))
    row = _stage(db, 'run-nouniverse', 'screen')
    assert row['status'] == 'degraded'
    assert any(d['kind'] == 'universe_load_failed' for d in row['degradations'])


def test_regime_stage(db):
    seed_watchlist(db, [('AAA', ['core']), ('BBB', []), ('CCC', [])])
    summary = service.run_batch(now=NOW, deps=batch_deps(), stages=_recorder('run-regime'))
    row = _stage(db, 'run-regime', 'regime')
    assert row['input_count'] == len({'AAA', 'BBB', 'CCC'} | set(UNIVERSE))   # 广度样本
    assert row['output_count'] == 1
    assert row['outputs']['market_regime_id'] == str(db.execute(
        'SELECT id FROM market_regimes WHERE session = %s', [SESSION]).fetchone()[0])

    service.run_batch(tickers=['NVDA'], now=NOW, deps=batch_deps(), stages=_recorder('run-thin'))
    row = _stage(db, 'run-thin', 'regime')
    assert row['status'] == 'degraded'                            # 广度样本不足
    assert any(d['kind'] == 'label_insufficient' for d in row['degradations'])


def test_non_trading_day_skips_six():
    """周六早退：前 6 个阶段整段 skipped，push 留给任务层，不写行。"""
    rows = []
    recorder = stages_module.StageRecorder('run-closed', 'scheduled', date(2026, 10, 24),
                                            writer=rows.append, wall_now=lambda: SATURDAY)
    summary = service.run_batch(now=SATURDAY, skip_non_trading=True, deps=batch_deps(),
                                stages=recorder)
    assert summary['status'] == 'skipped'
    assert [row['stage'] for row in rows] == list(stages_module.STAGE_IDS[:-1])
    assert all(row['status'] == 'skipped' and row['reason'] == 'not_trading_day'
               for row in rows)


# ---------------------------------------------------------------- signals / plan / agent / push

class ShortHistorySources(Sources):
    """NEW has only 30 sessions of history: every rule skips it as insufficient_history."""

    def bars(self, ticker, start, end_exclusive):
        out = super().bars(ticker, start, end_exclusive)
        return out.tail(30) if ticker == 'NEW' else out


@pytest.fixture
def wired(db, monkeypatch):
    """Task runs write job_reports into the disposable schema, so run_ids can be compared."""
    from contextlib import contextmanager

    @contextmanager
    def connect(url):
        yield db

    monkeypatch.setattr('investment_assistant.db.connect', connect)
    monkeypatch.setenv('INVESTMENT_ASSISTANT_DATABASE_URL', 'postgresql://wired-to-test-schema')
    monkeypatch.setattr('investment_assistant.services.settings.effective_notify_config',
                        lambda notify: notify)          # 测试库没有 notify_settings 表
    return db


def _sent(monkeypatch, out=None):
    """Replace the notifier, so the real push() / push_closed() build their payloads but send nothing."""
    from investment_assistant.notify import notifier

    calls = []

    def fake(task, notifications, notify_cfg, *, client=None):
        calls.append(len(notifications))
        return out if out is not None else {'sent': True, 'messages': len(notifications), 'channel': 'discord'}

    monkeypatch.setattr(notifier, 'send_notifications', fake)
    return calls


def _rows(db, run_id: str) -> dict[str, dict]:
    return {row['stage']: row for row in repository.stage_runs_for_run(db, run_id)}


def _job_run_id(db) -> str:
    return db.execute("SELECT run_id FROM job_reports WHERE task = 'workbench' "
                      'ORDER BY id DESC LIMIT 1').fetchone()[0]


def test_every_run_writes_exactly_seven(wired, monkeypatch):
    seed_watchlist(wired, [('NVDA', ['core'])])
    _sent(monkeypatch)
    saturday = datetime(2026, 10, 24, 22, 30, tzinfo=UTC)
    seen = []
    for trigger, moment in (('scheduled', NOW), ('manual', NOW + timedelta(minutes=5)),
                            ('scheduled', saturday)):
        result = _task_run(trigger, moment=moment)
        run_id = _job_run_id(wired)
        assert run_id == result['run_id']
        rows = repository.stage_runs_for_run(wired, run_id)
        assert [r['stage'] for r in rows].count('push') == 1
        assert {r['stage'] for r in rows} == set(stages_module.STAGE_IDS) and len(rows) == 7
        assert {r['run_id'] for r in rows} == {run_id}
        assert result['summary']['stage_status'] == {'written': 7, 'error': None}
        seen.append(rows)
    assert {r['trigger'] for r in seen[0]} == {'scheduled'}
    assert {r['trigger'] for r in seen[1]} == {'manual_batch'}
    assert {r['status'] for r in seen[2] if r['stage'] != 'push'} == {'skipped'}

    # 显式池：直接调 run_batch，再 close
    recorder = _recorder('run-explicit-pool')
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()), stages=recorder)
    assert recorder.close() == {'written': 7, 'error': None}
    rows = _rows(wired, 'run-explicit-pool')
    assert set(rows) == set(stages_module.STAGE_IDS)
    assert rows['screen']['reason'] == 'explicit_pool'
    assert (rows['push']['status'], rows['push']['reason']) == ('skipped', 'not_reached')


def test_signals_and_plan_counts(db, monkeypatch):
    from investment_assistant.workbench import plans

    real = plans.build_rule_plan

    def build(**kwargs):
        return {'skip': 'atr_unavailable'} if kwargs['ticker'] == 'MU' else real(**kwargs)

    monkeypatch.setattr(plans, 'build_rule_plan', build)
    summary = service.run_batch(tickers=['NEW', 'MU', 'NVDA'], now=NOW, deps=deps(ShortHistorySources()),
                                run_id='run-counts', stages=_recorder('run-counts'))
    rows = _rows(db, 'run-counts')
    signals, plan = rows['signals'], rows['plan']

    assert signals['status'] == 'success'
    assert signals['input_count'] == 3
    candidates = sum(len(t['candidates']) for t in summary['tickers'].values())
    assert signals['output_count'] == candidates > 0
    stored = db.execute("SELECT id FROM signal_candidates WHERE run_id = 'run-counts'").fetchall()
    assert sorted(signals['outputs']['inserted']) == sorted(str(r[0]) for r in stored)
    assert signals['outputs']['existing'] == []
    skip = {group['reason']: group for group in signals['skips']}
    assert skip['trend_reclaim:insufficient_history']['samples'] == ['NEW']
    assert skip['trend_reclaim:insufficient_history']['count'] == 1

    assert plan['input_count'] == 2                                  # MU 与 NVDA 是无冲突的买入单元
    assert summary['plans'] == {'MU': 'skip: atr_unavailable', 'NVDA': 'inserted'}
    assert plan['output_count'] == 1 == sum(not v.startswith('skip:') for v in summary['plans'].values())
    assert [(g['reason'], g['count'], g['samples']) for g in plan['skips']] == \
        [('atr_unavailable', 1, ['MU'])]
    ids = db.execute("SELECT id FROM trade_plans WHERE kind = 'rule'").fetchall()
    assert plan['outputs'] == {'inserted': [str(r[0]) for r in ids], 'existing': []}
    assert plan['status'] == 'success'


def test_rerun_marks_existing_plans(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()), stages=_recorder('run-first'))
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()), stages=_recorder('run-second'))
    first, second = _rows(db, 'run-first'), _rows(db, 'run-second')
    assert len(first['plan']['outputs']['inserted']) == 1 and first['plan']['outputs']['existing'] == []
    assert second['plan']['outputs']['inserted'] == []
    assert second['plan']['outputs']['existing'] == first['plan']['outputs']['inserted']
    assert second['plan']['output_count'] == 1
    assert second['signals']['outputs']['inserted'] == []
    assert sorted(second['signals']['outputs']['existing']) == sorted(first['signals']['outputs']['inserted'])


def test_agent_unavailable_beats_empty(db, scripted_model):
    d = agent_deps(scripted_model, [], settings=_agent_settings(api_key=None))
    d.bar_fetcher = ShortHistorySources().bars                         # 没有买入单元
    service.run_batch(tickers=['NEW'], now=NOW, deps=d, stages=_recorder('run-noagent'))
    row = _rows(db, 'run-noagent')['agent']
    assert row['status'] == 'skipped' and row['reason'] == 'agent_unavailable: not_configured'


def test_agent_stage_counts(db, scripted_model):
    d = agent_deps(scripted_model, _ok_responses('AAA'))               # AAA 有回复；BBB 回复用完 → error
    service.run_batch(tickers=['AAA', 'BBB'], now=NOW, deps=d, stages=_recorder('run-agent'))
    row = _rows(db, 'run-agent')['agent']
    runs = db.execute('SELECT id, ticker, status, plan_id FROM agent_runs ORDER BY ticker').fetchall()
    assert [(r[1], r[2]) for r in runs] == [('AAA', 'ok'), ('BBB', 'error')]
    assert row['status'] == 'partial'
    assert row['input_count'] == 2 and row['output_count'] == 1
    assert [f['target'] for f in row['failures']] == ['BBB']
    assert row['outputs']['agent_run_ids'] == [str(runs[0][0]), str(runs[1][0])]
    assert row['outputs']['plan_ids'] == [str(runs[0][3])]
    assert set(row['detail']['tokens']) == {'input', 'output'}

    # 重跑：已完成的单元记进 skips，不再产出新的运行
    service.run_batch(tickers=['AAA', 'BBB'], now=NOW, deps=agent_deps(scripted_model, []),
                      stages=_recorder('run-agent-again'))
    again = _rows(db, 'run-agent-again')['agent']
    assert again['output_count'] == 0 and again['input_count'] == 2
    assert [(g['reason'], g['samples']) for g in again['skips']] == [('already_completed', ['AAA'])]
    assert [f['target'] for f in again['failures']] == ['BBB']


def test_push_stage_outcomes(wired, monkeypatch):
    seed_watchlist(wired, [('NVDA', ['core'])])

    def run(outcome, trigger='scheduled', moment=NOW):
        _sent(monkeypatch, outcome)
        result = _task_run(trigger, moment=moment)
        return _rows(wired, result['run_id'])['push']

    manual = run(None, 'manual')
    assert (manual['status'], manual['reason']) == ('skipped', 'manual_run')

    disabled = run({'sent': False, 'messages': 0, 'reason': 'task_disabled'})
    assert (disabled['status'], disabled['reason']) == ('skipped', 'task_disabled')

    failed = run({'sent': False, 'messages': 1, 'reason': 'send_failed: discord down'})
    assert failed['status'] == 'failed' and failed['reason'] == 'send_failed: discord down'
    assert failed['outputs']['push']['messages'] == 1

    empty = run({'sent': False, 'messages': 0, 'reason': 'no_notifications'})
    assert (empty['status'], empty['input_count'], empty['output_count']) == ('success', 0, 0)

    first = run(None)
    assert first['status'] == 'success' and first['output_count'] > 0
    assert first['outputs']['push']['sent'] is True
    assert first['outputs']['push']['messages'] == first['output_count']

    again = run(None)                                  # 同日已推送成功：真实 push() 判定，不再发送
    assert (again['status'], again['reason']) == ('skipped', 'already_pushed')

    closed = run({'sent': True, 'messages': 1, 'channel': 'discord'},
                 moment=datetime(2026, 10, 24, 22, 30, tzinfo=UTC))
    assert closed['status'] == 'success' and closed['detail']['closed'] is True
    assert closed['output_count'] == 1
    closed_failed = run({'sent': False, 'messages': 0, 'reason': 'send_failed: down'},
                        moment=datetime(2026, 10, 24, 22, 30, tzinfo=UTC))
    assert closed_failed['status'] == 'failed' and closed_failed['detail']['closed'] is True


def test_abort_marks_remaining_failed(wired, monkeypatch):
    seed_watchlist(wired, [('AAA', ['core']), ('BBB', [])])

    def boom(**_):
        raise service.Unavailable('boom')

    monkeypatch.setattr(regime_module, 'snapshot', boom)
    result = _task_run('scheduled', task_deps=batch_deps())
    assert result['status'] == 'error' and result['summary'] == {'error': 'boom'}
    rows = _rows(wired, result['run_id'])
    assert set(rows) == set(stages_module.STAGE_IDS)
    assert rows['collect']['status'] in ('success', 'partial')
    assert rows['screen']['status'] == 'success'
    assert (rows['regime']['status'], rows['regime']['reason']) == ('failed', 'aborted: boom')
    for stage in ('signals', 'plan', 'agent', 'push'):
        assert (rows[stage]['status'], rows[stage]['reason']) == ('failed', 'aborted: boom')


def test_missing_stage_runs_table_does_not_fail_batch(wired):
    seed_watchlist(wired, [('NVDA', ['core'])])
    with_table = _task_run('manual')
    assert with_table['summary']['stage_status'] == {'written': 7, 'error': None}

    wired.execute('DROP TABLE stage_runs')
    wired.commit()
    without = _task_run('manual')
    status = without['summary']['stage_status']
    assert status['written'] == 0 and status['error']
    assert without['summary']['errors'] == with_table['summary']['errors']
    assert without['status'] == with_table['status']
