"""All workbench SQL. Callers own transactions: this layer never commits or rolls back."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg.rows import dict_row

BAR_VALUES = ('open', 'high', 'low', 'close', 'adj_close', 'volume', 'split_factor')
_FLOAT_FIELDS = ('open', 'high', 'low', 'close', 'adj_close', 'split_factor')


def _quantized(row: dict[str, Any]) -> tuple:
    return tuple(int(row[k]) if k == 'volume' else Decimal(row[k]).quantize(Decimal('0.000001'))
                 for k in BAR_VALUES)


def store_bars(conn, ticker: str, rows: list[dict[str, Any]], *, now: datetime) -> dict[str, int]:
    """Append a revision only when values differ from the latest one.

    Dividends rewrite historical adj_close, so a re-fetch after one appends new
    revisions for older dates; earlier revisions stay readable by cutoff.
    """
    ticker = ticker.upper()
    counts = {'inserted': 0, 'unchanged': 0}
    with conn.cursor(row_factory=dict_row) as cur:
        for row in rows:
            cur.execute(
                f"SELECT revision, {', '.join(BAR_VALUES)} FROM price_bars "
                'WHERE ticker = %s AND price_date = %s ORDER BY revision DESC LIMIT 1',
                (ticker, row['price_date']))
            latest = cur.fetchone()
            if latest and _quantized(latest) == _quantized(row):
                counts['unchanged'] += 1
                continue
            cur.execute(
                f"INSERT INTO price_bars (ticker, price_date, {', '.join(BAR_VALUES)}, revision, fetched_at) "
                f"VALUES (%s, %s, {', '.join(['%s'] * len(BAR_VALUES))}, %s, %s)",
                (ticker, row['price_date'], *(row[k] for k in BAR_VALUES),
                 (latest['revision'] + 1) if latest else 1, now))
            counts['inserted'] += 1
    return counts


def read_bars(conn, ticker: str, end_date: date, *, cutoff_at: datetime, limit: int = 260) -> list[dict[str, Any]]:
    """Latest revision per date known by ``cutoff_at``, oldest first, at most ``limit`` dates."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT DISTINCT ON (price_date) id, price_date, revision, fetched_at, {', '.join(BAR_VALUES)} "
            'FROM price_bars WHERE ticker = %s AND price_date <= %s AND fetched_at <= %s '
            'ORDER BY price_date DESC, revision DESC LIMIT %s',
            (ticker.upper(), end_date, cutoff_at, limit))
        rows = cur.fetchall()
    for row in rows:
        for key in _FLOAT_FIELDS:
            row[key] = float(row[key])
    return list(reversed(rows))


def _news_hash(item: dict[str, Any]) -> str:
    payload = {k: item.get(k) for k in ('title', 'publisher')}
    payload['published_at'] = item['published_at'].isoformat() if item.get('published_at') else None
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def store_news(conn, entries: list[tuple[dict[str, Any], list[str]]], *, now: datetime) -> dict[str, int]:
    """First sighting wins: a re-fetched (source, url) keeps its original row and fetched_at."""
    counts = {'inserted': 0, 'existing': 0}
    with conn.cursor() as cur:
        for item, tickers in entries:
            cur.execute(
                'INSERT INTO news_items (source, title, url, publisher, published_at, fetched_at, content_hash) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (source, url) DO NOTHING RETURNING id',
                (item['source'], item['title'], item['url'], item.get('publisher'), item.get('published_at'),
                 now, _news_hash(item)))
            row = cur.fetchone()
            if row:
                counts['inserted'] += 1
            else:
                counts['existing'] += 1
                cur.execute('SELECT id FROM news_items WHERE source = %s AND url = %s', (item['source'], item['url']))
                row = cur.fetchone()
            for ticker in tickers:
                cur.execute('INSERT INTO news_item_tickers (news_item_id, ticker) VALUES (%s, %s) '
                            'ON CONFLICT DO NOTHING', (row[0], ticker.upper()))
    return counts


def read_news(conn, ticker: str, *, cutoff_at: datetime, since: datetime | None = None,
              limit: int = 50) -> list[dict[str, Any]]:
    """News known by ``cutoff_at``; undated items are kept and must be shown as such."""
    clauses = ['t.ticker = %s', 'n.fetched_at <= %s', '(n.published_at IS NULL OR n.published_at <= %s)']
    params: list[Any] = [ticker.upper(), cutoff_at, cutoff_at]
    if since is not None:
        clauses.append('COALESCE(n.published_at, n.fetched_at) >= %s')
        params.append(since)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            'SELECT n.id, n.source, n.title, n.url, n.publisher, n.published_at, n.fetched_at '
            'FROM news_items n JOIN news_item_tickers t ON t.news_item_id = n.id '
            f"WHERE {' AND '.join(clauses)} "
            'ORDER BY COALESCE(n.published_at, n.fetched_at) DESC, n.id DESC LIMIT %s',
            (*params, limit))
        return cur.fetchall()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def store_candidate(conn, ticker: str, signal_date: date, candidate, *, run_id: str | None) -> dict[str, Any]:
    """Insert once per (ticker, date, rule, version). A re-run with other inputs is a conflict, never an overwrite."""
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO signal_candidates (ticker, signal_date, action, rule_id, rule_version, inputs, run_id) '
            'VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s) '
            'ON CONFLICT (ticker, signal_date, rule_id, rule_version) DO NOTHING RETURNING id',
            (ticker.upper(), signal_date, candidate.action, candidate.rule_id, candidate.rule_version,
             _canonical(candidate.inputs), run_id))
        row = cur.fetchone()
        if row:
            return {'status': 'inserted', 'id': row[0]}
        cur.execute(
            'SELECT id, action, inputs FROM signal_candidates '
            'WHERE ticker = %s AND signal_date = %s AND rule_id = %s AND rule_version = %s',
            (ticker.upper(), signal_date, candidate.rule_id, candidate.rule_version))
        existing_id, action, inputs = cur.fetchone()
    same = action == candidate.action and _canonical(inputs) == _canonical(json.loads(_canonical(candidate.inputs)))
    return {'status': 'existing', 'id': existing_id} if same else {'status': 'conflict', 'id': existing_id}


def open_candidate_groups(conn, *, since: date) -> list[dict[str, Any]]:
    """Candidates grouped by (ticker, signal_date) that have no decision yet, newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            'SELECT c.id, c.ticker, c.signal_date, c.action, c.rule_id, c.rule_version, c.inputs, c.created_at '
            'FROM signal_candidates c WHERE c.signal_date >= %s AND NOT EXISTS ('
            '  SELECT 1 FROM signal_decisions d WHERE d.ticker = c.ticker AND d.signal_date = c.signal_date) '
            'ORDER BY c.signal_date DESC, c.ticker, c.created_at, c.rule_id', (since,))
        rows = cur.fetchall()
    groups: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = (row['ticker'], row['signal_date'])
        groups.setdefault(key, {'ticker': key[0], 'signal_date': key[1], 'candidates': []})['candidates'].append(row)
    return list(groups.values())


def store_brief(conn, brief: dict[str, Any]):
    with conn.cursor() as cur:
        cur.execute(
            # clock_timestamp(): several briefs in one transaction must still order by creation.
            'INSERT INTO signal_briefs (ticker, signal_date, model, prompt_version, cutoff_at, input_refs, output, '
            'status, error, created_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, clock_timestamp()) '
            'RETURNING id',
            (brief['ticker'], brief['signal_date'], brief.get('model'), brief['prompt_version'], brief['cutoff_at'],
             _canonical(brief['input_refs']), _canonical(brief['output']), brief['status'], brief.get('error')))
        return cur.fetchone()[0]


def latest_brief(conn, ticker: str, signal_date: date) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            'SELECT id, ticker, signal_date, model, prompt_version, cutoff_at, input_refs, output, status, error, '
            'created_at FROM signal_briefs WHERE ticker = %s AND signal_date = %s '
            'ORDER BY created_at DESC, id DESC LIMIT 1', (ticker.upper(), signal_date))
        return cur.fetchone()
