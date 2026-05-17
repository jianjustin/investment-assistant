#!/usr/bin/env python3
"""Validate Discord webhook connectivity. Run: python scripts/test_discord.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notify.discord import DiscordClient, DiscordChannel
from notify.templates import earnings_alert_embed

client = DiscordClient.from_env()
payload = earnings_alert_embed(
    ticker="TEST",
    earnings_date="2026-05-17",
    direction="Watch",
    eps_beat="$1.00 vs $0.95E (+5.3%)",
    revenue_beat="$10.0B vs $9.8BE (+2.0%)",
    guidance="上调",
    confidence=3,
    highlights=["这是测试消息", "验证 Discord webhook 连接", "可以安全忽略"],
)
client.send(DiscordChannel.EARNINGS, payload)
print("✅ Discord #earnings-alerts 发送成功")
