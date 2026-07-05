from investment_assistant import db


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConn:
    def __init__(self, rows=()):
        self.cur = FakeCursor(list(rows))
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


def test_get_notify_settings_returns_channel_and_email():
    row = (True, {}, {}, {}, "email", {"to_addr": "you@outlook.com"})
    out = db.get_notify_settings(FakeConn(rows=[row]))
    assert out["channel"] == "email"
    assert out["email"] == {"to_addr": "you@outlook.com"}


def test_update_notify_settings_writes_channel_scalar_and_email_merge():
    conn = FakeConn()
    db.update_notify_settings(conn, channel="email", email={"to_addr": "you@outlook.com"})
    sql, params = conn.cur.executed[0]
    assert "channel = %(channel)s" in sql
    assert "email = email || %(email)s::jsonb" in sql
    assert params["channel"] == "email"
    assert "you@outlook.com" in params["email"]
    assert conn.committed is True
