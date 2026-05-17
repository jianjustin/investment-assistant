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
