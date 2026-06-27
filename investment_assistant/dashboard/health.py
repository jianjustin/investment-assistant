"""Aggregated health checks for the monitoring status page.

Probes internal infrastructure (Postgres, systemd units, storage) and external
online services (DeepSeek, SEC EDGAR, Yahoo Finance, Discord, FRED). Everything
uses the standard library only, matching the rest of the dashboard server.

Each check returns a uniform shape so the status page can render it generically:

    {
      "id": str,
      "name": str,
      "category": "infrastructure" | "storage" | "online",
      "status": "up" | "degraded" | "down" | "unknown",
      "latency_ms": float | None,
      "detail": str,
      "meta": dict,
    }
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from investment_assistant.db import connect, get_latest_market_signal
from investment_assistant.hermes.deepseek_client import DEEPSEEK_BASE_URL, deepseek_configured
from investment_assistant.runtime_paths import DEFAULT_FILINGS_DIR

# status precedence: down beats degraded beats unknown beats up.
_SEVERITY = {"up": 0, "unknown": 1, "degraded": 2, "down": 3}

DASHBOARD_SERVICE = "hermes-investment-dashboard.service"
POSTGRES_SERVICE = "investment-assistant-postgres.service"
DAILY_TIMER = "hermes-investment-daily.timer"
DAILY_SERVICE = "hermes-investment-daily.service"


def _check(
    id: str,
    name: str,
    category: str,
    status: str,
    detail: str,
    *,
    latency_ms: float | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "category": category,
        "status": status,
        "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
        "detail": detail,
        "meta": meta or {},
    }


def _http_probe(url: str, *, headers: dict[str, str] | None = None, timeout: float = 5.0, method: str = "GET") -> dict[str, Any]:
    """Probe an HTTP(S) endpoint. Any response < 500 counts as reachable."""
    request = Request(url, headers=headers or {}, method=method)
    start = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            code = response.status
        latency = (time.monotonic() - start) * 1000
        return {"reachable": True, "status": "up", "code": code, "latency_ms": latency, "error": None}
    except HTTPError as exc:
        latency = (time.monotonic() - start) * 1000
        # The host answered; a 4xx still means the service is up and reachable.
        status = "degraded" if exc.code >= 500 else "up"
        return {"reachable": True, "status": status, "code": exc.code, "latency_ms": latency, "error": f"HTTP {exc.code}"}
    except (URLError, socket.timeout, TimeoutError) as exc:
        latency = (time.monotonic() - start) * 1000
        reason = getattr(exc, "reason", exc)
        return {"reachable": False, "status": "down", "code": None, "latency_ms": latency, "error": str(reason)}
    except Exception as exc:  # noqa: BLE001
        latency = (time.monotonic() - start) * 1000
        return {"reachable": False, "status": "down", "code": None, "latency_ms": latency, "error": str(exc)}


def _systemctl(args: list[str], *, timeout: float = 5.0) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["systemctl", *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


# --- infrastructure -------------------------------------------------------


def check_database() -> dict[str, Any]:
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        return _check("database", "PostgreSQL", "infrastructure", "down", "INVESTMENT_ASSISTANT_DATABASE_URL 未配置")
    start = time.monotonic()
    try:
        with connect(url) as conn:
            latest = get_latest_market_signal(conn)
        latency = (time.monotonic() - start) * 1000
        signal_date = None
        if isinstance(latest, dict):
            signal_date = latest.get("signal_date")
        detail = f"连接正常，最新市场信号 {signal_date}" if signal_date else "连接正常"
        return _check(
            "database", "PostgreSQL", "infrastructure", "up", detail,
            latency_ms=latency, meta={"latest_signal_date": str(signal_date) if signal_date else None},
        )
    except Exception as exc:  # noqa: BLE001
        latency = (time.monotonic() - start) * 1000
        return _check("database", "PostgreSQL", "infrastructure", "down", f"连接失败：{exc}", latency_ms=latency)


def check_systemd_service(id: str, unit: str, name: str) -> dict[str, Any]:
    code, output = _systemctl(["is-active", unit])
    active = output.splitlines()[0].strip() if output else ""
    if active == "active":
        return _check(id, name, "infrastructure", "up", f"{unit} 运行中 (active)", meta={"unit": unit, "state": active})
    if active in {"activating", "reloading"}:
        return _check(id, name, "infrastructure", "degraded", f"{unit} 状态 {active}", meta={"unit": unit, "state": active})
    return _check(id, name, "infrastructure", "down", f"{unit} 状态 {active or 'unknown'}", meta={"unit": unit, "state": active})


def check_daily_timer() -> dict[str, Any]:
    code, active = _systemctl(["is-active", DAILY_TIMER])
    active = active.splitlines()[0].strip() if active else ""
    _, next_raw = _systemctl(["show", DAILY_TIMER, "--property=NextElapseUSecRealtime", "--value"])
    _, last_result = _systemctl(["show", DAILY_SERVICE, "--property=ExecMainStatus", "--value"])
    next_run = next_raw.strip() or "未排期"
    meta = {"state": active, "next_run": next_run, "last_exit_status": last_result.strip()}
    if active == "active":
        return _check("daily_timer", "每日任务定时器", "infrastructure", "up", f"已激活，下次运行：{next_run}", meta=meta)
    return _check("daily_timer", "每日任务定时器", "infrastructure", "down", f"定时器状态 {active or 'unknown'}", meta=meta)


# --- storage --------------------------------------------------------------


def check_filings_storage() -> dict[str, Any]:
    root = DEFAULT_FILINGS_DIR
    if not root.exists():
        return _check("filings", "Filings 存储", "storage", "degraded", f"目录不存在：{root}", meta={"path": str(root), "file_count": 0})
    files = [p for p in root.rglob("*") if p.is_file()]
    return _check(
        "filings", "Filings 存储", "storage", "up",
        f"{len(files)} 个文件",
        meta={"path": str(root), "file_count": len(files)},
    )


# --- online services ------------------------------------------------------


def check_deepseek() -> dict[str, Any]:
    configured = deepseek_configured()
    probe = _http_probe(DEEPSEEK_BASE_URL, timeout=6.0)
    if not probe["reachable"]:
        return _check("deepseek", "DeepSeek API", "online", "down", f"无法连接 {DEEPSEEK_BASE_URL}：{probe['error']}", latency_ms=probe["latency_ms"], meta={"configured": configured})
    if not configured:
        return _check("deepseek", "DeepSeek API", "online", "degraded", "可达，但 DEEPSEEK_API_KEY 未配置", latency_ms=probe["latency_ms"], meta={"configured": False})
    return _check("deepseek", "DeepSeek API", "online", "up", f"可达，API Key 已配置 (HTTP {probe['code']})", latency_ms=probe["latency_ms"], meta={"configured": True})


def check_sec_edgar() -> dict[str, Any]:
    ua = os.environ.get("SEC_USER_AGENT", "investment-assistant status-page")
    probe = _http_probe(
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=10-K&dateb=&owner=include&count=1",
        headers={"User-Agent": ua},
        timeout=6.0,
    )
    if not probe["reachable"]:
        return _check("sec_edgar", "SEC EDGAR", "online", "down", f"不可达：{probe['error']}", latency_ms=probe["latency_ms"])
    return _check("sec_edgar", "SEC EDGAR", "online", probe["status"], f"可达 (HTTP {probe['code']})", latency_ms=probe["latency_ms"], meta={"user_agent_set": bool(os.environ.get("SEC_USER_AGENT"))})


def check_yahoo_finance() -> dict[str, Any]:
    probe = _http_probe(
        "https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=1d&interval=1d",
        headers={"User-Agent": "Mozilla/5.0 (investment-assistant status-page)"},
        timeout=6.0,
    )
    if not probe["reachable"]:
        return _check("yahoo_finance", "Yahoo Finance (yfinance)", "online", "down", f"不可达：{probe['error']}", latency_ms=probe["latency_ms"])
    return _check("yahoo_finance", "Yahoo Finance (yfinance)", "online", probe["status"], f"行情接口可达 (HTTP {probe['code']})", latency_ms=probe["latency_ms"])


def check_discord() -> dict[str, Any]:
    webhooks = [
        os.environ.get("DISCORD_WEBHOOK_EARNINGS"),
        os.environ.get("DISCORD_WEBHOOK_SIGNALS"),
        os.environ.get("DISCORD_WEBHOOK_DAILY"),
    ]
    configured = sum(1 for w in webhooks if w)
    probe = _http_probe("https://discord.com/api/v10/gateway", timeout=6.0)
    if not probe["reachable"]:
        return _check("discord", "Discord 推送", "online", "down", f"不可达：{probe['error']}", latency_ms=probe["latency_ms"], meta={"configured_webhooks": configured})
    if configured == 0:
        return _check("discord", "Discord 推送", "online", "degraded", "API 可达，但未配置任何 Webhook", latency_ms=probe["latency_ms"], meta={"configured_webhooks": 0})
    return _check("discord", "Discord 推送", "online", "up", f"可达，已配置 {configured}/3 个 Webhook", latency_ms=probe["latency_ms"], meta={"configured_webhooks": configured})


def check_fred() -> dict[str, Any]:
    configured = bool(os.environ.get("FRED_API_KEY"))
    probe = _http_probe("https://api.stlouisfed.org/", timeout=6.0)
    if not probe["reachable"]:
        return _check("fred", "FRED 宏观数据", "online", "down", f"不可达：{probe['error']}", latency_ms=probe["latency_ms"], meta={"configured": configured})
    if not configured:
        return _check("fred", "FRED 宏观数据", "online", "degraded", "可达，但 FRED_API_KEY 未配置（宏观采集尚未接入）", latency_ms=probe["latency_ms"], meta={"configured": False})
    return _check("fred", "FRED 宏观数据", "online", "up", f"可达，API Key 已配置 (HTTP {probe['code']})", latency_ms=probe["latency_ms"], meta={"configured": True})


CHECKS: list[Callable[[], dict[str, Any]]] = [
    check_database,
    lambda: check_systemd_service("dashboard_service", DASHBOARD_SERVICE, "Dashboard 服务"),
    lambda: check_systemd_service("postgres_service", POSTGRES_SERVICE, "Postgres 服务单元"),
    check_daily_timer,
    check_filings_storage,
    check_deepseek,
    check_sec_edgar,
    check_yahoo_finance,
    check_discord,
    check_fred,
]


def _run_check(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return _check("unknown", getattr(fn, "__name__", "check"), "online", "down", f"检查异常：{exc}")


def health_report() -> dict[str, Any]:
    """Run every check (external probes in parallel) and aggregate."""
    with ThreadPoolExecutor(max_workers=len(CHECKS)) as pool:
        checks = list(pool.map(_run_check, CHECKS))

    overall = "up"
    for check in checks:
        if _SEVERITY[check["status"]] > _SEVERITY[overall]:
            overall = check["status"]

    summary = {"up": 0, "degraded": 0, "down": 0, "unknown": 0}
    for check in checks:
        summary[check["status"]] = summary.get(check["status"], 0) + 1

    return {
        "overall": overall,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "checks": checks,
    }
