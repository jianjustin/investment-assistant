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
