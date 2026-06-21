from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import uuid
import os
import subprocess
from dataclasses import asdict, dataclass, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from investment_assistant.config import load_config
from investment_assistant.db import connect, get_latest_market_signal, list_market_signals, upsert_market_signal
from investment_assistant.hermes import agents as hermes_agents
from investment_assistant.hermes.run_log import append_run
from investment_assistant.hermes.macro_analyst import analyze_macro_environment
from investment_assistant.market.service import compute_market_signal_for_date
from investment_assistant.runtime_paths import DEFAULT_FILINGS_DIR

HOST = os.environ.get("HERMES_DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("HERMES_DASHBOARD_PORT", "8787"))
AUTH_USER = os.environ.get("HERMES_DASHBOARD_USER", "jianjustin")
AUTH_PASSWORD = os.environ.get("SERVER_PWD") or os.environ.get("HERMES_DASHBOARD_PASSWORD", "")
STATIC_DIR = Path(__file__).resolve().parents[2] / "web" / "dist"


@dataclass(frozen=True)
class StaticResponse:
    status: int
    content_type: str
    body: bytes


@dataclass(frozen=True)
class ApiResponse:
    payload: Any
    status: int = 200


def status_payload() -> dict[str, Any]:
    return {"database": database_status(), "filings": filing_status(), "system": system_status()}


def database_status() -> dict[str, Any]:
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        return {"ok": False, "error": "INVESTMENT_ASSISTANT_DATABASE_URL missing"}
    try:
        with connect(url) as conn:
            return {"ok": True, "latest_market_signal": get_latest_market_signal(conn)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def filing_status() -> dict[str, Any]:
    root = DEFAULT_FILINGS_DIR
    files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
    return {"path": str(root), "exists": root.exists(), "file_count": len(files)}


def filing_rows(limit: int = 100) -> list[dict[str, Any]]:
    root = DEFAULT_FILINGS_DIR
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()
        try:
            relative_path = str(path.relative_to(root))
        except ValueError:
            relative_path = path.name
        rows.append({
            "name": path.name,
            "path": relative_path,
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
        })
    rows.sort(key=lambda row: row["modified_at"], reverse=True)
    return rows[:limit]


def operation_registry() -> list[dict[str, Any]]:
    return [
        {
            "id": "fetch_market_signals",
            "label": "拉取市场信号",
            "description": "按日期或日期区间计算市场信号，并写入 market_signals。",
            "risk": "medium",
            "enabled": True,
            "requires_confirmation": True,
            "method": "POST",
            "endpoint": "/api/market/signals/fetch",
        },
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


def api_response_for_path(path: str) -> ApiResponse | None:
    parsed = urlparse(path)
    parsed_path = unquote(parsed.path)
    query = parse_qs(parsed.query)
    if parsed_path == "/api/status" or parsed_path == "/api/raw/status":
        return ApiResponse(status_payload())
    if parsed_path == "/api/services":
        return ApiResponse(system_status())
    if parsed_path == "/api/market/signals/latest":
        return ApiResponse(database_status().get("latest_market_signal"))
    if parsed_path == "/api/market/signals":
        rows = market_signal_rows(query)
        return ApiResponse({"rows": rows, "count": len(rows)})
    if parsed_path == "/api/market/signals/trend":
        return ApiResponse(market_signal_trend(query))
    if parsed_path == "/api/hermes":
        return ApiResponse(hermes_agents.hermes_overview())
    if parsed_path == "/api/hermes/agents":
        return ApiResponse({"agents": hermes_agents.list_agents()})
    if parsed_path == "/api/hermes/macro-analysis":
        return ApiResponse(hermes_macro_analysis(query))
    if parsed_path == "/api/hermes/market-signals/interpretation":
        return ApiResponse(hermes_macro_analysis(query))
    if parsed_path == "/api/filings":
        return ApiResponse({"summary": filing_status(), "files": filing_rows()})
    if parsed_path == "/api/operations":
        return ApiResponse({"operations": operation_registry()})
    if parsed_path.startswith("/api/"):
        return None
    return None


def api_post_response_for_path(path: str, payload: dict[str, Any]) -> ApiResponse | None:
    parsed_path = unquote(urlparse(path).path)
    if parsed_path == "/api/hermes/macro-analysis/run":
        try:
            return ApiResponse(run_hermes_macro_llm_analysis(payload))
        except ValueError as exc:
            return ApiResponse({"error": str(exc)}, status=400)
    if parsed_path == "/api/market/signals/fetch":
        try:
            return ApiResponse(fetch_market_signals(payload))
        except ValueError as exc:
            return ApiResponse({"error": str(exc)}, status=400)
    if parsed_path == "/api/hermes/agents":
        try:
            return ApiResponse({"agent": hermes_agents.save_agent(payload)})
        except ValueError as exc:
            return ApiResponse({"error": str(exc)}, status=400)
    if parsed_path.startswith("/api/"):
        return None
    return None


def market_signal_rows(query: dict[str, list[str]]) -> list[dict[str, Any]]:
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        return []
    start_date = _parse_optional_date(_first(query, "from"))
    end_date = _parse_optional_date(_first(query, "to"))
    limit = _parse_int(_first(query, "limit"), default=100, minimum=1, maximum=500)
    with connect(url) as conn:
        return list_market_signals(conn, start_date=start_date, end_date=end_date, limit=limit)


def market_signal_trend(query: dict[str, list[str]]) -> dict[str, Any]:
    window = _parse_int(_first(query, "window"), default=20, minimum=3, maximum=120)
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


def hermes_macro_analysis(query: dict[str, list[str]]) -> dict[str, Any]:
    window = _parse_int(_first(query, "window"), default=30, minimum=5, maximum=90)
    rows = market_signal_rows({"limit": [str(window)]})
    watchlist = _parse_csv(_first(query, "watchlist"))
    if not watchlist:
        watchlist = list(load_config().watchlist)
    return analyze_macro_environment(rows, window=window, watchlist=watchlist)


def run_hermes_macro_llm_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    window = _parse_int(str(payload.get("window")) if payload.get("window") is not None else None, default=30, minimum=5, maximum=90)
    model = str(payload.get("model") or config.model_default or "deepseek-v4-pro")
    watchlist = _parse_payload_watchlist(payload.get("watchlist")) or list(config.watchlist)
    rows = market_signal_rows({"limit": [str(window)]})
    run_id = f"macro-llm-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    analysis = analyze_macro_environment(rows, window=window, watchlist=watchlist, use_llm=True, model=model)
    record = {
        "type": "hermes_macro_llm_analysis",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "window": window,
        "model": model,
        "watchlist": watchlist,
        "macro_state": analysis.get("macro_state"),
        "stance_label": analysis.get("stance_label"),
        "llm": analysis.get("llm"),
        "summary": analysis.get("summary"),
    }
    append_run(record)
    return {"run_id": run_id, "analysis": analysis}


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


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _parse_optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _parse_payload_watchlist(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _parse_csv(value)
    if isinstance(value, list):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    raise ValueError("watchlist must be a list or comma-separated string")


def system_status() -> dict[str, Any]:
    return {
        "postgres_service": _run_cmd(["systemctl", "is-active", "investment-assistant-postgres.service"]),
        "dashboard_service": _run_cmd(["systemctl", "is-active", "hermes-investment-dashboard.service"]),
        "timer": _run_cmd(["systemctl", "list-timers", "hermes-investment*", "--no-pager"]),
    }


def static_response_for_path(path: str) -> StaticResponse | None:
    parsed_path = unquote(urlparse(path).path)
    if parsed_path == "/":
        target = STATIC_DIR / "index.html"
    elif parsed_path.startswith("/assets/"):
        target = STATIC_DIR / parsed_path.removeprefix("/")
    else:
        return None

    try:
        resolved = target.resolve()
        resolved.relative_to(STATIC_DIR.resolve())
    except Exception:
        return StaticResponse(403, "application/json; charset=utf-8", b'{"error":"forbidden"}')

    if not resolved.exists() or not resolved.is_file():
        if parsed_path == "/":
            body = json.dumps({"error": "frontend_not_built", "expected": str(STATIC_DIR / "index.html")}).encode("utf-8")
            return StaticResponse(503, "application/json; charset=utf-8", body)
        return None

    content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
    if content_type.startswith("text/"):
        content_type += "; charset=utf-8"
    return StaticResponse(200, content_type, resolved.read_bytes())


def _run_cmd(cmd: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5)
        return {"ok": result.returncode == 0, "returncode": result.returncode, "output": result.stdout.strip()}
    except Exception as exc:
        return {"ok": False, "returncode": 1, "output": str(exc)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _authorized(self) -> bool:
        if not AUTH_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            username, password = base64.b64decode(header[6:]).decode("utf-8").split(":", 1)
        except Exception:
            return False
        return hmac.compare_digest(username, AUTH_USER) and hmac.compare_digest(password, AUTH_PASSWORD)

    def _send(self, body: bytes, content_type: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False, default=str, indent=2).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", code)

    def do_GET(self):
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Basic realm=\"Hermes Investment Assistant\"")
            self.end_headers()
            return
        api_response = api_response_for_path(self.path)
        if api_response is not None:
            self._send_json(api_response.payload, api_response.status)
            return
        static_response = static_response_for_path(self.path)
        if static_response is not None:
            self._send(static_response.body, static_response.content_type, static_response.status)
            return
        self._send_json({"error": "not found"}, 404)


    def do_POST(self):
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Basic realm=\"Hermes Investment Assistant\"")
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception as exc:
            self._send_json({"error": f"invalid json: {exc}"}, 400)
            return
        api_response = api_post_response_for_path(self.path, payload)
        if api_response is not None:
            self._send_json(api_response.payload, api_response.status)
            return
        self._send_json({"error": "not found"}, 404)


def main() -> None:
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
