"""Pre-launch historical rule check (backcheck-1, spec §10).

Replays stored bars through the current rules with no position, prices buy
candidates with plan-1 and simulates them with plan-shadow-1. Descriptive
only: no parameter tuning, no claim of validity.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from statistics import fmean, median, quantiles
from typing import Any

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import plans, plan_shadow, rules

CALC_VERSION = 'backcheck-1'
WARMUP = rules.MIN_BARS
MATURE_SESSIONS = 20
SWEEP_SESSIONS = 5
FREQ_LIMIT = 5.0
SWEEP_SHARE = 0.5
MIN_FILLED = 10
CLUSTER_MIN = 3
BUY_RULES = ('trend_reclaim', 'volume_breakout', 'earnings_gap_up')

NOTE = '描述性检查，不调参，不代表规则有效。'


def replay(ticker: str, bars: list[dict[str, Any]], filings: list[dict[str, Any]], spy_bars: list[dict[str, Any]],
           *, splits: list, evaluate=rules.evaluate) -> dict[str, Any]:
    """Evaluate every session after the warmup on the bars known at that time.

    The first WARMUP bars only warm the indicators; signals need a priceable
    plan, days without ATR count as skipped. Immature signals count as
    triggers but are not scored.
    """
    from investment_assistant.config import WorkbenchConfig

    signals: list[dict[str, Any]] = []
    skipped_atr = 0
    warmup_end = bars[WARMUP - 1]['price_date'] if len(bars) >= WARMUP else None
    eval_start = bars[WARMUP]['price_date'] if len(bars) > WARMUP else None
    eval_end = bars[-1]['price_date'] if len(bars) > WARMUP else None
    for i in range(WARMUP, len(bars)):
        day, upto = bars[i]['price_date'], bars[:i + 1]
        result = evaluate(ticker, day, upto, filings, None)
        cands = [c for c in result['candidates']
                 if getattr(c, 'rule_id', None) in BUY_RULES and getattr(c, 'action', None) == 'buy']
        if not cands:
            continue
        plan = plans.build_rule_plan(ticker=ticker, signal_date=day, bars=upto, earnings_row=None, snapshot=None,
                                     exposure={'ticker_value': 0, 'total_value': 0}, params=WorkbenchConfig())
        if 'skip' in plan:
            skipped_atr += 1
            continue
        shadow_plan = {'ticker': ticker, 'signal_date': day, 'entry_low': plan['entry_low'],
                       'entry_high': plan['entry_high'], 'stop': plan['stop'], 'target1': plan['target1'],
                       'atr': plan['atr'], 'trail_atr_multiple': plan['trail_atr_multiple'],
                       'valid_from': plan['valid_from'], 'valid_until': plan['valid_until']}
        mature = add_trading_days(plan['valid_until'], MATURE_SESSIONS) <= bars[-1]['price_date']
        outcome = (plan_shadow.simulate(shadow_plan, bars, spy_bars, splits=splits) if mature else None)
        signals.append({'rule_id': cands[0].rule_id, 'signal_date': day, 'mature': mature, 'outcome': outcome})
    return {'ticker': ticker, 'warmup_end': warmup_end, 'eval_start': eval_start, 'eval_end': eval_end,
            'eval_sessions': max(0, len(bars) - WARMUP), 'skipped_atr': skipped_atr, 'signals': signals}


def _row() -> dict[str, Any]:
    return {'triggers': 0, 'ticker_sessions': 0, 'per_100': 0.0, 'max_per_ticker': 0, 'cluster_days': 0,
            'filled': 0, 'expired': 0, 'stopped_within_5': 0, 'stopped_within_5_share': None, 't1_share': None,
            'r': {'count': 0, 'mean': None, 'median': None, 'p25': None, 'p75': None}, 'flags': []}


def _stopped_within_5(outcome: dict[str, Any]) -> bool:
    legs = outcome.get('legs') or []
    fill_date = outcome.get('fill_date')
    if not legs or fill_date is None:
        return False
    first = legs[0]
    return (first.get('reason') == 'stop' and first.get('exit_date') is not None
            and date.fromisoformat(first['exit_date']) <= add_trading_days(fill_date, SWEEP_SESSIONS))


def _fill_row(row: dict[str, Any], signals: list[dict[str, Any]], per_ticker_counts: dict[str, int],
              ticker_sessions: int, cluster_dates: set[date]) -> None:
    row['triggers'] += len(signals)
    row['ticker_sessions'] += ticker_sessions
    row['per_100'] = round(row['triggers'] / row['ticker_sessions'] * 100, 6) if row['ticker_sessions'] else 0.0
    row['max_per_ticker'] = max([row['max_per_ticker'], *per_ticker_counts.values()]) if per_ticker_counts else \
        row['max_per_ticker']
    row['cluster_days'] = len(cluster_dates)
    mature_filled = 0
    t1_reached = 0
    rs: list[float] = []
    for signal in signals:
        outcome = signal.get('outcome') or {}
        status = outcome.get('status')
        if status in ('open', 'closed'):
            row['filled'] += 1
            if _stopped_within_5(outcome):
                row['stopped_within_5'] += 1
            if signal['mature']:
                mature_filled += 1
                if any(leg.get('reason') == 'target1' for leg in outcome.get('legs') or []):
                    t1_reached += 1
        elif status == 'expired':
            row['expired'] += 1
        if signal['mature'] and outcome.get('r') is not None:
            rs.append(outcome['r'])
    row['stopped_within_5_share'] = (row['stopped_within_5'] / row['filled']) if row['filled'] else None
    row['t1_share'] = (t1_reached / mature_filled) if mature_filled else None
    row['r'] = {'count': len(rs), 'mean': fmean(rs) if rs else None, 'median': median(rs) if rs else None,
                'p25': quantiles(rs, n=4, method='inclusive')[0] if len(rs) >= 2 else None,
                'p75': quantiles(rs, n=4, method='inclusive')[2] if len(rs) >= 2 else None}
    if row['per_100'] > FREQ_LIMIT:
        row['flags'].append('too_frequent')
    if row['filled'] >= MIN_FILLED and row['stopped_within_5_share'] is not None \
            and row['stopped_within_5_share'] >= SWEEP_SHARE:
        row['flags'].append('stops_swept')
    if row['filled'] < MIN_FILLED:
        row['flags'].append('insufficient')


def summarize(replays: list[dict[str, Any]]) -> dict[str, Any]:
    """Per rule and overall rows from replay outputs; flags answer the two launch questions."""
    by_rule: dict[str, dict[str, list]] = {}
    all_signals: list[dict[str, Any]] = []
    tickers_meta = []
    for replayed in replays:
        tickers_meta.append({k: (replayed[k].isoformat() if isinstance(replayed[k], date) else replayed[k])
                             for k in ('ticker', 'warmup_end', 'eval_start', 'eval_end', 'eval_sessions')})
        for signal in replayed['signals']:
            by_rule.setdefault(signal['rule_id'], {'signals': [], 'counts': {}, 'dates': {},
                                                   'ticker_sessions': 0})
            bucket = by_rule[signal['rule_id']]
            bucket['signals'].append(signal)
            bucket['counts'][replayed['ticker']] = bucket['counts'].get(replayed['ticker'], 0) + 1
            day_tickers = bucket['dates'].setdefault(signal['signal_date'], set())
            day_tickers.add(replayed['ticker'])
        all_signals.append((replayed, [s for s in replayed['signals']]))

    rules_out: dict[str, Any] = {}
    total_sessions = sum(r['eval_sessions'] for r in replays)
    for rule_id, bucket in by_rule.items():
        row = _row()
        cluster_dates = {day for day, tickers in bucket['dates'].items() if len(tickers) >= CLUSTER_MIN}
        merged = []
        for replayed, signals in all_signals:
            kept = [s for s in signals if s['rule_id'] == rule_id]
            if kept:
                merged.extend(kept)
        _fill_row(row, merged, bucket['counts'], total_sessions, cluster_dates)
        rules_out[rule_id] = row
    all_row = _row()
    all_counts: dict[str, int] = {}
    all_dates: dict[date, set] = {}
    for replayed, signals in all_signals:
        if signals:
            all_counts[replayed['ticker']] = all_counts.get(replayed['ticker'], 0) + len(signals)
        for s in signals:
            all_dates.setdefault(s['signal_date'], set()).add(replayed['ticker'])
    cluster_all = {day for day, tickers in all_dates.items() if len(tickers) >= CLUSTER_MIN}
    _fill_row(all_row, [s for _, signals in all_signals for s in signals], all_counts, total_sessions, cluster_all)
    return {'rules': rules_out, 'all': all_row, 'tickers': tickers_meta, 'note': NOTE}


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m investment_assistant.workbench.backcheck [--tickers A,B]"""
    import argparse

    parser = argparse.ArgumentParser(description='上线前历史检查（backcheck-1）')
    parser.add_argument('--tickers', help='逗号分隔的标的；缺省用当前观察池')
    args = parser.parse_args(argv)
    from investment_assistant.workbench import service
    record = service.run_backcheck(now=datetime.now(UTC),
                                   tickers=[t.strip().upper() for t in args.tickers.split(',')] if args.tickers else None)
    print(json.dumps({'id': str(record['id']), 'all': record['stats']['all']}, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
