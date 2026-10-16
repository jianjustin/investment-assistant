"""Append-only US observations. Caller owns transactions and dataset commits."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

# Acquisition metadata is not an economic revision. Keep the original pointer/hash
# together on consecutive repeats, even when another fact changes the response.
_PROVENANCE = {'id', 'source_url', 'source_hash', 'source_locator', 'snapshot_path',
               'collected_at', 'raw_snapshots', 'snapshots', 'first_seen_at', 'last_seen_at',
               'revision', 'security_id', 'dataset', 'natural_key', 'disclosed_at'}


def _economic(value):
    if isinstance(value, dict):
        return {k: _economic(v) for k, v in value.items() if k not in _PROVENANCE}
    if isinstance(value, list):
        return [_economic(v) for v in value]
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def store_rows(conn, sid, dataset, rows, *, now=None):
    """Return one persisted record per input (including deduplicated inputs).

    Each input is {natural_key, payload, disclosed_at?, source_url?, source_hash?}.
    Dataset-level serialization includes absent-row creation. Dataset acquisition
    ordering is additionally protected by the service lock held before remote I/O.
    """
    now = now or datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('us-research:' + sid + ':' + dataset,))
        ids = []
        for row in rows:
            payload = dict(row['payload'])
            payload.pop('id', None)  # Adapter hashes are never database references.
            # Human guidance edits include source-only corrections. Acquisition-only
            # metadata is not part of its authored content, but URL/locator are.
            content = ({k: v for k, v in payload.items() if k not in {'collected_at', 'first_seen_at', 'last_seen_at', 'revision', 'snapshot_path'}}
                       if dataset == 'guidance' else _economic(payload))
            fingerprint = hashlib.sha256(_json({'payload': content,
                'disclosed_at': str(row.get('disclosed_at'))}).encode()).hexdigest()
            cur.execute('''SELECT id,revision,content_hash FROM us_research_observations
                WHERE security_id=%s AND dataset=%s AND natural_key=%s ORDER BY id DESC LIMIT 1''',
                (sid, dataset, row['natural_key']))
            old = cur.fetchone()
            if old and old[2] == fingerprint:
                cur.execute('UPDATE us_research_observations SET last_seen_at=%s WHERE id=%s', (now, old[0]))
                ids.append(old[0])
                continue
            revision = hashlib.sha256((fingerprint + (old[1] if old else '')).encode()).hexdigest()
            cur.execute('''INSERT INTO us_research_observations
                (security_id,dataset,natural_key,revision,content_hash,payload,source_url,source_hash,
                 disclosed_at,first_seen_at,last_seen_at) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s) RETURNING id''',
                (sid, dataset, row['natural_key'], revision, fingerprint, _json(payload), row.get('source_url'),
                 row.get('source_hash'), row.get('disclosed_at'), now, now))
            ids.append(cur.fetchone()[0])
        if not ids:
            return []
        cur.execute('''SELECT id,payload,security_id,dataset,natural_key,revision,source_url,source_hash,
            disclosed_at,first_seen_at,last_seen_at FROM us_research_observations WHERE id=ANY(%s)''', (ids,))
        records = {r[0]: _record(r) for r in cur.fetchall()}
        return [records[id_] for id_ in ids]


def _record(r):
    return {**r[1], 'id': r[0], 'security_id': r[2], 'dataset': r[3], 'natural_key': r[4], 'revision': r[5],
            'source_url': r[6] or r[1].get('source_url'), 'source_hash': r[7] or r[1].get('source_hash'),
            'disclosed_at': r[8], 'first_seen_at': r[9], 'last_seen_at': r[10]}


def _read(conn, sid, dataset, *, as_of=None, history=False):
    params = [sid, dataset]
    cutoff = ''
    if as_of is not None:
        cutoff = 'AND first_seen_at<=%s AND (disclosed_at IS NULL OR disclosed_at<=%s)'
        params.extend([as_of, as_of])
    distinct = '' if history else 'DISTINCT ON (natural_key)'
    order = 'id' if history else 'natural_key,id DESC'
    with conn.cursor() as cur:
        cur.execute(f'''SELECT {distinct} id,payload,security_id,dataset,natural_key,revision,source_url,source_hash,
            disclosed_at,first_seen_at,last_seen_at FROM us_research_observations
            WHERE security_id=%s AND dataset=%s {cutoff} ORDER BY {order}''', params)
        return [_record(r) for r in cur.fetchall()]


def read_rows(conn, sid, dataset, *, as_of=None):
    """Current eligible revision per natural key, local observation/disclosure cutoff."""
    return _read(conn, sid, dataset, as_of=as_of)


def read_history(conn, sid, dataset, *, as_of=None):
    """All eligible append-only revisions in insertion order (including guidance)."""
    return _read(conn, sid, dataset, as_of=as_of, history=True)


def collection_state(conn, sid, dataset, *, status, count=0, error=None, details=None):
    now = datetime.now(UTC)
    succeeded = now if status in {'ready', 'partial', 'empty'} else None
    details = _json(details or {})
    with conn.cursor() as cur:
        cur.execute('''INSERT INTO us_research_collection_state
            (security_id,dataset,status,attempted_at,succeeded_at,row_count,error,details,last_success_details)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
            ON CONFLICT (security_id,dataset) DO UPDATE SET status=excluded.status,
            attempted_at=excluded.attempted_at,error=excluded.error,details=excluded.details,
            succeeded_at=COALESCE(excluded.succeeded_at,us_research_collection_state.succeeded_at),
            row_count=CASE WHEN excluded.succeeded_at IS NULL THEN us_research_collection_state.row_count ELSE excluded.row_count END,
            last_success_details=CASE WHEN excluded.succeeded_at IS NULL THEN us_research_collection_state.last_success_details ELSE excluded.last_success_details END''',
            (sid, dataset, status, now, succeeded, count, error, details, details if succeeded else '{}'))


def states(conn, sid):
    keys = ['dataset', 'status', 'attempted_at', 'succeeded_at', 'row_count', 'error', 'details', 'last_success_details']
    with conn.cursor() as cur:
        cur.execute('''SELECT dataset,status,attempted_at,succeeded_at,row_count,error,details,last_success_details
            FROM us_research_collection_state WHERE security_id=%s''', (sid,))
        return {r[0]: dict(zip(keys, r)) for r in cur.fetchall()}
