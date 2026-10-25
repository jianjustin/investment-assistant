"""The daily screen stage inside the batch, offline end to end.

Universe: U00-U29 fabricated range tickers plus SYNTH on the manual list.
U00-U02 trigger trend_reclaim on S1, U03-U24 form the setup band with
descending relative strength, U25-U29 fail the setup band; QQQ is flat.
"""
import socket
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from investment_assistant.data.calendar import add_trading_days, trading_days_between
from investment_assistant.workbench import repository, service
from investment_assistant.workbench import universe as universe_module

NY = ZoneInfo('America/New_York')
S1 = add_trading_days(datetime(2026, 9, 1).date(), 0)          # Tuesday signal session
HISTORY = 299
FORWARD = 90
DAYS_BACK = [add_trading_days(S1, -(HISTORY - i)) for i in range(HISTORY + 1)]
ALL_DAYS = DAYS_BACK + [add_trading_days(S1, k) for k in range(1, FORWARD + 1)]
UNIVERSE_TICKERS = (*(f'U{i:02d}' for i in range(30)), 'SYNTH')


def evening(day):
    return datetime.combine(day, time(18, 30), tzinfo=NY).astimezone(UTC)


def _trigger_path(start):
    """Uptrend, 3-day dip, reclaim on S1 (closes; pad 0 like the SYNTH scenario)."""
    up = [start + i * 0.25 for i in range(HISTORY - 3)]
    closes = up + [up[-1] - 6] * 3 + [up[-1] + 1]   # reclaim above the pre-dip close on S1
    return dict(zip(DAYS_BACK, closes))


def _series(ticker):
    """{date: (close, pad)} over the whole horizon."""
    if ticker in ('SPY', 'QQQ', 'SMH', 'XLK', 'SYNB'):
        return {d: (500.0 if ticker != 'SYNB' else 100.0, 0.0) for d in ALL_DAYS}
    if ticker == 'SYNTH':
        path = _trigger_path(50.0)
        tail = path[S1]
        for k in range(1, FORWARD + 1):
            tail += 0.5
            path[add_trading_days(S1, k)] = tail
        return {d: (c, 0.0) for d, c in path.items()}
    if ticker in ('U00', 'U01', 'U02'):
        path = _trigger_path({'U00': 50.0, 'U01': 60.0, 'U02': 70.0}[ticker])
        tail = path[S1]
        for k in range(1, FORWARD + 1):
            if ticker == 'U00':      # drops out of every screen condition after S1
                path[add_trading_days(S1, k)] = path[S1] * 0.85
            else:
                tail += 0.5
                path[add_trading_days(S1, k)] = tail
        return {d: (c, 0.0) for d, c in path.items()}
    i = int(ticker[1:])
    if 3 <= i <= 24:                 # setup band: uptrend, pad 2% of close -> ATR% ~4%, RS descending
        step = 0.30 - 0.01 * (i - 3)
        closes = [100.0 + step * k for k in range(len(ALL_DAYS))]
        series = {d: (c, c * 0.02) for d, c in zip(ALL_DAYS, closes)}
        if ticker == 'U05':          # one big day: setup kept, abnormal_move watch candidate on S1
            series[S1] = (series[S1][0] * 1.05, series[S1][1])
        return series
    closes = [100.0 + 0.1 * k for k in range(len(ALL_DAYS))]   # U25-U29: ATR% far below the band
    return {d: (c, c * 0.001) for d, c in zip(ALL_DAYS, closes)}


class ScreenSources:
    """Serves only what was 'published' by the requested end date."""

    def __init__(self, *, fail=(), qqq_last=None):
        self.fail = set(fail)
        self.qqq_last = qqq_last

    def bars(self, ticker, start, end_exclusive):
        end = end_exclusive - timedelta(days=1)
        if ticker in self.fail:
            raise RuntimeError(f'no bars returned for {ticker} {start}..{end}')
        series = _series(ticker)
        if ticker == 'QQQ' and self.qqq_last is not None:
            series = {d: v for d, v in series.items() if d <= self.qqq_last}
        rows = [(d, c, p) for d, (c, p) in series.items() if start <= d <= end]
        if not rows:
            raise RuntimeError(f'no bars returned for {ticker} {start}..{end}')
        index = pd.DatetimeIndex([pd.Timestamp(d, tz='America/New_York') for d, _, _ in rows])
        closes = [c for _, c, _ in rows]
        pads = [p for _, _, p in rows]
        return pd.DataFrame({'Open': closes, 'High': [c + p for c, p in zip(closes, pads)],
                             'Low': [c - p for c, p in zip(closes, pads)], 'Close': closes,
                             'Adj Close': closes, 'Volume': [1_000_000] * len(rows),
                             'Stock Splits': [0.0] * len(rows)}, index=index)

    def news(self, ticker):
        return []

    def discover(self, tickers, start, end):
        return []


def make_deps(sources=None, *, universe=None, earnings=None):
    s = sources or ScreenSources()
    return service.Deps(bar_fetcher=s.bars, news_fetcher=s.news, filing_source=s,
                        earnings_fetcher=earnings or (lambda t: {'Earnings Date': []}),
                        universe=universe if universe is not None else
                        universe_module.Universe('test', S1, 'test', UNIVERSE_TICKERS))


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

    @contextmanager
    def connection():
        yield workbench_db
    monkeypatch.setattr(service, 'connection', connection)
    return workbench_db


def seed_watchlist(conn, rows=(('SYNTH', ['core']),)):
    for ticker, tags in rows:
        conn.execute("INSERT INTO watchlist_items (ticker, status, tags) VALUES (%s, 'active', %s)",
                     [ticker, tags])
    conn.commit()


def stored_results(conn, session, *, now):
    run = repository.latest_screen_run(conn, session=session)
    assert run is not None
    return repository.screen_results(conn, run['id'])


def test_screen_selects_and_extends_pool(offline):
    seed_watchlist(offline)
    batch = service.run_batch(now=evening(S1), deps=make_deps())
    assert batch['errors'] == []
    screen = batch['screen']
    assert screen['status'] == 'success'
    assert screen['selected'][:3] == ['U00', 'U01', 'U02']
    assert len(screen['selected']) == 20
    results = stored_results(offline, S1, now=evening(S1))
    assert len(results) == 30                                   # every range ticker evaluated
    assert all(r['ticker'] != 'SYNTH' for r in results)         # manual list is never screened
    rows = offline.execute("SELECT ticker, tier, source FROM pool_tiers WHERE source = 'screen'").fetchall()
    assert len(rows) == 20 and all(r[1] == 'extended' for r in rows)
    assert batch['pool']['screen'] == 20


def test_valid_screen_plan_is_decidable(offline):
    seed_watchlist(offline)
    service.run_batch(now=evening(S1), deps=make_deps())
    view = service.today(now=evening(S1))
    u00 = next(u for u in view['units'] if u['ticker'] == 'U00')
    assert u00['source'] == 'screen' and u00['plan'] is not None and u00['plan']['status'] == 'ok'
    ctx = u00['plan']['inputs']['context']
    assert ctx['source'] == 'screen' and ctx['screen']['rank'] == 1 and ctx['screen']['group'] == 'trigger'
    u05 = next(u for u in view['extended_units'] if u['ticker'] == 'U05')
    assert u05['plan'] is None and u05['proposed_action'] == 'watch'
    with service.connection() as conn:
        groups = service._session_units(conn, S1, now=evening(S1))
    assert any(u['ticker'] == 'U00' for u in groups['main_buy'])
    assert not any(u['ticker'] == 'U05' for u in groups['main_buy'])


def test_invalid_screen_plan_stays_read_only(offline):
    class FlippingEarnings:
        """First fetch says the date is far away, later fetches move it inside plan validity."""
        def __init__(self, first, then):
            self.first, self.then, self.calls = first, then, {}

        def __call__(self, ticker):
            n = self.calls.get(ticker, 0)
            self.calls[ticker] = n + 1
            day = self.first if n == 0 else self.then
            return {'Earnings Date': [day.isoformat()]}

    seed_watchlist(offline)
    deps = make_deps(earnings=FlippingEarnings(add_trading_days(S1, 20), add_trading_days(S1, 2)))
    service.run_batch(now=evening(S1), deps=deps)
    view = service.today(now=evening(S1))
    assert not any(u['ticker'] == 'U01' for u in view['units'])
    u01 = next(u for u in view['extended_units'] if u['ticker'] == 'U01')
    assert u01['plan'] is not None and u01['plan']['status'] == 'invalid'
    assert 'earnings_in_validity' in u01['plan']['invalid_reasons']


def test_retention_and_eviction(offline):
    seed_watchlist(offline)
    service.run_batch(now=evening(S1), deps=make_deps())
    for k in range(1, 10):                                     # S1+1 .. S1+9: U00 stays a member
        batch = service.run_batch(now=evening(add_trading_days(S1, k)), deps=make_deps())
        assert 'U00' in batch['screen']['members']
        assert 'U00' not in batch['screen']['removed']
    batch = service.run_batch(now=evening(add_trading_days(S1, 10)), deps=make_deps())
    assert 'U00' not in batch['screen']['members']
    assert 'U00' in batch['screen']['removed']
    assert 'U00' not in batch['screen']['evicted']              # expired, not crowded out
    entry = repository.pool_entry_at(offline, 'U00', add_trading_days(S1, 10),
                                     cutoff_at=evening(add_trading_days(S1, 11)))
    assert entry['tier'] == 'removed' and entry['source'] == 'screen'


def test_rerun_same_session_is_stable(offline):
    seed_watchlist(offline)
    deps = make_deps()
    first = service.run_batch(now=evening(S1), deps=deps)
    tiers = offline.execute('SELECT count(*) FROM pool_tiers').fetchone()[0]
    second = service.run_batch(now=evening(S1), deps=deps)
    runs = offline.execute('SELECT count(*) FROM screen_runs').fetchone()[0]
    assert runs == 2
    assert offline.execute('SELECT count(*) FROM pool_tiers').fetchone()[0] == tiers
    assert second['screen']['selected'] == first['screen']['selected']


def test_universe_fetch_failures_are_skips_not_filters(offline):
    seed_watchlist(offline)
    failed = {f'U{i:02d}' for i in range(25, 30)}
    deps = make_deps(ScreenSources(fail=failed))
    batch = service.run_batch(now=evening(S1), deps=deps)
    assert batch['screen']['status'] == 'success'
    for t in failed:
        assert t in batch['sources']['bars']
        assert t in batch['screen']['skips']
    assert not (failed & set(batch['screen']['selected']))
    assert batch['screen']['counts']['no_setup'] == 0          # they were skipped, not filtered


def test_universe_missing_carries_members(offline):
    seed_watchlist(offline)
    deps = make_deps()
    service.run_batch(now=evening(S1), deps=deps)
    baseline = service.run_batch(now=evening(add_trading_days(S1, 1)), deps=deps)

    def broken_loader():
        raise universe_module.UniverseError('config/universes/missing.json: cannot read')

    day2 = add_trading_days(S1, 2)
    batch = service.run_batch(now=evening(day2),
                              deps=service.Deps(bar_fetcher=deps.bar_fetcher, news_fetcher=deps.news_fetcher,
                                                filing_source=deps.filing_source,
                                                earnings_fetcher=deps.earnings_fetcher,
                                                universe_loader=broken_loader))
    screen = batch['screen']
    assert screen['status'] == 'error' and 'universe' in screen['error']
    assert sorted(screen['members']) == sorted(baseline['screen']['members'])   # retention only, no new picks
    assert any(str(e).startswith('screen:') for e in batch['errors'])
    assert 'regime_universe_missing' in batch['errors']
    error_runs = offline.execute("SELECT count(*) FROM screen_runs WHERE status = 'error'").fetchone()[0]
    assert error_runs == 1

    # QQQ losing its bar fails the whole run the same way: benchmark_missing, members carried.
    day3 = add_trading_days(S1, 3)
    batch = service.run_batch(now=evening(day3), deps=make_deps(ScreenSources(qqq_last=add_trading_days(S1, 1))))
    assert batch['screen']['error'] == 'benchmark_missing'
    assert sorted(batch['screen']['members']) == sorted(baseline['screen']['members'])


def test_universe_stale_flag(offline):
    seed_watchlist(offline)
    stale = universe_module.Universe('test', S1 - timedelta(days=121), 'test', UNIVERSE_TICKERS)
    batch = service.run_batch(now=evening(S1), deps=make_deps(universe=stale))
    assert 'universe_stale' in batch['screen']['flags']
    assert batch['screen']['status'] == 'success' and len(batch['screen']['selected']) == 20


def test_manual_source_flip(offline):
    seed_watchlist(offline)
    deps = make_deps()
    service.run_batch(now=evening(S1), deps=deps)
    day1 = add_trading_days(S1, 1)
    offline.execute("INSERT INTO watchlist_items (ticker, status, tags) VALUES ('U03', 'active', '{}')")
    offline.commit()
    service.run_batch(now=evening(day1), deps=deps)
    entry = repository.pool_entry_at(offline, 'U03', day1, cutoff_at=evening(day1) + timedelta(hours=1))
    assert entry == {'tier': 'extended', 'sector_etf': None, 'source': 'watchlist'}
    day2 = add_trading_days(S1, 2)
    offline.execute("DELETE FROM watchlist_items WHERE ticker = 'U03'")
    offline.commit()
    service.run_batch(now=evening(day2), deps=deps)
    entry = repository.pool_entry_at(offline, 'U03', day2, cutoff_at=evening(day2) + timedelta(hours=1))
    assert entry == {'tier': 'extended', 'sector_etf': None, 'source': 'screen'}


def test_explicit_tickers_skip_screen(offline):
    seed_watchlist(offline)
    batch = service.run_batch(now=evening(S1), tickers=['SYNTH'], deps=make_deps())
    assert batch['screen'] == {'status': 'skipped', 'reason': 'explicit_pool'}
    assert offline.execute('SELECT count(*) FROM screen_runs').fetchone()[0] == 0


class PushSpy:
    def __init__(self):
        self.payloads = []

    def send(self, channel, payload):
        self.payloads.append(payload)
        return 'ok'


def test_force_push_reads_screen_from_db(offline, monkeypatch):
    from investment_assistant.config import NotifyConfig
    seed_watchlist(offline)
    service.run_batch(now=evening(S1), deps=make_deps())
    spy = PushSpy()
    out = service.push(now=evening(S1) + timedelta(hours=1), force=True, summary=None,
                       notify_cfg=NotifyConfig(), client=spy)
    assert out['sent'] is True
    pushed = '\n'.join(str(p) for p in spy.payloads)
    assert 'U00' in pushed
    assert len(spy.payloads) == 5


def test_replay_is_read_only(offline, monkeypatch):
    seed_watchlist(offline)
    deps = make_deps()
    service.run_batch(now=evening(S1), deps=deps)
    service.run_batch(now=evening(add_trading_days(S1, 1)), deps=deps)
    tables = ('screen_runs', 'screen_results', 'pool_tiers', 'trade_plans', 'signal_candidates')
    before = {t: offline.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables}
    monkeypatch.setattr(universe_module, 'load',
                        lambda: universe_module.Universe('test', S1, 'test', UNIVERSE_TICKERS))
    reports = service.replay_screen(now=evening(add_trading_days(S1, 1)), sessions=2)['reports']
    assert [r['session'] for r in reports] == [add_trading_days(S1, 1).isoformat(), S1.isoformat()]
    s1_run = repository.latest_screen_run(offline, session=S1)
    stored_selected = [r['ticker'] for r in repository.screen_results(offline, s1_run['id']) if r['selected']]
    assert reports[1]['selected'] == stored_selected
    assert all(r.get('note') == '财报日用当前已知值，非当时时点值' for r in reports)
    after = {t: offline.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables}
    assert after == before


def test_replay_bounds(offline):
    for n in (0, 21):
        with pytest.raises(ValueError):
            service.replay_screen(now=evening(S1), sessions=n)
