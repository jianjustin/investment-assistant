"""Batch + read model against a disposable schema; all market data below is synthetic."""
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from investment_assistant.data.calendar import add_trading_days
from decimal import Decimal

from investment_assistant.workbench import account, plans, repository, service

SESSION = date(2026, 10, 22)                         # Thursday
NOW = datetime(2026, 10, 22, 22, 30, tzinfo=UTC)     # 18:30 New York


def closes_for(ticker):
    if ticker == 'SPY':
        return [500.0] * 300
    base = [50 + i * 0.25 for i in range(296)]
    return base + [base[-1] - 6] * 3 + [base[-1] + 1]   # trend_reclaim on SESSION


def frame(ticker, end):
    closes = closes_for(ticker)
    days = [add_trading_days(SESSION, -(len(closes) - 1 - i)) for i in range(len(closes))]
    rows = [(d, c) for d, c in zip(days, closes) if d <= end]
    index = pd.DatetimeIndex([pd.Timestamp(d, tz='America/New_York') for d, _ in rows])
    return pd.DataFrame({'Open': [c for _, c in rows], 'High': [c * 1.02 for _, c in rows],
                         'Low': [c * 0.99 for _, c in rows], 'Close': [c for _, c in rows],
                         'Adj Close': [c for _, c in rows], 'Volume': [1000] * len(rows),
                         'Stock Splits': [0.0] * len(rows)}, index=index)


class Sources:
    def __init__(self, fail=(), fail_news=(), fail_earnings=()):
        self.fail = set(fail)
        self.fail_news = set(fail_news)
        self.fail_earnings = set(fail_earnings)
        self.calls = []

    def bars(self, ticker, start, end_exclusive):
        self.calls.append(('bars', ticker))
        if ticker in self.fail:
            raise RuntimeError('provider down')
        return frame(ticker, end_exclusive - timedelta(days=1))

    def news(self, ticker):
        if ticker in self.fail_news:
            raise RuntimeError('news down')
        return [{'content': {'title': f'{ticker} headline', 'pubDate': '2026-10-22T12:00:00Z',
                             'canonicalUrl': {'url': f'https://news.example.com/{ticker}'}}}]

    def earnings(self, ticker, **_):
        if ticker in self.fail_earnings:
            raise RuntimeError('earnings down')
        return {'Earnings Date': [date(2027, 2, 18)]}

    def discover(self, tickers, start, end):
        return [{'ticker': 'NVDA', 'form': '8-K', 'filing_date': '2026-10-22', 'items': ['8.01'],
                 'accepted_at': '2026-10-22T08:00:00-04:00', 'edgar_url': 'https://www.sec.gov/Archives/x.htm'}]


@pytest.fixture
def db(workbench_db, monkeypatch):
    @contextmanager
    def connection():
        yield workbench_db
    monkeypatch.setattr(service, 'connection', connection)
    return workbench_db


def deps(sources, brief_client=None, earnings=None):
    return service.Deps(bar_fetcher=sources.bars, news_fetcher=sources.news, filing_source=sources,
                        brief_client=brief_client or (lambda **_: (None, {'error': 'no key'})),
                        earnings_fetcher=earnings or sources.earnings)


def test_batch_collects_evaluates_and_briefs(db):
    summary = service.run_batch(tickers=['NVDA', 'MU'], now=NOW, deps=deps(Sources()))
    assert summary['session'] == SESSION.isoformat()
    nvda = summary['tickers']['NVDA']
    assert nvda['bars']['inserted'] > 0 and nvda['error'] is None
    assert set(nvda['candidates']) >= {'trend_reclaim', 'new_filing'}
    assert summary['briefs'] == {'NVDA': 'fallback', 'MU': 'fallback'}
    assert summary['benchmark']['error'] is None
    stored = db.execute('SELECT count(*) FROM news_items WHERE source = %s', ['sec_8k']).fetchone()
    assert stored == (1,)


def test_batch_rerun_is_idempotent(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    again = service.run_batch(tickers=['NVDA'], now=NOW + timedelta(minutes=5), deps=deps(Sources()))
    assert again['tickers']['NVDA']['bars']['inserted'] == 0
    assert again['conflicts'] == []
    assert db.execute('SELECT count(*) FROM signal_candidates').fetchone()[0] == len(again['tickers']['NVDA']['candidates'])


def test_one_ticker_failure_does_not_block_others(db):
    summary = service.run_batch(tickers=['NVDA', 'MU'], now=NOW, deps=deps(Sources(fail={'MU'})))
    assert 'provider down' in summary['tickers']['MU']['error']
    assert summary['tickers']['NVDA']['error'] is None
    assert any('MU' in e for e in summary['errors'])


def test_too_many_tickers_is_an_error_not_a_truncation(db):
    with pytest.raises(ValueError):
        service.run_batch(tickers=[f'T{i}' for i in range(101)], now=NOW, deps=deps(Sources()))


def test_scheduled_run_skips_when_new_york_day_was_not_a_session(db):
    saturday = datetime(2026, 10, 24, 22, 30, tzinfo=UTC)
    sources = Sources()
    out = service.run_batch(tickers=['NVDA'], now=saturday, deps=deps(sources), skip_non_trading=True)
    assert out == {'status': 'skipped', 'reason': 'not a trading day in New York', 'ny_date': '2026-10-24'}
    assert sources.calls == []


def test_today_lists_open_units_with_brief_and_context(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    view = service.today(now=NOW)
    unit = view['units'][0]
    assert unit['ticker'] == 'NVDA' and unit['signal_date'] == SESSION
    assert unit['proposed_action'] == 'buy' and unit['entry_passed'] is False
    assert unit['brief']['status'] == 'fallback'
    assert {c['rule_id'] for c in unit['candidates']} >= {'trend_reclaim', 'new_filing'}
    assert unit['news'][0]['source'] == 'sec_8k' or unit['news'][0]['source'] == 'yfinance'


def test_decide_then_unit_leaves_today(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    unit = service.today(now=NOW)['units'][0]
    out = service.decide({'request_id': '6f1d1c1e-1111-4444-8888-000000000001', 'ticker': 'NVDA',
                          'signal_date': SESSION.isoformat(), 'candidate_ids': [str(c['id']) for c in unit['candidates']],
                          'brief_id': str(unit['brief']['id']), 'proposed_action': 'buy', 'final_action': 'buy',
                          'decision': 'accept', 'reason': '合成样例：趋势修复',
                          'plan_id': str(unit['plan']['id'])}, now=NOW)
    assert out['status'] == 'created'
    assert service.today(now=NOW)['units'] == []


def test_unavailable_database_is_reported(monkeypatch):
    monkeypatch.delenv('INVESTMENT_ASSISTANT_DATABASE_URL', raising=False)
    with pytest.raises(service.Unavailable):
        service.today(now=NOW)


def test_missing_schema_is_unavailable_not_empty(workbench_db, monkeypatch):
    workbench_db.execute('DROP TABLE signal_candidates CASCADE')

    @contextmanager
    def connection():
        yield workbench_db
    monkeypatch.setattr(service, 'connection', connection)
    with pytest.raises(service.Unavailable):
        service.today(now=NOW)


def test_sec_listing_fills_unknown_filing_acceptance_without_overwriting(db):
    insert = ("INSERT INTO filings (ticker, form, filing_date, accession_number, primary_document, file_path, "
              "accepted_at, items) VALUES ('NVDA', '8-K', '2026-10-21', %s, 'k.htm', '/x', %s, %s)")
    db.execute(insert, ['0001045810-26-000001', None, None])
    known = datetime(2026, 10, 20, 12, tzinfo=UTC)
    db.execute(insert, ['0001045810-26-000002', known, ['8.01']])

    class Listing(Sources):
        def discover(self, tickers, start, end):
            return [{'ticker': 'NVDA', 'form': '8-K', 'filing_date': '2026-10-21', 'accession_number': acc,
                     'items': ['2.02', '9.01'], 'accepted_at': '2026-10-22T00:41:42+00:00',
                     'edgar_url': f'https://www.sec.gov/Archives/{acc}.htm'}
                    for acc in ('0001045810-26-000001', '0001045810-26-000002')]
    summary = service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Listing()))
    assert summary['filings']['acceptance_filled'] == 1
    rows = {acc: (accepted, items) for acc, accepted, items in
            db.execute('SELECT accession_number, accepted_at, items FROM filings').fetchall()}
    assert rows['0001045810-26-000001'] == (datetime(2026, 10, 22, 0, 41, 42, tzinfo=UTC), ['2.02', '9.01'])
    assert rows['0001045810-26-000002'] == (known, ['8.01'])


def breakdown_closes():
    base = [50 + i * 0.25 for i in range(299)]
    return base + [110.0]   # 10+ days above MA50, then a break below it: trend_break


class BreakdownSources(Sources):
    def bars(self, ticker, start, end_exclusive):
        if ticker != 'AMD' and ticker != 'MU':
            return super().bars(ticker, start, end_exclusive)
        closes = breakdown_closes() if ticker == 'AMD' else closes_for(ticker)
        days = [add_trading_days(SESSION, -(len(closes) - 1 - i)) for i in range(len(closes))]
        rows = [(d, c) for d, c in zip(days, closes) if d <= end_exclusive - timedelta(days=1)]
        index = pd.DatetimeIndex([pd.Timestamp(d, tz='America/New_York') for d, _ in rows])
        return pd.DataFrame({'Open': [c for _, c in rows], 'High': [c * 1.02 for _, c in rows],
                             'Low': [c * 0.99 for _, c in rows], 'Close': [c for _, c in rows],
                             'Adj Close': [c for _, c in rows], 'Volume': [1000] * len(rows),
                             'Stock Splits': [0.0] * len(rows)}, index=index)


def test_batch_writes_rule_plan_for_buy_unit(db):
    summary = service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    assert summary['plans']['NVDA'] == 'inserted'
    unit = service.today(now=NOW)['units'][0]
    plan = unit['plan']
    assert plan['kind'] == 'rule' and plan['plan_version'] == 'plan-1' and plan['status'] == 'ok'
    assert plan['sizing']['status'] == 'no_equity'
    bars = repository.read_bars(db, 'NVDA', SESSION, cutoff_at=NOW)
    levels = plans.rule_levels(Decimal(str(bars[-1]['close'])), plans.atr14(bars))
    for key, value in levels.items():
        assert plan[key] == value
    assert plan['inputs']['bar_ids'] == [b['id'] for b in bars[-15:]]
    assert plan['inputs']['earnings_date_id'] is not None


def test_no_plan_for_conflict_or_sell_units(db):
    # 冲突单元：趋势修复（buy）+ 持仓回撤（sell）
    service.add_trade({'request_id': '6f1d1c1e-2222-4444-8888-000000000001', 'ticker': 'NVDA', 'side': 'buy',
                       'quantity': '10', 'price': '137.00', 'executed_at': '2026-10-10T15:00:00+00:00'}, now=NOW)
    conflict = service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    assert 'plans' not in conflict or 'NVDA' not in conflict['plans']
    # 卖出单元：趋势跌破且无持仓
    sell = service.run_batch(tickers=['AMD'], now=NOW, deps=deps(BreakdownSources()))
    assert 'AMD' not in sell['plans']
    assert db.execute('SELECT count(*) FROM trade_plans').fetchone()[0] == 0


def test_rerun_returns_existing_plan(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    again = service.run_batch(tickers=['NVDA'], now=NOW + timedelta(minutes=5), deps=deps(Sources()))
    assert again['plans']['NVDA'] == 'existing'
    assert db.execute('SELECT count(*) FROM trade_plans').fetchone()[0] == 1


def test_changed_inputs_record_conflict_without_overwrite(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    original = service.today(now=NOW)['units'][0]['plan']

    class Shifted(Sources):
        def bars(self, ticker, start, end_exclusive):
            f = super().bars(ticker, start, end_exclusive)
            f.iloc[-1, f.columns.get_loc('Close')] += 2
            f.iloc[-1, f.columns.get_loc('Adj Close')] += 2
            return f

    again = service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Shifted()))
    assert again['plans']['NVDA'] == 'conflict'
    assert any(c.get('rule_id') == 'rule_plan' for c in again['conflicts'])
    assert db.execute('SELECT count(*) FROM trade_plans').fetchone()[0] == 1
    assert service.today(now=NOW)['units'][0]['plan']['ref_price'] == original['ref_price']


def test_backdated_snapshot_recorded_after_cutoff_ignored(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    plan = service.today(now=NOW)['units'][0]['plan']
    assert plan['sizing']['status'] == 'no_equity'
    # 补录一笔 as_of 在信号日之前、recorded_at 晚于本次运行截止时间的快照
    account.record_snapshot(db, {'request_id': '6f1d1c1e-3333-4444-8888-000000000001',
                                 'as_of': (SESSION - timedelta(days=2)).isoformat(),
                                 'equity': '100000'}, now=NOW + timedelta(hours=1))
    again = service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    assert again['plans']['NVDA'] == 'existing'  # 补录不可见，重算结果与原计划一致


def test_earnings_fetch_failure_not_stored(db):
    def boom(_t):
        raise RuntimeError('calendar down')

    summary = service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources(), earnings=boom))
    assert summary['earnings']['NVDA'].startswith('error:')
    assert db.execute('SELECT count(*) FROM earnings_dates').fetchone()[0] == 0
    plan = service.today(now=NOW)['units'][0]['plan']
    assert 'earnings_unknown' in plan['warnings']


def test_holding_outside_watchlist_is_collected(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    service.add_trade({'request_id': '6f1d1c1e-4444-4444-8888-000000000001', 'ticker': 'AMD', 'side': 'buy',
                       'quantity': '10', 'price': '100.00', 'executed_at': '2026-10-20T15:00:00+00:00'}, now=NOW)
    summary = service.run_batch(tickers=['NVDA'], now=NOW + timedelta(minutes=10), deps=deps(Sources()))
    assert 'AMD' in summary['tickers']
    assert 'AMD' in summary['earnings']


def test_today_includes_holdings(db):
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    service.add_trade({'request_id': '6f1d1c1e-5555-4444-8888-000000000001', 'ticker': 'NVDA', 'side': 'buy',
                       'quantity': '10', 'price': '110.00', 'executed_at': '2026-10-22T20:00:00+00:00'}, now=NOW)
    view = service.today(now=NOW)
    holding = view['holdings'][0]
    assert holding['ticker'] == 'NVDA'
    assert holding['plan_id'] is None and holding['stop'] is None and holding['t1_reached'] is False
    assert holding['last_close'] > 0
    assert holding['next_earnings'] == '2027-02-18'


def test_plan_shadow_view(db):
    from investment_assistant.workbench import plan_shadow as shadow_module
    service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(Sources()))
    view = service.plan_shadow(now=NOW)
    assert view['calc_version'] == shadow_module.SHADOW_VERSION
    assert len(view['plans']) == 1
    plan = view['plans'][0]
    assert plan['ticker'] == 'NVDA' and plan['outcome']['status'] in ('pending', 'open', 'expired')


def test_discipline_since_filters_trades(db):
    service.add_trade({'request_id': '6f1d1c1e-8888-4444-8888-000000000001', 'ticker': 'NVDA', 'side': 'buy',
                       'quantity': '10', 'price': '100.00',
                       'executed_at': '2026-06-15T15:00:00+00:00'}, now=NOW)
    service.add_trade({'request_id': '6f1d1c1e-9999-4444-8888-000000000002', 'ticker': 'AMD', 'side': 'buy',
                       'quantity': '10', 'price': '100.00',
                       'executed_at': '2026-10-20T15:00:00+00:00'}, now=NOW)
    view = service.discipline(now=NOW, since=date(2026, 10, 1))
    assert [t['ticker'] for t in view['trades']] == ['AMD']


class PushClient:
    def __init__(self):
        self.sent = []

    def send(self, channel, payload):
        self.sent.append(payload)


def test_push_once_per_session_and_force(db):
    from investment_assistant.config import NotifyConfig

    cfg = NotifyConfig()
    out = service.push(now=NOW, force=False, notify_cfg=cfg, client=PushClient())
    assert out['sent'] is True and out['messages'] >= 1 and out['session'] == SESSION.isoformat()
    db.execute("INSERT INTO job_reports (task, run_id, status, started_at, finished_at, summary) "
               "VALUES ('workbench', 'r1', 'success', %s, %s, %s::jsonb)",
               [NOW, NOW, json.dumps({'push': out})])
    again = service.push(now=NOW, force=False, notify_cfg=cfg, client=PushClient())
    assert again['sent'] is False and again['reason'] == 'already_pushed'
    forced = service.push(now=NOW, force=True, notify_cfg=cfg, client=PushClient())
    assert forced['sent'] is True


def test_push_failure_recorded_not_raised(db):
    from investment_assistant.config import NotifyConfig

    class Boom:
        def send(self, channel, payload):
            raise RuntimeError('discord down')

    out = service.push(now=NOW, force=True, notify_cfg=NotifyConfig(), client=Boom())
    assert out['sent'] is False and out['reason'].startswith('send_failed')


def seed_watchlist(db, rows):
    for ticker, tags in rows:
        db.execute("INSERT INTO watchlist_items (ticker, status, tags) VALUES (%s, 'active', %s)", [ticker, tags])


def _task_run(trigger, moment=NOW, task_deps=None):
    from investment_assistant.config import AssistantConfig
    from investment_assistant.tasks import workbench as workbench_task

    return workbench_task.run(config=AssistantConfig(), trigger_source=trigger, now=moment,
                              deps=task_deps or deps(Sources()))


def test_scheduled_run_pushes_once_per_session(db, monkeypatch):
    seed_watchlist(db, [('NVDA', ['core'])])
    calls = []

    def fake_push(*, now, force, summary=None, notify_cfg=None, client=None):
        calls.append(force)
        return {'session': SESSION.isoformat(), 'sent': True, 'messages': 4}

    monkeypatch.setattr(service, 'push', fake_push)
    result = _task_run('scheduled')
    assert calls == [False]
    assert result['summary']['push'] == {'session': SESSION.isoformat(), 'sent': True, 'messages': 4}


def test_manual_run_does_not_push(db, monkeypatch):
    seed_watchlist(db, [('NVDA', ['core'])])

    def boom(**_):
        raise AssertionError('manual run must not push')

    monkeypatch.setattr(service, 'push', boom)
    result = _task_run('manual')
    assert 'push' not in result['summary']


def test_closed_day_pushes_closed_message(db, monkeypatch):
    closed = []

    def fake_closed(*, now, notify_cfg=None, client=None):
        closed.append(now)
        return {'session': '2026-10-24', 'sent': True, 'messages': 1}

    monkeypatch.setattr(service, 'push_closed', fake_closed)
    result = _task_run('scheduled', moment=datetime(2026, 10, 24, 22, 30, tzinfo=UTC))
    assert closed and result['summary']['status'] == 'skipped'
    assert result['summary']['push']['sent'] is True


# --- P2: pool, ETF/FRED collection, regime snapshot, extended units ---

def recording_deps(sources):
    calls = []

    def brief_client(**kw):
        calls.append(kw['user_payload'].get('ticker'))
        return (None, {'error': 'no key'})
    d = deps(sources, brief_client=brief_client)
    return d, calls


def test_batch_reads_pool_from_watchlist(db):
    seed_watchlist(db, [('AAA', ['core']), ('BBB', ['core', 'sector:SMH']), ('CCC', []), ('DDD', []), ('EEE', [])])
    summary = service.run_batch(now=NOW, deps=deps(Sources()))
    assert summary['pool']['core'] == 2 and summary['pool']['extended'] == 3 and summary['pool']['holdings'] == 0
    assert len(summary['pool']['changes']) == 5
    assert db.execute('SELECT count(*) FROM pool_tiers').fetchone()[0] == 5


def test_rerun_appends_no_tier_changes(db):
    seed_watchlist(db, [('AAA', ['core']), ('CCC', [])])
    service.run_batch(now=NOW, deps=deps(Sources()))
    again = service.run_batch(now=NOW + timedelta(minutes=5), deps=deps(Sources()))
    assert again['pool']['changes'] == []
    assert db.execute('SELECT count(*) FROM pool_tiers').fetchone()[0] == 2


def test_pool_over_limit_fails_batch(db):
    seed_watchlist(db, [(f'T{i:03d}', []) for i in range(101)])
    sources = Sources()
    with pytest.raises(ValueError, match='100'):
        service.run_batch(now=NOW, deps=deps(sources))
    assert sources.calls == []


def test_core_empty_runs_and_reports(db):
    seed_watchlist(db, [('CCC', []), ('DDD', [])])
    summary = service.run_batch(now=NOW, deps=deps(Sources()))
    assert summary['pool']['core'] == 0
    assert 'core_empty' in summary['errors']
    assert set(summary['tickers']) == {'CCC', 'DDD'}


def test_etf_bars_collected_and_isolated(db):
    class FailingXLK(Sources):
        def bars(self, ticker, start, end_exclusive):
            if ticker == 'XLK':
                raise RuntimeError('etf down')
            return super().bars(ticker, start, end_exclusive)
    summary = service.run_batch(tickers=['NVDA'], now=NOW, deps=deps(FailingXLK()))
    assert summary['etfs']['XLK'].startswith('error:')
    assert summary['etfs']['SMH'].startswith('inserted ')
    assert summary['sources']['etf_bars'] == ['XLK']
    assert summary['tickers']['NVDA']['error'] is None


def test_fred_not_configured(db, monkeypatch):
    monkeypatch.delenv('FRED_API_KEY', raising=False)
    called = []

    def macro_fetcher(url, *, params):
        called.append(params)
        return ({'observations': []}, {'ok': True})
    summary = service.run_batch(tickers=['NVDA'], now=NOW,
                                deps=service.Deps(bar_fetcher=Sources().bars, news_fetcher=Sources().news,
                                                  filing_source=Sources(), brief_client=lambda **_: (None, {'error': 'x'}),
                                                  earnings_fetcher=Sources().earnings, macro_fetcher=macro_fetcher))
    assert summary['macro'] == {'BAMLH0A0HYM2': 'not_configured', 'T10Y2Y': 'not_configured'}
    assert summary['sources']['fred'] == []
    assert called == []


def test_fred_error_in_sources(db, monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'SECRET123')

    def macro_fetcher(url, *, params):
        raise RuntimeError(f'FRED down api_key=SECRET123 url={url}')
    summary = service.run_batch(tickers=['NVDA'], now=NOW,
                                deps=service.Deps(bar_fetcher=Sources().bars, news_fetcher=Sources().news,
                                                  filing_source=Sources(), brief_client=lambda **_: (None, {'error': 'x'}),
                                                  earnings_fetcher=Sources().earnings, macro_fetcher=macro_fetcher))
    assert sorted(summary['sources']['fred']) == ['BAMLH0A0HYM2', 'T10Y2Y']
    assert 'SECRET123' not in json.dumps(summary)
    assert all(v.startswith('error:') for v in summary['macro'].values())


def test_regime_snapshot_written(db):
    seed_watchlist(db, [(f'T{i:02d}', []) for i in range(25)])
    summary = service.run_batch(now=NOW, deps=deps(Sources()))
    assert db.execute('SELECT count(*) FROM market_regimes').fetchone()[0] == 1
    assert summary['regime']['label'] != 'insufficient'
    assert summary['regime']['status'] == 'inserted'
    assert summary['sources']['regime'] == []


def test_extended_unit_has_plan_but_no_brief(db):
    seed_watchlist(db, [('AAA', ['core']), ('NVDA', [])])   # NVDA extended, triggers trend_reclaim
    d, calls = recording_deps(Sources())
    summary = service.run_batch(now=NOW, deps=d)
    assert summary['plans']['NVDA'] == 'inserted'
    assert 'NVDA' not in summary['briefs']
    assert 'NVDA' not in calls
    assert 'AAA' in calls  # core ticker still gets its model brief


def test_held_extended_ticker_gets_brief(db):
    from investment_assistant.workbench import ledger
    seed_watchlist(db, [('AAA', ['core']), ('NVDA', [])])
    ledger.record_trade(db, {'request_id': str(uuid.uuid4()), 'ticker': 'NVDA', 'side': 'buy', 'quantity': '10',
                             'price': '101.5', 'fee': '1', 'executed_at': '2026-10-10T14:00:00+00:00'},
                        now=datetime(2026, 10, 10, 15, tzinfo=UTC))
    d, calls = recording_deps(Sources())
    summary = service.run_batch(now=NOW, deps=d)
    assert summary['plans']['NVDA'] == 'inserted'
    assert summary['briefs']['NVDA'] == 'fallback'
    assert 'NVDA' in calls


def test_sources_distinguish_failures(db):
    seed_watchlist(db, [('AAA', []), ('BBB', []), ('CCC', [])])
    summary = service.run_batch(now=NOW, deps=deps(Sources(fail={'AAA'}, fail_news={'BBB'}, fail_earnings={'CCC'})))
    assert summary['sources']['bars'] == ['AAA']
    assert summary['sources']['news'] == ['BBB']
    assert summary['sources']['earnings'] == ['CCC']
    assert summary['sources']['sec'] == []
    assert summary['sources']['etf_bars'] == []
    assert summary['sources']['fred'] == []


def test_100_tickers_complete_with_timings(db):
    seed_watchlist(db, [(f'T{i:03d}', []) for i in range(100)])
    summary = service.run_batch(now=NOW, deps=deps(Sources()))
    assert len(summary['tickers']) == 100
    assert all(isinstance(v, (int, float)) for v in summary['timings'].values())
    assert set(summary['timings']) == {'collect', 'regime', 'rules', 'total'}
    assert not any('batch_over_budget' in e for e in summary['errors'])


def test_over_budget_recorded(db):
    tick = {'t': 0.0}

    def clock():
        tick['t'] += 1000.0
        return tick['t']
    seed_watchlist(db, [('AAA', ['core'])])
    summary = service.run_batch(now=NOW, deps=service.Deps(
        bar_fetcher=Sources().bars, news_fetcher=Sources().news, filing_source=Sources(),
        brief_client=lambda **_: (None, {'error': 'x'}), earnings_fetcher=Sources().earnings, clock=clock))
    assert any(e.startswith('batch_over_budget') for e in summary['errors'])


def test_rerun_with_context_returns_existing_p1_plan(db):
    from investment_assistant.config import load_config
    seed_watchlist(db, [('NVDA', ['core'])])
    service.run_batch(now=NOW, deps=deps(Sources()))  # stores bars and candidates
    plan_id = db.execute("SELECT id FROM trade_plans WHERE kind = 'rule' AND ticker = 'NVDA'").fetchone()[0]
    db.execute('DELETE FROM trade_plans WHERE id = %s', [plan_id])
    with service._tx() as conn:
        p1 = plans.build_rule_plan(
            ticker='NVDA', signal_date=SESSION, bars=repository.read_bars(conn, 'NVDA', SESSION, cutoff_at=NOW),
            earnings_row=repository.latest_earnings(conn, 'NVDA', cutoff_at=NOW),
            snapshot=repository.snapshot_at(conn, SESSION, cutoff_at=NOW),
            exposure=service.exposure(conn, SESSION, cutoff_at=NOW, ticker='NVDA'),
            params=load_config().workbench)
        assert repository.store_plan(conn, p1)['status'] == 'inserted'
        assert 'context' not in p1['inputs']
    again = service.run_batch(now=NOW + timedelta(minutes=5), deps=deps(Sources()))
    assert again['plans']['NVDA'] == 'existing'
    assert again['conflicts'] == []


# --- P2: today split, market block ---

def test_today_splits_extended_units(db):
    seed_watchlist(db, [('AAA', ['core']), ('NVDA', [])])
    service.run_batch(now=NOW, deps=deps(Sources()))
    view = service.today(now=NOW)
    assert [u['ticker'] for u in view['units']] == ['AAA']
    assert [u['ticker'] for u in view['extended_units']] == ['NVDA']
    ext = view['extended_units'][0]
    assert set(ext) >= {'ticker', 'signal_date', 'proposed_action', 'rule_ids', 'plan'}
    assert ext['proposed_action'] == 'buy' and ext['plan'] is not None


def test_held_extended_stays_in_main_list(db):
    from investment_assistant.workbench import ledger
    seed_watchlist(db, [('AAA', ['core']), ('NVDA', [])])
    ledger.record_trade(db, {'request_id': str(uuid.uuid4()), 'ticker': 'NVDA', 'side': 'buy', 'quantity': '10',
                             'price': '101.5', 'fee': '1', 'executed_at': '2026-10-10T14:00:00+00:00'},
                        now=datetime(2026, 10, 10, 15, tzinfo=UTC))
    service.run_batch(now=NOW, deps=deps(Sources()))
    view = service.today(now=NOW)
    assert 'NVDA' in [u['ticker'] for u in view['units']]
    assert 'NVDA' not in [u['ticker'] for u in view['extended_units']]


def test_today_market_block(db):
    seed_watchlist(db, [(f'T{i:02d}', []) for i in range(25)])
    service.run_batch(now=NOW, deps=deps(Sources()))
    view = service.today(now=NOW)
    assert view['market']['session'] == SESSION
    assert view['market']['calc_version'] == 'regime-1'
    assert view['market']['label'] in ('risk_on', 'neutral', 'risk_off', 'insufficient')


def test_manual_tickers_override_does_not_rewrite_tiers(db):
    from investment_assistant.workbench import repository
    seed_watchlist(db, [('AAA', ['core']), ('BBB', [])])
    service.run_batch(now=NOW, deps=deps(Sources()))
    service.run_batch(tickers=['NVDA'], now=NOW + timedelta(minutes=5), deps=deps(Sources()))
    assert db.execute("SELECT count(*) FROM pool_tiers WHERE tier = 'removed'").fetchone()[0] == 0
    assert repository.pool_latest(db) == {'AAA': {'tier': 'core', 'sector_etf': None},
                                          'BBB': {'tier': 'extended', 'sector_etf': None}}
