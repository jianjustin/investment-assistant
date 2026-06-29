from enum import Enum
import requests


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


if __name__ == "__main__":
    import argparse
    from investment_assistant.notify.templates import earnings_alert_embed, signal_alert_embed, daily_summary_embed

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
        payload = earnings_alert_embed(
            ticker="TEST",
            earnings_date="2026-05-20",
            direction="Watch",
            eps_beat="$1.00 vs $0.95E (+5.3%)",
            revenue_beat="$10.0B vs $9.8BE (+2.0%)",
            guidance="上调",
            confidence=3,
            highlights=["这是测试消息", "验证 Discord webhook 连接", "可以安全忽略"],
        )
    elif ch == DiscordChannel.SIGNALS:
        payload = signal_alert_embed("TEST", 1.5, True, False, "green")
    else:
        payload = daily_summary_embed("green", 15.0, [])

    client.send(ch, payload)
    print(f"✅ 测试消息已发送至 #{args.channel}")
