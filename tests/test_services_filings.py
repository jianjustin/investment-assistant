import pytest

from investment_assistant.services import filings as filings_svc


def test_filing_records_degraded_without_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = filings_svc.filing_records()
    assert out == {"records": [], "tickers": [], "degraded": True}


def test_filing_records_queries_db(monkeypatch):
    from datetime import date

    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    seen = {}
    monkeypatch.setattr(filings_svc, "connect", lambda url: _FakeCtx("CONN"))
    monkeypatch.setattr(filings_svc.db, "list_filings",
                        lambda conn, **kw: seen.update(kw) or [{"id": 1, "ticker": "AAPL"}])
    monkeypatch.setattr(filings_svc.db, "list_filing_tickers", lambda conn: ["AAPL"])
    out = filings_svc.filing_records(ticker="AAPL", form="10-Q",
                                     from_="2026-01-01", to="2026-06-30", limit=20)
    assert out["records"][0]["ticker"] == "AAPL" and out["tickers"] == ["AAPL"]
    assert seen["start_date"] == date(2026, 1, 1) and seen["limit"] == 20


class _FakeCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *a):
        return False


def test_download_path_missing_record_raises_lookup(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(filings_svc, "connect", lambda url: _FakeCtx("CONN"))
    monkeypatch.setattr(filings_svc.db, "get_filing", lambda conn, i: None)
    with pytest.raises(LookupError):
        filings_svc.filing_download_path(42)


def test_download_path_missing_file_raises_filenotfound(monkeypatch, tmp_path):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(filings_svc, "connect", lambda url: _FakeCtx("CONN"))
    monkeypatch.setattr(filings_svc.db, "get_filing",
                        lambda conn, i: {"id": i, "file_path": str(tmp_path / "gone.htm")})
    with pytest.raises(FileNotFoundError):
        filings_svc.filing_download_path(1)


def test_download_route_404s(client, monkeypatch):
    monkeypatch.setattr(filings_svc, "filing_download_path",
                        lambda i: (_ for _ in ()).throw(LookupError("filing 9 not found")))
    resp = client.get("/api/filings/records/9/download")
    assert resp.status_code == 404


def test_download_route_serves_file(client, monkeypatch, tmp_path):
    f = tmp_path / "a.htm"
    f.write_text("<html>report</html>")
    monkeypatch.setattr(filings_svc, "filing_download_path", lambda i: f)
    resp = client.get("/api/filings/records/1/download")
    assert resp.status_code == 200
    assert b"report" in resp.content
