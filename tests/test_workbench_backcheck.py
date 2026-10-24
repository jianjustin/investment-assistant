"""Pre-launch historical rule check: replay window, maturity and flag thresholds."""
from datetime import date, timedelta
from statistics import quantiles

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import backcheck
from investment_assistant.workbench.rules import Candidate

START = date(2026, 1, 5)


def _bars(n=260, *, flat=False, start=START, close=100):
    out = []
    for i in range(n):
        d = add_trading_days(start, i)
        if flat:
            hi = lo = c = close
        else:
            hi, lo, c = close + 2, close, close
        out.append({'id': i + 1, 'price_date': d, 'open': close, 'high': hi, 'low': lo, 'close': c,
                    'adj_close': c, 'volume': 1000, 'split_factor': 1.0})
    return out


def _evaluator(trigger_lengths):
    def evaluate(ticker, d, bars, filings, position):
        cands = ([Candidate('trend_reclaim', 'buy', {'signal_date': d.isoformat()})]
                 if len(bars) in trigger_lengths else [])
        return {'candidates': cands, 'skips': []}
    return evaluate


def test_constants():
    assert backcheck.WARMUP == 200
    assert backcheck.MATURE_SESSIONS == 20
    assert backcheck.SWEEP_SESSIONS == 5
    assert backcheck.FREQ_LIMIT == 5.0
    assert backcheck.SWEEP_SHARE == 0.5
    assert backcheck.MIN_FILLED == 10
    assert backcheck.CLUSTER_MIN == 3
    assert backcheck.BUY_RULES == ('trend_reclaim', 'volume_breakout', 'earnings_gap_up')
    assert backcheck.CALC_VERSION == 'backcheck-1'


def test_no_signal_inside_warmup():
    bars = _bars(260)
    out = backcheck.replay('NVDA', bars, [], bars, splits=[],
                           evaluate=_evaluator({151, 211}))
    dates = [s['signal_date'] for s in out['signals']]
    assert dates == [bars[210]['price_date']]
    assert out['warmup_end'] == bars[199]['price_date']
    assert out['eval_start'] == bars[200]['price_date']
    assert out['eval_end'] == bars[259]['price_date']
    assert out['eval_sessions'] == 60


def test_eval_window_reported_short_history():
    out = backcheck.replay('NVDA', _bars(150), [], _bars(150), splits=[], evaluate=_evaluator(set()))
    assert out['warmup_end'] is None and out['eval_start'] is None and out['eval_end'] is None
    assert out['eval_sessions'] == 0 and out['signals'] == []


def test_immature_counted_not_scored():
    bars = _bars(260)
    out = backcheck.replay('NVDA', bars, [], bars, splits=[],
                           evaluate=_evaluator({211, 259}))
    by_len = {s['signal_date']: s for s in out['signals']}
    early = by_len[bars[210]['price_date']]
    late = by_len[bars[258]['price_date']]
    assert early['mature'] is True and early['outcome'] is not None
    assert late['mature'] is False and late['outcome'] is None
    stats = backcheck.summarize([out])
    assert stats['all']['triggers'] == 2


def test_atr_unavailable_skipped():
    out = backcheck.replay('NVDA', _bars(260, flat=True), [], _bars(260, flat=True), splits=[],
                           evaluate=_evaluator(set(range(201, 261))))
    assert out['skipped_atr'] == 60
    assert out['signals'] == []


def _signal(rule_id='trend_reclaim', day=None, outcome=None):
    return {'rule_id': rule_id, 'signal_date': day or date(2026, 5, 3), 'mature': True, 'outcome': outcome}


def _replay(ticker, signals, sessions=100):
    return {'ticker': ticker, 'warmup_end': date(2026, 1, 1), 'eval_start': date(2026, 1, 2),
            'eval_end': date(2026, 5, 30), 'eval_sessions': sessions, 'skipped_atr': 0, 'signals': signals}


def _outcome(status='closed', r=-1.0, legs=(), fill=date(2026, 5, 4)):
    return {'status': status, 'fill_date': fill, 'legs': list(legs), 'r': r}


def _stop_leg(exit_day, reason='stop'):
    return {'fraction': 1.0, 'exit_date': exit_day.isoformat(), 'exit_price': 90, 'reason': reason}


def test_per_100_and_too_frequent():
    signals = [_signal(day=date(2026, 5, 3 + i)) for i in range(10)]
    stats = backcheck.summarize([_replay('A', signals), _replay('B', [], sessions=100)])
    assert stats['all']['triggers'] == 10 and stats['all']['ticker_sessions'] == 200
    assert stats['all']['per_100'] == 5.0
    assert 'too_frequent' not in stats['all']['flags']  # boundary: > 5.0, not >=
    dense = backcheck.summarize([_replay('A', [_signal(day=date(2026, 5, 3 + i)) for i in range(11)]),
                                 _replay('B', [])])
    assert dense['all']['per_100'] == 5.5 and 'too_frequent' in dense['all']['flags']
    assert 'too_frequent' in dense['rules']['trend_reclaim']['flags']


def test_stops_swept_needs_min_filled():
    def swept(count):
        signals = [_signal(outcome=_outcome(legs=[_stop_leg(date(2026, 5, 6))])) for _ in range(count)]
        return backcheck.summarize([_replay('A', signals)])['all']
    nine = swept(9)
    assert nine['filled'] == 9 and 'stops_swept' not in nine['flags'] and 'insufficient' in nine['flags']
    ten = swept(10)
    assert 'stops_swept' in ten['flags'] and ten['stopped_within_5'] == 10 and ten['stopped_within_5_share'] == 1.0


def test_stop_after_five_sessions_not_swept():
    fill = date(2026, 5, 4)
    late_stop = _stop_leg(add_trading_days(fill, 6))
    stats = backcheck.summarize([_replay('A', [_signal(outcome=_outcome(fill=fill, legs=[late_stop]))
                                         for _ in range(12)])])
    assert stats['all']['stopped_within_5'] == 0 and 'stops_swept' not in stats['all']['flags']


def test_cluster_days():
    day = date(2026, 5, 3)
    replays = [_replay(t, [_signal(day=day)]) for t in ('A', 'B', 'C')] + [_replay('D', [])]
    stats = backcheck.summarize(replays)
    assert stats['all']['cluster_days'] == 1
    assert backcheck.summarize(replays[:2])['all']['cluster_days'] == 0


def test_r_quartiles():
    rs = [1.0, 2.0, 3.0, 4.0]
    signals = [_signal(outcome=_outcome(r=r, legs=[{'fraction': 1.0, 'exit_date': '2026-05-06',
                                                    'exit_price': 120, 'reason': 'stop'}])) for r in rs]
    r = backcheck.summarize([_replay('A', signals)])['all']['r']
    assert r['count'] == 4 and r['mean'] == 2.5 and r['median'] == 2.5
    assert r['p25'] == quantiles(rs, n=4, method='inclusive')[0]
    single = backcheck.summarize([_replay('A', [signals[0]])])['all']['r']
    assert single['count'] == 1 and single['p25'] is None and single['p75'] is None


def test_t1_share_and_note():
    legs = [{'fraction': 0.5, 'exit_date': '2026-05-06', 'exit_price': 120, 'reason': 'target1'},
            {'fraction': 0.5, 'exit_date': '2026-05-20', 'exit_price': 95, 'reason': 'trail'}]
    signals = ([_signal(outcome=_outcome(status='open', r=0.5, legs=legs))]
               + [_signal(outcome=_outcome(status='expired', r=None)) for _ in range(11)])
    stats = backcheck.summarize([_replay('A', signals)])
    assert stats['all']['t1_share'] == 1.0  # mature and filled denominator is 1
    assert '描述性检查，不调参，不代表规则有效。' == stats['note']
    assert stats['tickers'][0]['ticker'] == 'A' and stats['tickers'][0]['eval_sessions'] == 100
