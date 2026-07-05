from enum import Enum
import requests

from investment_assistant.notify.message import Notification


class DiscordChannel(Enum):
    EARNINGS = "earnings"
    SIGNALS = "signals"
    DAILY = "daily"


class DiscordClient:
    def __init__(self, earnings_url: str, signals_url: str, daily_url: str):
        self._urls = {
            DiscordChannel.EARNINGS: earnings_url,
            DiscordChannel.SIGNALS: signals_url,
            DiscordChannel.DAILY: daily_url,
        }

    def send(self, channel: DiscordChannel, payload: dict) -> None:
        url = self._urls[channel]
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"Discord send failed: {resp.status_code} {resp.text}")

    @classmethod
    def from_env(cls) -> "DiscordClient":
        from dotenv import load_dotenv
        import os
        load_dotenv()
        return cls(
            earnings_url=os.environ["DISCORD_WEBHOOK_EARNINGS"],
            signals_url=os.environ["DISCORD_WEBHOOK_SIGNALS"],
            daily_url=os.environ["DISCORD_WEBHOOK_DAILY"],
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
            daily_url=url("daily", "DISCORD_WEBHOOK_DAILY"),
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

    from investment_assistant.notify.templates import filings_digest, metrics_summary, scores_summary

    parser = argparse.ArgumentParser(description="发送测试消息到指定 Discord 频道")
    parser.add_argument(
        "--channel",
        choices=["earnings", "signals", "daily"],
        default="earnings",
        help="目标频道（默认：earnings）",
    )
    args = parser.parse_args()

    client = DiscordClient.from_env()
    ch = DiscordChannel(args.channel)

    if ch == DiscordChannel.EARNINGS:
        n = filings_digest({"downloaded_count": 1, "filings": [
            {"ticker": "TEST", "form": "10-Q", "filing_date": "2026-07-05"}]})
    elif ch == DiscordChannel.SIGNALS:
        n = scores_summary({"rows": [{"ticker": "TEST", "score": 88}]})
    else:
        n = metrics_summary({"market_status": "green", "vix": 15.0,
                             "tickers": [{"ticker": "TEST", "trend_state": "uptrend"}]})
    client.send(ch, render_discord(n))
    print(f"✅ 测试消息已发送至 #{args.channel}")
