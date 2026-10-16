"""Direct Discord delivery, independent of an OpenClaw process."""
from __future__ import annotations

import os

import requests


class DeliveryError(RuntimeError):
    def __init__(self, message: str, *, uncertain: bool):
        super().__init__(message)
        self.uncertain = uncertain


class DiscordBotClient:
    def __init__(self, channel_id: str, *, session=None):
        if not channel_id.isdigit():
            raise ValueError("Discord channel id 无效")
        self.channel_id = channel_id
        self.session = session or requests.Session()

    def send(self, content: str, nonce: str) -> dict:
        token = os.environ.get("SEC_DISCORD_BOT_TOKEN")
        if not token:
            raise DeliveryError("SEC_DISCORD_BOT_TOKEN 未配置", uncertain=False)
        try:
            response = self.session.post(
                f"https://discord.com/api/v10/channels/{self.channel_id}/messages",
                headers={"Authorization": f"Bot {token}"},
                json={"content": content, "nonce": nonce, "enforce_nonce": True,
                      "allowed_mentions": {"parse": []}},
                timeout=30,
            )
        except requests.RequestException as exc:
            # Never serialize request headers or token-bearing exceptions.
            raise DeliveryError(f"Discord {type(exc).__name__}; 投递待核验", uncertain=True) from None
        if response.status_code != 200:
            raise DeliveryError(f"Discord HTTP {response.status_code}", uncertain=response.status_code >= 500)
        try:
            receipt = response.json()
            if not receipt.get("id") or receipt.get("channel_id") != self.channel_id:
                raise ValueError("invalid receipt")
        except (ValueError, TypeError, AttributeError):
            raise DeliveryError("Discord 回执无效；投递待核验", uncertain=True) from None
        return {"message_id": receipt["id"], "channel_id": receipt["channel_id"]}
