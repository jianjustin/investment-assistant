"""All workbench SQL. Callers own transactions: this layer never commits or rolls back."""
from __future__ import annotations

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
