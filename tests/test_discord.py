import pytest
from unittest.mock import patch, MagicMock
from notify.discord import DiscordClient, DiscordChannel


def test_send_earnings_calls_correct_webhook():
    client = DiscordClient(
        earnings_url="https://discord.com/api/webhooks/test/earnings",
        signals_url="https://discord.com/api/webhooks/test/signals",
        daily_url="https://discord.com/api/webhooks/test/daily",
    )
    with patch("notify.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=204)
        client.send(DiscordChannel.EARNINGS, {"content": "test"})
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "earnings" in call_url


def test_send_raises_on_non_204():
    client = DiscordClient(
        earnings_url="https://discord.com/api/webhooks/test/earnings",
        signals_url="",
        daily_url="",
    )
    with patch("notify.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")
        with pytest.raises(RuntimeError, match="Discord send failed"):
            client.send(DiscordChannel.EARNINGS, {"content": "test"})


def test_send_signals_calls_signals_webhook():
    client = DiscordClient(
        earnings_url="https://discord.com/api/webhooks/test/earnings",
        signals_url="https://discord.com/api/webhooks/test/signals",
        daily_url="https://discord.com/api/webhooks/test/daily",
    )
    with patch("notify.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=204)
        client.send(DiscordChannel.SIGNALS, {"content": "test"})
        call_url = mock_post.call_args[0][0]
        assert "signals" in call_url
