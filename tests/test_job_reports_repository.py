from datetime import UTC, datetime

from investment_assistant import db


class FakeCursor:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.store.append((sql, params))


class FakeConn:
    def __init__(self):
        self.store = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.commits += 1


def test_insert_job_report_writes_and_prunes():
    conn = FakeConn()
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    db.insert_job_report(
        conn, task="metrics", run_id="metrics-1", status="success",
        started_at=now, finished_at=now, summary={"n": 1},
    )
    sqls = [sql for sql, _ in conn.store]
    assert any("INSERT INTO job_reports" in s for s in sqls)
    assert any("DELETE FROM job_reports" in s and "30 days" in s for s in sqls)
    assert conn.commits == 1
