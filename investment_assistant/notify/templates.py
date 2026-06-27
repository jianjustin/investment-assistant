from datetime import date


def _footer() -> dict:
    return {"text": f"earning-agent • {date.today().isoformat()}"}


def earnings_alert_embed(
    ticker: str,
    earnings_date: str,
    direction: str,
    eps_beat: str,
    revenue_beat: str,
    guidance: str,
    confidence: int,
    highlights: list[str],
) -> dict:
    color = {
        "Long": 3066993,
        "Short": 15158332,
        "Watch": 16776960,
        "Wait": 9807270,
    }.get(direction, 9807270)
    return {
        "embeds": [{
            "title": f"📊 {ticker} Earnings — {direction}",
            "color": color,
            "fields": [
                {"name": "EPS", "value": eps_beat, "inline": True},
                {"name": "Revenue", "value": revenue_beat, "inline": True},
                {"name": "Guidance", "value": guidance, "inline": True},
                {"name": "Confidence", "value": f"{confidence}/5", "inline": True},
                {"name": "Earnings Date", "value": earnings_date, "inline": True},
                {
                    "name": "Highlights",
                    "value": "\n".join(f"• {h}" for h in highlights[:3]) or "—",
                    "inline": False,
                },
            ],
            "footer": _footer(),
        }]
    }


def signal_alert_embed(
    ticker: str,
    rs_score: float,
    vcp: bool,
    ma_reclaim: bool,
    market_status: str,
) -> dict:
    signals = []
    if vcp:
        signals.append("VCP 收缩形态")
    if ma_reclaim:
        signals.append("MA 穿越")
    if rs_score >= 1.2:
        signals.append(f"RS {rs_score:.2f} 强势")
    return {
        "embeds": [{
            "title": f"📈 {ticker} 技术信号",
            "color": 3447003,
            "fields": [
                {"name": "触发信号", "value": " | ".join(signals) or "无", "inline": False},
                {"name": "RS Score", "value": f"{rs_score:.2f}", "inline": True},
                {"name": "市场环境", "value": market_status.upper(), "inline": True},
            ],
            "footer": _footer(),
        }]
    }


def daily_summary_embed(
    market_status: str,
    vix: float,
    candidates: list[dict],
) -> dict:
    rows = "\n".join(
        f"• **{c['ticker']}** — {', '.join(c['signals'])}"
        for c in candidates[:10]
    ) or "今日无候选"
    return {
        "embeds": [{
            "title": "🗓 每日扫描摘要",
            "color": 10070709,
            "fields": [
                {"name": "市场环境", "value": f"{market_status.upper()} | VIX {vix:.1f}", "inline": False},
                {"name": f"候选股票 ({len(candidates)})", "value": rows, "inline": False},
            ],
            "footer": _footer(),
        }]
    }
