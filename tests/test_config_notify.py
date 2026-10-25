from investment_assistant.config import _config_from_dict
from investment_assistant.notify.discord import DiscordChannel, DiscordClient


def test_notify_config_defaults():
    cfg = _config_from_dict({})
    assert cfg.notify.channel == "discord"
    assert cfg.notify.discord_enabled is True
    assert cfg.notify.email["host"] == "smtp.gmail.com"
    assert cfg.notify.email["port"] == 465
    assert cfg.notify.task_channels["filings"] == "earnings"
    assert cfg.notify.task_enabled["filings"] is True
    assert "metrics" not in cfg.notify.task_channels and "scores" not in cfg.notify.task_channels
    assert not hasattr(cfg.notify, "email_enabled")


def test_notify_config_override_from_dict():
    cfg = _config_from_dict({"notify": {
        "discord_enabled": False,
        "webhooks": {"signals": "https://hook/signals"},
        "task_enabled": {"filings": False},
    }})
    assert cfg.notify.discord_enabled is False
    assert cfg.notify.webhooks["signals"] == "https://hook/signals"
    assert cfg.notify.task_enabled["filings"] is False


def test_notify_config_channel_override_from_dict():
    cfg = _config_from_dict({"notify": {
        "channel": "email",
        "email": {"from_addr": "me@gmail.com", "to_addr": "you@outlook.com"},
    }})
    assert cfg.notify.channel == "email"
    assert cfg.notify.email["to_addr"] == "you@outlook.com"


def test_from_config_prefers_config_webhook(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_EARNINGS", "env-earnings")
    monkeypatch.setenv("DISCORD_WEBHOOK_SIGNALS", "env-signals")
    from investment_assistant.config import NotifyConfig
    cfg = NotifyConfig(webhooks={"signals": "cfg-signals"})
    client = DiscordClient.from_config(cfg)
    assert client._urls[DiscordChannel.SIGNALS] == "cfg-signals"
    assert client._urls[DiscordChannel.EARNINGS] == "env-earnings"


def test_notify_defaults_include_workbench():
    cfg = _config_from_dict({})
    assert cfg.notify.task_channels["workbench"] == "signals"
    assert cfg.notify.task_enabled["workbench"] is True


def test_review_task_notify_defaults():
    cfg = _config_from_dict({})
    assert cfg.notify.task_channels['workbench_review'] == 'signals'
    assert cfg.notify.task_enabled['workbench_review'] is True


def test_default_routes_have_no_legacy_tasks():
    from investment_assistant.config import NotifyConfig

    cfg = NotifyConfig()
    assert set(cfg.task_channels) == {"filings", "workbench", "workbench_review"}
    assert set(cfg.task_enabled) == {"filings", "workbench", "workbench_review"}
    assert "daily" not in cfg.task_channels.values()
