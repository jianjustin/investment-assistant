"""只读的推导命令行（v2.4 §8 第 3 点）：check 逐份列出计划的一致性，stages 核对阶段证据。

计划与阶段行来自真实批处理（假 fetcher、一次性库）；篡改直接 UPDATE 已存计划。
两个子命令都在只读事务里执行，前后各表行数不变。"""
import subprocess
import sys
from pathlib import Path
from datetime import UTC, date, datetime

import pytest

from test_workbench_service import NOW, SESSION, _ok_responses, _task_run, agent_deps, db, seed_watchlist   # noqa: F401
from test_workbench_stage_runs import _recorder, _sent, wired   # noqa: F401  (fixtures)
from investment_assistant.workbench import derivation, service
from investment_assistant.workbench import stages as stages_module

TABLES = ('trade_plans', 'signal_candidates', 'stage_runs', 'job_reports', 'agent_runs', 'price_bars')


def _counts(db):
    return {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in TABLES}


def _insert_report(db, run_id, started_at, trigger='scheduled'):
    db.execute("INSERT INTO job_reports (task, run_id, status, started_at, trigger_source) "
               "VALUES ('workbench', %s, 'ok', %s, %s)", [run_id, started_at, trigger])
    db.commit()


def _scheduled(wired, monkeypatch, tickers=(('NVDA', ['core']), ('MU', ['core']))):
    seed_watchlist(wired, list(tickers))
    _sent(monkeypatch)
    result = _task_run('scheduled')
    wired.commit()
    return result


def _run(capsys, *argv):
    code = derivation.main(list(argv))
    out = capsys.readouterr().out
    return code, out


def _line(out: str, needle: str) -> str:
    [line] = [x for x in out.splitlines() if needle in x]
    return line


# ---------------------------------------------------------------- offline

def test_import_is_database_free():
    code = ("import sys; import investment_assistant.workbench.derivation as d; "
            "bad = [m for m in ('psycopg', 'investment_assistant.workbench.service', "
            "'investment_assistant.workbench.derivation_view') if m in sys.modules]; "
            "assert not bad, bad; assert callable(d.main)")
    done = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                          cwd=Path(__file__).resolve().parent.parent)
    assert done.returncode == 0, done.stderr


def test_session_window_runs_from_ny_close_to_next_trading_day_close():
    start, end = derivation.session_window(date(2026, 10, 22))          # 周四 → 周五，夏令时 UTC-4
    assert (start, end) == (datetime(2026, 10, 22, 20, 0, tzinfo=UTC), datetime(2026, 10, 23, 20, 0, tzinfo=UTC))
    start, end = derivation.session_window(date(2026, 10, 23))          # 周五 → 下周一
    assert end == datetime(2026, 10, 26, 20, 0, tzinfo=UTC)
    start, end = derivation.session_window(date(2026, 10, 30))          # 周五 → 周一，期间夏令时结束（UTC-5）
    assert (start, end) == (datetime(2026, 10, 30, 20, 0, tzinfo=UTC), datetime(2026, 11, 2, 21, 0, tzinfo=UTC))


def test_bad_arguments_exit_two(capsys):
    for argv in (['check'], ['check', '--since', 'yesterday'], ['stages'], ['check', '--since', '2026-10-22',
                                                                           '--kind', 'x']):
        with pytest.raises(SystemExit) as raised:
            derivation.main(argv)
        assert raised.value.code == 2
    capsys.readouterr()


# ---------------------------------------------------------------- check

def test_check_all_consistent(wired, monkeypatch, capsys):
    _scheduled(wired, monkeypatch)
    ids = [str(r[0]) for r in wired.execute('SELECT id FROM trade_plans').fetchall()]
    assert len(ids) == 2
    before = _counts(wired)
    code, out = _run(capsys, 'check', '--since', SESSION.isoformat())
    assert code == 0
    for plan_id in ids:
        assert 'consistent' in _line(out, plan_id)
    assert 'NVDA' in out and 'MU' in out and 'rule' in out
    last = out.strip().splitlines()[-1]
    assert last.startswith('汇总') and '2 份' in last and 'mismatch 0' in last and 'incomplete 0' in last
    assert _counts(wired) == before


def test_check_flags_tampered_stop(wired, monkeypatch, capsys):
    _scheduled(wired, monkeypatch)
    wired.execute("UPDATE trade_plans SET stop = stop + 1 WHERE ticker = 'NVDA'")
    wired.commit()
    nvda, mu = [str(wired.execute("SELECT id FROM trade_plans WHERE ticker = %s", [t]).fetchone()[0])
                for t in ('NVDA', 'MU')]
    code, out = _run(capsys, 'check', '--since', SESSION.isoformat())
    assert code == 1
    assert 'mismatch' in _line(out, nvda) and 'stop' in out
    assert 'consistent' in _line(out, mu) and 'mismatch' not in _line(out, mu)
    assert '1 份 mismatch' in out.strip().splitlines()[-1] or 'mismatch 1' in out.strip().splitlines()[-1]


def test_check_ignores_inconsistency_of_non_ok_plans(wired, monkeypatch, capsys):
    """退出码只看 status = ok 的计划（spec §8）：作废计划不一致仍逐份列出，但不失败。"""
    _scheduled(wired, monkeypatch, [('NVDA', ['core'])])
    wired.execute("UPDATE trade_plans SET stop = stop + 1, status = 'invalid', "
                  "invalid_reasons = ARRAY['earnings_in_validity']")
    wired.commit()
    code, out = _run(capsys, 'check', '--since', SESSION.isoformat())
    assert 'mismatch' in out and code == 0


def test_check_filters_kind_and_dates(db, scripted_model, capsys):
    d = agent_deps(scripted_model, _ok_responses('AAA'))
    service.run_batch(tickers=['AAA'], now=NOW, deps=d, run_id='run-cli', stages=_recorder('run-cli'))
    db.commit()
    rule_id = str(db.execute("SELECT id FROM trade_plans WHERE kind = 'rule'").fetchone()[0])
    agent_id = str(db.execute("SELECT id FROM trade_plans WHERE kind = 'agent'").fetchone()[0])

    code, out = _run(capsys, 'check', '--since', SESSION.isoformat(), '--kind', 'agent')
    assert code == 0 and agent_id in out and rule_id not in out and '1 份' in out.splitlines()[-1]
    code, out = _run(capsys, 'check', '--since', SESSION.isoformat(), '--kind', 'rule')
    assert code == 0 and rule_id in out and agent_id not in out
    code, out = _run(capsys, 'check', '--since', SESSION.isoformat())
    assert rule_id in out and agent_id in out and '2 份' in out.splitlines()[-1]

    code, out = _run(capsys, 'check', '--since', '2026-10-23')            # 信号日在窗口之前
    assert code == 0 and '0 份' in out.splitlines()[-1]
    code, out = _run(capsys, 'check', '--since', '2026-10-01', '--until', '2026-10-21')
    assert code == 0 and '0 份' in out.splitlines()[-1]
    code, out = _run(capsys, 'check', '--since', '2026-10-01', '--until', SESSION.isoformat())
    assert code == 0 and '2 份' in out.splitlines()[-1]


# ---------------------------------------------------------------- stages

def test_stages_complete_run_passes(wired, monkeypatch, capsys):
    result = _scheduled(wired, monkeypatch)
    before = _counts(wired)
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert code == 0, out
    assert result['run_id'] in out
    for stage in stages_module.STAGE_IDS:
        assert any(line.lstrip().startswith(stage) for line in out.splitlines()), stage
    assert out.strip().splitlines()[-1].startswith('汇总')
    assert _counts(wired) == before


def test_stages_missing_row_fails(wired, monkeypatch, capsys):
    result = _scheduled(wired, monkeypatch)
    wired.execute("DELETE FROM stage_runs WHERE run_id = %s AND stage = 'agent'", [result['run_id']])
    wired.commit()
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert code == 1
    assert '7 行' in out and 'agent' in _line(out, '缺少阶段')


def test_run_stage_count_by_version():
    assert derivation.RUN_STAGE_COUNT == {'stages-1': 7, 'stages-2': 8}
    assert {v: len(ids) for v, ids in stages_module.STAGE_IDS_BY_VERSION.items()} == derivation.RUN_STAGE_COUNT


def test_stages_cli_counts_by_version(wired, monkeypatch, capsys):
    """v2.5 §7.1: stages-1 runs pass with 7 rows, stages-2 runs with 8; a stages-2 run short of a row fails."""
    eight = _scheduled(wired, monkeypatch)
    wired.execute('DROP TABLE plan_reviews, user_inputs, agent_plan_versions CASCADE')   # 026 未执行 → stages-1
    wired.commit()
    seven = _task_run('manual')
    wired.commit()
    def rows(run_id):
        return wired.execute('SELECT stages_version, count(*) FROM stage_runs WHERE run_id = %s '
                             'GROUP BY stages_version', [run_id]).fetchall()

    assert rows(eight['run_id']) == [('stages-2', 8)] and rows(seven['run_id']) == [('stages-1', 7)]
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert code == 0, out
    assert 'stages-2' in _line(out, eight['run_id']) and '8 行' in _line(out, eight['run_id'])
    assert 'stages-1' in _line(out, seven['run_id']) and '7 行' in _line(out, seven['run_id'])
    assert '2 个齐全' in out.splitlines()[-1]

    wired.execute("DELETE FROM stage_runs WHERE run_id = %s AND stage = 'review'", [eight['run_id']])
    wired.commit()
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert code == 1
    assert 'review' in _line(out, '缺少阶段') and '1 个齐全' in out.splitlines()[-1]


def test_stages_run_missing_from_job_reports_fails(wired, monkeypatch, capsys):
    result = _scheduled(wired, monkeypatch)
    wired.execute('DELETE FROM job_reports WHERE run_id = %s', [result['run_id']])
    wired.commit()
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert code == 1 and 'job_reports' in out


def test_stages_report_without_rows_is_missing_evidence(wired, monkeypatch, capsys):
    _scheduled(wired, monkeypatch)
    _insert_report(wired, 'run-no-evidence', datetime(2026, 10, 22, 22, 50, tzinfo=UTC), trigger='manual_batch')
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert code == 1
    line = _line(out, 'run-no-evidence')
    assert '缺证据' in line and '2026-10-23 06:50' in line            # 北京时间


def test_stages_window_is_ny_close_to_next_close(wired, monkeypatch, capsys):
    _scheduled(wired, monkeypatch)
    _insert_report(wired, 'run-before', datetime(2026, 10, 22, 19, 59, tzinfo=UTC))        # 收盘前一分钟
    _insert_report(wired, 'run-after', datetime(2026, 10, 23, 20, 0, tzinfo=UTC))          # 下一收盘时刻，不含
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert code == 0 and 'run-before' not in out and 'run-after' not in out
    _insert_report(wired, 'run-first-minute', datetime(2026, 10, 22, 20, 0, tzinfo=UTC))
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert code == 1 and '缺证据' in _line(out, 'run-first-minute')


def test_stages_without_table_or_runs(wired, monkeypatch, capsys):
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())          # 没有任何运行
    assert code == 0 and '0 个运行' in out.splitlines()[-1]
    _scheduled(wired, monkeypatch)
    wired.execute('DROP TABLE stage_runs')
    wired.commit()
    code, out = _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert code == 1 and '迁移 025 未执行' in out


def test_commands_run_in_read_only_transactions(wired, monkeypatch, capsys):
    _scheduled(wired, monkeypatch)
    opened = []
    real = service.read_only_tx

    def counting():
        opened.append(1)
        return real()

    monkeypatch.setattr(service, 'read_only_tx', counting)
    _run(capsys, 'check', '--since', SESSION.isoformat())
    _run(capsys, 'stages', '--session', SESSION.isoformat())
    assert len(opened) == 2                                        # 每个子命令一个只读事务
