from dataclasses import replace

from investment_assistant.config import NotifyConfig
from investment_assistant.services import settings


def test_effective_notify_config_no_db_returns_base(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    base = NotifyConfig(webhooks={"daily": "file-url"})
    assert settings.effective_notify_config(base) is base


def test_effective_notify_config_overlays_db(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(settings.db, "get_notify_settings", lambda conn: {
        "discord_enabled": False, "webhooks": {"daily": "db-url"},
        "task_channels": {}, "task_enabled": {"metrics": False},
    })
    base = NotifyConfig(webhooks={"daily": "file-url", "signals": "s"})
    out = settings.effective_notify_config(base)
    assert out.discord_enabled is False
    assert out.webhooks["daily"] == "db-url" and out.webhooks["signals"] == "s"  # 合并覆盖
    assert out.task_enabled["metrics"] is False


def test_read_notify_view_masks_webhooks(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(settings.db, "get_notify_settings", lambda conn: {
        "discord_enabled": True, "webhooks": {"daily": "https://secret"},
        "task_channels": {"metrics": "daily"}, "task_enabled": {"metrics": True},
    })
    view = settings.read_notify_view()
    assert view["webhooks"] == {"daily": {"configured": True}}  # 不回显明文
    assert "https://secret" not in str(view)


def test_test_notify_channel_uses_candidate_url():
    sent = []

    class FakeClient:
        def __init__(self, **urls):
            self._urls = urls

        def send(self, channel, payload):
            sent.append((channel, payload))

    out = settings.test_notify_channel("daily", url="https://candidate", client=FakeClient())
    assert out["ok"] is True and sent


def test_test_notify_channel_reports_failure():
    class Boom:
        def send(self, channel, payload):
            raise RuntimeError("network")

    out = settings.test_notify_channel("daily", url="https://x", client=Boom())
    assert out["ok"] is False and "network" in out["error"]


def test_test_notify_channel_sanitizes_webhook_token_in_error():
    """Error messages containing Discord webhook URLs must not leak the secret token."""
    class LeakyClient:
        def send(self, channel, payload):
            raise RuntimeError(
                "Max retries exceeded with url: "
                "https://discord.com/api/webhooks/123/SECRETTOKEN"
            )

    out = settings.test_notify_channel("daily", url="https://x", client=LeakyClient())
    assert out["ok"] is False
    assert "SECRETTOKEN" not in out["error"]
    assert "<webhook redacted>" in out["error"]


def test_read_env_status_booleans(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "x y@z")
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = settings.read_env_status()
    assert out["SEC_USER_AGENT"] is True and out["INVESTMENT_ASSISTANT_DATABASE_URL"] is False


def test_effective_notify_config_overlays_channel_and_email(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(settings.db, "get_notify_settings", lambda conn: {
        "channel": "email", "email": {"to_addr": "you@outlook.com"},
    })
    out = settings.effective_notify_config(NotifyConfig())
    assert out.channel == "email"
    assert out.email["to_addr"] == "you@outlook.com"
    assert out.email["host"] == "smtp.gmail.com"  # 与基础默认合并


def test_read_notify_view_includes_channel_and_email(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(settings.db, "get_notify_settings", lambda conn: {
        "channel": "email", "email": {"from_addr": "me@gmail.com", "to_addr": "you@outlook.com"},
    })
    view = settings.read_notify_view()
    assert view["channel"] == "email"
    assert view["email"]["to_addr"] == "you@outlook.com"


def test_update_notify_rejects_invalid_channel(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    out = settings.update_notify({"channel": "sms"})
    assert out == {"updated": False, "error": "invalid channel"}


def test_update_notify_passes_channel_and_email(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    captured = {}

    def fake_update(conn, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(settings.db, "update_notify_settings", fake_update)
    settings.update_notify({"channel": "email", "email": {"to_addr": "you@outlook.com", "from_addr": "  "}})
    assert captured["channel"] == "email"
    assert captured["email"] == {"to_addr": "you@outlook.com"}  # 空白值不覆盖


def test_update_notify_rejects_unknown_email_keys(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    captured = {}

    def fake_update(conn, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(settings.db, "update_notify_settings", fake_update)
    settings.update_notify({"email": {"to_addr": "you@outlook.com", "password": "hunter2"}})
    assert captured["email"] == {"to_addr": "you@outlook.com"}
    assert "password" not in captured["email"]


def test_test_notify_channel_email_uses_client():
    sent = []

    class FakeEmail:
        def send(self, subject, html_body):
            sent.append((subject, html_body))

    out = settings.test_notify_channel("email", client=FakeEmail())
    assert out["ok"] is True and sent and sent[0][0].startswith("[Hermes]")


def test_test_notify_channel_email_requires_password(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = settings.test_notify_channel("email", email={"to_addr": "you@outlook.com"})
    assert out["ok"] is False and "SMTP_PASSWORD" in out["error"]


def test_test_notify_channel_email_requires_recipient(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = settings.test_notify_channel("email")
    assert out["ok"] is False and "recipient" in out["error"]


def test_read_env_status_includes_smtp_password(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert settings.read_env_status()["SMTP_PASSWORD"] is False
