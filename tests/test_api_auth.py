import base64
import pytest
from investment_assistant.api import auth


def _basic(u, p):
    return "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()


def test_no_password_allows(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "")
    assert auth.authorize(None) is True


def test_correct_password(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "secret")
    monkeypatch.setattr(auth, "AUTH_USER", "jianjustin")
    assert auth.authorize(_basic("jianjustin", "secret")) is True
    assert auth.authorize(_basic("jianjustin", "wrong")) is False
    assert auth.authorize(None) is False


def test_public_bind_without_auth_refused(monkeypatch):
    monkeypatch.setattr(auth, "HOST", "0.0.0.0")
    monkeypatch.setattr(auth, "ALLOW_PUBLIC_BIND", True)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "")
    with pytest.raises(SystemExit):
        auth.resolve_bind_host()
