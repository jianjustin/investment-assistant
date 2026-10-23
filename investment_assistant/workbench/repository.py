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


# yfinance re-derives adj_close with ~1e-7 relative float noise between fetches; a real dividend
# adjustment is around 1e-3 or larger. Raw prices and volume still compare exactly.
ADJ_CLOSE_TOLERANCE = Decimal('0.000001')


def _quantized(row: dict[str, Any]) -> tuple:
    return tuple(int(row[k]) if k == 'volume' else Decimal(row[k]).quantize(Decimal('0.000001'))
                 for k in BAR_VALUES if k != 'adj_close')


def _same_bar(stored: dict[str, Any], fetched: dict[str, Any]) -> bool:
    if _quantized(stored) != _quantized(fetched):
        return False
    old, new = Decimal(stored['adj_close']), Decimal(fetched['adj_close'])
    return abs(new - old) <= abs(old) * ADJ_CLOSE_TOLERANCE


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
            if latest and _same_bar(latest, row):
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


def lock(conn, key: str) -> None:
    """Transaction-scoped advisory lock serialising writes to one unit or ticker."""
    conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (key,))


_DECISION_COLUMNS = ('id, request_id, request_hash, ticker, signal_date, candidate_ids, brief_id, proposed_action, '
                     'final_action, decision, reason, decided_at, supersedes_id')
_TRADE_COLUMNS = ('id, request_id, request_hash, ticker, side, quantity, price, fee, executed_at, decision_id, note, '
                  'recorded_at, voided_at, void_reason')


def _one(conn, sql: str, params) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _all(conn, sql: str, params) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def decision_by_request(conn, request_id):
    return _one(conn, f'SELECT {_DECISION_COLUMNS} FROM signal_decisions WHERE request_id = %s', (request_id,))


def decision_by_id(conn, decision_id):
    return _one(conn, f'SELECT {_DECISION_COLUMNS} FROM signal_decisions WHERE id = %s', (decision_id,))


def decision_head(conn, ticker: str, signal_date: date) -> dict[str, Any] | None:
    """The unit's current decision: the one no other decision supersedes."""
    return _one(conn,
                f'SELECT {_DECISION_COLUMNS} FROM signal_decisions d WHERE ticker = %s AND signal_date = %s '
                'AND NOT EXISTS (SELECT 1 FROM signal_decisions s WHERE s.supersedes_id = d.id) '
                'ORDER BY decided_at DESC LIMIT 1', (ticker, signal_date))


def decision_heads(conn, *, since: date | None = None, ticker: str | None = None) -> list[dict[str, Any]]:
    clauses = ['NOT EXISTS (SELECT 1 FROM signal_decisions s WHERE s.supersedes_id = d.id)']
    params: list[Any] = []
    if since is not None:
        clauses.append('signal_date >= %s')
        params.append(since)
    if ticker is not None:
        clauses.append('ticker = %s')
        params.append(ticker.upper())
    return _all(conn, f"SELECT {_DECISION_COLUMNS} FROM signal_decisions d WHERE {' AND '.join(clauses)} "
                      'ORDER BY signal_date, ticker', params)


def count_unit_candidates(conn, ticker: str, signal_date: date, ids) -> int:
    return conn.execute('SELECT count(*) FROM signal_candidates WHERE ticker = %s AND signal_date = %s AND id = ANY(%s)',
                        (ticker, signal_date, list(ids))).fetchone()[0]


def brief_in_unit(conn, brief_id, ticker: str, signal_date: date) -> bool:
    return conn.execute('SELECT 1 FROM signal_briefs WHERE id = %s AND ticker = %s AND signal_date = %s',
                        (brief_id, ticker, signal_date)).fetchone() is not None


def insert_decision(conn, rec: dict[str, Any], digest: str, *, decided_at: datetime) -> dict[str, Any]:
    return _one(conn,
                'INSERT INTO signal_decisions (request_id, request_hash, ticker, signal_date, candidate_ids, brief_id, '
                'proposed_action, final_action, decision, reason, decided_at, supersedes_id) '
                f'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_DECISION_COLUMNS}',
                (rec['request_id'], digest, rec['ticker'], rec['signal_date'], rec['candidate_ids'], rec['brief_id'],
                 rec['proposed_action'], rec['final_action'], rec['decision'], rec['reason'], decided_at,
                 rec['supersedes_id']))


def trade_by_request(conn, request_id):
    return _one(conn, f'SELECT {_TRADE_COLUMNS} FROM trades WHERE request_id = %s', (request_id,))


def trade_by_id(conn, trade_id):
    return _one(conn, f'SELECT {_TRADE_COLUMNS} FROM trades WHERE id = %s', (trade_id,))


def list_trades(conn, ticker: str | None = None) -> list[dict[str, Any]]:
    if ticker is None:
        return _all(conn, f'SELECT {_TRADE_COLUMNS} FROM trades ORDER BY executed_at, id', ())
    return _all(conn, f'SELECT {_TRADE_COLUMNS} FROM trades WHERE ticker = %s ORDER BY executed_at, id', (ticker.upper(),))


def insert_trade(conn, rec: dict[str, Any], digest: str, *, recorded_at: datetime) -> dict[str, Any]:
    return _one(conn,
                'INSERT INTO trades (request_id, request_hash, ticker, side, quantity, price, fee, executed_at, '
                f'decision_id, note, recorded_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_TRADE_COLUMNS}',
                (rec['request_id'], digest, rec['ticker'], rec['side'], rec['quantity'], rec['price'], rec['fee'],
                 rec['executed_at'], rec['decision_id'], rec['note'], recorded_at))


def mark_trade_voided(conn, trade_id, reason: str, *, voided_at: datetime) -> dict[str, Any]:
    # The only post-insert write in the workbench: status fields, never the trade itself.
    return _one(conn, f'UPDATE trades SET voided_at = %s, void_reason = %s WHERE id = %s AND voided_at IS NULL '
                      f'RETURNING {_TRADE_COLUMNS}', (voided_at, reason, trade_id))


def split_events(conn, ticker: str) -> list[tuple[date, Decimal]]:
    rows = conn.execute(
        'SELECT price_date, split_factor FROM (SELECT DISTINCT ON (price_date) price_date, split_factor '
        '  FROM price_bars WHERE ticker = %s ORDER BY price_date, revision DESC) latest '
        'WHERE split_factor <> 1 ORDER BY price_date', (ticker.upper(),)).fetchall()
    return [(d, Decimal(f)) for d, f in rows]


_WEEKLY_COLUMNS = 'id, week_start, calc_version, stats, notes, supersedes_id, created_at'


def weekly_head(conn, week_start: date) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_WEEKLY_COLUMNS} FROM weekly_reviews w WHERE week_start = %s AND NOT EXISTS '
                      '(SELECT 1 FROM weekly_reviews s WHERE s.supersedes_id = w.id)', (week_start,))


def weekly_heads(conn, limit: int) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_WEEKLY_COLUMNS} FROM weekly_reviews w WHERE NOT EXISTS '
                      '(SELECT 1 FROM weekly_reviews s WHERE s.supersedes_id = w.id) '
                      'ORDER BY week_start DESC LIMIT %s', (limit,))


def insert_weekly_review(conn, week_start: date, calc_version: str, stats: dict[str, Any], notes: str,
                         supersedes_id) -> dict[str, Any]:
    return _one(conn, 'INSERT INTO weekly_reviews (week_start, calc_version, stats, notes, supersedes_id) '
                      f'VALUES (%s, %s, %s::jsonb, %s, %s) RETURNING {_WEEKLY_COLUMNS}',
                (week_start, calc_version, _canonical(stats), notes, supersedes_id))


_EARNINGS_COLUMNS = 'id, ticker, earnings_date, status, source, fetched_at, created_at'


def store_earnings(conn, ticker: str, row: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Append only when the answer changed; a same-day re-fetch writes nothing."""
    latest = latest_earnings(conn, ticker, cutoff_at=now)
    if latest and latest['status'] == row['status'] and latest['earnings_date'] == row.get('earnings_date'):
        return {'status': 'unchanged', 'id': latest['id']}
    with conn.cursor() as cur:
        cur.execute('INSERT INTO earnings_dates (ticker, earnings_date, status, fetched_at) '
                    'VALUES (%s, %s, %s, %s) RETURNING id',
                    (ticker.upper(), row.get('earnings_date'), row['status'], now))
        return {'status': 'inserted', 'id': cur.fetchone()[0]}


def latest_earnings(conn, ticker: str, *, cutoff_at: datetime) -> dict[str, Any] | None:
    """The newest earnings answer known by ``cutoff_at``."""
    return _one(conn, f'SELECT {_EARNINGS_COLUMNS} FROM earnings_dates WHERE ticker = %s AND fetched_at <= %s '
                      'ORDER BY fetched_at DESC, created_at DESC LIMIT 1', (ticker.upper(), cutoff_at))


_CANDIDATE_COLUMNS = 'id, ticker, signal_date, action, rule_id, rule_version, inputs, run_id, created_at'


def unit_candidates(conn, ticker: str, signal_date: date) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_CANDIDATE_COLUMNS} FROM signal_candidates WHERE ticker = %s AND signal_date = %s '
                      'ORDER BY created_at, rule_id', (ticker.upper(), signal_date))


def read_candidates(conn, ticker: str, *, since: date) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_CANDIDATE_COLUMNS} FROM signal_candidates WHERE ticker = %s AND signal_date >= %s '
                      'ORDER BY signal_date DESC, created_at, rule_id', (ticker.upper(), since))


def candidates_by_ids(conn, ids) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_CANDIDATE_COLUMNS} FROM signal_candidates WHERE id = ANY(%s)', (list(ids),))


def read_filings(conn, ticker: str, *, since: date, cutoff_at: datetime) -> list[dict[str, Any]]:
    """Filings indexed by ``cutoff_at`` (created_at is when this system first stored them)."""
    return _all(conn, 'SELECT id, ticker, form, filing_date, accession_number, primary_document, accepted_at, items '
                      'FROM filings WHERE ticker = %s AND filing_date >= %s AND created_at <= %s '
                      'ORDER BY filing_date, id', (ticker.upper(), since, cutoff_at))


def market_status(conn, signal_date: date) -> str | None:
    if conn.execute("SELECT to_regclass('market_signals')").fetchone()[0] is None:
        return None
    row = conn.execute('SELECT market_status FROM market_signals WHERE signal_date = %s', (signal_date,)).fetchone()
    return row[0] if row else None


WORKBENCH_TABLES = ('price_bars', 'news_items', 'news_item_tickers', 'signal_candidates', 'signal_briefs',
                    'signal_decisions', 'trades', 'weekly_reviews', 'filings', 'trade_plans', 'earnings_dates',
                    'account_snapshots', 'cash_flows', 'monthly_reviews')


def missing_tables(conn) -> list[str]:
    row = conn.execute('SELECT ' + ', '.join(f"to_regclass('{t}')" for t in WORKBENCH_TABLES)).fetchone()
    missing = [t for t, found in zip(WORKBENCH_TABLES, row) if found is None]
    if 'filings' not in missing and conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'filings' AND column_name = 'accepted_at' "
            "AND table_schema = ANY(current_schemas(false))").fetchone() is None:
        missing.append('filings.accepted_at')
    return missing


def fill_filing_acceptance(conn, metas: list[dict[str, Any]]) -> int:
    """Copy SEC's acceptance time and items onto indexed filings that lack them; never overwrite."""
    filled = 0
    for meta in metas:
        accession, accepted = meta.get('accession_number'), meta.get('accepted_at')
        if not accession or (accepted is None and meta.get('items') is None):
            continue
        filled += conn.execute(
            'UPDATE filings SET accepted_at = COALESCE(accepted_at, %s), items = COALESCE(items, %s) '
            'WHERE accession_number = %s AND ((accepted_at IS NULL AND %s::timestamptz IS NOT NULL) '
            'OR (items IS NULL AND %s::text[] IS NOT NULL))',
            (accepted, meta.get('items'), accession, accepted, meta.get('items'))).rowcount
    return filled
