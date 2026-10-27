"""Stage registry and recorder: order vs migration check, classify, accumulator, row shape."""
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from investment_assistant.workbench import stages

SESSION = date(2026, 10, 27)
WALL = datetime(2026, 10, 27, 12, 30, tzinfo=UTC)


def _recorder(rows, *, run_id='run-1', clock=None):
    return stages.StageRecorder(run_id, 'manual_batch', SESSION, writer=rows.append,
                                wall_now=lambda: WALL, clock=clock or (lambda: 0.0))


def test_stage_ids_match_migration_check():
    sql = Path('migrations/025_stage_runs.sql').read_text(encoding='utf-8')
    match = re.search(r"CHECK \(stage IN \(([^)]+)\)\)", sql)
    assert stages.STAGE_IDS == tuple(re.findall(r"'([^']+)'", match.group(1)))


def test_registry_seven_stages_in_order_and_described():
    assert stages.STAGES_VERSION == 'stages-1'
    assert stages.STAGE_IDS == ('collect', 'screen', 'regime', 'signals', 'plan', 'agent', 'push')
    assert [s.title for s in stages.STAGES] == [
        '数据采集', '筛选 `screen-1`', '市场环境 `regime-2`', '信号与候选', '规则计划 `plan-1`',
        'Agent 建议', '复核与推送']
    assert all(s.purpose for s in stages.STAGES)


def test_classify_precedence():
    assert stages.classify(executed=False, failed_reason=None, failures=[], degradations=[]) == 'skipped'
    assert stages.classify(executed=True, failed_reason='整体报错', failures=[], degradations=[]) == 'failed'
    assert stages.classify(executed=True, failed_reason=None,
                           failures=[{'target': 'bars:MU', 'reason': 'x'}],
                           degradations=[{'kind': 'conflict', 'detail': ''}]) == 'partial'
    assert stages.classify(executed=True, failed_reason=None, failures=[],
                           degradations=[{'kind': 'conflict', 'detail': ''}]) == 'degraded'
    assert stages.classify(executed=True, failed_reason=None, failures=[], degradations=[]) == 'success'


def test_skip_groups_and_caps_samples():
    acc = stages.StageAcc()
    for i in range(12):
        acc.skip('trend_reclaim:insufficient_history', f'T{i}')
    assert acc.skips[0]['count'] == 12
    assert len(acc.skips[0]['samples']) == 10
    acc.skip('trend_reclaim:insufficient_history', 'T0')   # 重复样本去重，计数照加
    acc.skip('atr_unavailable')                            # 无样本同样计数
    assert acc.skips[0]['count'] == 13
    assert acc.skips[0]['samples'] == [f'T{i}' for i in range(10)]
    assert acc.skips[1] == {'reason': 'atr_unavailable', 'count': 1, 'samples': []}


def test_row_shape():
    rows = []
    ticks = iter((100.0, 100.35))          # timing() 读两次单调时钟：350 ms
    rec = _recorder(rows, clock=lambda: next(ticks))
    with rec.stage('collect') as acc:
        acc.input(20)
        acc.output(18)
        acc.skip('trend_reclaim:insufficient_history', 'MU')
        acc.fail('bars:AAPL', 'timeout')
        acc.degrade('fred_not_configured', 'FRED_API_KEY 未配置')
        acc.ref('data_fetch_runs', 7)
        acc.set_ref('marker', 'm')
        acc.detail['earnings'] = 3
    row = rows[0]
    assert set(row) == {'run_id', 'job', 'trigger', 'session', 'stage', 'stages_version', 'status',
                        'reason', 'input_count', 'output_count', 'skips', 'failures', 'degradations',
                        'outputs', 'detail', 'started_at', 'finished_at', 'duration_ms'}
    assert row['run_id'] == 'run-1' and row['job'] == 'workbench'
    assert row['trigger'] == 'manual_batch' and row['session'] == SESSION
    assert row['stage'] == 'collect' and row['stages_version'] == 'stages-1'
    assert row['status'] == 'partial' and row['reason'] is None
    assert row['input_count'] == 20 and row['output_count'] == 18
    assert row['skips'] == [{'reason': 'trend_reclaim:insufficient_history', 'count': 1, 'samples': ['MU']}]
    assert row['failures'] == [{'target': 'bars:AAPL', 'reason': 'timeout'}]
    assert row['degradations'] == [{'kind': 'fred_not_configured', 'detail': 'FRED_API_KEY 未配置'}]
    assert row['outputs'] == {'data_fetch_runs': [7], 'marker': 'm'}
    assert row['detail'] == {'earnings': 3}
    assert row['started_at'] == WALL and row['finished_at'] == WALL
    assert row['duration_ms'] == 350


def test_stage_context_writes_aborted_and_reraises():
    rows = []
    rec = _recorder(rows)
    with pytest.raises(RuntimeError, match='boom'):
        with rec.stage('collect') as acc:
            acc.input(2)
            raise RuntimeError('boom')
    assert rows[0]['status'] == 'failed'
    assert rows[0]['reason'] == 'aborted: boom'
    assert rows[0]['input_count'] == 2


def test_close_fills_remaining_stages():
    rows = []
    rec = _recorder(rows, run_id='r-skip')
    with rec.stage('collect') as acc:
        acc.input(3)
    assert rec.close(None) == {'written': 7, 'error': None}
    assert len(rows) == 7
    assert rows[0]['stage'] == 'collect' and rows[0]['status'] == 'success'
    rest = [row for row in rows if row['stage'] != 'collect']
    assert {row['stage'] for row in rest} == set(stages.STAGE_IDS) - {'collect'}
    assert all(row['status'] == 'skipped' and row['reason'] == 'not_reached' for row in rest)

    rows2 = []                             # 有异常：其余阶段记 failed / aborted
    rec2 = _recorder(rows2, run_id='r-fail')
    with rec2.stage('collect'):
        pass
    rec2.close(RuntimeError('x'))
    assert all(row['status'] == 'failed' and row['reason'] == 'aborted: x'
               for row in rows2 if row['stage'] != 'collect')


def test_finish_twice_writes_once():
    rows = []
    rec = _recorder(rows)
    acc = rec.open('signals')
    acc.input(5)
    rec.finish('signals')
    acc.output(9)
    rec.finish('signals')
    rec.skip('signals', 'late')            # 已写过：忽略
    assert len(rows) == 1
    assert rows[0]['status'] == 'success'
    assert rows[0]['input_count'] == 5 and rows[0]['output_count'] == 0


def test_skip_and_skip_many_write_skipped_rows():
    rows = []
    rec = _recorder(rows)
    rec.skip('push', 'manual_run')
    rec.skip_many(['signals', 'plan'], 'not_trading_day')
    assert [row['stage'] for row in rows] == ['push', 'signals', 'plan']
    assert all(row['status'] == 'skipped' for row in rows)
    assert rows[0]['reason'] == 'manual_run' and rows[1]['reason'] == 'not_trading_day'
    assert all(row['input_count'] == 0 and row['duration_ms'] == 0 for row in rows)


def test_writer_failure_is_swallowed():
    def boom(row):
        raise RuntimeError('db down')

    rec = stages.StageRecorder('run-1', 'scheduled', SESSION, writer=boom,
                               wall_now=lambda: WALL, clock=lambda: 0.0)
    with rec.stage('collect'):
        pass
    assert rec.close() == {'written': 0, 'error': 'db down'}
