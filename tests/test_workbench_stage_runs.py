"""run_batch 的 collect / screen / regime 阶段记账（v2.4 §4）：计数与四族 fetch 行、
筛选与区制的产出引用对得上；非交易日六个阶段整段跳过。复用 characterization 的假 fetcher，
recorder 用默认写入，行落在一次性库的 stage_runs 里再读回。"""
from datetime import UTC, date, datetime

from test_workbench_batch_characterization import UNIVERSE, batch_deps
from test_workbench_service import NOW, SESSION, db, seed_watchlist
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
