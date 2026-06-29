from __future__ import annotations

from typing import Any

from investment_assistant.notify.discord import DiscordChannel, DiscordClient
from investment_assistant.notify.templates import (
    filings_digest_embed,
    metrics_summary_embed,
    scores_summary_embed,
)

_EMBED_BUILDERS = {
    "metrics": metrics_summary_embed,
    "filings": filings_digest_embed,
    "scores": scores_summary_embed,
}


def dispatch(task: str, status: str, summary: dict[str, Any], notify_cfg, *, client=None) -> dict[str, Any]:
    if not notify_cfg.discord_enabled:
        return {"sent": False, "reason": "discord_disabled"}
    if notify_cfg.task_enabled.get(task) is False:
        return {"sent": False, "reason": "task_disabled"}
    channel_name = notify_cfg.task_channels.get(task)
    if not channel_name:
        return {"sent": False, "reason": "no_channel"}

    builder = _EMBED_BUILDERS.get(task)
    payload = builder(summary) if builder else {"content": f"[{task}] {status}"}
    try:
        cli = client or DiscordClient.from_config(notify_cfg)
        cli.send(DiscordChannel(channel_name), payload)
        return {"sent": True, "channel": channel_name}
    except Exception as exc:  # 通知失败不拖垮任务；结构化返回
        return {"sent": False, "reason": f"send_failed: {exc}"}
