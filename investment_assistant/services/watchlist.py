from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

from investment_assistant.api.http import parse_payload_tags
from investment_assistant.config import load_config
from investment_assistant.db import connect, delete_watchlist_item as db_delete_watchlist_item, list_watchlist_items, upsert_watchlist_item


def validated_symbol(value: str) -> str:
    from investment_assistant.ashare.domain import is_cn_symbol, stock_id
    if not isinstance(value, str):
        raise ValueError('证券代码必须为字符串')
    symbol = value.strip().upper()
    if is_cn_symbol(symbol):
        return stock_id(symbol).split(':')[-1]
    from investment_assistant.us_research.domain import stock_id as us_stock_id
    return us_stock_id(symbol).split(':')[-1]


def market_of(ticker: str) -> str:
    from investment_assistant.ashare.domain import is_cn_symbol
    return 'CN' if is_cn_symbol(validated_symbol(ticker)) else 'US'


def watchlist_rows(market: str | None = None, *, enriched: bool = False) -> list[dict[str, Any]]:
    if market not in {None, 'CN', 'US'}:
        raise ValueError('market只能为CN或US')
    database_url = os.environ.get('INVESTMENT_ASSISTANT_DATABASE_URL')
    if not database_url:
        rows = _config_watchlist_rows()
        rows = [r for r in rows if market is None or _row_market(r) == market]
        return [_enrich(r, None) if enriched else _listed(r) for r in rows]
    with connect(database_url) as conn:
        rows = list_watchlist_items(conn)
        rows = [r for r in rows if market is None or _row_market(r) == market]
        return [_enrich(r, conn) if enriched else _listed(r) for r in rows]


def _row_market(row):
    try:
        return market_of(row.get('ticker'))
    except ValueError:
        return None


def _listed(row):
    if _row_market(row) is None:
        return {**row, 'market': None, 'identity_error': '证券身份无效，请删除后使用完整有效代码重新添加'}
    return row


def _enrich(row, conn):
    market = _row_market(row)
    result = {**_listed(row), 'market': market, 'name': None, 'board': None, 'latest_period': None,
              'datasets': {}, 'next_event': None}
    if conn is None or market is None:
        return result
    if market == 'US':
        from investment_assistant.us_research import repository as us_repo
        from investment_assistant.us_research.domain import stock_id as us_stock_id
        from investment_assistant.research.card_repository import get_card
        sid = us_stock_id(row['ticker'])
        states = us_repo.states(conn, sid)
        financials = us_repo.read_rows(conn, sid, 'financials')
        # Instant shares can be reported after the fiscal quarter; they are not a report period.
        periods = [r['end'] for r in financials if r.get('period_kind') == 'duration'
                   and r.get('start') and r.get('end') and r['start'] < r['end']]
        successful = states.get('financials', {}).get('last_success_details') or {}
        identity = successful.get('identity') or {}
        card = get_card(conn, sid)
        event = ((card or {}).get('body') or {}).get('improvement') or {}
        event_date = event.get('next_event_date')
        next_event = ({'date': event_date, 'kind': 'research_verification', 'title': event.get('next_event')}
                      if event_date and str(event_date) >= date.today().isoformat() else None)
        result.update(name=identity.get('name'), latest_period=max(periods, default=None),
                      datasets=states, next_event=next_event)
        return result
    from investment_assistant.ashare import repository as repo
    from investment_assistant.ashare.domain import stock_id
    sid = stock_id(row['ticker'])
    profiles = repo.read_rows(conn, sid, 'profile')
    financials = repo.read_rows(conn, sid, 'financials')
    profile = profiles[-1] if profiles else {}
    periods = [r['period_end'] for r in financials if r.get('period_end')]
    events = [{'date': r.get('scheduled_date'), 'kind': 'disclosure', 'period': r.get('period_end')}
              for r in repo.read_rows(conn, sid, 'disclosure') if not r.get('actual_date')]
    events += [{'date': r.get('event_date'), 'kind': 'unlock'} for r in repo.read_rows(conn, sid, 'unlocks')]
    events = sorted((e for e in events if e['date'] and str(e['date']) >= date.today().isoformat()), key=lambda e: str(e['date']))
    result.update(name=profile.get('name'), board=profile.get('board'), latest_period=max(periods, default=None),
                  datasets=repo.states(conn, sid), next_event=events[0] if events else None)
    return result


def current_watchlist() -> list[str]:
    """Legacy consumers get only active US entries; an empty selection stays empty."""
    return [str(r['ticker']).upper() for r in watchlist_rows()
            if r.get('ticker') and r.get('status', 'active') == 'active' and _row_market(r) == 'US']


def resolve_candidates(symbol: str) -> list[dict[str, Any]]:
    symbol = str(symbol).strip().upper()
    from investment_assistant.ashare import service
    from investment_assistant.ashare.domain import stock_id
    if re.fullmatch(r'\d{6}', symbol):
        symbols = []
        for exchange in ('SH', 'SZ', 'BJ'):
            try:
                symbols.append(stock_id(f'{symbol}.{exchange}').split(':')[-1])
            except ValueError:
                continue
        if not symbols:
            raise ValueError('没有可确认的A股股票身份；指数须单独指定类型')
    else:
        symbols = [validated_symbol(symbol)]
    return [service.resolve(s) if market_of(s) == 'CN' else {'symbol': s, 'market': 'US', 'asset_type': 'stock'} for s in symbols]


def add_watchlist_item(payload: dict[str, Any]) -> dict[str, Any]:
    database_url = os.environ.get('INVESTMENT_ASSISTANT_DATABASE_URL')
    if not database_url:
        raise ValueError('INVESTMENT_ASSISTANT_DATABASE_URL missing')
    ticker = validated_symbol(payload.get('ticker', ''))
    # Only complete identities are saved. A status edit never needs remote ingestion.
    if market_of(ticker) == 'CN' and 'expected_updated_at' not in payload:
        from investment_assistant.ashare.service import resolve
        identity = resolve(ticker)
        if validated_symbol(identity.get('symbol', '')) != ticker:
            raise ValueError('返回的证券身份与选择不一致')
    fields = {k: payload[k] for k in ('status', 'thesis', 'expected_updated_at') if k in payload}
    if 'tags' in payload:
        fields['tags'] = parse_payload_tags(payload['tags'])
    if 'expected_updated_at' in fields and not fields['expected_updated_at']:
        raise ValueError('编辑必须提供有效的expected_updated_at')
    with connect(database_url) as conn:
        _validate_pool_write(conn, ticker, fields)
        return upsert_watchlist_item(conn, ticker=ticker, **fields)


def _validate_pool_write(conn, ticker: str, fields: dict[str, Any]) -> None:
    """Pool caps and sector tags are checked before the write, on the would-be result."""
    from investment_assistant.ashare.domain import is_cn_symbol
    if is_cn_symbol(ticker):
        return
    rows = list_watchlist_items(conn, include_archived=True)
    existing = next((r for r in rows if r['ticker'] == ticker), None)
    status = fields.get('status') or (existing or {}).get('status') or 'active'
    if status != 'active':
        return  # only rows that are active US stocks after the write join the pool
    merged = dict(existing) if existing else {'ticker': ticker, 'thesis': None, 'tags': []}
    merged['ticker'] = ticker
    merged['status'] = status
    if 'tags' in fields:
        merged['tags'] = fields['tags']
    result = [merged if r['ticker'] == ticker else r for r in rows] if existing else rows + [merged]
    from investment_assistant.workbench.pool import from_watchlist
    from_watchlist(result)


def delete_watchlist_item(ticker: str) -> dict[str, Any]:
    database_url = os.environ.get('INVESTMENT_ASSISTANT_DATABASE_URL')
    if not database_url:
        raise ValueError('INVESTMENT_ASSISTANT_DATABASE_URL missing')
    with connect(database_url) as conn:
        return db_delete_watchlist_item(conn, ticker)


def _config_watchlist_rows() -> list[dict[str, Any]]:
    return [{'ticker': ticker, 'status': 'active', 'thesis': '来自配置文件的默认标的', 'tags': [], 'source': 'config'} for ticker in load_config().watchlist]
