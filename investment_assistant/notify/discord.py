import time
from collections.abc import Mapping
from enum import Enum
import requests

from investment_assistant.data import fetch_policy
from investment_assistant.notify.message import Notification

# fetch-1 (D23): a push is not idempotent, so it is retried only when the request never left (connection failure)
# or on 429 (Retry-After capped at 8 s); a read timeout or a 5xx is never resent.
PUSH_POLICY = fetch_policy.FetchPolicy(retry_post=False)


class DiscordChannel(Enum):
    EARNINGS = "earnings"
    SIGNALS = "signals"


class DiscordClient:
    def __init__(self, earnings_url: str, signals_url: str, *, policy: fetch_policy.FetchPolicy = PUSH_POLICY,
                 sleep=time.sleep):
        self._urls = {
            DiscordChannel.EARNINGS: earnings_url,
            DiscordChannel.SIGNALS: signals_url,
        }
        self._policy = policy
        self._sleep = sleep

    def send(self, channel: DiscordChannel, payload: dict) -> None:
        url = self._urls[channel]

        def attempt() -> None:
            resp = requests.post(url, json=payload, timeout=(self._policy.connect_s, self._policy.total_s))
            if resp.status_code not in (200, 204):
                headers = getattr(resp, "headers", None)
                retry_after = headers.get("Retry-After") if isinstance(headers, Mapping) else None
                raise fetch_policy.http_error(
                    resp.status_code, f"Discord send failed: {resp.status_code} {resp.text}", retry_after=retry_after)

        fetch_policy.fetch(f"discord:{channel.value}", attempt, policy=self._policy, sleep=self._sleep)

    @classmethod
    def from_env(cls) -> "DiscordClient":
        from dotenv import load_dotenv
        import os
        load_dotenv()
        return cls(
            earnings_url=os.environ["DISCORD_WEBHOOK_EARNINGS"],
            signals_url=os.environ["DISCORD_WEBHOOK_SIGNALS"],
        )

    @classmethod
    def from_config(cls, notify_cfg) -> "DiscordClient":
        from dotenv import load_dotenv
        import os
        load_dotenv()

        def url(channel: str, env_key: str) -> str:
            return notify_cfg.webhooks.get(channel) or os.environ.get(env_key, "")

        return cls(
            earnings_url=url("earnings", "DISCORD_WEBHOOK_EARNINGS"),
            signals_url=url("signals", "DISCORD_WEBHOOK_SIGNALS"),
        )


def render_discord(notification: Notification) -> dict:
    return {
        "embeds": [{
            "title": notification.title,
            "color": notification.color,
            "fields": [
                {"name": f.name, "value": f.value, "inline": f.inline}
                for f in notification.fields
            ],
            "footer": {"text": notification.footer},
        }]
    }


if __name__ == "__main__":
    import argparse

    from investment_assistant.notify.templates import filings_digest

    parser = argparse.ArgumentParser(description="发送测试消息到指定 Discord 频道")
    parser.add_argument(
        "--channel",
        choices=["earnings", "signals"],
        default="earnings",
        help="目标频道（默认：earnings）",
    )
    args = parser.parse_args()

    client = DiscordClient.from_env()
    ch = DiscordChannel(args.channel)

    if ch == DiscordChannel.EARNINGS:
        n = filings_digest({"downloaded_count": 1, "filings": [
            {"ticker": "TEST", "form": "10-Q", "filing_date": "2026-07-05"}]})
    else:
        n = filings_digest({"downloaded_count": 0, "filings": []})
    client.send(ch, render_discord(n))
    print(f"✅ 测试消息已发送至 #{args.channel}")
