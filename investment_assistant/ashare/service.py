"""A-share ingestion and views; all derived metrics are workbench calculations."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

from investment_assistant.db import connect, list_watchlist_items
from . import repository as repo
from .domain import (BENCHMARKS, CALENDAR_END, CALENDAR_SOURCE, CALENDAR_START,
                     comparison, financial_periods, last_closed_session, performance,
                     security_id, stock_id, today_cn, trading_dates)
from .sources import PublicSources, UPSTREAM_COMMIT

DATASETS = ('profile', 'bars', 'factors', 'financials', 'valuation', 'announcements', 'disclosure', 'unlocks')


def connection():
    url = os.environ.get('INVESTMENT_ASSISTANT_DATABASE_URL')
    if not url:
        raise ValueError('未配置数据库，尚未采集A股数据')
    return connect(url)


def window(start=None, end=None):
    end = date.fromisoformat(str(end)) if end else last_closed_session()
    start = date.fromisoformat(str(start)) if start else end - timedelta(days=400)
    if end > today_cn() or end < start or (end - start).days > 550:
        raise ValueError('行情窗口须为过去日期且不超过550个自然日')
    if start < CALENDAR_START or end > CALENDAR_END:
        raise ValueError('首批仅支持2025–2026已核实日历窗口')
    return start, end


def sync(symbols=None, *, start=None, end=None, datasets=None, retry_failed=False, source=None):
    start, end = window(start, end)
    # Daily prices must be completed sessions, never intraday values called a close.
    effective_end = min(end, last_closed_session())
    selected = list(datasets) if datasets is not None else list(DATASETS)
    if not selected or set(selected) - set(DATASETS):
        raise ValueError('未知或空的数据集')
    source = source or PublicSources()
    results = []
    with connection() as conn:
        if symbols is None:
            symbols = [r['ticker'] for r in list_watchlist_items(conn) if r['status'] == 'active' and r['ticker'].endswith(('.SH', '.SZ', '.BJ'))]
        if not symbols:
            raise ValueError('更新需要至少一只明确关注股票')
        sids = list(dict.fromkeys(stock_id(s) for s in symbols))
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext('ashare-sync'))")
            acquired = cur.fetchone()[0]
        conn.commit()
        if not acquired:
            raise ValueError('A股更新正在运行，请查看运行记录后重试')
        try:
            jobs = [(sid, ds) for offset in range(0, len(sids), 10)
                    for sid in sids[offset:offset + 10] for ds in selected]
            if 'bars' in selected:
                jobs += [(sid, 'bars') for sid in BENCHMARKS]
            for sid, ds in jobs:
                old_state = repo.states(conn, sid).get(ds)
                if retry_failed and old_state and old_state['status'] not in {'failed', 'partial'}:
                    results.append({'security_id': sid, 'dataset': ds, 'status': 'skipped'})
                    continue
                fetch_start = start
                if ds in {'bars', 'valuation'} and old_state and old_state['status'] == 'ready':
                    old_rows = repo.read_rows(conn, sid, ds)
                    dates = sorted(r['data_date'] for r in old_rows)
                    if dates and dates[0] <= start.isoformat():
                        # Overlap catches recent revisions; missing old holes require a full refresh.
                        fetch_start = max(start, date.fromisoformat(dates[-1]) - timedelta(days=10))
                try:
                    rows = getattr(source, ds)(sid, fetch_start, effective_end)
                    now = datetime.now(UTC)
                    inserted = repo.store_rows(conn, sid, ds, rows, now=now)
                    details = {'inserted_versions': inserted, 'fetch_start': str(fetch_start),
                               'requested_end': str(end), 'effective_end': str(effective_end)}
                    state = 'ready' if rows else 'empty'
                    if ds in {'bars', 'valuation'}:
                        available = repo.read_rows(conn, sid, ds)
                        present = {r['data_date'] for r in available}
                        missing = [d for d in trading_dates(start, effective_end) if d not in present]
                        details['missing_sessions'] = missing
                        if missing:
                            state = 'partial'
                    if ds == 'financials' and any(r['payload'].get(f) is None for r in rows
                            for f in ('revenue', 'parent_profit', 'deducted_profit', 'operating_cashflow', 'receivables', 'inventory')):
                        state = 'partial'
                        details['limitation'] = '部分财务字段缺失，详情保留null'
                    if ds == 'financials' and any(r['payload'].get('component_errors') for r in rows):
                        state = 'partial'
                        errors = {k: v for r in rows for k, v in r['payload'].get('component_errors', {}).items()}
                        details['component_errors'] = errors
                        details['limitation'] = '；'.join(f'{k}: {v}' for k, v in errors.items())
                    repo.collection_state(conn, sid, ds, status=state, start=start, end=effective_end,
                                          count=len(rows), details=details)
                    conn.commit()
                    results.append({'security_id': sid, 'dataset': ds, 'status': state,
                                    'rows': len(rows), 'inserted_versions': inserted})
                except Exception as exc:
                    conn.rollback()
                    # Adapters deliberately emit sanitized errors. Unexpected exception text may contain secrets.
                    from .sources import SourceError
                    error = str(exc) if isinstance(exc, (SourceError, ValueError)) else f'{type(exc).__name__}: 数据处理失败'
                    repo.collection_state(conn, sid, ds, status='failed', start=start, end=effective_end, error=error)
                    conn.commit()
                    results.append({'security_id': sid, 'dataset': ds, 'status': 'failed', 'error': error})
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtext('ashare-sync'))")
            conn.commit()
    return {'results': results, 'errors': [r for r in results if r['status'] in {'failed', 'partial'}],
            'window': {'start': str(start), 'end': str(effective_end)}, 'notifications': 'disabled'}


def adjusted_bars(raw, factors, end, *, basis):
    if basis not in {'raw', 'qfq', 'hfq'}:
        raise ValueError('价格口径只能为raw/qfq/hfq')
    if basis == 'raw':
        return [dict(r, price_basis='raw') for r in raw]
    values = factors[-1]['factors'] if factors else []

    def factor_at(d):
        candidates = [f['factor'] for f in values if f['date'] <= d]
        return candidates[-1] if candidates else None

    anchor = factor_at(end)
    out = []
    for row in raw:
        f = factor_at(row['date'])
        multiplier = f / anchor if basis == 'qfq' and f and anchor else (f if basis == 'hfq' else None)
        result = {**row, 'price_basis': basis, 'factor': f, 'anchor_factor': anchor,
                  'factor_observation_id': factors[-1]['id'] if factors else None}
        for key in ('open', 'close', 'high', 'low'):
            result[key] = row[key] * multiplier if multiplier is not None else None
        out.append(result)
    return out


def describe_status(state, rows, dataset, *, now=None):
    now = now or datetime.now(UTC)
    if not state:
        return {'dataset': dataset, 'status': 'never_collected', 'row_count': 0, 'missing_reason': '尚未采集'}
    status = state['status']
    if status in {'ready', 'empty'} and state.get('succeeded_at') and now - state['succeeded_at'] > timedelta(days=2):
        status = 'stale'
    if dataset in {'bars', 'valuation'} and status == 'ready' and rows:
        try:
            if max(r['data_date'] for r in rows) < last_closed_session(now).isoformat():
                status = 'stale'
        except ValueError:
            status = 'stale'
    dates = sorted(r['data_date'] for r in rows if r.get('data_date'))
    return {**state, 'status': status, 'stored_rows': len(rows),
            'coverage_start': dates[0] if dates else None, 'coverage_end': dates[-1] if dates else None,
            'first_collected_at': min((r['first_seen_at'] for r in rows), default=None),
            'retained_old_values': status in {'failed', 'stale', 'empty'} and bool(rows)}


def checked_valuation(row, financials):
    if row is None:
        return None
    result = dict(row)
    eligible = [f for f in financials if f['period_end'] <= row['date']
                and f.get('first_disclosed_date') and f['first_disclosed_date'] <= row['date']]
    if eligible:
        latest = max(eligible, key=lambda f: f['period_end'])
        profit = latest.get('ttm', {}).get('parent_profit')
        if profit is not None and profit <= 0:
            result.update(pe_ttm=None, source_pe_ttm=row.get('pe_ttm'),
                          pe_status='已采集可比TTM归母利润非正，常规PE不适用；来源值保留供核对')
    return result


def view(symbol, *, start=None, end=None, basis='qfq', as_of=None):
    sid = stock_id(symbol)
    start, end = window(start, end)
    cutoff = datetime.fromisoformat(as_of) if as_of else None
    if cutoff and cutoff.tzinfo is None:
        raise ValueError('历史观察截止时间必须包含时区')
    with connection() as conn:
        rows = {ds: repo.read_rows(conn, sid, ds, as_of=cutoff) for ds in DATASETS}
        states = repo.states(conn, sid)
        statuses = [describe_status(states.get(ds), rows[ds], ds) for ds in DATASETS]
        firsts = repo.first_collection(conn, sid)
        for s in statuses:
            s['first_collected_at'] = firsts.get(s['dataset'])
            if cutoff and not rows[s['dataset']]:
                s['status'] = 'unavailable_at_cutoff'
                s['missing_reason'] = '该截止时间前，本机尚无已观察且可用的版本'
            if s['dataset'] in {'bars', 'valuation'} and s['status'] == 'ready':
                present = {r['data_date'] for r in rows[s['dataset']]}
                absent = [d for d in trading_dates(start, min(end, last_closed_session())) if d not in present]
                if absent:
                    s['status'] = 'partial'
                    s['details'] = {**s.get('details', {}), 'missing_sessions': absent}
        raw = [r for r in rows['bars'] if start.isoformat() <= r['date'] <= end.isoformat()]
        bars = adjusted_bars(raw, rows['factors'], raw[-1]['date'] if raw else end.isoformat(), basis=basis)
        comparisons = []
        for bid, meta in BENCHMARKS.items():
            benchmarks = repo.read_rows(conn, bid, 'bars', as_of=cutoff)
            bwindow = [r for r in benchmarks if start.isoformat() <= r['date'] <= end.isoformat()]
            state = describe_status(repo.states(conn, bid).get('bars'), benchmarks, 'bars')
            if cutoff and not benchmarks:
                state['status'] = 'unavailable_at_cutoff'
                state['missing_reason'] = '该截止时间前，本机尚无已观察的基准版本'
            comparisons.append({'security_id': bid, **meta, **comparison(bars, bwindow), 'collection': state,
                                'basis': f'个股{basis}价格收益 vs 官方价格指数（非全收益指数）'})
        card = repo.get_card(conn, sid)
        if cutoff and card and card['updated_at'] > cutoff:
            card = None  # Current research must not leak into a historical data view.
    profiles = rows['profile']
    financials = financial_periods(rows['financials'])
    valuation = [r for r in rows['valuation'] if r['date'] <= end.isoformat()]
    expected = trading_dates(start, min(end, last_closed_session()))
    missing = [d for d in expected if d not in {r['date'] for r in raw}]
    return {'security_id': sid, 'profile': profiles[-1] if profiles else None,
        'window': {'start': str(start), 'end': str(end)}, 'statuses': statuses,
        'bars': bars, 'raw_bars': raw, 'performance': performance(bars),
        'adjustment': {'basis': basis, 'factor_source': '新浪后复权乘数', 'missing_sessions': sum(r.get('close') is None for r in bars),
            'formula': '后复权=原价×当日累计因子；前复权=原价×当日因子/窗口末端因子；量额不复权',
            'limit': '复权是当前因子快照；无因子不补1，缺失价格留空。回填与复权均非启用前严格PIT。'},
        'coverage': {'requested_sessions': len(expected), 'present_sessions': len(raw), 'missing_sessions': missing,
                     'note': '缺行可能停牌或来源缺失，未核实停牌前不自动填充'},
        'financials': financials, 'valuation': checked_valuation(valuation[-1] if valuation else None, financials),
        'announcements': sorted([r for r in rows['announcements'] if start.isoformat() <= r['notice_date'] <= end.isoformat()],
                                key=lambda r: r['notice_date'], reverse=True),
        'disclosure': rows['disclosure'], 'unlocks': rows['unlocks'], 'comparisons': comparisons,
        'calendar': {'timezone': 'Asia/Shanghai', 'coverage_start': str(CALENDAR_START), 'coverage_end': str(CALENDAR_END),
                     'source_url': CALENDAR_SOURCE, 'next_year': '2027尚未核实，调度到期报错，不按工作日猜测'},
        'pit': {'mode': 'observed_versions_only' if cutoff else 'latest_collected_snapshot', 'strict': False,
                'as_of': as_of, 'note': '历史筛选同时要求首次采集与保守披露可用时间不晚于截止；本机采集前不提供历史值。'},
        'upstream': {'name': 'CNEquity', 'version': '0.16.0', 'commit': UPSTREAM_COMMIT}, 'card': card}


def resolve(symbol):
    sid = stock_id(symbol)
    with connection() as conn:
        rows = repo.read_rows(conn, sid, 'profile')
    if not rows:
        outcome = sync([symbol], datasets=['profile'])
        if outcome['errors']:
            raise ValueError(outcome['errors'][0]['error'])
        with connection() as conn:
            rows = repo.read_rows(conn, sid, 'profile')
    if not rows:
        raise ValueError('没有证券主数据，无法确认身份')
    return {'security_id': sid, **rows[-1]}
