"""PostgreSQL repositories using the application's existing connection pool."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime


def _stable(value):
    if isinstance(value, dict):
        return {k: (str(v)[:19] if k in {'display_time', 'eiTime', 'provider_ingest_time'} and v else _stable(v))
                for k, v in value.items()
                if k not in {'origins', 'source_url', 'response_sha256'}}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def content_hash(row):
    body = {'payload': _stable(row['payload']), 'data_date': str(row.get('data_date')),
            'disclosed_at': str(row.get('disclosed_at'))}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def store_rows(conn, sid, dataset, rows, *, now=None):
    now = now or datetime.now(UTC)
    inserted = 0
    with conn.cursor() as cur:
        for r in rows:
            fingerprint = content_hash(r)
            cur.execute('''SELECT id, revision, payload FROM cn_observations
                WHERE security_id=%s AND dataset=%s AND natural_key=%s
                ORDER BY first_seen_at DESC,id DESC LIMIT 1''', (sid, dataset, r['natural_key']))
            old = cur.fetchone()
            if old and old[2].get('_content_hash') == fingerprint:
                cur.execute('UPDATE cn_observations SET last_seen_at=%s WHERE id=%s', (now, old[0]))
                continue
            # Chaining preserves A→B→A revisions while consecutive retries deduplicate.
            revision = hashlib.sha256((fingerprint + (old[1] if old else '')).encode()).hexdigest()
            payload = {**r['payload'], '_content_hash': fingerprint,
                       'response_sha256': r.get('response_sha256')}
            cur.execute('''INSERT INTO cn_observations
                (security_id,dataset,natural_key,revision,data_date,disclosed_at,source,source_url,payload,first_seen_at,last_seen_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)''',
                (sid, dataset, r['natural_key'], revision, r.get('data_date'), r.get('disclosed_at'),
                 r['source'], r['source_url'], json.dumps(payload, ensure_ascii=False), now, now))
            inserted += 1
    return inserted


def read_rows(conn, sid, dataset, *, as_of=None):
    params = [sid, dataset]
    cutoff = ''
    if as_of:
        cutoff = 'AND first_seen_at <= %s AND (disclosed_at IS NULL OR disclosed_at <= %s)'
        params += [as_of, as_of]
    with conn.cursor() as cur:
        cur.execute(f'''SELECT DISTINCT ON (natural_key) id, payload, source, source_url,
              data_date, disclosed_at, first_seen_at, last_seen_at, revision
            FROM cn_observations WHERE security_id=%s AND dataset=%s {cutoff}
            ORDER BY natural_key,first_seen_at DESC,id DESC''', params)
        return [{**r[1], 'id': r[0], 'source': r[2], 'source_url': r[3], 'data_date': str(r[4]),
                 'available_after': r[5], 'first_seen_at': r[6], 'last_seen_at': r[7], 'revision': r[8]}
                for r in cur.fetchall()]


def collection_state(conn, sid, dataset, *, status, start, end, count=0, error=None, details=None):
    now = datetime.now(UTC)
    succeeded = now if status in {'ready', 'empty', 'partial'} else None
    with conn.cursor() as cur:
        cur.execute('''INSERT INTO cn_collection_state
            (security_id,dataset,status,attempted_at,succeeded_at,requested_start,requested_end,row_count,error,details)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT (security_id,dataset) DO UPDATE SET status=excluded.status,
            attempted_at=excluded.attempted_at,
            succeeded_at=COALESCE(excluded.succeeded_at,cn_collection_state.succeeded_at),
            requested_start=excluded.requested_start, requested_end=excluded.requested_end,
            row_count=excluded.row_count,error=excluded.error,details=excluded.details''',
            (sid, dataset, status, now, succeeded, start, end, count, error, json.dumps(details or {})))


def states(conn, sid):
    with conn.cursor() as cur:
        cur.execute('''SELECT dataset,status,attempted_at,succeeded_at,requested_start,requested_end,row_count,error,details
            FROM cn_collection_state WHERE security_id=%s''', (sid,))
        keys = ['dataset', 'status', 'attempted_at', 'succeeded_at', 'requested_start', 'requested_end', 'row_count', 'error', 'details']
        return {r[0]: dict(zip(keys, r)) for r in cur.fetchall()}


def first_collection(conn, sid):
    with conn.cursor() as cur:
        cur.execute('''SELECT dataset,min(first_seen_at) FROM cn_observations
                       WHERE security_id=%s GROUP BY dataset''', (sid,))
        return dict(cur.fetchall())


def get_card(conn, sid):
    with conn.cursor() as cur:
        cur.execute('''SELECT version,body,evidence_seen_at,updated_at
                       FROM research_observation_cards WHERE security_id=%s''', (sid,))
        row = cur.fetchone()
        if not row:
            return None
        table = 'us_research_observations' if sid.startswith('US:') else 'cn_observations'
        datasets = ['financials', 'filings'] if sid.startswith('US:') else ['financials', 'announcements', 'disclosure', 'unlocks']
        cur.execute(f'''SELECT count(*),max(first_seen_at) FROM {table}
                       WHERE security_id=%s AND first_seen_at>%s
                       AND dataset=ANY(%s)''', (sid, row[2], datasets))
        changes = cur.fetchone()
        return {'security_id': sid, 'version': row[0], 'body': row[1], 'evidence_seen_at': row[2],
                'updated_at': row[3], 'new_evidence_count': changes[0], 'latest_evidence_at': changes[1]}


class CardConflict(ValueError):
    pass


def save_card(conn, sid, body, expected_version):
    with conn.cursor() as cur:
        # Serialize absent-row creation as well as edits without a lost update.
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('research-card:' + sid,))
        cur.execute('SELECT version FROM research_observation_cards WHERE security_id=%s FOR UPDATE', (sid,))
        existing = cur.fetchone()
        version = existing[0] if existing else 0
        if expected_version != version:
            raise CardConflict('观察卡已被更新，请刷新后合并；没有覆盖其他修改')
        value = json.dumps(body, ensure_ascii=False)
        cur.execute('''INSERT INTO research_observation_cards(security_id,version,body) VALUES(%s,%s,%s::jsonb)
            ON CONFLICT(security_id) DO UPDATE SET version=excluded.version,body=excluded.body,
            updated_at=now(),evidence_seen_at=now()''', (sid, version + 1, value))
        cur.execute('''INSERT INTO research_observation_card_versions(security_id,version,body)
            VALUES(%s,%s,%s::jsonb)''', (sid, version + 1, value))
    return get_card(conn, sid)
