from datetime import date

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

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class FakeConn:
    def __init__(self):
        self.store = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.commits += 1


def test_upsert_filing_conflicts_on_accession():
    conn = FakeConn()
    db.upsert_filing(
        conn, ticker="AAPL", form="10-Q", filing_date=date(2026, 6, 28),
        accession_number="acc-1", primary_document="q.htm",
        file_path="/data/AAPL/10-Q/acc-1-q.htm",
    )
    sql, params = conn.store[0]
    assert "INSERT INTO filings" in sql
    assert "ON CONFLICT (accession_number, primary_document)" in sql
    assert params["ticker"] == "AAPL" and params["run_id"] is None
    assert conn.commits == 1


def test_list_filings_applies_filters():
    conn = FakeConn()
    db.list_filings(conn, ticker="AAPL", form="10-Q",
                    start_date=date(2026, 1, 1), end_date=date(2026, 6, 30), limit=20)
    sql, params = conn.store[0]
    assert "ticker = %(ticker)s" in sql and "form = %(form)s" in sql
    assert "filing_date >= %(start_date)s" in sql and "filing_date <= %(end_date)s" in sql
    assert params["limit"] == 20


def test_get_filing_by_id_returns_none_when_missing():
    assert db.get_filing(FakeConn(), 42) is None
