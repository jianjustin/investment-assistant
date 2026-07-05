from pathlib import Path

import investment_assistant.api.static_files as static_files_mod
import investment_assistant.services.status as status_svc


def test_static_route_serves_index_html(tmp_path, monkeypatch, client):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>Hermes Dashboard</body></html>", encoding="utf-8")
    monkeypatch.setattr(static_files_mod, "STATIC_DIR", dist)

    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert b"Hermes Dashboard" in resp.content


def test_status_payload_includes_system(monkeypatch):
    monkeypatch.setattr(status_svc, "database_status", lambda: {"ok": True})
    monkeypatch.setattr(status_svc, "filing_status", lambda: {"file_count": 49})
    monkeypatch.setattr(status_svc, "system_status", lambda: {"dashboard_service": "active"})

    payload = status_svc.status_payload()

    assert set(payload) == {"database", "filings", "system"}
    assert payload["system"]["dashboard_service"] == "active"


def test_api_response_for_path_returns_feature_payloads(monkeypatch, client):
    monkeypatch.setattr(status_svc, "database_status", lambda: {"ok": True, "latest_market_signal": {"market_status": "green"}})
    monkeypatch.setattr(status_svc, "filing_status", lambda: {"path": "/srv/filings", "exists": True, "file_count": 2})
    monkeypatch.setattr(status_svc, "system_status", lambda: {"dashboard_service": {"ok": True, "output": "active"}})

    assert client.get("/api/services").json() == {"dashboard_service": {"ok": True, "output": "active"}}
    assert client.get("/api/market/signals/latest").json() == {"market_status": "green"}
    operations_payload = client.get("/api/operations").json()
    assert operations_payload["operations"][0]["id"] == "fetch_market_signals"
    assert operations_payload["operations"][0]["enabled"] is True
    assert sorted(client.get("/api/raw/status").json()) == ["database", "filings", "system"]
    missing_resp = client.get("/api/missing")
    assert missing_resp.status_code == 404
    assert missing_resp.json() == {"error": "not found"}
