"""Agent tool layer: recording, bounds, indicator math and cutoff visibility. No network."""
from datetime import UTC, date, datetime, timedelta

import pytest

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench.agent import REASON_TEXT, STATUSES
from investment_assistant.workbench.agent.tools import (MAX_LOOKBACK, PRICE_TOOLS, Recorder, ToolContext,
                                                        ToolError, call, get_price_bars, get_trigger, indicators,
                                                        result_hash)

S = date(2026, 10, 21)
CUTOFF = datetime(2026, 10, 21, 22, 30, tzinfo=UTC)


def ctx(ticker='AMD', read=lambda fn: None):
    return ToolContext(ticker=ticker, session=S, cutoff_at=CUTOFF, read=read)


def test_reason_text_covers_every_status_reason():
    reasons = {'disabled', 'not_configured', 'quota_exhausted', 'token_budget', 'stage_budget', 'max_attempts',
               'malformed', 'invalid_citation', 'level_check', 'tool_rounds_exceeded', 'model_error',
               'checkpoint_unavailable', 'thesis_count', 'invalid_condition', 'changes_mismatch', 'no_change',
               'review_malformed', 'migration_026_missing', 'review_in_progress'}
    assert set(REASON_TEXT) == reasons
    assert STATUSES == ('ok', 'pass', 'rejected', 'error', 'skipped')


def test_ticker_outside_allowed_is_error_and_recorded():
    rec = Recorder()
    env = call(ctx(), rec, 'get_price_bars', {'ticker': 'NVDA', 'lookback': 60}, now=CUTOFF)
    assert env['ref'] == 'call:1' and env['error']
    assert len(rec.calls) == 1
    assert rec.calls[0]['tool'] == 'get_price_bars'
    assert rec.calls[0]['result'] == env
    assert rec.calls[0]['result_sha256'] == result_hash(env)


def test_lookback_out_of_range_is_error():
    for bad in (0, 1000):
        with pytest.raises(ToolError):
            get_price_bars(ctx(), 'AMD', lookback=bad)
    assert MAX_LOOKBACK == 120
    assert PRICE_TOOLS == frozenset({'get_price_bars', 'get_indicators'})


def test_trigger_has_no_plan_levels():
    rows = [{'id': 1, 'ticker': 'AMD', 'signal_date': S, 'action': 'buy', 'rule_id': 'trend_reclaim',
             'rule_version': '1', 'inputs': {'close': 110, 'ma20': 108}, 'run_id': None, 'created_at': CUTOFF,
             'entry_low': '99.5', 'entry_high': '101.5', 'stop': '96', 'target1': '108'}]
    out = get_trigger(ctx(read=lambda fn: rows))
    assert out == [{'rule_id': 'trend_reclaim', 'action': 'buy', 'inputs': {'close': 110, 'ma20': 108}}]


def test_seq_increments_across_phases():
    rec = Recorder()
    r1 = rec.record('get_news', {}, data={'a': 1}, now=CUTOFF)
    r2 = rec.record('get_price_bars', {'ticker': 'AMD'}, data={'bars': []}, now=CUTOFF)
    rec.phase = 'counter'
    r3 = rec.record('get_news', {}, data={'b': 2}, now=CUTOFF)
    assert [r['ref'] for r in (r1, r2, r3)] == ['call:1', 'call:2', 'call:3']
    assert rec.refs('propose') == {'call:1', 'call:2'}
    assert rec.refs('counter') == {'call:3'}
    assert rec.refs() == {'call:1', 'call:2', 'call:3'}
    assert [c['seq'] for c in rec.calls] == [1, 2, 3]
    assert [c['phase'] for c in rec.calls] == ['propose', 'propose', 'counter']


def test_price_refs_exclude_errors():
    rec = Recorder()
    rec.record('get_price_bars', {}, data={'bars': []}, now=CUTOFF)
    rec.record('get_indicators', {}, error='boom', now=CUTOFF)
    rec.record('get_news', {}, data={'items': []}, now=CUTOFF)
    assert rec.price_refs() == {'call:1'}


def test_hash_is_canonical():
    assert result_hash({'a': 1, 'b': 2}) == result_hash({'b': 2, 'a': 1})
    assert len(result_hash({'a': 1})) == 64


def _bars(closes, volume=1000):
    days = [add_trading_days(S, -(len(closes) - 1 - i)) for i in range(len(closes))]
    return [{'price_date': d, 'open': c, 'high': c * 1.02, 'low': c * 0.98, 'close': c, 'adj_close': c,
             'volume': volume, 'split_factor': 1.0} for d, c in zip(days, closes)]


def test_indicators_short_history_nulls():
    out = indicators(_bars([100 + i for i in range(120)]), _bars([500] * 120))
    assert out['ma200'] is None and out['high_252'] is None and out['low_252'] is None
    assert out['ma50'] is not None
    assert out['rs20'] is not None  # 21 根即可
    assert out['rs60'] is not None  # 61 根即够，120 根充足


def test_indicators_values():
    ticker = _bars([100 + i for i in range(300)], volume=1000)
    ticker[-1]['volume'] = 3000
    spy = _bars([500.0] * 300)
    out = indicators(ticker, spy)
    assert out['last_close'] == 399
    assert out['ma20'] == pytest.approx(sum(range(380, 400)) / 20)
    assert out['volume_ratio'] == pytest.approx(3000 / 1100)  # 均量含当日：19×1000+3000 / 20
    assert out['rs20'] == pytest.approx(399 / 379 - 1)  # 21 根窗口，SPY 20 日收益为 0


def _bar_row(conn, **overrides):
    values = {'ticker': 'NVDA', 'price_date': date(2026, 10, 20), 'open': 100, 'high': 105, 'low': 99,
              'close': 100, 'volume': 1000, 'adj_close': 100, 'revision': 1, 'fetched_at': CUTOFF - timedelta(hours=2)}
    values.update(overrides)
    cols = ', '.join(values)
    marks = ', '.join(['%s'] * len(values))
    conn.execute(f'INSERT INTO price_bars ({cols}) VALUES ({marks})', list(values.values()))


def _news_row(conn, title, *, fetched_at):
    row = conn.execute("INSERT INTO news_items (source, title, url, publisher, published_at, fetched_at, "
                       "content_hash) VALUES ('yfinance', %s, %s, 'p', %s, %s, %s) RETURNING id",
                       [title, f'https://n.example/{title}', CUTOFF - timedelta(days=1), fetched_at,
                        f'hash-{title}']).fetchone()
    conn.execute('INSERT INTO news_item_tickers (news_item_id, ticker) VALUES (%s, %s)', [row[0], 'NVDA'])


def test_bars_after_cutoff_invisible(workbench_db):
    before = CUTOFF - timedelta(hours=2)
    after = CUTOFF + timedelta(hours=2)
    _bar_row(workbench_db, price_date=date(2026, 10, 20), close=100, fetched_at=before)
    _bar_row(workbench_db, price_date=date(2026, 10, 21), close=101, fetched_at=before)
    _bar_row(workbench_db, price_date=date(2026, 10, 20), close=999, revision=2, fetched_at=after)  # cutoff 后的修订
    _bar_row(workbench_db, price_date=date(2026, 10, 21), close=888, revision=2, fetched_at=after)  # cutoff 后的修订
    _bar_row(workbench_db, price_date=date(2026, 10, 22), close=777, fetched_at=after)              # cutoff 后才抓到的 K 线
    _news_row(workbench_db, 'before', fetched_at=before)
    _news_row(workbench_db, 'after', fetched_at=after)

    sql_ctx = ctx('NVDA', read=lambda fn: fn(workbench_db))
    from investment_assistant.workbench.agent.tools import get_news
    assert [(b['date'], b['close']) for b in get_price_bars(sql_ctx, 'NVDA', lookback=10)] \
        == [('2026-10-20', 100.0), ('2026-10-21', 101.0)]
    assert [n['title'] for n in get_news(sql_ctx, days=7)] == ['before']
