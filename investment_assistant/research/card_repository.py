"""Research card storage. Callers own transactions: this layer never commits or rolls back."""
from __future__ import annotations

import json

# Evidence that, when collected after the card was last saved, counts as new for the card.
EVIDENCE_DATASETS = ['financials', 'filings']


class CardConflict(ValueError):
    pass


def get_card(conn, sid):
    with conn.cursor() as cur:
        cur.execute('''SELECT version,body,evidence_seen_at,updated_at
                       FROM research_observation_cards WHERE security_id=%s''', (sid,))
        row = cur.fetchone()
        if not row:
            return None
        cur.execute('''SELECT count(*),max(first_seen_at) FROM us_research_observations
                       WHERE security_id=%s AND first_seen_at>%s
                       AND dataset=ANY(%s)''', (sid, row[2], EVIDENCE_DATASETS))
        changes = cur.fetchone()
        return {'security_id': sid, 'version': row[0], 'body': row[1], 'evidence_seen_at': row[2],
                'updated_at': row[3], 'new_evidence_count': changes[0], 'latest_evidence_at': changes[1]}


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
