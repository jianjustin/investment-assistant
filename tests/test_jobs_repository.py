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


def test_list_scheduled_jobs_maps_rows():
    rows = [("metrics", "08:00", "1-5", "America/New_York", True, None, None)]
    conn = FakeConn(rows=rows)
    out = db.list_scheduled_jobs(conn)
    assert out[0]["name"] == "metrics" and out[0]["enabled"] is True
    assert "ORDER BY name" in conn.store[0][0]


def test_list_job_reports_filters_by_task_and_limit():
    rows = [("metrics", "metrics-1", "success", None, None, {"n": 1}, None)]
    conn = FakeConn(rows=rows)
    out = db.list_job_reports(conn, task="metrics", limit=10)
    assert out[0]["run_id"] == "metrics-1" and out[0]["summary"] == {"n": 1}
    sql, params = conn.store[0]
    assert "WHERE task = %(task)s" in sql and params["task"] == "metrics" and params["limit"] == 10


def test_list_job_reports_no_task_omits_where():
    conn = FakeConn(rows=[])
    db.list_job_reports(conn)
    assert "WHERE task" not in conn.store[0][0]


def test_job_report_metrics_aggregates():
    rows = [("metrics", 5, 4, 12.5, [{"day": "2026-06-28", "count": 1}])]
    conn = FakeConn(rows=rows)
    out = db.job_report_metrics(conn, since=datetime(2026, 6, 22, tzinfo=UTC))
    assert out[0]["task"] == "metrics" and out[0]["success"] == 4 and out[0]["avg_seconds"] == 12.5


def test_update_scheduled_job_partial_and_clears_next_run_on_time_change():
    conn = FakeConn()
    db.update_scheduled_job(conn, "metrics", time_local="09:30")
    sql, params = conn.store[0]
    assert "UPDATE scheduled_jobs" in sql and "next_run_at = NULL" in sql
    assert params["time_local"] == "09:30" and params["name"] == "metrics"
    assert conn.commits == 1


def test_update_scheduled_job_enabled_only_keeps_next_run():
    conn = FakeConn()
    db.update_scheduled_job(conn, "metrics", enabled=False)
    sql, _ = conn.store[0]
    assert "enabled = %(enabled)s" in sql and "next_run_at = NULL" not in sql


def test_get_notify_settings_maps_row():
    rows = [(True, {"daily": "u"}, {"metrics": "daily"}, {"metrics": True})]
    conn = FakeConn(rows=rows)
    out = db.get_notify_settings(conn)
    assert out["discord_enabled"] is True and out["webhooks"]["daily"] == "u"


def test_get_notify_settings_empty_when_no_row():
    conn = FakeConn(rows=[])
    assert db.get_notify_settings(conn) == {}


def test_update_notify_settings_merges_jsonb():
    conn = FakeConn()
    db.update_notify_settings(conn, webhooks={"daily": "u2"}, discord_enabled=False)
    sql, params = conn.store[0]
    assert "UPDATE notify_settings" in sql and "webhooks = webhooks ||" in sql
    assert "discord_enabled = %(discord_enabled)s" in sql
    assert conn.commits == 1
