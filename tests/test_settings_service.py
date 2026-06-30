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
