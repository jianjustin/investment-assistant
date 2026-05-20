#!/usr/bin/env python3
"""Daily technical scan: market gate → watchlist signals → Discord notifications.
Cron: 0 21 * * 1-5 (21:00 Beijing time, Mon–Fri)
"""
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/daily_scan.log"),
    ],
)
log = logging.getLogger(__name__)


def _load_watchlist(path: str) -> list[str]:
    text = Path(path).read_text()
    tickers, in_block = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if in_block:
            t = line.strip().upper()
            if t and not t.startswith("#"):
                tickers.append(t)
    return tickers


def run(dry_run: bool = False) -> None:
    from signals.market import get_market_condition
    from signals.technicals import compute_technicals
    from notify.discord import DiscordClient, DiscordChannel
    from notify.templates import signal_alert_embed, daily_summary_embed

    tickers = _load_watchlist(os.environ["WATCHLIST_PATH"])
    log.info(f"Scanning {len(tickers)} tickers: {tickers}")

    market = get_market_condition()
    log.info(f"Market: {market.status.upper()} | VIX {market.vix:.1f} | SPY>200MA {market.spy_above_200ma}")

    client = DiscordClient.from_env() if not dry_run else None
    candidates = []

    if market.status == "red":
        log.warning("Market RED — skipping individual scans")
    else:
        for ticker in tickers:
            try:
                sig = compute_technicals(ticker)
                if sig.has_signal:
                    fired = []
                    if sig.vcp:
                        fired.append("VCP")
                    if sig.ma_reclaim:
                        fired.append("MA Reclaim")
                    if sig.rs_score >= 1.2:
                        fired.append(f"RS {sig.rs_score:.2f}")
                    candidates.append({"ticker": ticker, "signals": fired})
                    if not dry_run:
                        client.send(
                            DiscordChannel.SIGNALS,
                            signal_alert_embed(ticker, sig.rs_score, sig.vcp, sig.ma_reclaim, market.status),
                        )
                    log.info(f"{ticker}: fired {fired}")
                else:
                    log.info(f"{ticker}: no signal (RS {sig.rs_score:.2f})")
            except Exception as exc:
                log.error(f"{ticker}: error — {exc}")

    Path("data").mkdir(exist_ok=True)
    Path("data/daily_scan.json").write_text(
        json.dumps(
            {"date": date.today().isoformat(), "market": market.status, "candidates": candidates},
            indent=2,
        )
    )

    if not dry_run:
        client.send(
            DiscordChannel.DAILY,
            daily_summary_embed(market.status, market.vix, candidates),
        )
        log.info(f"Scan complete. {len(candidates)} candidates sent to #trade-signals.")
    else:
        log.info(f"Scan complete (dry-run). {len(candidates)} candidates found, Discord skipped.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="每日技术面扫描：大盘门控 → watchlist 信号 → Discord 推送")
    parser.add_argument("--dry-run", action="store_true", help="仅扫描和打印，不发送 Discord 消息")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
