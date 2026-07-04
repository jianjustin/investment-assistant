from investment_assistant.api import auth


def test_unknown_api_path_returns_legacy_404_shape(client):
    resp = client.get("/api/does-not-exist-xyz")
    assert resp.status_code == 404
    assert resp.json() == {"error": "not found"}


def test_no_password_configured_allows_anonymous(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "")
    resp = client.get("/api/does-not-exist-xyz")
    assert resp.status_code == 404  # 通过认证，走到 404


def test_password_configured_rejects_anonymous_with_basic_challenge(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "secret")
    resp = client.get("/api/does-not-exist-xyz")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == 'Basic realm="Hermes Investment Assistant"'


def test_password_configured_accepts_valid_basic(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "secret")
    resp = client.get("/api/does-not-exist-xyz", auth=(auth.AUTH_USER, "secret"))
    assert resp.status_code == 404
