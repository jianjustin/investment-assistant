from pathlib import Path

from investment_assistant.dashboard import server


def test_static_response_serves_index_html(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>Hermes Dashboard</body></html>", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC_DIR", dist)

    response = server.static_response_for_path("/")

    assert response is not None
    assert response.status == 200
    assert response.content_type.startswith("text/html")
    assert b"Hermes Dashboard" in response.body


def test_status_payload_includes_system(monkeypatch):
    monkeypatch.setattr(server, "database_status", lambda: {"ok": True})
    monkeypatch.setattr(server, "filing_status", lambda: {"file_count": 49})
    monkeypatch.setattr(server, "system_status", lambda: {"dashboard_service": "active"})

    payload = server.status_payload()

    assert set(payload) == {"database", "filings", "system"}
    assert payload["system"]["dashboard_service"] == "active"


def test_api_response_for_path_returns_feature_payloads(monkeypatch):
    monkeypatch.setattr(server, "database_status", lambda: {"ok": True, "latest_market_signal": {"market_status": "green"}})
    monkeypatch.setattr(server, "filing_status", lambda: {"path": "/srv/filings", "exists": True, "file_count": 2})
    monkeypatch.setattr(server, "filing_rows", lambda: [{"name": "a.htm", "size": 10}])
    monkeypatch.setattr(server, "system_status", lambda: {"dashboard_service": {"ok": True, "output": "active"}})

    assert server.api_response_for_path("/api/services").payload == {"dashboard_service": {"ok": True, "output": "active"}}
    assert server.api_response_for_path("/api/market/signals/latest").payload == {"market_status": "green"}
    filings_payload = server.api_response_for_path("/api/filings").payload
    assert filings_payload["summary"] == {"path": "/srv/filings", "exists": True, "file_count": 2}
    assert filings_payload["files"] == [{"name": "a.htm", "size": 10}]
    operations_payload = server.api_response_for_path("/api/operations").payload
    assert operations_payload["operations"][0]["id"] == "fetch_market_signals"
    assert operations_payload["operations"][0]["enabled"] is True
    assert sorted(server.api_response_for_path("/api/raw/status").payload) == ["database", "filings", "system"]
    assert server.api_response_for_path("/api/missing") is None
