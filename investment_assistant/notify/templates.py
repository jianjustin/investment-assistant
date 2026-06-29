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


def metrics_summary_embed(summary: dict) -> dict:
    status = str(summary.get("market_status", "?")).upper()
    vix = summary.get("vix")
    tickers = summary.get("tickers", [])
    rows = "\n".join(f"• **{t.get('ticker')}** — {t.get('trend_state', '?')}" for t in tickers[:10]) or "无"
    return {
        "embeds": [{
            "title": "🗓 每日指标 · 08:00",
            "color": 3447003,
            "fields": [
                {"name": "市场环境", "value": f"{status} | VIX {vix}", "inline": False},
                {"name": f"关注列表 ({len(tickers)})", "value": rows, "inline": False},
            ],
            "footer": _footer(),
        }]
    }


def filings_digest_embed(summary: dict) -> dict:
    filings = summary.get("filings", [])
    rows = "\n".join(
        f"• **{f.get('ticker')}** {f.get('form')} — {f.get('filed_at', '')}" for f in filings[:15]
    ) or "昨日无新财报"
    return {
        "embeds": [{
            "title": "📄 昨日财报 · 09:00",
            "color": 15844367,
            "fields": [
                {"name": f"新提交 ({summary.get('downloaded_count', 0)})", "value": rows, "inline": False},
            ],
            "footer": _footer(),
        }]
    }


def scores_summary_embed(summary: dict) -> dict:
    rows = summary.get("rows", [])
    listing = "\n".join(
        f"• **{r.get('ticker')}** — {r.get('score')}" for r in rows[:10]
    ) or "无评分"
    return {
        "embeds": [{
            "title": "📈 策略评分 · 18:00",
            "color": 10070709,
            "fields": [
                {"name": f"评分 ({len(rows)})", "value": listing, "inline": False},
            ],
            "footer": _footer(),
        }]
    }
