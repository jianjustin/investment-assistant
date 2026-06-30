from __future__ import annotations

import os
import re
from dataclasses import replace
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.config import NotifyConfig
from investment_assistant.db import connect
from investment_assistant.notify.discord import DiscordChannel, DiscordClient

_ENV_KEYS = [
    "SEC_USER_AGENT",
    "INVESTMENT_ASSISTANT_DATABASE_URL",
    "DISCORD_WEBHOOK_EARNINGS",
    "DISCORD_WEBHOOK_SIGNALS",
    "DISCORD_WEBHOOK_DAILY",
]


def _has_db() -> bool:
    return bool(os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"))


def _with_conn(fn: Callable[[Any], Any]) -> Any:
    with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
        return fn(conn)


def _stored() -> dict[str, Any]:
    if not _has_db():
        return {}
    return _with_conn(db.get_notify_settings) or {}


def effective_notify_config(base: NotifyConfig) -> NotifyConfig:
    stored = _stored()
    if not stored:
        return base
    return replace(
        base,
        discord_enabled=stored.get("discord_enabled", base.discord_enabled),
        webhooks={**base.webhooks, **(stored.get("webhooks") or {})},
        task_channels={**base.task_channels, **(stored.get("task_channels") or {})},
        task_enabled={**base.task_enabled, **(stored.get("task_enabled") or {})},
    )


def read_notify_view() -> dict[str, Any]:
    stored = _stored()
    base = NotifyConfig()
    webhooks = {**base.webhooks, **(stored.get("webhooks") or {})}
    return {
        "discord_enabled": stored.get("discord_enabled", base.discord_enabled),
        "task_channels": {**base.task_channels, **(stored.get("task_channels") or {})},
        "task_enabled": {**base.task_enabled, **(stored.get("task_enabled") or {})},
        "webhooks": {ch: {"configured": bool(url)} for ch, url in webhooks.items()},
        "degraded": not _has_db(),
    }


def update_notify(payload: dict[str, Any]) -> dict[str, Any]:
    if not _has_db():
        return {"updated": False, "degraded": True}
    webhooks = {k: v for k, v in (payload.get("webhooks") or {}).items() if str(v).strip()}  # 留空不覆盖
    _with_conn(lambda conn: db.update_notify_settings(
        conn,
        discord_enabled=payload.get("discord_enabled"),
        webhooks=webhooks or None,
        task_channels=payload.get("task_channels"),
        task_enabled=payload.get("task_enabled"),
    ))
    return {"updated": True}


def test_notify_channel(channel: str, url: str | None = None, *, client=None) -> dict[str, Any]:
    ch = DiscordChannel(channel)
    if client is None:
        cfg = effective_notify_config(NotifyConfig())
        target = url or cfg.webhooks.get(channel)
        if not target:
            return {"ok": False, "error": "no webhook configured"}
        client = DiscordClient(**{f"{c.value}_url": (target if c == ch else "") for c in DiscordChannel})
    payload = {"content": "✅ Hermes 测试消息：webhook 配置正常，可安全忽略。"}
    try:
        client.send(ch, payload)
        return {"ok": True}
    except Exception as exc:  # 测试失败结构化返回，不抛；脱敏 webhook 明文
        msg = str(exc)
        # redact any discord webhook URL (with token) that requests may embed in the error
        msg = re.sub(r"https?://\S*discord(?:app)?\.com/api/webhooks/\S+", "<webhook redacted>", msg)
        return {"ok": False, "error": msg}


def read_env_status() -> dict[str, bool]:
    return {key: bool(os.environ.get(key)) for key in _ENV_KEYS}
