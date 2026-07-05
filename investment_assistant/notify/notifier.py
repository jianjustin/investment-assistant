from __future__ import annotations

import os
from typing import Any

from investment_assistant.notify.discord import DiscordChannel, DiscordClient, render_discord
from investment_assistant.notify.email import EmailClient, render_email
from investment_assistant.notify.message import Notification
from investment_assistant.notify.templates import (
    date_label_for,
    filings_digest,
    metrics_summary,
    scores_summary,
)

_BUILDERS = {
    "metrics": metrics_summary,
    "filings": filings_digest,
    "scores": scores_summary,
}


def _build_notification(task: str, status: str, summary: dict[str, Any], *,
                        target_start_date=None, target_end_date=None) -> Notification:
    builder = _BUILDERS.get(task)
    if builder:
        return builder(summary, date_label=date_label_for(target_start_date, target_end_date))
    return Notification(title=f"[{task}] {status}", color=9807270, fields=[], footer="")


def dispatch(task: str, status: str, summary: dict[str, Any], notify_cfg, *,
             client=None, target_start_date=None, target_end_date=None) -> dict[str, Any]:
    if notify_cfg.task_enabled.get(task) is False:
        return {"sent": False, "reason": "task_disabled"}
    notification = _build_notification(task, status, summary,
                                       target_start_date=target_start_date, target_end_date=target_end_date)
    if notify_cfg.channel == "email":
        return _send_email(notification, notify_cfg, client=client)
    return _send_discord(task, notification, notify_cfg, client=client)


def _send_discord(task: str, notification: Notification, notify_cfg, *, client=None) -> dict[str, Any]:
    if not notify_cfg.discord_enabled:
        return {"sent": False, "reason": "discord_disabled"}
    channel_name = notify_cfg.task_channels.get(task)
    if not channel_name:
        return {"sent": False, "reason": "no_channel"}
    try:
        cli = client or DiscordClient.from_config(notify_cfg)
        cli.send(DiscordChannel(channel_name), render_discord(notification))
        return {"sent": True, "channel": "discord", "discord_channel": channel_name}
    except Exception as exc:  # 通知失败不拖垮任务；结构化返回
        return {"sent": False, "reason": f"send_failed: {exc}"}


def _send_email(notification: Notification, notify_cfg, *, client=None) -> dict[str, Any]:
    if client is None:  # 前置检查只针对真实客户端；测试注入的 fake 自带配置
        if not os.environ.get("SMTP_PASSWORD"):
            return {"sent": False, "reason": "email_no_password"}
        if not (notify_cfg.email or {}).get("to_addr"):
            return {"sent": False, "reason": "email_no_recipient"}
        if not (notify_cfg.email or {}).get("from_addr"):
            return {"sent": False, "reason": "email_no_sender"}
        client = EmailClient.from_config(notify_cfg)
    subject, html_body = render_email(notification)
    try:
        client.send(subject, html_body)
        return {"sent": True, "channel": "email"}
    except Exception as exc:  # 通知失败不拖垮任务；结构化返回
        return {"sent": False, "reason": f"send_failed: {exc}"}
