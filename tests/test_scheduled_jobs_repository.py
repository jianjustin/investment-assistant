from datetime import UTC, datetime

from investment_assistant import db


class FakeCursor:
    def __init__(self, store, rows):
        self.store = store
        self.rows = rows

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
        self.store = []
        self.commits = 0
        self.rows = rows or []

    def cursor(self):
        return FakeCursor(self.store, self.rows)

    def commit(self):
        self.commits += 1


def test_due_scheduled_jobs_uses_skip_locked():
    rows = [(1, "metrics", "08:00", "1-5", "America/New_York", None)]
    conn = FakeConn(rows=rows)
    out = db.due_scheduled_jobs(conn, now=datetime(2026, 6, 29, 12, 0, tzinfo=UTC))
    assert out[0]["name"] == "metrics" and out[0]["time_local"] == "08:00"
    assert any("FOR UPDATE SKIP LOCKED" in sql for sql, _ in conn.store)


def test_reschedule_job_updates_next_run():
    conn = FakeConn()
    db.reschedule_job(
        conn, "metrics",
        next_run_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        last_run_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
    )
    assert any("UPDATE scheduled_jobs" in sql for sql, _ in conn.store)
    assert conn.commits == 1
