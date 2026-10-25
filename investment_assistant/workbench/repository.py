"""All workbench SQL. Callers own transactions: this layer never commits or rolls back."""
from __future__ import annotations

import hashlib
import json
import uuid
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
                     'final_action, decision, reason, decided_at, supersedes_id, plan_id')
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
                'proposed_action, final_action, decision, reason, decided_at, supersedes_id, plan_id) '
                f'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_DECISION_COLUMNS}',
                (rec['request_id'], digest, rec['ticker'], rec['signal_date'], rec['candidate_ids'], rec['brief_id'],
                 rec['proposed_action'], rec['final_action'], rec['decision'], rec['reason'], decided_at,
                 rec['supersedes_id'], rec.get('plan_id')))


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


_PLAN_COLUMNS = ('id, ticker, signal_date, kind, based_on_id, plan_version, ref_price, atr, entry_low, '
                 'entry_high, stop, target1, trail_atr_multiple, valid_from, valid_until, sizing, status, '
                 'invalid_reasons, warnings, inputs, request_id, request_hash, created_at')


def _plan_json(value: Any) -> str:
    """Canonical JSON with Decimals and dates as strings, stable across a jsonb round-trip."""
    def scalar(item: Any) -> Any:
        if isinstance(item, Decimal):
            return format(item.normalize(), 'f')
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, uuid.UUID):
            return str(item)
        raise TypeError(f'not JSON-serializable: {type(item)!r}')

    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, default=scalar)


def store_plan(conn, plan: dict[str, Any]) -> dict[str, Any]:
    """Insert once per rule unit; same levels/sizing/status returns the stored row, different is a conflict."""
    if plan.get('kind') == 'rule':
        existing = rule_plan(conn, plan['ticker'], plan['signal_date'], plan.get('plan_version', 'plan-1'))
        if existing is not None:
            same = (existing['status'] == plan['status']
                    and all(Decimal(existing[k]) == plan[k]
                            for k in ('ref_price', 'atr', 'entry_low', 'entry_high', 'stop', 'target1'))
                    and _plan_json(existing['sizing']) == _plan_json(plan['sizing']))
            if same:
                return {'status': 'existing', 'record': existing}
            return {'status': 'conflict', 'record': existing}
    return {'status': 'inserted', 'record': insert_plan(conn, plan)}


def insert_plan(conn, plan: dict[str, Any]) -> dict[str, Any]:
    return _one(conn,
                'INSERT INTO trade_plans (ticker, signal_date, kind, based_on_id, plan_version, ref_price, atr, '
                'entry_low, entry_high, stop, target1, trail_atr_multiple, valid_from, valid_until, sizing, '
                'status, invalid_reasons, warnings, inputs, request_id, request_hash) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, '
                f'%s, %s) RETURNING {_PLAN_COLUMNS}',
                (plan['ticker'], plan['signal_date'], plan['kind'], plan.get('based_on_id'),
                 plan.get('plan_version', 'plan-1'), plan['ref_price'], plan['atr'], plan['entry_low'],
                 plan['entry_high'], plan['stop'], plan['target1'], plan['trail_atr_multiple'],
                 plan['valid_from'], plan['valid_until'], _plan_json(plan['sizing']), plan['status'],
                 plan['invalid_reasons'], plan['warnings'], _plan_json(plan['inputs']),
                 plan.get('request_id'), plan.get('request_hash')))


def plan_for_buy_trades(conn, trade_ids: list) -> dict[Any, dict[str, Any]]:
    """Trade id -> the plan its decision confirmed, for trades that have one."""
    if not trade_ids:
        return {}
    plan_columns = ', '.join('p.' + c.strip() for c in _PLAN_COLUMNS.split(','))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f'SELECT t.id AS trade_id, {plan_columns} FROM trades t '
                    'JOIN signal_decisions d ON d.id = t.decision_id '
                    'JOIN trade_plans p ON p.id = d.plan_id WHERE t.id = ANY(%s)', (list(trade_ids),))
        return {row['trade_id']: {k: row[k] for k in row if k != 'trade_id'} for row in cur.fetchall()}


def plan_by_request(conn, request_id) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_PLAN_COLUMNS} FROM trade_plans WHERE request_id = %s', (request_id,))


def rule_plan(conn, ticker: str, signal_date: date, plan_version: str = 'plan-1') -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_PLAN_COLUMNS} FROM trade_plans WHERE ticker = %s AND signal_date = %s '
                      "AND kind = 'rule' AND plan_version = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (ticker.upper(), signal_date, plan_version))


def plan_by_id(conn, plan_id) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_PLAN_COLUMNS} FROM trade_plans WHERE id = %s', (plan_id,))


def plans_since(conn, since: date) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_PLAN_COLUMNS} FROM trade_plans WHERE signal_date >= %s '
                      'ORDER BY signal_date, created_at, id', (since,))


_SNAPSHOT_COLUMNS = ('id, request_id, request_hash, as_of, equity, note, recorded_at, supersedes_id, '
                    'created_at')
_FLOW_COLUMNS = 'id, request_id, request_hash, flow_date, amount, note, recorded_at, voided_at, void_reason'


def snapshot_by_request(conn, request_id):
    return _one(conn, f'SELECT {_SNAPSHOT_COLUMNS} FROM account_snapshots WHERE request_id = %s', (request_id,))


def snapshot_head(conn) -> dict[str, Any] | None:
    """The latest snapshot nothing else supersedes; a correction must target this row."""
    return _one(conn, f'SELECT {_SNAPSHOT_COLUMNS} FROM account_snapshots s WHERE NOT EXISTS '
                      '(SELECT 1 FROM account_snapshots x WHERE x.supersedes_id = s.id) '
                      'ORDER BY recorded_at DESC, created_at DESC LIMIT 1', ())


def insert_snapshot(conn, rec: dict[str, Any], digest: str, *, recorded_at: datetime) -> dict[str, Any]:
    return _one(conn, 'INSERT INTO account_snapshots (request_id, request_hash, as_of, equity, note, recorded_at, '
                      f'supersedes_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {_SNAPSHOT_COLUMNS}',
                (rec['request_id'], digest, rec['as_of'], rec['equity'], rec['note'], recorded_at,
                 rec['supersedes_id']))


def snapshot_at(conn, as_of: date, *, cutoff_at: datetime) -> dict[str, Any] | None:
    """Latest valid snapshot usable at ``cutoff_at``: recorded on time, not superseded, as_of on or before."""
    return _one(conn, f'SELECT {_SNAPSHOT_COLUMNS} FROM account_snapshots s WHERE s.as_of <= %s '
                      'AND s.recorded_at <= %s AND NOT EXISTS '
                      '(SELECT 1 FROM account_snapshots x WHERE x.supersedes_id = s.id) '
                      'ORDER BY s.as_of DESC, s.recorded_at DESC LIMIT 1', (as_of, cutoff_at))


def list_snapshots(conn) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_SNAPSHOT_COLUMNS} FROM account_snapshots ORDER BY recorded_at DESC, '
                      'created_at DESC', ())


def flow_by_request(conn, request_id):
    return _one(conn, f'SELECT {_FLOW_COLUMNS} FROM cash_flows WHERE request_id = %s', (request_id,))


def flow_by_id(conn, flow_id):
    return _one(conn, f'SELECT {_FLOW_COLUMNS} FROM cash_flows WHERE id = %s', (flow_id,))


def insert_flow(conn, rec: dict[str, Any], digest: str, *, recorded_at: datetime) -> dict[str, Any]:
    return _one(conn, 'INSERT INTO cash_flows (request_id, request_hash, flow_date, amount, note, recorded_at) '
                      f'VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_FLOW_COLUMNS}',
                (rec['request_id'], digest, rec['flow_date'], rec['amount'], rec['note'], recorded_at))


def mark_flow_voided(conn, flow_id, reason: str, *, voided_at: datetime) -> dict[str, Any]:
    # Status fields only, as with trades; the flow itself is never rewritten.
    return _one(conn, f'UPDATE cash_flows SET voided_at = %s, void_reason = %s WHERE id = %s AND voided_at IS NULL '
                      f'RETURNING {_FLOW_COLUMNS}', (voided_at, reason, flow_id))


def list_flows(conn) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_FLOW_COLUMNS} FROM cash_flows ORDER BY flow_date, created_at', ())


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


_MONTHLY_COLUMNS = 'id, month, calc_version, stats, notes, supersedes_id, created_at'


def insert_monthly_review(conn, month: date, calc_version: str, stats: dict[str, Any], notes: str,
                          supersedes_id) -> dict[str, Any]:
    return _one(conn, 'INSERT INTO monthly_reviews (month, calc_version, stats, notes, supersedes_id) '
                      f'VALUES (%s, %s, %s::jsonb, %s, %s) RETURNING {_MONTHLY_COLUMNS}',
                (month, calc_version, _plan_json(stats), notes, supersedes_id))


def monthly_head(conn, month: date) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_MONTHLY_COLUMNS} FROM monthly_reviews m WHERE month = %s AND NOT EXISTS '
                      '(SELECT 1 FROM monthly_reviews s WHERE s.supersedes_id = m.id) '
                      'ORDER BY created_at DESC LIMIT 1', (month,))


def monthly_heads(conn, limit: int) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_MONTHLY_COLUMNS} FROM monthly_reviews m WHERE NOT EXISTS '
                      '(SELECT 1 FROM monthly_reviews s WHERE s.supersedes_id = m.id) '
                      'ORDER BY month DESC, created_at DESC LIMIT %s', (limit,))


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
                    'account_snapshots', 'cash_flows', 'monthly_reviews', 'watchlist_items', 'pool_tiers',
                    'macro_observations', 'market_regimes', 'rule_backchecks', 'agent_runs', 'agent_tool_calls')


def store_macro(conn, series_id: str, rows: list[dict[str, Any]], *, now: datetime) -> dict[str, int]:
    """Append observations; the same date with a different value appends a revision."""
    counts = {'inserted': 0, 'unchanged': 0}
    with conn.cursor() as cur:
        for row in rows:
            cur.execute('SELECT value FROM macro_observations '
                        'WHERE series_id = %s AND obs_date = %s ORDER BY fetched_at DESC LIMIT 1',
                        (series_id, row['obs_date']))
            latest = cur.fetchone()
            if latest is not None and latest[0] == row['value']:
                counts['unchanged'] += 1
                continue
            cur.execute('INSERT INTO macro_observations (series_id, obs_date, value, fetched_at) '
                        'VALUES (%s, %s, %s, %s)', (series_id, row['obs_date'], row['value'], now))
            counts['inserted'] += 1
    return counts


def read_macro(conn, series_id: str, *, end_date: date, cutoff_at: datetime, limit: int = 60) -> list[dict[str, Any]]:
    """Per obs_date the newest row fetched by the cutoff, oldest first, at most `limit` dates."""
    with conn.cursor() as cur:
        cur.execute('SELECT DISTINCT ON (obs_date) obs_date, value FROM macro_observations '
                    'WHERE series_id = %s AND obs_date <= %s AND fetched_at <= %s '
                    'ORDER BY obs_date DESC, fetched_at DESC LIMIT %s',
                    (series_id, end_date, cutoff_at, limit))
        rows = cur.fetchall()
    return [{'obs_date': r[0], 'value': r[1]} for r in reversed(rows)]


_REGIME_COLUMNS = 'id, session, calc_version, label, breadth, sectors, macro, inputs, created_at'


def _regime_fingerprint(snap: dict[str, Any]) -> str:
    compared = {k: snap[k] for k in ('label', 'breadth', 'sectors', 'macro')}
    return json.dumps(compared, sort_keys=True, separators=(',', ':'), default=str)


def store_regime(conn, snap: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Insert a snapshot; same content returns the stored row, different content is a conflict."""
    from investment_assistant.workbench.regime import REGIME_VERSION
    existing = _one(conn, f'SELECT {_REGIME_COLUMNS} FROM market_regimes '
                         'WHERE session = %s AND calc_version = %s', (snap['session'], snap['calc_version']))
    if existing is not None:
        stored = _regime_fingerprint(existing)
        return {'status': 'existing' if stored == _regime_fingerprint(snap) else 'conflict', 'record': existing}
    def _dumps(value: Any) -> str:
        return json.dumps(value, default=str)  # macro values arrive as Decimal

    placeholders = ', '.join(['%s'] * (7 if now is None else 8))
    params = [snap['session'], REGIME_VERSION, snap['label'], _dumps(snap['breadth']),
              _dumps(snap['sectors']), _dumps(snap['macro']), _dumps(snap['inputs'])]
    if now is not None:
        params.append(now)
    record = _one(conn, f'INSERT INTO market_regimes (session, calc_version, label, breadth, sectors, macro, inputs'
                        f'{", created_at" if now is not None else ""}) '
                        f'VALUES ({placeholders}) RETURNING {_REGIME_COLUMNS}', params)
    return {'status': 'inserted', 'record': record}


def regime_for(conn, session: date, *, cutoff_at: datetime) -> dict[str, Any] | None:
    """The regime-1 snapshot of that session, as visible by the cutoff."""
    from investment_assistant.workbench.regime import REGIME_VERSION
    return _one(conn, f'SELECT {_REGIME_COLUMNS} FROM market_regimes '
                      'WHERE session = %s AND calc_version = %s AND created_at <= %s',
                (session, REGIME_VERSION, cutoff_at))


def latest_regime(conn, *, on_or_before: date, cutoff_at: datetime) -> dict[str, Any] | None:
    """The newest regime-1 snapshot at or before the date, visible by the cutoff."""
    from investment_assistant.workbench.regime import REGIME_VERSION
    return _one(conn, f'SELECT {_REGIME_COLUMNS} FROM market_regimes '
                      'WHERE session <= %s AND calc_version = %s AND created_at <= %s '
                      'ORDER BY session DESC, created_at DESC LIMIT 1',
                (on_or_before, REGIME_VERSION, cutoff_at))


_BACKCHECK_COLUMNS = 'id, calc_version, params, stats, created_at'


def insert_backcheck(conn, calc_version: str, params: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    """Freeze one backcheck run; rows are never rewritten."""
    return _one(conn, 'INSERT INTO rule_backchecks (calc_version, params, stats) '
                      f'VALUES (%s, %s::jsonb, %s::jsonb) RETURNING {_BACKCHECK_COLUMNS}',
                (calc_version, _canonical(params), _canonical(stats)))


def list_backchecks(conn, limit: int) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_BACKCHECK_COLUMNS} FROM rule_backchecks ORDER BY created_at DESC LIMIT %s',
                (limit,))


def pool_latest(conn) -> dict[str, dict[str, Any]]:
    """Each ticker's newest pool_tiers row: {'tier', 'sector_etf'}."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT DISTINCT ON (ticker) ticker, tier, sector_etf FROM pool_tiers '
                    'ORDER BY ticker, effective_session DESC, recorded_at DESC, id DESC')
        return {row['ticker']: {'tier': row['tier'], 'sector_etf': row['sector_etf']}
                for row in cur.fetchall()}


def insert_pool_tiers(conn, rows: list[dict[str, Any]], *, session: date, now: datetime) -> int:
    """Append tier change rows; callers only pass rows that actually changed."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO pool_tiers (ticker, tier, sector_etf, effective_session, recorded_at) '
                        'VALUES (%s, %s, %s, %s, %s)',
                        [(r['ticker'], r['tier'], r['sector_etf'], session, now) for r in rows])
    return len(rows)


def pool_entry_at(conn, ticker: str, day: date, *, cutoff_at: datetime) -> dict[str, Any] | None:
    """The tier in force on `day` as known by `cutoff_at`; removed rows count too."""
    row = conn.execute('SELECT tier, sector_etf FROM pool_tiers '
                       'WHERE ticker = %s AND effective_session <= %s AND recorded_at <= %s '
                       'ORDER BY effective_session DESC, recorded_at DESC, id DESC LIMIT 1',
                       (ticker, day, cutoff_at)).fetchone()
    if row is None:
        return None
    return {'tier': row[0], 'sector_etf': row[1]}


def last_push(conn, *, session: date | None = None) -> dict[str, Any] | None:
    """The newest recorded push result for the workbench task, optionally for one session."""
    if conn.execute("SELECT to_regclass('job_reports')").fetchone()[0] is None:
        return None
    sql = "SELECT summary->'push' AS push FROM job_reports WHERE task = 'workbench' AND summary ? 'push'"
    params: list[Any] = []
    if session is not None:
        sql += " AND (summary->'push'->>'session') = %s"
        params.append(session.isoformat())
    sql += ' ORDER BY created_at DESC LIMIT 1'
    row = conn.execute(sql, params).fetchone()
    return row[0] if row and row[0] is not None else None


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


# ---------------------------------------------------------------- agent track (P3 §3)

_AGENT_RUN_COLUMNS = ('id, ticker, signal_date, pool, attempt, agent_version, provider, model, cutoff_at, '
                      'status, reason, detail, output, counter, plan_id, input_tokens, output_tokens, '
                      'started_at, finished_at, created_at')


def insert_agent_run(conn, run: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    """The run row and all its tool calls, in the caller's transaction (§3.3 order:
    plan, run, calls; the plan is inserted by the service before this call)."""
    record = _one(conn,
                  'INSERT INTO agent_runs (id, ticker, signal_date, pool, attempt, agent_version, provider, '
                  'model, cutoff_at, status, reason, detail, output, counter, plan_id, input_tokens, output_tokens, '
                  'started_at, finished_at) '
                  'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s) '
                  f'RETURNING {_AGENT_RUN_COLUMNS}',
                  (run['id'], run['ticker'], run['signal_date'], run['pool'], run['attempt'],
                   run['agent_version'], run['provider'], run['model'], run['cutoff_at'], run['status'],
                   run['reason'], run.get('detail'),
                   _plan_json(run['output']) if run.get('output') is not None else None,
                   _plan_json(run['counter']) if run.get('counter') is not None else None,
                   run.get('plan_id'), run['input_tokens'], run['output_tokens'],
                   run['started_at'], run['finished_at']))
    for c in calls:
        conn.execute('INSERT INTO agent_tool_calls (run_id, seq, phase, tool, args, result, result_sha256, '
                     'called_at) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)',
                     (run['id'], c['seq'], c['phase'], c['tool'], _plan_json(c['args']),
                      _plan_json(c['result']), c['result_sha256'], c['called_at']))
    return record


def agent_runs_for(conn, ticker: str, signal_date: date) -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs WHERE ticker = %s AND signal_date = %s '
                      'ORDER BY created_at, id', (ticker.upper(), signal_date))


def latest_agent_run(conn, ticker: str, signal_date: date) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs WHERE ticker = %s AND signal_date = %s '
                      'ORDER BY created_at DESC, id DESC LIMIT 1', (ticker.upper(), signal_date))


def agent_run_by_id(conn, run_id) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs WHERE id = %s', (run_id,))


def agent_tool_calls(conn, run_id) -> list[dict[str, Any]]:
    return _all(conn, 'SELECT id, run_id, seq, phase, tool, args, result, result_sha256, called_at '
                      'FROM agent_tool_calls WHERE run_id = %s ORDER BY seq', (run_id,))


def list_agent_runs(conn, since: date) -> list[dict[str, Any]]:
    """Run rows for the API list view: no result payloads, but a tool-call count each."""
    return _all(conn, 'SELECT r.id, r.ticker, r.signal_date, r.pool, r.attempt, r.agent_version, r.provider, '
                      'r.model, r.cutoff_at, r.status, r.reason, r.detail, r.plan_id, r.input_tokens, r.output_tokens, '
                      'r.started_at, r.finished_at, r.created_at, '
                      '(SELECT count(*) FROM agent_tool_calls c WHERE c.run_id = r.id) AS tool_calls '
                      'FROM agent_runs r WHERE r.signal_date >= %s ORDER BY r.created_at, r.id', (since,))


def agent_tokens_on(conn, ny_date: date) -> int:
    """Tokens of runs whose started_at falls on that New York date (§4 daily cap)."""
    row = conn.execute("SELECT COALESCE(sum(input_tokens + output_tokens), 0) FROM agent_runs "
                       "WHERE (started_at AT TIME ZONE 'America/New_York')::date = %s", (ny_date,)).fetchone()
    return int(row[0] or 0)


def agent_plan(conn, ticker: str, signal_date: date) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_PLAN_COLUMNS} FROM trade_plans WHERE ticker = %s AND signal_date = %s '
                      "AND kind = 'agent' ORDER BY created_at DESC LIMIT 1", (ticker.upper(), signal_date))


def candidate_groups_since(conn, since: date) -> list[dict[str, Any]]:
    """open_candidate_groups' shape, but decided units included (agent coverage needs them all)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            'SELECT c.id, c.ticker, c.signal_date, c.action, c.rule_id, c.rule_version, c.inputs, c.created_at '
            'FROM signal_candidates c WHERE c.signal_date >= %s '
            'ORDER BY c.signal_date DESC, c.ticker, c.created_at, c.rule_id', (since,))
        rows = cur.fetchall()
    groups: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = (row['ticker'], row['signal_date'])
        groups.setdefault(key, {'ticker': key[0], 'signal_date': key[1], 'candidates': []})['candidates'].append(row)
    return list(groups.values())
