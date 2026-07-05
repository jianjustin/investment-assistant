from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NotifyField:
    name: str
    value: str
    inline: bool = False


@dataclass(frozen=True)
class Notification:
    """渠道中立的通知消息模型；各渠道自行渲染。"""

    title: str
    color: int
    fields: list[NotifyField] = field(default_factory=list)
    footer: str = ""
