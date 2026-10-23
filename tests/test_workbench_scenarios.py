"""End-to-end workbench flow, offline. Tickers SYNTH/SYNB and every price are fabricated test data."""
import json
import socket
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from investment_assistant.data.calendar import add_trading_days
from investment_assistant.workbench import ledger, service

NY = ZoneInfo('America/New_York')
S1 = add_trading_days(datetime(2026, 9, 1).date(), 0)          # buy signal session (Tuesday)
S2 = add_trading_days(S1, 13)                                   # trend break session
HISTORY = 299                                                   # sessions before S1


def evening(day):
    return datetime.combine(day, time(18, 30), tzinfo=NY).astimezone(UTC)


def path():
    """{session: close}: uptrend, 3-day dip, reclaim on S1, rise, then a break below MA50 on S2."""
    days = [add_trading_days(S1, -(HISTORY - i)) for i in range(HISTORY + 1)]
    closes = [50 + i * 0.25 for i in range(HISTORY - 3)]
    closes += [closes[-1] - 6] * 3 + [closes[-1] + 1]
    for k in range(1, 40):
        days.append(add_trading_days(S1, k))
        closes.append(closes[-1] * 0.82 if days[-1] == S2 else closes[-1] + 0.5)
    return dict(zip(days, closes))


PATH = path()


class OfflineSources:
    """Serves only what was 'published' by the requested end date."""

    def bars(self, ticker, start, end_exclusive):
        end = end_exclusive - timedelta(days=1)
        flat = {'SPY': 500.0, 'SYNB': 100.0}
        rows = [(d, flat.get(ticker, c)) for d, c in PATH.items() if d <= end]
        index = pd.DatetimeIndex([pd.Timestamp(d, tz='America/New_York') for d, _ in rows])
        closes = [c for _, c in rows]
        return pd.DataFrame({'Open': closes, 'High': closes, 'Low': closes, 'Close': closes, 'Adj Close': closes,
                             'Volume': [1000] * len(rows), 'Stock Splits': [0.0] * len(rows)}, index=index)

    def news(self, ticker):
        return []

    def discover(self, tickers, start, end):
        if not start <= S1.isoformat() <= end:
            return []
        return [{'ticker': 'SYNB', 'form': '8-K', 'filing_date': S1.isoformat(), 'items': ['8.01'],
                 'accepted_at': f'{S1.isoformat()}T08:00:00-04:00',
                 'edgar_url': 'https://www.sec.gov/Archives/edgar/data/0/synthetic-synb.htm'}]


@pytest.fixture
def offline(workbench_db, monkeypatch):
    """Database via the disposable schema; any other network connection fails the test."""
    real_connect = socket.socket.connect

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ('127.0.0.1', '::1', 'localhost'):
            raise AssertionError(f'network access attempted: {address}')
        return real_connect(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', guarded)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)   # real client, real fallback path

    @contextmanager
    def connection():
        yield workbench_db
    monkeypatch.setattr(service, 'connection', connection)
    return workbench_db


def deps():
    s = OfflineSources()
    return service.Deps(bar_fetcher=s.bars, news_fetcher=s.news, filing_source=s,   # default brief client
                        earnings_fetcher=lambda t: {'Earnings Date': []})


def unit_for(view, ticker):
    return next(u for u in view['units'] if u['ticker'] == ticker)


def decide(u, decision, final, reason, now, supersedes=None):
    return service.decide({
        'request_id': str(__import__('uuid').uuid4()), 'ticker': u['ticker'], 'signal_date': u['signal_date'].isoformat(),
        'candidate_ids': [str(c) for c in u['candidate_ids']], 'proposed_action': u['proposed_action'],
        'final_action': final, 'decision': decision, 'reason': reason,
        'plan_id': str(u['plan']['id']) if u.get('plan') else None,
        'supersedes_id': str(supersedes) if supersedes else None}, now=now)['record']


def test_signal_to_weekly_review_end_to_end(offline):
    now1 = evening(S1)
    summary = service.run_batch(tickers=['SYNTH', 'SYNB'], now=now1, deps=deps())
    assert summary['errors'] == []
    assert summary['briefs'] == {'SYNTH': 'fallback', 'SYNB': 'fallback'}   # no key: rule-only briefs

    today = service.today(now=now1)
    synth, synb = unit_for(today, 'SYNTH'), unit_for(today, 'SYNB')
    assert synth['proposed_action'] == 'buy' and 'trend_reclaim' in synth['rule_ids']
    assert synb['proposed_action'] == 'watch' and synb['rule_ids'] == ['new_filing']

    buy_decision = decide(synth, 'accept', 'buy', '合成样例：趋势修复', now1)
    rejected = decide(synb, 'reject', 'ignore', '合成样例：公告无关', now1)
    entry_day = add_trading_days(S1, 1)
    service.add_trade({'request_id': '00000000-0000-4000-8000-000000000001', 'ticker': 'SYNTH', 'side': 'buy',
                       'quantity': '10', 'price': str(PATH[entry_day]), 'fee': '1',
                       'executed_at': datetime.combine(entry_day, time(10, 0), tzinfo=NY).isoformat(),
                       'decision_id': str(buy_decision['id'])}, now=evening(entry_day))

    now2 = evening(S2)
    service.run_batch(tickers=['SYNTH', 'SYNB'], now=now2, deps=deps())
    sell_unit = unit_for(service.today(now=now2), 'SYNTH')
    assert sell_unit['proposed_action'] == 'sell' and 'trend_break' in sell_unit['rule_ids']
    assert sell_unit['labels'] == []                                        # held, so not "avoid"
    sell_decision = decide(sell_unit, 'accept', 'sell', '合成样例：跌破 MA50', now2)
    exit_day = add_trading_days(S2, 1)
    service.add_trade({'request_id': '00000000-0000-4000-8000-000000000002', 'ticker': 'SYNTH', 'side': 'sell',
                       'quantity': '10', 'price': str(PATH[exit_day]),
                       'executed_at': datetime.combine(exit_day, time(10, 0), tzinfo=NY).isoformat(),
                       'decision_id': str(sell_decision['id'])}, now=evening(exit_day))

    later = evening(add_trading_days(S2, 5))
    trades = service.trade_review(now=later)
    assert len(trades['closed']) == 1 and trades['open'] == []
    assert trades['closed'][0]['realized_pnl'] == pytest.approx(10 * PATH[exit_day] - (10 * PATH[entry_day] + 1))

    shadow = {u['id']: u for u in service.shadow(now=later, since=S1)['units']}
    assert shadow[rejected['id']]['outcome']['windows']['5']['status'] == 'mature'   # rejected units are tracked too
    assert 'move' in shadow[rejected['id']]['outcome']['windows']['5']

    week = S1 - timedelta(days=S1.weekday())
    frozen = service.generate_weekly(week, notes='合成笔记', now=later)
    assert frozen['stats']['units']['decided'] == 2
    assert frozen['stats']['by_decision']['reject']['5']['count'] == 1
    assert frozen['stats']['execution'][0]['slippage'] == pytest.approx(0.0)

    # A later correction of a decision appends to the chain and leaves the frozen snapshot unchanged.
    decide(synb, 'accept', 'watch', '合成样例：改为观察', later, supersedes=rejected['id'])
    with pytest.raises(ledger.Conflict):
        decide(synb, 'accept', 'watch', '过期更正', later, supersedes=rejected['id'])
    stored = service.list_weekly()[0]
    assert stored['id'] == frozen['id'] and stored['stats'] == frozen['stats']

    timeline = service.instrument('SYNTH', now=later)
    assert {c['rule_id'] for c in timeline['candidates']} >= {'trend_reclaim', 'trend_break'}
    assert len(timeline['trades']) == 2 and timeline['position'] is None


def test_rerunning_a_past_session_never_uses_later_data(offline):
    service.run_batch(tickers=['SYNTH'], now=evening(S1), deps=deps())
    service.run_batch(tickers=['SYNTH'], now=evening(S2), deps=deps())
    # Re-reading S1 with S1's cutoff sees only bars fetched by then.
    from investment_assistant.workbench import repository
    bars = repository.read_bars(offline, 'SYNTH', S2, cutoff_at=evening(S1))
    assert bars[-1]['price_date'] == S1


# --- P1: plan to monthly review, end to end ---

def p1_path():
    """Same history and reclaim as path(), but the tail: entry, T1 touch, trail stop."""
    days = [add_trading_days(S1, -(HISTORY - i)) for i in range(HISTORY + 1)]
    closes = [50 + i * 0.25 for i in range(HISTORY - 3)]
    closes += [closes[-1] - 6] * 3 + [closes[-1] + 1]
    tail = [125.0, 125.5, 126.0, 126.5, 140.0, 127.0, 126.0]     # E1, 持有, T1 触及, 移动止损触发, 收尾
    for k, close in enumerate(tail, start=1):
        days.append(add_trading_days(S1, k))
        closes.append(close)
    return dict(zip(days, closes))


P1_PATH = p1_path()


class P1Sources(OfflineSources):
    """Bars with an intraday band so ATR is real; OHLC all split-adjusted synthetic."""

    def bars(self, ticker, start, end_exclusive):
        end = end_exclusive - timedelta(days=1)
        rows = [(d, 500.0 if ticker == 'SPY' else P1_PATH[d]) for d in P1_PATH if d <= end]
        band = 0.5 if ticker == 'SPY' else 1.5
        index = pd.DatetimeIndex([pd.Timestamp(d, tz='America/New_York') for d, _ in rows])
        closes = [c for _, c in rows]
        return pd.DataFrame({'Open': closes, 'High': [c + band for c in closes],
                             'Low': [c - band for c in closes], 'Close': closes, 'Adj Close': closes,
                             'Volume': [1000] * len(rows), 'Stock Splits': [0.0] * len(rows)}, index=index)


def p1_deps():
    source = P1Sources()
    return service.Deps(bar_fetcher=source.bars, news_fetcher=source.news, filing_source=source,
                        earnings_fetcher=lambda t: {'Earnings Date': []})


class PushSpy:
    def __init__(self):
        self.payloads = []

    def send(self, channel, payload):
        self.payloads.append(payload)


def _trade_payload(number, side, quantity, price, day, decision_id=None):
    return {'request_id': f'00000000-0000-4000-8000-{number:012d}', 'ticker': 'SYNTH', 'side': side,
            'quantity': quantity, 'price': price,
            'executed_at': datetime.combine(day, time(10, 0), tzinfo=NY).isoformat(),
            'decision_id': str(decision_id) if decision_id else None}


def test_plan_to_monthly_review_end_to_end(offline):
    from investment_assistant.config import NotifyConfig
    from investment_assistant.workbench import repository

    # 1. 批处理生成规则计划
    batch = service.run_batch(tickers=['SYNTH'], now=evening(S1), deps=p1_deps())
    assert batch['plans']['SYNTH'] == 'inserted' and batch['errors'] == []
    unit = unit_for(service.today(now=evening(S1)), 'SYNTH')
    rule_plan = unit['plan']
    assert rule_plan['kind'] == 'rule' and rule_plan['status'] == 'ok'
    assert rule_plan['sizing']['status'] == 'no_equity'

    # 2. 推送（替身客户端）：四条消息，含价位与证据状态
    spy = PushSpy()
    push_out = service.push(now=evening(S1), force=False, summary=batch, notify_cfg=NotifyConfig(), client=spy)
    assert push_out['sent'] is True and push_out['messages'] == 4
    pushed_text = json.dumps(spy.payloads, ensure_ascii=False)
    assert '证据：未验证' in pushed_text and 'SYNTH' in pushed_text

    # 3. 采纳自定价位：own 计划与决定同事务写入
    decision = service.decide({
        'request_id': str(uuid.uuid4()), 'ticker': 'SYNTH', 'signal_date': S1.isoformat(),
        'candidate_ids': [str(c) for c in unit['candidate_ids']], 'proposed_action': 'buy', 'final_action': 'buy',
        'decision': 'accept', 'reason': '自定价位：收紧止损',
        'own_plan': {'request_id': str(uuid.uuid4()), 'entry_low': '123.5', 'entry_high': '126.5',
                     'stop': '118', 'target1': '136'}}, now=evening(S1))['record']
    own_plan = repository.plan_by_id(offline, decision['plan_id'])
    assert own_plan['kind'] == 'own' and own_plan['based_on_id'] == rule_plan['id']
    assert float(own_plan['stop']) == 118.0

    # 4. 录入买入（E1 开盘 125，位于自定入场区间内）
    entry_day = add_trading_days(S1, 1)
    service.add_trade(_trade_payload(101, 'buy', '10', '125', entry_day, decision['id']), now=evening(entry_day))
    held = service.today(now=evening(entry_day))['holdings'][0]
    assert held['plan_id'] == own_plan['id'] and held['stop'] == 118.0 and held['mode'] == 'initial'

    # 5. T1 触及：plan_target 候选 + 卖出一半
    t1_day = add_trading_days(S1, 5)
    t1_batch = service.run_batch(tickers=['SYNTH'], now=evening(t1_day), deps=p1_deps())
    assert 'plan_target' in t1_batch['tickers']['SYNTH']['candidates']
    service.add_trade(_trade_payload(102, 'sell', '5', '136', t1_day), now=evening(t1_day))
    # t1_reached 只看 T 日之前的 bars：触及当晚仍按初始止损展示
    held_t1 = service.today(now=evening(t1_day))['holdings'][0]
    assert held_t1['mode'] == 'initial' and held_t1['t1_reached'] is False

    # 6. 移动止损触发：plan_stop 候选（不再跑 position_drawdown）+ 清仓
    stop_day = add_trading_days(S1, 6)
    stop_batch = service.run_batch(tickers=['SYNTH'], now=evening(stop_day), deps=p1_deps())
    trailing = service.today(now=evening(stop_day))['holdings'][0]
    assert trailing['mode'] == 'trailing' and trailing['t1_reached'] is True
    assert float(trailing['stop']) == pytest.approx(140.0 - 3 * float(own_plan['atr']))
    candidates = stop_batch['tickers']['SYNTH']['candidates']
    assert 'plan_stop' in candidates and 'position_drawdown' not in candidates
    service.add_trade(_trade_payload(103, 'sell', '5', '127', stop_day), now=evening(stop_day))
    assert service.today(now=evening(stop_day))['holdings'] == []

    # 7. 计划影子：rule 与 own 两份计划都走完两段腿
    after = evening(add_trading_days(S1, 7))
    shadow = service.plan_shadow(now=after, since=S1)
    assert {p['kind'] for p in shadow['plans']} == {'rule', 'own'}
    for p in shadow['plans']:
        assert p['outcome']['status'] == 'closed'
        assert [leg['reason'] for leg in p['outcome']['legs']] == ['target1', 'trail']

    # 8. 纪律：计划内买入、无违规、实际 R 按计划止损计
    disc = service.discipline(now=after)
    entry = disc['trades'][0]
    assert entry['track'] == 'own' and entry['flags'] == []
    assert disc['planned_buys'] == 1 and disc['compliance_rate'] == 1.0
    assert entry['r'] == pytest.approx(((136 - 125) + (127 - 125)) / 2 / (125 - 118), rel=1e-3)

    # 9. 资金快照 → 月度复盘
    service.add_snapshot({'request_id': str(uuid.uuid4()), 'as_of': '2026-08-31', 'equity': '100000'}, now=after)
    service.add_snapshot({'request_id': str(uuid.uuid4()), 'as_of': '2026-09-30', 'equity': '105000'}, now=after)
    review = service.generate_monthly(date(2026, 9, 1), notes='合成月度复盘', now=after)
    stats = review['stats']
    assert stats['return']['status'] == 'ok' and stats['return']['return'] == pytest.approx(0.05)
    assert stats['tier'] == 'viable' and stats['review_flag'] == 'insufficient'
    assert stats['sensitivity']['approximate'] is True and len(stats['sensitivity']['rows']) == 4
