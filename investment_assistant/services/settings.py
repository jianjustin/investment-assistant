from __future__ import annotations

import os
import re
from dataclasses import replace
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.config import NotifyConfig
from investment_assistant.db import connect
from investment_assistant.notify.discord import DiscordChannel, DiscordClient
from investment_assistant.notify.email import EmailClient

_ENV_KEYS = [
    "SEC_USER_AGENT",
    "INVESTMENT_ASSISTANT_DATABASE_URL",
    "DISCORD_WEBHOOK_EARNINGS",
    "DISCORD_WEBHOOK_SIGNALS",
    "DISCORD_WEBHOOK_DAILY",
    "SMTP_PASSWORD",
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
        channel=stored.get("channel") or base.channel,
        discord_enabled=stored.get("discord_enabled", base.discord_enabled),
        webhooks={**base.webhooks, **(stored.get("webhooks") or {})},
        email={**base.email, **(stored.get("email") or {})},
        task_channels={**base.task_channels, **(stored.get("task_channels") or {})},
        task_enabled={**base.task_enabled, **(stored.get("task_enabled") or {})},
    )


def read_notify_view() -> dict[str, Any]:
    stored = _stored()
    base = NotifyConfig()
    webhooks = {**base.webhooks, **(stored.get("webhooks") or {})}
    return {
        "channel": stored.get("channel") or base.channel,
        "discord_enabled": stored.get("discord_enabled", base.discord_enabled),
        "email": {**base.email, **(stored.get("email") or {})},  # 地址非敏感；密码只在环境变量
        "task_channels": {**base.task_channels, **(stored.get("task_channels") or {})},
        "task_enabled": {**base.task_enabled, **(stored.get("task_enabled") or {})},
        "webhooks": {ch: {"configured": bool(url)} for ch, url in webhooks.items()},
        "degraded": not _has_db(),
    }


def update_notify(payload: dict[str, Any]) -> dict[str, Any]:
    channel = payload.get("channel")
    if channel is not None and channel not in ("discord", "email"):
        return {"updated": False, "error": "invalid channel"}
    if not _has_db():
        return {"updated": False, "degraded": True}
    webhooks = {k: v for k, v in (payload.get("webhooks") or {}).items() if str(v).strip()}  # 留空不覆盖
    email = {k: v for k, v in (payload.get("email") or {}).items() if str(v).strip()}
    _with_conn(lambda conn: db.update_notify_settings(
        conn,
        discord_enabled=payload.get("discord_enabled"),
        webhooks=webhooks or None,
        task_channels=payload.get("task_channels"),
        task_enabled=payload.get("task_enabled"),
        channel=channel,
        email=email or None,
    ))
    return {"updated": True}


def test_notify_channel(channel: str, url: str | None = None, *,
                        email: dict[str, Any] | None = None, client=None) -> dict[str, Any]:
    if channel == "email":
        return _test_email(email or {}, client=client)
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


def _test_email(override: dict[str, Any], *, client=None) -> dict[str, Any]:
    if client is None:
        cfg = effective_notify_config(NotifyConfig())
        merged = {**cfg.email, **{k: v for k, v in override.items() if str(v).strip()}}
        if not os.environ.get("SMTP_PASSWORD"):
            return {"ok": False, "error": "SMTP_PASSWORD not set"}
        if not merged.get("to_addr"):
            return {"ok": False, "error": "no recipient configured"}
        client = EmailClient.from_config(replace(cfg, email=merged))
    try:
        client.send("[Hermes] ✅ 测试邮件", "<p>Hermes 测试邮件：SMTP 配置正常，可安全忽略。</p>")
        return {"ok": True}
    except Exception as exc:  # 测试失败结构化返回，不抛（SMTP 异常不携带密码）
        return {"ok": False, "error": str(exc)}


def read_env_status() -> dict[str, bool]:
    return {key: bool(os.environ.get(key)) for key in _ENV_KEYS}
