from __future__ import annotations

import os
import subprocess
from typing import Any

from investment_assistant.db import connect
from investment_assistant.runtime_paths import DEFAULT_FILINGS_DIR


def status_payload() -> dict[str, Any]:
    return {"database": database_status(), "filings": filing_status(), "system": system_status()}


def database_status() -> dict[str, Any]:
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        return {"ok": False, "error": "INVESTMENT_ASSISTANT_DATABASE_URL missing"}
    try:
        with connect(url) as conn:
            conn.execute("SELECT 1")
            return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def filing_status() -> dict[str, Any]:
    root = DEFAULT_FILINGS_DIR
    files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
    return {"path": str(root), "exists": root.exists(), "file_count": len(files)}


def operation_registry() -> list[dict[str, Any]]:
    return [
        {
            "id": "sync_filings",
            "label": "同步 Filings",
            "description": "重新下载 watchlist 中公司的 10-Q / 10-K 文件。",
            "risk": "medium",
            "enabled": False,
            "requires_confirmation": True,
            "method": "POST",
            "endpoint": "/api/operations/sync_filings/run",
        },
        {
            "id": "health_check",
            "label": "服务健康检查",
            "description": "检查 Postgres、Dashboard 和定时器状态。",
            "risk": "low",
            "enabled": False,
            "requires_confirmation": False,
            "method": "POST",
            "endpoint": "/api/operations/health_check/run",
        },
    ]


def system_status() -> dict[str, Any]:
    return {
        "postgres_service": _run_cmd(["systemctl", "is-active", "investment-assistant-postgres.service"]),
        "dashboard_service": _run_cmd(["systemctl", "is-active", "hermes-investment-dashboard.service"]),
        "timer": _run_cmd(["systemctl", "list-timers", "hermes-investment*", "--no-pager"]),
    }


def _run_cmd(cmd: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5)
        return {"ok": result.returncode == 0, "returncode": result.returncode, "output": result.stdout.strip()}
    except Exception as exc:
        return {"ok": False, "returncode": 1, "output": str(exc)}
