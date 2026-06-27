from pathlib import Path
from investment_assistant.db import apply_pending_migrations


class FakeCursor:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.store["executed"].append((sql.strip().split("\n")[0], params))
        if sql.strip().startswith("INSERT INTO schema_migrations"):
            self.store["applied"].add(params[0])

    def fetchall(self):
        return [(name,) for name in sorted(self.store["applied"])]


class FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.store["commits"] += 1


def test_apply_pending_runs_each_unapplied_in_order(tmp_path):
    (tmp_path / "001_a.sql").write_text("CREATE TABLE a();")
    (tmp_path / "002_b.sql").write_text("CREATE TABLE b();")
    store = {"executed": [], "applied": set(), "commits": 0}
    applied = apply_pending_migrations(FakeConn(store), tmp_path)
    assert applied == ["001_a.sql", "002_b.sql"]


def test_apply_pending_skips_already_recorded(tmp_path):
    (tmp_path / "001_a.sql").write_text("CREATE TABLE a();")
    (tmp_path / "002_b.sql").write_text("CREATE TABLE b();")
    store = {"executed": [], "applied": {"001_a.sql"}, "commits": 0}
    applied = apply_pending_migrations(FakeConn(store), tmp_path)
    assert applied == ["002_b.sql"]


from unittest.mock import patch
from investment_assistant import migrate


def test_run_invokes_apply_pending(monkeypatch, tmp_path):
    captured = {}

    class Ctx:
        def __enter__(self):
            return "CONN"

        def __exit__(self, *a):
            return False

    with patch.object(migrate, "connect", return_value=Ctx()) as conn, \
         patch.object(migrate, "apply_pending_migrations", return_value=["005_x.sql"]) as app:
        out = migrate.run("postgres://x", migrations_dir=tmp_path)
    conn.assert_called_once_with("postgres://x")
    app.assert_called_once()
    assert out == ["005_x.sql"]
