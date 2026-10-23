"""End-to-end workbench flow, offline. Tickers SYNTH/SYNB and every price are fabricated test data."""
import socket
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
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
