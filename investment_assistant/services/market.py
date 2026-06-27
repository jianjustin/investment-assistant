from __future__ import annotations

import os
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from typing import Any

from investment_assistant.api.http import first, parse_int, parse_optional_date
from investment_assistant.config import load_config
from investment_assistant.db import connect, list_market_signals, upsert_market_signal
from investment_assistant.market.service import compute_market_signal_for_date


def market_signal_rows(query: dict[str, list[str]]) -> list[dict[str, Any]]:
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        return []
    start_date = parse_optional_date(first(query, "from"))
    end_date = parse_optional_date(first(query, "to"))
    limit = parse_int(first(query, "limit"), default=100, minimum=1, maximum=500)
    with connect(url) as conn:
        return list_market_signals(conn, start_date=start_date, end_date=end_date, limit=limit)


def market_signal_trend(query: dict[str, list[str]]) -> dict[str, Any]:
    window = parse_int(first(query, "window"), default=20, minimum=3, maximum=120)
    rows = market_signal_rows({"limit": [str(window)]})
    counts = {"green": 0, "yellow": 0, "red": 0}
    for row in rows:
        status = str(row.get("market_status", "")).lower()
        if status in counts:
            counts[status] += 1
    latest_status = str(rows[0].get("market_status", "unknown")) if rows else "unknown"
    total = max(len(rows), 1)
    green_ratio = counts["green"] / total
    red_ratio = counts["red"] / total
    if latest_status == "red" or red_ratio >= 0.3:
        judgement = "risk_off"
        summary = "市场风险偏高，优先控制仓位。"
    elif latest_status == "green" and green_ratio >= 0.6:
        judgement = "risk_on"
        summary = "市场信号偏积极，可以正常跟踪候选机会。"
    else:
        judgement = "neutral"
        summary = "市场信号混合，建议等待更明确趋势。"
    return {
        "window": window,
        "sample_size": len(rows),
        "latest_status": latest_status,
        "status_counts": counts,
        "green_ratio": green_ratio,
        "red_ratio": red_ratio,
        "judgement": judgement,
        "summary": summary,
        "rows": rows,
    }


def fetch_market_signals(payload: dict[str, Any]) -> dict[str, Any]:
    start_date, end_date = _manual_fetch_range(payload)
    config = load_config()
    rows = []
    failures = []
    target = start_date
    while target <= end_date:
        run_id = f"manual-market-{target.isoformat()}-{uuid.uuid4().hex[:8]}"
        try:
            signal = compute_market_signal_for_date(getattr(config, "market", config), target, run_id=run_id)
            _persist_manual_market_signal(signal)
            rows.append(_plain_signal(signal))
        except Exception as exc:
            failures.append({"signal_date": target.isoformat(), "error": str(exc)})
        target += timedelta(days=1)
    return {
        "requested": {"from": start_date.isoformat(), "to": end_date.isoformat()},
        "rows": rows,
        "failures": failures,
    }


def _persist_manual_market_signal(signal) -> None:
    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    with connect(database_url) as conn:
        upsert_market_signal(conn, signal)


def _plain_signal(signal) -> dict[str, Any]:
    if is_dataclass(signal):
        payload = asdict(signal)
    else:
        payload = {key: getattr(signal, key) for key in [
            "signal_date", "market_status", "spy_ticker", "spy_close", "spy_ma200",
            "spy_above_200ma", "vix_ticker", "vix_close", "source", "details", "run_id",
        ] if hasattr(signal, key)}
    if "signal_date" in payload:
        payload["signal_date"] = str(payload["signal_date"])
    return payload


def _manual_fetch_range(payload: dict[str, Any]) -> tuple[date, date]:
    raw_date = payload.get("date")
    raw_from = payload.get("from") or payload.get("start_date")
    raw_to = payload.get("to") or payload.get("end_date")
    if raw_date:
        start_date = end_date = date.fromisoformat(str(raw_date))
    else:
        if not raw_from or not raw_to:
            raise ValueError("date or from/to is required")
        start_date = date.fromisoformat(str(raw_from))
        end_date = date.fromisoformat(str(raw_to))
    if end_date < start_date:
        raise ValueError("to must be greater than or equal to from")
    if (end_date - start_date).days > 45:
        raise ValueError("manual market fetch range is limited to 45 days")
    return start_date, end_date
