#!/usr/bin/env python3
"""
财报监听主脚本 — earnings_monitor.py

流程：
  1. yfinance 检测 watchlist 中哪些标的在目标日期发布了财报
  2. SEC EDGAR 下载对应 8-K 原文（Exhibit 99.1 新闻稿）
  3. 输出 data/earnings_today.json 供 Claude Scheduled Task 读取分析

运行模式：
  python earnings_monitor.py              # 检查上一个交易日
  python earnings_monitor.py --date 2026-05-07  # 检查指定日期
  python earnings_monitor.py --dry-run    # 仅检测和打印，不下载文件
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# ── 初始化 ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR.parent / ".env")

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "earnings_monitor.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("earnings_monitor")

from data.earnings import scan_watchlist, get_earnings_date_for_ticker
from data.sec import SECDownloader


# ── 配置 ──────────────────────────────────────────────────────────────────
def load_config() -> dict:
    return {
        "sec_user_agent": os.environ.get("SEC_USER_AGENT", "EarningsMonitor user@example.com"),
        "vault_path": os.environ.get("VAULT_PATH", str(SCRIPT_DIR.parent.parent)),
        "watchlist_path": os.environ.get(
            "WATCHLIST_PATH",
            str(SCRIPT_DIR.parent.parent / "02-项目" / "美股投资项目" / "watchlist.md"),
        ),
    }


# ── Watchlist ─────────────────────────────────────────────────────────────
def load_watchlist(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        logger.error(f"Watchlist not found: {path}")
        return []
    in_block = False
    tickers = []
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_block = not in_block
            continue
        if in_block and stripped and not stripped.startswith("#"):
            tickers.append(stripped.upper())
    logger.info(f"Watchlist: {tickers}")
    return tickers


# ── 交易日 ────────────────────────────────────────────────────────────────
def get_previous_trading_date() -> str:
    d = date.today() - timedelta(days=1)
    while d.isoweekday() in (6, 7):
        d -= timedelta(days=1)
    return d.isoformat()


# ── 主流程 ────────────────────────────────────────────────────────────────
def run(check_date: str, dry_run: bool = False) -> None:
    cfg = load_config()
    sec = SECDownloader(cfg["sec_user_agent"])
    data_dir = SCRIPT_DIR / "data" / "earnings_reports"
    output_json = SCRIPT_DIR / "data" / "earnings_today.json"

    tickers = load_watchlist(cfg["watchlist_path"])
    if not tickers:
        logger.warning("Watchlist is empty.")
        return

    logger.info(f"=== Checking {check_date} ===")

    # Step 1: yfinance 检测当日财报
    hits = scan_watchlist(tickers, check_date, window_days=2)

    if not hits:
        logger.info("No earnings hits. Done.")
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps({"date": check_date, "hits": [], "results": []},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return

    # Step 2: 对每个命中标的下载 SEC 8-K
    results = []
    for ticker in hits:
        logger.info(f"--- {ticker} ---")
        actual_date = get_earnings_date_for_ticker(ticker, check_date) or check_date

        doc_path = None
        if not dry_run:
            try:
                doc_path = sec.get_latest_8k_for_earnings(ticker, actual_date, data_dir)
            except Exception as e:
                logger.warning(f"SEC download failed for {ticker}: {e}")

        results.append({
            "ticker": ticker,
            "earnings_date": actual_date,
            "doc_path": str(doc_path) if doc_path else None,
        })
        logger.info(f"{ticker}: 8-K -> {doc_path or '(dry-run / failed)'}")

    # Step 3: 输出 JSON
    output = {"date": check_date, "hits": hits, "results": results}
    output_json.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print("\n=== DRY RUN output ===")
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        output_json.write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"Written: {output_json}")

    logger.info(f"=== Done: {len(hits)} hit(s) ===")


# ── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(check_date=args.date or get_previous_trading_date(), dry_run=args.dry_run)
