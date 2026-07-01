import json

from investment_assistant import db


class FakeCursor:
    def __init__(self, store, rows):
        self.store, self.rows = store, rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.store.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows=None):
        self.store, self.commits, self.rows = [], 0, rows or []

    def cursor(self):
        return FakeCursor(self.store, self.rows)

    def commit(self):
        self.commits += 1


def test_upsert_event_study_uses_conflict():
    conn = FakeConn()
    db.upsert_event_study(conn, kind="rs_strong", params_hash="h1", result={"n": 5})
    sql, params = conn.store[0]
    assert "INSERT INTO event_studies" in sql
    assert "ON CONFLICT (kind, params_hash) DO UPDATE" in sql
    assert params["kind"] == "rs_strong" and params["params_hash"] == "h1"
    assert params["result"] == json.dumps({"n": 5}, ensure_ascii=False)
    assert conn.commits == 1


def test_get_event_study_maps_row():
    rows = [("rs_strong", "h1", {"n": 5}, None)]
    conn = FakeConn(rows=rows)
    out = db.get_event_study(conn, kind="rs_strong", params_hash="h1")
    assert out["kind"] == "rs_strong" and out["result"] == {"n": 5}


def test_get_event_study_none_when_missing():
    conn = FakeConn(rows=[])
    assert db.get_event_study(conn, kind="rs_strong", params_hash="zzz") is None
