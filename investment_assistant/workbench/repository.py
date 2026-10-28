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


_BAR_BY_ID_COLUMNS = f"id, ticker, price_date, revision, fetched_at, {', '.join(BAR_VALUES)}"


def bars_by_ids(conn, ids: list[int]) -> list[dict[str, Any]]:
    """The exact bar rows (any revision) named by ``ids``, in the order given.

    Numbers stay ``Decimal``; an id that reads back nothing is simply absent."""
    if not ids:
        return []
    found = {row['id']: row for row in _all(
        conn, f'SELECT {_BAR_BY_ID_COLUMNS} FROM price_bars WHERE id = ANY(%s)', ([int(i) for i in ids],))}
    return [found[int(i)] for i in ids if int(i) in found]


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
              limit: int | None = 50, source: str | None = None) -> list[dict[str, Any]]:
    """News known by ``cutoff_at``; undated items are kept and must be shown as such.

    ``source`` filters in SQL before any window/dedup, so one source's rows can
    never be pushed out by another's volume (I10); ``limit=None`` reads the whole
    window — the caller's window is the only cap."""
    clauses = ['t.ticker = %s', 'n.fetched_at <= %s', '(n.published_at IS NULL OR n.published_at <= %s)']
    params: list[Any] = [ticker.upper(), cutoff_at, cutoff_at]
    if since is not None:
        clauses.append('COALESCE(n.published_at, n.fetched_at) >= %s')
        params.append(since)
    if source is not None:
        clauses.append('n.source = %s')
        params.append(source)
    sql = ('SELECT n.id, n.source, n.title, n.url, n.publisher, n.published_at, n.fetched_at '
           'FROM news_items n JOIN news_item_tickers t ON t.news_item_id = n.id '
           f"WHERE {' AND '.join(clauses)} "
           'ORDER BY COALESCE(n.published_at, n.fetched_at) DESC, n.id DESC')
    if limit is not None:
        sql += ' LIMIT %s'
        params.append(limit)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
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
            'status, error, agent_run_id, created_at) '
            'VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, clock_timestamp()) '
            'RETURNING id',
            (brief['ticker'], brief['signal_date'], brief.get('model'), brief['prompt_version'], brief['cutoff_at'],
             _canonical(brief['input_refs']), _canonical(brief['output']), brief['status'],
             brief.get('error'), brief.get('agent_run_id')))
        return cur.fetchone()[0]


def latest_brief(conn, ticker: str, signal_date: date) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            'SELECT id, ticker, signal_date, model, prompt_version, cutoff_at, input_refs, output, status, error, '
            'agent_run_id, created_at FROM signal_briefs WHERE ticker = %s AND signal_date = %s '
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


def _decision_columns(timeline: bool) -> str:
    """``timeline=True`` (migration 026 checked by the caller) adds ``agent_plan_id`` and ``review_view``."""
    return f'{_DECISION_COLUMNS}, agent_plan_id, review_view' if timeline else _DECISION_COLUMNS


def decision_by_request(conn, request_id, *, timeline: bool = False):
    return _one(conn, f'SELECT {_decision_columns(timeline)} FROM signal_decisions WHERE request_id = %s',
                (request_id,))


def decision_by_id(conn, decision_id):
    return _one(conn, f'SELECT {_DECISION_COLUMNS} FROM signal_decisions WHERE id = %s', (decision_id,))


def decision_head(conn, ticker: str, signal_date: date, *, timeline: bool = False) -> dict[str, Any] | None:
    """The unit's current decision: the one no other decision supersedes."""
    return _one(conn,
                f'SELECT {_decision_columns(timeline)} FROM signal_decisions d WHERE ticker = %s AND signal_date = %s '
                'AND NOT EXISTS (SELECT 1 FROM signal_decisions s WHERE s.supersedes_id = d.id) '
                'ORDER BY decided_at DESC LIMIT 1', (ticker, signal_date))


def unit_decision_ids(conn, ticker: str, signal_date: date) -> set:
    """Every decision id in the unit's chain, superseded ones included."""
    rows = conn.execute('SELECT id FROM signal_decisions WHERE ticker = %s AND signal_date = %s',
                        (ticker.upper(), signal_date)).fetchall()
    return {row[0] for row in rows}


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
    """`agent_plan_id` / `review_view` (migration 026) are written, and returned, only when one is
    set; without them the statement is the pre-026 one, so old callers and an unmigrated database
    behave as before."""
    if rec.get('agent_plan_id') is not None or rec.get('review_view') is not None:
        view = rec.get('review_view')
        return _one(conn,
                    'INSERT INTO signal_decisions (request_id, request_hash, ticker, signal_date, candidate_ids, '
                    'brief_id, proposed_action, final_action, decision, reason, decided_at, supersedes_id, plan_id, '
                    'agent_plan_id, review_view) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) '
                    f'RETURNING {_DECISION_COLUMNS}, agent_plan_id, review_view',
                    (rec['request_id'], digest, rec['ticker'], rec['signal_date'], rec['candidate_ids'],
                     rec['brief_id'], rec['proposed_action'], rec['final_action'], rec['decision'], rec['reason'],
                     decided_at, rec['supersedes_id'], rec.get('plan_id'), rec.get('agent_plan_id'),
                     _plan_json(view) if view is not None else None))
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


def plans_for_unit(conn, ticker: str, signal_date: date) -> list[dict[str, Any]]:
    """Every plan of one decision unit (rule, own, agent), oldest first."""
    return _all(conn, f'SELECT {_PLAN_COLUMNS} FROM trade_plans WHERE ticker = %s AND signal_date = %s '
                      'ORDER BY created_at, id', (ticker.upper(), signal_date))


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


def snapshot_by_id(conn, snapshot_id) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_SNAPSHOT_COLUMNS} FROM account_snapshots WHERE id = %s', (snapshot_id,))


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


def earnings_row_by_id(conn, earnings_id) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_EARNINGS_COLUMNS} FROM earnings_dates WHERE id = %s', (earnings_id,))


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


WORKBENCH_TABLES = ('price_bars', 'news_items', 'news_item_tickers', 'signal_candidates', 'signal_briefs',
                    'signal_decisions', 'trades', 'weekly_reviews', 'filings', 'trade_plans', 'earnings_dates',
                    'account_snapshots', 'cash_flows', 'monthly_reviews', 'watchlist_items', 'pool_tiers',
                    'macro_observations', 'market_regimes', 'rule_backchecks', 'agent_runs', 'agent_tool_calls',
                    'review_pushes', 'screen_runs', 'screen_results')


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


def regime_by_id(conn, regime_id) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_REGIME_COLUMNS} FROM market_regimes WHERE id = %s', (regime_id,))


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
    """Each ticker's newest pool_tiers row: {'tier', 'sector_etf', 'source'}."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT DISTINCT ON (ticker) ticker, tier, sector_etf, source FROM pool_tiers '
                    'ORDER BY ticker, effective_session DESC, recorded_at DESC, id DESC')
        return {row['ticker']: {'tier': row['tier'], 'sector_etf': row['sector_etf'],
                                'source': row['source']}
                for row in cur.fetchall()}


def insert_pool_tiers(conn, rows: list[dict[str, Any]], *, session: date, now: datetime) -> int:
    """Append tier change rows; callers only pass rows that actually changed."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO pool_tiers (ticker, tier, sector_etf, effective_session, recorded_at, source) '
                        'VALUES (%s, %s, %s, %s, %s, %s)',
                        [(r['ticker'], r['tier'], r['sector_etf'], session, now,
                          r.get('source', 'watchlist')) for r in rows])
    return len(rows)


def pool_entry_at(conn, ticker: str, day: date, *, cutoff_at: datetime) -> dict[str, Any] | None:
    """The tier in force on `day` as known by `cutoff_at`; removed rows count too."""
    row = conn.execute('SELECT tier, sector_etf, source FROM pool_tiers '
                       'WHERE ticker = %s AND effective_session <= %s AND recorded_at <= %s '
                       'ORDER BY effective_session DESC, recorded_at DESC, id DESC LIMIT 1',
                       (ticker, day, cutoff_at)).fetchone()
    if row is None:
        return None
    return {'tier': row[0], 'sector_etf': row[1], 'source': row[2]}


# ---------------------------------------------------------------- daily screen (v2.2 §10)

_SCREEN_RUN_COLUMNS = ('id, session, calc_version, universe_name, universe_as_of, cutoff_at, status, summary, '
                       'run_id, created_at')


def insert_screen_run(conn, run: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    """Append one screen run and its per-ticker rows; same-session reruns add new rows.

    `run` may carry `created_at` (tests pin it to order runs inside one transaction);
    the default is the database clock."""
    record = _one(conn,
                  'INSERT INTO screen_runs (session, calc_version, universe_name, universe_as_of, cutoff_at, '
                  'status, summary, run_id, created_at) '
                  'VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, COALESCE(%s, now())) '
                  f'RETURNING {_SCREEN_RUN_COLUMNS}',
                  (run['session'], run['calc_version'], run['universe_name'], run['universe_as_of'],
                   run['cutoff_at'], run['status'], _plan_json(run['summary']), run.get('run_id'),
                   run.get('created_at')))
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO screen_results (screen_run_id, ticker, screen_group, trigger_rules, filters, '
                        'rs, atr_pct, dollar_volume_20, rank, selected) '
                        'VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)',
                        [(record['id'], r['ticker'], r['group'], r.get('trigger_rules') or [],
                          _plan_json(r['filters']), r.get('rs'), r.get('atr_pct'),
                          r.get('dollar_volume_20'), r.get('rank'), r['selected']) for r in results])
    return record


def latest_screen_pick(conn, ticker: str, session: date, *,
                       cutoff_at: datetime | None = None) -> dict[str, Any] | None:
    """The ticker's newest selected row at or before `session`.

    `cutoff_at` is None inside the batch: the rule-plan stage must read the run the
    screen stage just wrote in this same pass, whose created_at is the database
    clock and would postdate the batch's own cutoff. Outside readers pass it."""
    sql = ('SELECT r.screen_run_id, r.screen_group, r.rs, r.rank FROM screen_results r '
           'JOIN screen_runs s ON s.id = r.screen_run_id '
           'WHERE r.ticker = %s AND r.selected AND s.session <= %s')
    params: list[Any] = [ticker.upper(), session]
    if cutoff_at is not None:
        sql += ' AND r.created_at <= %s'
        params.append(cutoff_at)
    row = conn.execute(sql + ' ORDER BY r.created_at DESC, r.id DESC LIMIT 1', params).fetchone()
    if row is None:
        return None
    return {'screen_run_id': row[0], 'group': row[1], 'rs': row[2], 'rank': row[3]}


def latest_screen_run(conn, *, session: date | None, cutoff_at: datetime | None = None) -> dict[str, Any] | None:
    """The newest run for one session, or overall.

    `cutoff_at` is None inside the batch (report and replay read the run the screen
    stage just wrote, whose database clock postdates the batch's own cutoff);
    time-point readers pass it as before."""
    where = 'WHERE session = %s' if session is not None else ''
    params: list[Any] = [session] if session is not None else []
    if cutoff_at is not None:
        where = (where + ' AND' if where else 'WHERE') + ' created_at <= %s'
        params.append(cutoff_at)
    return _one(conn, f'SELECT {_SCREEN_RUN_COLUMNS} FROM screen_runs {where} '
                      'ORDER BY created_at DESC, id DESC LIMIT 1', params)


def screen_results(conn, screen_run_id) -> list[dict[str, Any]]:
    """All rows of one run ordered by rank; the interface field is `group`."""
    return _all(conn, 'SELECT ticker, screen_group AS "group", trigger_rules, filters, rs, atr_pct, '
                      'dollar_volume_20, rank, selected FROM screen_results WHERE screen_run_id = %s '
                      'ORDER BY rank NULLS LAST, ticker', (screen_run_id,))


def screen_selected_since(conn, since: date, until: date, *,
                          cutoff_at: datetime | None = None) -> dict[str, dict[str, Any]]:
    """Latest-run-per-session picks in [since, until]: {ticker: {'session', 'rank'}} of the newest pick.

    cutoff_at defaults to None for the batch's own reads (the session window already
    bounds what is visible); time-point readers pass it."""
    visible = ' AND s.created_at <= %(cutoff)s' if cutoff_at is not None else ''
    rows = conn.execute(
        'WITH latest AS ('
        '  SELECT DISTINCT ON (session) session, id FROM screen_runs s'
        '   WHERE s.session BETWEEN %(since)s AND %(until)s' + visible +
        '   ORDER BY s.session, s.created_at DESC, s.id DESC),'
        ' picked AS ('
        '  SELECT r.ticker, l.session, r.rank FROM screen_results r JOIN latest l ON r.screen_run_id = l.id'
        '   WHERE r.selected)'
        ' SELECT DISTINCT ON (ticker) ticker, session, rank FROM picked'
        '  ORDER BY ticker, session DESC',
        {'since': since, 'until': until, 'cutoff': cutoff_at}).fetchall()
    return {row[0]: {'session': row[1], 'rank': row[2]} for row in rows}


def locked_screen_tickers(conn, session: date, *, cutoff_at: datetime) -> set[str]:
    """Valid plans for the session plus tickers holding an open position from unvoided trades."""
    tickers = {row[0] for row in conn.execute(
        'SELECT DISTINCT ticker FROM trade_plans '
        "WHERE kind IN ('rule', 'own') AND status = 'ok' AND valid_until >= %s AND created_at <= %s",
        (session, cutoff_at)).fetchall()}
    tickers |= open_position_tickers(conn)
    return tickers


def screen_lockable_tickers(conn) -> set[str]:
    """Tickers a lock may keep as screen members: still in the pool by their newest row and
    screen-sourced at some point (a screen member now, or a pick since flipped to the watchlist).

    Off-pool holdings and plans of tickers that never came from the screen stay out."""
    rows = conn.execute(
        'SELECT ticker FROM (SELECT DISTINCT ON (ticker) ticker, tier FROM pool_tiers '
        '  ORDER BY ticker, effective_session DESC, recorded_at DESC, id DESC) latest '
        "WHERE tier <> 'removed' AND EXISTS "
        "  (SELECT 1 FROM pool_tiers p WHERE p.ticker = latest.ticker AND p.source = 'screen')").fetchall()
    return {row[0] for row in rows}


def open_position_tickers(conn) -> set[str]:
    from investment_assistant.workbench import positions

    held: set[str] = set()
    for ticker in sorted({t['ticker'] for t in list_trades(conn) if t['voided_at'] is None}):
        try:
            book = positions.build(list_trades(conn, ticker), splits=split_events(conn, ticker))
        except positions.PositionError:
            continue  # a broken trade history must not fail the whole screen
        if book['position'] is not None:
            held.add(ticker)
    return held


# ---------------------------------------------------------------- fetch runs (v2.3 §5)

_FETCH_RUN_COLUMNS = ('id, family, job, trigger, run_id, scope, ticker, session, status, target_count, '
                      'ok_count, failures, detail, started_at, finished_at, created_at')


def insert_fetch_run(conn, row: dict[str, Any]) -> dict[str, Any]:
    """Append one fetch-run row; `failures`/`detail` arrive as Python objects, JSON-encoded here.

    `row` keys are the table columns except `id`/`created_at`, which the database sets."""
    return _one(conn,
                'INSERT INTO data_fetch_runs (family, job, trigger, run_id, scope, ticker, session, status, '
                'target_count, ok_count, failures, detail, started_at, finished_at) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s) '
                f'RETURNING {_FETCH_RUN_COLUMNS}',
                (row['family'], row['job'], row['trigger'], row.get('run_id'), row['scope'], row.get('ticker'),
                 row.get('session'), row['status'], row['target_count'], row['ok_count'],
                 _plan_json(row.get('failures') or []), _plan_json(row.get('detail') or {}),
                 row['started_at'], row['finished_at']))


def fetch_runs_ready(conn) -> bool:
    """True when migration 024 has run; the workbench itself does not require this table."""
    return conn.execute("SELECT to_regclass('data_fetch_runs')").fetchone()[0] is not None


def latest_fetch_runs(conn, *, scope: str | None = None) -> dict[str, dict[str, Any]]:
    """The newest run per family: {family: row}; ``scope`` ('family' / 'ticker') narrows it."""
    where, params = ('WHERE scope = %s ', [scope]) if scope is not None else ('', [])
    return {row['family']: row for row in _all(
        conn, f'SELECT DISTINCT ON (family) {_FETCH_RUN_COLUMNS} FROM data_fetch_runs {where}'
              'ORDER BY family, created_at DESC, id DESC', params)}


def fetch_runs(conn, family: str, limit: int = 20) -> list[dict[str, Any]]:
    """One family's runs, newest first."""
    return _all(conn, f'SELECT {_FETCH_RUN_COLUMNS} FROM data_fetch_runs WHERE family = %s '
                      'ORDER BY created_at DESC, id DESC LIMIT %s', (family, limit))


def last_success_at(conn, *, scope: str | None = None) -> dict[str, datetime]:
    """Per family, the finished_at of the newest run that succeeded (status success or partial);
    ``scope`` ('family' / 'ticker') narrows it."""
    where, params = ('AND scope = %s ', [scope]) if scope is not None else ('', [])
    rows = conn.execute("SELECT DISTINCT ON (family) family, finished_at FROM data_fetch_runs "
                        f"WHERE status IN ('success', 'partial') {where}"
                        'ORDER BY family, finished_at DESC, id DESC', params).fetchall()
    return {row[0]: row[1] for row in rows}


# --- stage runs (v2.4 §5) ---

_STAGE_RUN_COLUMNS = ('id, run_id, job, trigger, session, stage, stages_version, status, reason, input_count, '
                      'output_count, skips, failures, degradations, outputs, detail, started_at, finished_at, '
                      'duration_ms, created_at')


def insert_stage_run(conn, row: dict[str, Any]) -> dict[str, Any]:
    """Append one stage-run row; the five JSONB columns arrive as Python objects, encoded here.

    `row` keys are the table columns except `id`/`created_at`, which the database sets."""
    return _one(conn,
                'INSERT INTO stage_runs (run_id, job, trigger, session, stage, stages_version, status, reason, '
                'input_count, output_count, skips, failures, degradations, outputs, detail, started_at, '
                'finished_at, duration_ms) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, '
                f'%s::jsonb, %s, %s, %s) RETURNING {_STAGE_RUN_COLUMNS}',
                (row['run_id'], row['job'], row['trigger'], row.get('session'), row['stage'],
                 row['stages_version'], row['status'], row.get('reason'), row['input_count'],
                 row['output_count'], _plan_json(row.get('skips') or []),
                 _plan_json(row.get('failures') or []), _plan_json(row.get('degradations') or []),
                 _plan_json(row.get('outputs') or {}), _plan_json(row.get('detail') or {}),
                 row['started_at'], row['finished_at'], row['duration_ms']))


def stage_runs_ready(conn) -> bool:
    """True when migration 025 has run; the workbench itself does not require this table."""
    return conn.execute("SELECT to_regclass('stage_runs')").fetchone()[0] is not None


def stage_runs_for_run(conn, run_id: str) -> list[dict[str, Any]]:
    """One run's stage rows, oldest first."""
    return _all(conn, f'SELECT {_STAGE_RUN_COLUMNS} FROM stage_runs WHERE run_id = %s ORDER BY created_at, id',
                (run_id,))


def stage_runs_for_session(conn, session: date) -> list[dict[str, Any]]:
    """One session's stage rows across runs, oldest first."""
    return _all(conn, f'SELECT {_STAGE_RUN_COLUMNS} FROM stage_runs WHERE session = %s ORDER BY created_at, id',
                (session,))


def stage_run_for_plan(conn, plan_id: str) -> dict[str, Any] | None:
    """The earliest plan/agent stage row that inserted the plan (agent rows via outputs.plan_ids).

    Not the candidate's run_id: a candidate may have been written by an earlier run."""
    return _one(conn, f'SELECT {_STAGE_RUN_COLUMNS} FROM stage_runs '
                      "WHERE stage IN ('plan', 'agent') "
                      "AND (outputs->'inserted' ? %s OR outputs->'plan_ids' ? %s) "
                      'ORDER BY created_at, id LIMIT 1', (plan_id, plan_id))


def workbench_reports_between(conn, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """workbench run reports with started_at in [start, end), oldest first."""
    return _all(conn, "SELECT run_id, started_at, trigger_source FROM job_reports "
                      "WHERE task = 'workbench' AND started_at >= %s AND started_at < %s "
                      'ORDER BY started_at, id', (start, end))


def workbench_run_ids(conn, run_ids: list[str]) -> set[str]:
    """The given run ids that have a workbench report in job_reports."""
    if not run_ids:
        return set()
    rows = _all(conn, "SELECT run_id FROM job_reports WHERE task = 'workbench' AND run_id = ANY(%s)",
                (list(run_ids),))
    return {row['run_id'] for row in rows}


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


def last_successful_push_at(conn, *, before_session: date) -> datetime | None:
    """Where the newest successful daily push of a session earlier than `before_session` stopped reading
    reviews (v2.5 D25): its `summary.push.reviews_until`, or the report's created_at for pushes recorded
    before that key existed. A New York holiday's one-line message (summary.status = skipped) is not a
    daily push and does not move the window."""
    if conn.execute("SELECT to_regclass('job_reports')").fetchone()[0] is None:
        return None
    row = conn.execute(
        "SELECT max(COALESCE((summary->'push'->>'reviews_until')::timestamptz, created_at)) "
        "FROM job_reports WHERE task = 'workbench' "
        "AND summary->'push'->'sent' = 'true'::jsonb AND (summary->'push'->>'session') < %s "
        "AND (summary->>'status') IS DISTINCT FROM 'skipped'", (before_session.isoformat(),)).fetchone()
    return row[0] if row else None


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

_AGENT_RUN_COLUMNS = ('id, ticker, signal_date, pool, attempt, mode, agent_version, provider, model, cutoff_at, '
                      'status, reason, detail, output, counter, plan_id, input_tokens, output_tokens, '
                      'started_at, finished_at, created_at')


def insert_agent_run(conn, run: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    """The run row and all its tool calls, in the caller's transaction (§3.3 order:
    plan, run, calls; the plan is inserted by the service before this call)."""
    record = _one(conn,
                  'INSERT INTO agent_runs (id, ticker, signal_date, pool, attempt, mode, agent_version, provider, '
                  'model, cutoff_at, status, reason, detail, output, counter, plan_id, input_tokens, output_tokens, '
                  'started_at, finished_at) '
                  'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s) '
                  f'RETURNING {_AGENT_RUN_COLUMNS}',
                  (run['id'], run['ticker'], run['signal_date'], run['pool'], run['attempt'],
                   run.get('mode', 'propose'), run['agent_version'], run['provider'], run['model'], run['cutoff_at'], run['status'],
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


def agent_runs_for(conn, ticker: str, signal_date: date, mode: str = 'propose') -> list[dict[str, Any]]:
    return _all(conn, f'SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs WHERE ticker = %s AND signal_date = %s '
                      'AND mode = %s ORDER BY created_at, id', (ticker.upper(), signal_date, mode))


def latest_agent_run(conn, ticker: str, signal_date: date, mode: str = 'propose') -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs WHERE ticker = %s AND signal_date = %s '
                      'AND mode = %s ORDER BY created_at DESC, id DESC LIMIT 1',
                (ticker.upper(), signal_date, mode))


def agent_run_by_id(conn, run_id) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs WHERE id = %s', (run_id,))


def agent_tool_calls(conn, run_id) -> list[dict[str, Any]]:
    return _all(conn, 'SELECT id, run_id, seq, phase, tool, args, result, result_sha256, called_at '
                      'FROM agent_tool_calls WHERE run_id = %s ORDER BY seq', (run_id,))


def list_agent_runs(conn, since: date) -> list[dict[str, Any]]:
    """Run rows for the API list view: no result payloads, but a tool-call count each."""
    return _all(conn, 'SELECT r.id, r.ticker, r.signal_date, r.pool, r.attempt, r.mode, r.agent_version, r.provider, '
                      'r.model, r.cutoff_at, r.status, r.reason, r.detail, r.plan_id, r.input_tokens, r.output_tokens, '
                      'r.started_at, r.finished_at, r.created_at, '
                      '(SELECT count(*) FROM agent_tool_calls c WHERE c.run_id = r.id) AS tool_calls '
                      'FROM agent_runs r WHERE r.signal_date >= %s ORDER BY r.created_at, r.id', (since,))


def track_units(conn, since: date, until: date) -> list[dict[str, Any]]:
    """§4.1: units with a rule plan or a propose run in the window (union),
    each pool membership decided later; ordered by (signal_date, ticker)."""
    return _all(conn,
                'SELECT u.ticker, u.signal_date FROM ('
                "SELECT ticker, signal_date FROM trade_plans WHERE kind = 'rule' AND signal_date BETWEEN %s AND %s "
                'UNION '
                "SELECT ticker, signal_date FROM agent_runs WHERE mode = 'propose' AND signal_date BETWEEN %s AND %s"
                ') u ORDER BY u.signal_date, u.ticker',
                (since, until, since, until))


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


# --- plan timeline (v2.5 §6): agent_plan_versions, plan_reviews, user_inputs ---
# Append-only tables from migration 026; deliberately not in WORKBENCH_TABLES (§6.5): an
# unmigrated database degrades through timeline_ready() instead of failing the workbench.

EFFECTIVE_REVIEW_OUTCOMES = ('maintain', 'revise', 'invalidate')

_VERSION_COLUMNS = ('plan_id, ticker, signal_date, version_no, supersedes_plan_id, origin, agent_run_id, '
                    'cutoff_at, as_of_session, diff, schema_version, created_at')
_REVIEW_COLUMNS = ('id, ticker, signal_date, head_plan_id, session, trigger, run_id, mode, timeline_version, '
                   'signals, conditions, user_input_ids, outcome, decided_by, reason, refs, review_agent_run_id, '
                   'revision_agent_run_id, new_plan_id, detail, attempt, cutoff_at, input_tokens, output_tokens, '
                   'created_at')
_USER_INPUT_COLUMNS = ('id, request_id, request_hash, ticker, signal_date, kind, body, source_url, supersedes_id, '
                       'created_at')


def timeline_ready(conn) -> bool:
    """True when migration 026 has run: the three tables and signal_decisions.agent_plan_id exist.

    Resolved through the search_path like every other query here, and never raises on a missing
    table, so the caller's transaction stays usable."""
    row = conn.execute(
        "SELECT to_regclass('agent_plan_versions') IS NOT NULL AND to_regclass('plan_reviews') IS NOT NULL "
        "AND to_regclass('user_inputs') IS NOT NULL AND EXISTS (SELECT 1 FROM pg_attribute "
        "WHERE attrelid = to_regclass('signal_decisions') AND attname = 'agent_plan_id' AND NOT attisdropped)"
    ).fetchone()
    return bool(row[0])


def try_review_lock(conn, ticker: str, signal_date: date) -> bool:
    """Transaction-scoped, non-blocking lock on one chain shared by the batch review and a recheck."""
    key = f'review:{ticker.upper()}:{signal_date.isoformat()}'
    return bool(conn.execute('SELECT pg_try_advisory_xact_lock(hashtext(%s))', (key,)).fetchone()[0])


def insert_plan_version(conn, row: dict[str, Any]) -> dict[str, Any]:
    """`row` keys are the §6.1 columns except `created_at`; `diff` arrives as a Python list or None."""
    diff = row.get('diff')
    return _one(conn,
                'INSERT INTO agent_plan_versions (plan_id, ticker, signal_date, version_no, supersedes_plan_id, '
                'origin, agent_run_id, cutoff_at, as_of_session, diff, schema_version) '
                f'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s) RETURNING {_VERSION_COLUMNS}',
                (row['plan_id'], row['ticker'], row['signal_date'], row['version_no'], row.get('supersedes_plan_id'),
                 row['origin'], row['agent_run_id'], row['cutoff_at'], row['as_of_session'],
                 _plan_json(diff) if diff is not None else None, row['schema_version']))


def chain_versions(conn, ticker: str, signal_date: date) -> list[dict[str, Any]]:
    """One chain's version rows, version 0 first."""
    return _all(conn, f'SELECT {_VERSION_COLUMNS} FROM agent_plan_versions WHERE ticker = %s AND signal_date = %s '
                      'ORDER BY version_no', (ticker.upper(), signal_date))


def version_by_plan(conn, plan_id) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_VERSION_COLUMNS} FROM agent_plan_versions WHERE plan_id = %s', (plan_id,))


def chain_head(conn, ticker: str, signal_date: date) -> dict[str, Any] | None:
    """The chain's head — its highest-numbered agent-2 version — as {'plan': trade_plans row,
    'version': agent_plan_versions row}; None when the unit has no agent-2 chain."""
    version = _one(conn, f"SELECT {', '.join('v.' + c.strip() for c in _VERSION_COLUMNS.split(','))} "
                         'FROM agent_plan_versions v JOIN trade_plans p ON p.id = v.plan_id '
                         "WHERE v.ticker = %s AND v.signal_date = %s AND p.plan_version = 'agent-2' "
                         'ORDER BY v.version_no DESC LIMIT 1', (ticker.upper(), signal_date))
    if version is None:
        return None
    return {'plan': plan_by_id(conn, version['plan_id']), 'version': version}


def all_chains(conn) -> list[dict[str, Any]]:
    """Every chain: ticker, signal_date, the head's plan_id and version_no, and `pool` of the run
    that produced version 0 (agent_runs.pool); ordered by (signal_date, ticker)."""
    return _all(conn,
                'SELECT h.ticker, h.signal_date, h.plan_id, h.version_no, r.pool FROM ('
                'SELECT DISTINCT ON (ticker, signal_date) ticker, signal_date, plan_id, version_no '
                'FROM agent_plan_versions ORDER BY ticker, signal_date, version_no DESC) h '
                'LEFT JOIN agent_plan_versions v0 ON v0.ticker = h.ticker AND v0.signal_date = h.signal_date '
                'AND v0.version_no = 0 '
                'LEFT JOIN agent_runs r ON r.id = v0.agent_run_id '
                'ORDER BY h.signal_date, h.ticker', ())


def insert_plan_review(conn, row: dict[str, Any]) -> dict[str, Any]:
    """`row` keys are the §6.2 columns except `id`/`created_at`; JSONB columns arrive as Python
    objects and, like the token counts and user_input_ids, fall back to the table defaults."""
    return _one(conn,
                'INSERT INTO plan_reviews (ticker, signal_date, head_plan_id, session, trigger, run_id, mode, '
                'timeline_version, signals, conditions, user_input_ids, outcome, decided_by, reason, refs, '
                'review_agent_run_id, revision_agent_run_id, new_plan_id, detail, attempt, cutoff_at, '
                'input_tokens, output_tokens) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s::jsonb, '
                f'%s, %s, %s, %s::jsonb, %s, %s, %s, %s) RETURNING {_REVIEW_COLUMNS}',
                (row['ticker'], row['signal_date'], row['head_plan_id'], row['session'], row['trigger'],
                 row.get('run_id'), row['mode'], row['timeline_version'], _plan_json(row.get('signals') or []),
                 _plan_json(row.get('conditions') or []), list(row.get('user_input_ids') or []), row['outcome'],
                 row['decided_by'], row['reason'], _plan_json(row.get('refs') or []),
                 row.get('review_agent_run_id'), row.get('revision_agent_run_id'), row.get('new_plan_id'),
                 _plan_json(row.get('detail') or {}), row['attempt'], row['cutoff_at'],
                 row.get('input_tokens') or 0, row.get('output_tokens') or 0))


def chain_reviews(conn, ticker: str, signal_date: date) -> list[dict[str, Any]]:
    """One chain's review rows (every outcome and trigger), oldest first."""
    return _all(conn, f'SELECT {_REVIEW_COLUMNS} FROM plan_reviews WHERE ticker = %s AND signal_date = %s '
                      'ORDER BY created_at, id', (ticker.upper(), signal_date))


def reviews_on(conn, session: date) -> list[dict[str, Any]]:
    """Every review row of one review session S, across chains, oldest first."""
    return _all(conn, f'SELECT {_REVIEW_COLUMNS} FROM plan_reviews WHERE session = %s ORDER BY created_at, id',
                (session,))


def reviews_since(conn, since: datetime | None, session: date,
                  until: datetime | None = None) -> list[dict[str, Any]]:
    """The review rows the daily push of `session` reports (v2.5 D25): every row written after `since`
    (the read time of the last successful push of an earlier session) whose session is not later than
    `session`, batch and recheck alike; with no earlier push, only the rows of `session` itself. `until`
    (the push's own read time) bounds both cases, so a row written while the push is being sent falls in
    the next window. Oldest first."""
    if since is None:
        sql, params = 'session = %s', [session]
    else:
        sql, params = 'created_at > %s AND session <= %s', [since, session]
    if until is not None:
        sql += ' AND created_at <= %s'
        params.append(until)
    return _all(conn, f'SELECT {_REVIEW_COLUMNS} FROM plan_reviews WHERE {sql} ORDER BY created_at, id', params)


def batch_attempts(conn, ticker: str, signal_date: date, session: date) -> list[dict[str, Any]]:
    """The batch review rows of one chain on one session (any outcome), in attempt order."""
    return _all(conn, f'SELECT {_REVIEW_COLUMNS} FROM plan_reviews WHERE ticker = %s AND signal_date = %s '
                      "AND session = %s AND trigger = 'batch' ORDER BY attempt, created_at, id",
                (ticker.upper(), signal_date, session))


def last_effective_review(conn, head_plan_id) -> dict[str, Any] | None:
    """The newest maintain / revise / invalidate row that reviewed this version, batch or recheck."""
    return _one(conn, f'SELECT {_REVIEW_COLUMNS} FROM plan_reviews WHERE head_plan_id = %s '
                      'AND outcome = ANY(%s) ORDER BY created_at DESC, id DESC LIMIT 1',
                (head_plan_id, list(EFFECTIVE_REVIEW_OUTCOMES)))


def insert_user_input(conn, row: dict[str, Any]) -> dict[str, Any]:
    """`row` keys are the §6.3 columns except `id`/`created_at`."""
    return _one(conn,
                'INSERT INTO user_inputs (request_id, request_hash, ticker, signal_date, kind, body, source_url, '
                f'supersedes_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_USER_INPUT_COLUMNS}',
                (row['request_id'], row['request_hash'], row['ticker'], row.get('signal_date'), row['kind'],
                 row['body'], row.get('source_url'), row.get('supersedes_id')))


def user_input_by_request(conn, request_id) -> dict[str, Any] | None:
    return _one(conn, f'SELECT {_USER_INPUT_COLUMNS} FROM user_inputs WHERE request_id = %s', (request_id,))


def user_inputs_for(conn, ticker: str, signal_date: date | None) -> list[dict[str, Any]]:
    """The ticker-level inputs (signal_date NULL) plus, when given, the inputs of that chain, oldest
    first. Each row carries `superseded_by`: the earliest row whose supersedes_id points at it
    (correction or retract, wherever it was filed), or None. Callers apply their own cutoff."""
    columns = ', '.join('u.' + c.strip() for c in _USER_INPUT_COLUMNS.split(','))
    return _all(conn,
                f'SELECT {columns}, (SELECT min(s.id) FROM user_inputs s WHERE s.supersedes_id = u.id) '
                'AS superseded_by FROM user_inputs u WHERE u.ticker = %s '
                'AND (u.signal_date IS NULL OR u.signal_date = %s) ORDER BY u.created_at, u.id',
                (ticker.upper(), signal_date))


# --- review pushes (P4 §3.3) ---

def insert_review_push(conn, row: dict[str, Any]) -> dict[str, Any]:
    """One row per push attempt, successful or not; append-only."""
    return _one(conn, 'INSERT INTO review_pushes (kind, period, review_id, trigger_source, sent, messages, reason) '
                      'VALUES (%s, %s, %s, %s, %s, %s, %s) '
                      'RETURNING id, kind, period, review_id, trigger_source, sent, messages, reason, created_at',
                (row['kind'], row['period'], row.get('review_id'), row['trigger_source'],
                 row['sent'], row.get('messages') or 0, row.get('reason')))


def review_push_sent(conn, kind: str, period: date) -> bool:
    """Whether this kind and period already has a fully successful push (§6.1 idempotence)."""
    return conn.execute('SELECT EXISTS (SELECT 1 FROM review_pushes WHERE kind = %s AND period = %s '
                        'AND sent = true)', (kind, period)).fetchone()[0]


def list_review_pushes(conn, limit: int) -> list[dict[str, Any]]:
    return _all(conn, 'SELECT id, kind, period, review_id, trigger_source, sent, messages, reason, created_at '
                      'FROM review_pushes ORDER BY created_at DESC, id DESC LIMIT %s', (limit,))


def workbench_started_on(conn) -> date | None:
    """The first day the workbench was in use: the earliest decision (New York date)
    or account snapshot as_of, whichever comes first; None while neither exists."""
    row = conn.execute(
        "SELECT least((SELECT min((decided_at AT TIME ZONE 'America/New_York')::date) FROM signal_decisions), "
        '(SELECT min(as_of) FROM account_snapshots))').fetchone()
    return row[0] if row else None


def latest_account_record_at(conn) -> datetime | None:
    """The latest moment account inputs were recorded or corrected: snapshots and flows."""
    row = conn.execute(
        'SELECT greatest(s.rec, f.rec, f.void) FROM '
        '(SELECT max(recorded_at) AS rec FROM account_snapshots) s, '
        '(SELECT max(recorded_at) AS rec, max(voided_at) AS void FROM cash_flows) f').fetchone()
    return row[0] if row else None

# ---------------------------------------------------------------- coverage reads (v2.3 §8)


def latest_bar_dates(conn, tickers, *, cutoff_at: datetime) -> dict[str, date]:
    """Per ticker the newest bar date any revision of which was known by ``cutoff_at``."""
    if not tickers:
        return {}
    rows = _all(conn, 'SELECT ticker, max(price_date) AS latest FROM price_bars '
                      'WHERE ticker = ANY(%s) AND fetched_at <= %s GROUP BY ticker',
                (list(tickers), cutoff_at))
    return {row['ticker']: row['latest'] for row in rows}


def bar_counts(conn, tickers, *, end_date: date, cutoff_at: datetime) -> dict[str, int]:
    """Per ticker the distinct bar dates up to ``end_date`` known by ``cutoff_at``; revisions count once."""
    if not tickers:
        return {}
    rows = _all(conn, 'SELECT ticker, count(DISTINCT price_date) AS n FROM price_bars '
                      'WHERE ticker = ANY(%s) AND price_date <= %s AND fetched_at <= %s GROUP BY ticker',
                (list(tickers), end_date, cutoff_at))
    return {row['ticker']: row['n'] for row in rows}


def latest_news_at(conn, tickers, *, cutoff_at: datetime) -> dict[str, datetime]:
    """Per ticker the newest COALESCE(published_at, fetched_at) visible to read_news at ``cutoff_at``."""
    if not tickers:
        return {}
    rows = _all(conn, 'SELECT t.ticker, max(COALESCE(n.published_at, n.fetched_at)) AS latest '
                      'FROM news_items n JOIN news_item_tickers t ON t.news_item_id = n.id '
                      'WHERE t.ticker = ANY(%s) AND n.fetched_at <= %s '
                      'AND (n.published_at IS NULL OR n.published_at <= %s) '
                      'GROUP BY t.ticker', (list(tickers), cutoff_at, cutoff_at))
    return {row['ticker']: row['latest'] for row in rows}


def latest_filing_dates(conn, tickers, *, cutoff_at: datetime) -> dict[str, date]:
    """Per ticker the greater of the newest filing_date and the newest sec_8k news date.

    Both sources are checked as known by ``cutoff_at`` (filings.created_at, news
    fetched_at); the news date is the New York calendar date of its published_at
    (EDGAR acceptance time). sec_8k rows without a published_at have no filing-date
    basis and are not counted — the fetch date must not masquerade as a filing
    date; better undercounted than faked (I14)."""
    if not tickers:
        return {}
    rows = _all(conn, 'SELECT ticker, max(day) AS latest FROM ('
                      '  SELECT ticker, max(filing_date) AS day FROM filings '
                      '  WHERE ticker = ANY(%s) AND created_at <= %s GROUP BY ticker '
                      '  UNION ALL '
                      '  SELECT t.ticker, (max(n.published_at) '
                      "                    AT TIME ZONE 'America/New_York')::date AS day "
                      '  FROM news_items n JOIN news_item_tickers t ON t.news_item_id = n.id '
                      "  WHERE t.ticker = ANY(%s) AND n.source = 'sec_8k' AND n.fetched_at <= %s "
                      '  AND n.published_at IS NOT NULL AND n.published_at <= %s '
                      '  GROUP BY t.ticker) days GROUP BY ticker',
                (list(tickers), cutoff_at, list(tickers), cutoff_at, cutoff_at))
    return {row['ticker']: row['latest'] for row in rows}


def latest_macro_dates(conn, series_ids, *, cutoff_at: datetime) -> dict[str, date]:
    """Per series the newest observation date any revision of which was known by ``cutoff_at``."""
    if not series_ids:
        return {}
    rows = _all(conn, 'SELECT series_id, max(obs_date) AS latest FROM macro_observations '
                      'WHERE series_id = ANY(%s) AND fetched_at <= %s GROUP BY series_id',
                (list(series_ids), cutoff_at))
    return {row['series_id']: row['latest'] for row in rows}


def bar_revision_counts(conn, ticker: str, *, since: date, cutoff_at: datetime) -> dict[date, int]:
    """Per price_date from ``since`` on, how many revisions were known by ``cutoff_at``."""
    rows = conn.execute('SELECT price_date, count(*) FROM price_bars '
                        'WHERE ticker = %s AND price_date >= %s AND fetched_at <= %s '
                        'GROUP BY price_date', (ticker.upper(), since, cutoff_at)).fetchall()
    return {row[0]: row[1] for row in rows}


def macro_revision_counts(conn, series_id: str, *, cutoff_at: datetime) -> dict[date, int]:
    """Per obs_date how many revisions of the series were known by ``cutoff_at``."""
    rows = conn.execute('SELECT obs_date, count(*) FROM macro_observations '
                        'WHERE series_id = %s AND fetched_at <= %s GROUP BY obs_date',
                        (series_id, cutoff_at)).fetchall()
    return {row[0]: row[1] for row in rows}
