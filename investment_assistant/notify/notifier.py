from __future__ import annotations

from typing import Any

from investment_assistant.notify.discord import DiscordChannel, DiscordClient, render_discord
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
    if not notify_cfg.discord_enabled:
        return {"sent": False, "reason": "discord_disabled"}
    if notify_cfg.task_enabled.get(task) is False:
        return {"sent": False, "reason": "task_disabled"}
    channel_name = notify_cfg.task_channels.get(task)
    if not channel_name:
        return {"sent": False, "reason": "no_channel"}

    notification = _build_notification(task, status, summary,
                                       target_start_date=target_start_date, target_end_date=target_end_date)
    try:
        cli = client or DiscordClient.from_config(notify_cfg)
        cli.send(DiscordChannel(channel_name), render_discord(notification))
        return {"sent": True, "channel": channel_name}
    except Exception as exc:  # 通知失败不拖垮任务；结构化返回
        return {"sent": False, "reason": f"send_failed: {exc}"}
