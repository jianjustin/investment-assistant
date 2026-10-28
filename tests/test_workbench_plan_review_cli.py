"""The plan_review command line (v2.5 spec §12): chain and check are read-only, recheck writes.

Chains and reviews come from real batches (fake fetchers, routed scripted model — the helpers of
test_workbench_plan_review); every price is synthetic test data. Tampering is done with plain SQL.
"""
import uuid
from contextlib import nullcontext
from datetime import timedelta

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from test_workbench_service import db   # noqa: F401  (fixture: service wired to the disposable schema)
from test_workbench_plan_review import (QUIET, S1, Market, counter, day, evening, make_model, proposal,
                                        reviews, run, settings, signal_day, verdict)
from investment_assistant.workbench import plan_review, repository, service, user_inputs

TABLES = ('trade_plans', 'agent_plan_versions', 'plan_reviews', 'user_inputs', 'agent_runs', 'agent_tool_calls',
          'signal_decisions')


def _counts(db):
    return {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in TABLES}


def _run(capsys, *argv):
    code = plan_review.main(list(argv))
    return code, capsys.readouterr().out


def _lines(out: str, needle: str) -> list[str]:
    return [line for line in out.splitlines() if needle in line]


# ---------------------------------------------------------------- arguments and availability

def test_bad_arguments_exit_two(capsys):
    for argv in (['check'], ['check', '--session', 'yesterday'], ['chain', '--ticker', 'SYNTH'],
                 ['chain', '--ticker', 'SYNTH', '--date', '2026-13-01'], ['recheck', '--date', '2026-09-01'],
                 ['chain', '--ticker', 'mu!', '--date', '2026-09-01'],
                 ['recheck', '--ticker', '1234', '--date', '2026-09-01'], ['nope']):
        with pytest.raises(SystemExit) as raised:
            plan_review.main(argv)
        assert raised.value.code == 2
    capsys.readouterr()


def test_unavailable_database_exits_two_other_errors_propagate(capsys, monkeypatch):
    def down():
        raise service.Unavailable('数据库未配置')

    monkeypatch.setattr(service, 'connection', down)
    for argv in (['check', '--session', '2026-09-02'], ['chain', '--ticker', 'SYNTH', '--date', '2026-09-01'],
                 ['recheck', '--ticker', 'SYNTH', '--date', '2026-09-01']):
        assert plan_review.main(argv) == 2
    assert '数据库不可用' in capsys.readouterr().err

    def broken(*args, **kwargs):
        raise ValueError('a bug, not an argument')

    monkeypatch.setattr(plan_review, 'check', broken)
    with pytest.raises(ValueError, match='a bug'):                     # 只有参数错误才是退出码 2
        plan_review.main(['check', '--session', '2026-09-02'])


def test_migration_026_missing_exits_two(db, monkeypatch, capsys):
    monkeypatch.setattr(repository, 'timeline_ready', lambda conn: False)
    assert plan_review.main(['check', '--session', day(1).isoformat()]) == 2
    assert '迁移 026 未执行' in capsys.readouterr().err


# ---------------------------------------------------------------- chain

def test_chain_prints_state_versions_and_reviews_read_only(db, capsys, monkeypatch):
    monkeypatch.setattr(plan_review, '_cli_now', lambda: evening(day(1)) + timedelta(hours=1))
    market = Market()
    signal_day(db, market, ['SYNTH'])
    model = make_model(review=verdict('SYNTH', 'revise', '止损应上移'),
                       revise=proposal('SYNTH', stop=117.0,
                                       changes=[{'field': 'stop', 'text': '止损上移到 117', 'refs': ['call:1']}]),
                       counter=counter())
    run(db, market, 1, tickers=['SYNTH'], model=model)
    db.commit()
    before = _counts(db)
    code, out = _run(capsys, 'chain', '--ticker', 'synth', '--date', S1.isoformat())
    assert code == 0 and _counts(db) == before
    assert _lines(out, '状态 entry')
    [v0] = [line for line in out.splitlines() if line.startswith('第 0 版')]
    [v1] = [line for line in out.splitlines() if line.startswith('第 1 版')]
    assert 'signal' in v0 and 'review' in v1 and '止损 117.00' in v1
    assert _lines(out, 'stop 115.00 → 117.00')
    [review] = _lines(out, '止损应上移')
    assert day(1).isoformat() in review and 'batch' in review and 'revise' in review

    code, out = _run(capsys, 'chain', '--ticker', 'SYNB', '--date', S1.isoformat())
    assert code == 1 and '没有' in out


# ---------------------------------------------------------------- check

def test_check_complete_exits_zero(db, capsys):
    market = Market()
    signal_day(db, market, ['SYNQ', 'SYNTH'], review_when={'SYNQ': QUIET})
    run(db, market, 1, tickers=['SYNQ', 'SYNTH'],
        model=make_model(review=verdict('SYNTH', 'maintain', '照旧')))
    db.commit()
    before = _counts(db)
    code, out = _run(capsys, 'check', '--session', day(1).isoformat())
    assert code == 0, out
    assert _counts(db) == before
    assert len(_lines(out, '有效批处理复查 1 条')) == 2
    assert _lines(out, '汇总') and '通过' in _lines(out, '汇总')[0] and '不通过' not in out


def test_check_missing_review_lists_chain_and_skipped_reason(db, capsys):
    market = Market()
    signal_day(db, market, ['SYNQ', 'SYNTH'], review_when={'SYNQ': QUIET})
    run(db, market, 1, tickers=['SYNQ', 'SYNTH'], agent=settings(api_key=None))      # SYNTH 记 skipped
    assert [r['outcome'] for r in reviews(db, 'SYNTH')] == ['skipped']
    db.commit()
    before = _counts(db)
    code, out = _run(capsys, 'check', '--session', day(1).isoformat())
    assert code == 1 and _counts(db) == before
    [missing] = _lines(out, '缺有效复查')
    assert 'SYNTH' in missing and 'skipped（not_configured）' in missing
    assert not _lines(out, '缺有效复查  SYNQ')
    assert '不通过' in _lines(out, '汇总')[0]


def test_check_accepts_fresh_version(db, capsys):
    """Review Focus 1: the signal-day batch generates version 0 and its review stage skips it
    (fresh_version); check must not report it as missing."""
    market = Market()
    signal_day(db, market, ['SYNTH'])
    assert reviews(db) == []
    db.commit()
    code, out = _run(capsys, 'check', '--session', S1.isoformat())
    assert code == 0, out
    assert _lines(out, '当天生成（fresh_version）')
    code, out = _run(capsys, 'check', '--session', day(1).isoformat())       # 次日没有复查 → 缺
    assert code == 1 and _lines(out, '缺有效复查')


def test_check_version_and_ref_violations(db, capsys):
    market = Market()
    signal_day(db, market, ['SYNTH'])
    note = user_inputs.add({'request_id': str(uuid.uuid4()), 'ticker': 'SYNTH', 'kind': 'research',
                            'body': '研报：毛利率上行'}, now=evening(day(1)))['record']
    db.execute('UPDATE user_inputs SET created_at = %s WHERE id = %s',
               [evening(day(1)) - timedelta(hours=2), note['id']])
    cite = [{'field': 'stop', 'text': '研报支持上移止损', 'refs': [f"user:{note['id']}"]}]
    model = make_model(review=verdict('SYNTH', 'revise', '研报支持上移止损'),
                       revise=proposal('SYNTH', stop=117.0, changes=cite), counter=counter())
    run(db, market, 1, tickers=['SYNTH'], model=model)
    db.commit()
    code, out = _run(capsys, 'check', '--session', day(1).isoformat())
    assert code == 0, out
    assert _lines(out, '新版 1 份')

    # 新版引用的 user:<id> 晚于它的截止时间（直接插入一行带更晚 created_at 的输入并让版本引用它）
    late = db.execute(
        "INSERT INTO user_inputs (request_id, request_hash, ticker, kind, body, created_at) "
        "VALUES (%s, 'x', 'SYNTH', 'news', '晚到的新闻', %s) RETURNING id",
        [str(uuid.uuid4()), evening(day(1)) + timedelta(hours=1)]).fetchone()[0]
    head = repository.chain_head(db, 'SYNTH', S1)
    db.execute("UPDATE agent_runs SET output = jsonb_set(output, '{changes,0,refs}', %s::jsonb) WHERE id = %s",
               [f'["user:{late}"]', head['version']['agent_run_id']])
    db.commit()
    before = _counts(db)
    code, out = _run(capsys, 'check', '--session', day(1).isoformat())
    assert code == 1 and _counts(db) == before
    [bad] = _lines(out, f'user:{late}')
    assert '晚于截止时间' in bad and 'SYNTH' in bad

    # 引用不存在的工具调用、版本截止时间与修订运行不一致
    db.execute("UPDATE agent_runs SET output = jsonb_set(output, '{changes,0,refs}', '[\"call:99\"]'::jsonb), "
               "cutoff_at = cutoff_at + interval '1 minute' WHERE id = %s", [head['version']['agent_run_id']])
    db.commit()
    code, out = _run(capsys, 'check', '--session', day(1).isoformat())
    assert code == 1
    assert _lines(out, 'call:99') and _lines(out, 'cutoff_at')


# ---------------------------------------------------------------- recheck

def test_recheck_command_writes_one_review(db, capsys, monkeypatch):
    market = Market()
    signal_day(db, market, ['SYNTH'], review_when={'SYNTH': QUIET})
    run(db, market, 1, tickers=['SYNTH'])
    model = make_model(review=verdict('SYNTH', 'maintain', '命令行重新复查', cite=False))
    deps = service.Deps(agent_model=model, agent_checkpointer=lambda: nullcontext(InMemorySaver()),
                        agent_settings=settings())
    monkeypatch.setattr(plan_review, '_cli_deps', lambda: deps)
    monkeypatch.setattr(plan_review, '_cli_now', lambda: evening(day(1)) + timedelta(hours=1))
    code, out = _run(capsys, 'recheck', '--ticker', 'SYNTH', '--date', S1.isoformat())
    assert code == 0, out
    row = reviews(db)[-1]
    assert (row['trigger'], row['outcome'], row['reason']) == ('recheck', 'maintain', '命令行重新复查')
    assert _lines(out, f"复查记录 {row['id']}") and _lines(out, '新版：无')

    monkeypatch.setattr(plan_review, '_cli_deps',
                        lambda: service.Deps(agent_model=make_model(), agent_settings=settings(api_key=None)))
    code, out = _run(capsys, 'recheck', '--ticker', 'SYNTH', '--date', S1.isoformat())
    assert code == 1 and 'agent_unavailable: not_configured' in out


def _store_stage_rows(db, rows):
    """The run helper records stage rows in a list; write them to stage_runs as a real batch would."""
    for row in rows.values():
        repository.insert_stage_run(db, row)
    db.commit()


def test_check_reads_object_cap_per_chain_from_stage_evidence(db, capsys, monkeypatch):
    market = Market()
    signal_day(db, market, ['SYNA', 'SYNTH'])
    monkeypatch.setattr(plan_review, 'REVIEW_MAX_OBJECTS', 1)
    _, rows, _ = run(db, market, 1, tickers=['SYNA', 'SYNTH'],
                     model=make_model(review=verdict('SYNA', 'maintain', '照旧')))
    assert rows['review']['detail']['excluded'] == [
        {'ticker': 'SYNTH', 'signal_date': S1.isoformat(), 'reason': 'object_cap'}]
    db.commit()
    code, out = _run(capsys, 'check', '--session', day(1).isoformat())
    assert code == 1 and _lines(out, '缺有效复查  SYNTH')                  # 没有阶段证据：看不出被上限排除
    _store_stage_rows(db, rows)
    code, out = _run(capsys, 'check', '--session', day(1).isoformat())
    assert code == 0, out
    assert _lines(out, 'SYNTH 2026-09-01 第 0 版 entry：超出复查上限（object_cap）')


def test_later_recheck_version_does_not_mask_missing_batch_review(db, capsys):
    """The batch skipped the chain without a row (its lock was busy); a recheck after the batch produced a
    version of S. The batch's start comes from the review stage row, so that version is not the batch's
    input and the chain is reported missing with the stage's reason."""
    import os

    import psycopg

    market = Market()
    signal_day(db, market, ['SYNTH'])
    with psycopg.connect(os.environ['INVESTMENT_ASSISTANT_TEST_DATABASE_URL']) as other:
        other.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [f'review:SYNTH:{S1.isoformat()}'])
        _, rows, _ = run(db, market, 1, tickers=['SYNTH'])
        other.rollback()
    _store_stage_rows(db, rows)
    model = make_model(review=verdict('SYNTH', 'revise', '止损应上移'),
                       revise=proposal('SYNTH', stop=117.0,
                                       changes=[{'field': 'stop', 'text': '止损上移到 117', 'refs': ['call:1']}]),
                       counter=counter())
    deps = service.Deps(agent_model=model, agent_checkpointer=lambda: nullcontext(InMemorySaver()),
                        agent_settings=settings())
    row = plan_review.recheck('SYNTH', S1, now=evening(day(1)) + timedelta(hours=1), deps=deps)
    assert row['new_plan_id'] is not None
    assert repository.chain_head(db, 'SYNTH', S1)['version']['as_of_session'] == day(1)
    db.commit()
    code, out = _run(capsys, 'check', '--session', day(1).isoformat())
    assert code == 1
    [missing] = _lines(out, '缺有效复查')
    assert 'SYNTH 2026-09-01 第 0 版 entry' in missing and '阶段跳过（review_in_progress）' in missing
