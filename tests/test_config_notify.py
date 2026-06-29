from investment_assistant.config import _config_from_dict
from investment_assistant.notify.discord import DiscordChannel, DiscordClient


def test_notify_config_defaults():
    cfg = _config_from_dict({})
    assert cfg.notify.discord_enabled is True
    assert cfg.notify.task_channels["metrics"] == "daily"
    assert cfg.notify.task_channels["filings"] == "earnings"
    assert cfg.notify.task_enabled["metrics"] is True


def test_notify_config_override_from_dict():
    cfg = _config_from_dict({"notify": {
        "discord_enabled": False,
        "webhooks": {"daily": "https://hook/daily"},
        "task_enabled": {"filings": False},
    }})
    assert cfg.notify.discord_enabled is False
    assert cfg.notify.webhooks["daily"] == "https://hook/daily"
    assert cfg.notify.task_enabled["filings"] is False


def test_from_config_prefers_config_webhook(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_EARNINGS", "env-earnings")
    monkeypatch.setenv("DISCORD_WEBHOOK_SIGNALS", "env-signals")
    monkeypatch.setenv("DISCORD_WEBHOOK_DAILY", "env-daily")
    from investment_assistant.config import NotifyConfig
    cfg = NotifyConfig(webhooks={"daily": "cfg-daily"})
    client = DiscordClient.from_config(cfg)
    assert client._urls[DiscordChannel.DAILY] == "cfg-daily"
    assert client._urls[DiscordChannel.EARNINGS] == "env-earnings"
