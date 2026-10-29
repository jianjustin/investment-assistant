"""Direct Discord delivery, independent of an OpenClaw process."""
from __future__ import annotations

import os
import time
from collections.abc import Mapping

import requests

from investment_assistant.data import fetch_policy
from investment_assistant.data.fetch_policy import FetchError


class DeliveryError(RuntimeError):
    def __init__(self, message: str, *, uncertain: bool):
        super().__init__(message)
        self.uncertain = uncertain


class DiscordBotClient:
    def __init__(self, channel_id: str, *, session=None, policy: fetch_policy.FetchPolicy | None = None,
                 sleep=time.sleep):
        if not channel_id.isdigit():
            raise ValueError("Discord channel id 无效")
        self.channel_id = channel_id
        # D23 / spec §6.2 row 10: retried only on connection failure and 429; the nonce makes a resend after 429 safe.
        self.policy = policy or fetch_policy.FetchPolicy(retry_post=False)
        self.session = session or fetch_policy.policy_session(self.policy)
        self._sleep = sleep

    def send(self, content: str, nonce: str) -> dict:
        token = os.environ.get("SEC_DISCORD_BOT_TOKEN")
        if not token:
            raise DeliveryError("SEC_DISCORD_BOT_TOKEN 未配置", uncertain=False)

        def attempt():
            response = self.session.post(
                f"https://discord.com/api/v10/channels/{self.channel_id}/messages",
                headers={"Authorization": f"Bot {token}"},
                json={"content": content, "nonce": nonce, "enforce_nonce": True,
                      "allowed_mentions": {"parse": []}},
                timeout=(self.policy.connect_s, self.policy.total_s),
            )
            if response.status_code == 429:
                headers = getattr(response, "headers", None)
                raise fetch_policy.http_error(
                    429, "Discord HTTP 429",
                    retry_after=headers.get("Retry-After") if isinstance(headers, Mapping) else None)
            return response

        try:
            response = fetch_policy.fetch(f"discord_bot:{self.channel_id}", attempt, policy=self.policy,
                                          sleep=self._sleep).value
        except FetchError as exc:
            if exc.kind == "http_429":
                raise DeliveryError("Discord HTTP 429", uncertain=False) from None
            # Never serialize request headers or token-bearing exceptions: only the error category is kept.
            raise DeliveryError(f"Discord {exc.kind}; 投递待核验", uncertain=True) from None
        except requests.RequestException as exc:
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
