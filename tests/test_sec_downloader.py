from datetime import date

from investment_assistant.filings import sec_downloader
from investment_assistant.filings.sec_downloader import SecEdgarDownloader


def make_getter(tickers_json, submissions_json):
    def _getter(url, **kw):
        if "company_tickers.json" in url:
            return tickers_json, {"ok": True, "error": None, "status_code": 200}
        if "submissions" in url:
            return submissions_json, {"ok": True, "error": None, "status_code": 200}
        return None, {"ok": False, "error": "404", "status_code": 404}
    return _getter


def test_download_filters_by_form_and_yesterday(tmp_path, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    tickers_json = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}
    submissions_json = {"filings": {"recent": {
        "form": ["10-Q", "8-K", "10-K"],
        "filingDate": ["2026-06-28", "2026-06-28", "2026-06-01"],
        "accessionNumber": ["acc-q", "acc-8k", "acc-k"],
        "primaryDocument": ["q.htm", "8k.htm", "k.htm"],
    }}}
    getter = make_getter(tickers_json, submissions_json)
    written = []
    monkeypatch.setattr(sec_downloader, "_download_document",
                        lambda url, dest, *, headers: (written.append((url, dest)) or dest))

    dl = SecEdgarDownloader(getter=getter, cache_dir=tmp_path)
    out = dl.download_filings_batch("AAPL", ["10-Q", "10-K"], date(2026, 6, 28), tmp_path / "filings")
    # 仅 2026-06-28 的 10-Q 命中（10-K 日期不符、8-K 表单不符）
    assert len(out) == 1
    assert "10-Q" in str(out[0])


def test_download_degrades_without_user_agent(tmp_path, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    dl = SecEdgarDownloader(getter=lambda *a, **k: (None, {"ok": False}), cache_dir=tmp_path)
    out = dl.download_filings_batch("AAPL", ["10-Q"], date(2026, 6, 28), tmp_path / "filings")
    assert out == []
