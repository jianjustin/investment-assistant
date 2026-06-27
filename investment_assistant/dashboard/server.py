from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from investment_assistant.api.http import ApiResponse, StaticResponse
from investment_assistant.dashboard.health import health_report
from investment_assistant.dashboard.status_page import STATUS_PAGE_HTML
from investment_assistant.hermes import agents as hermes_agents
from investment_assistant.services.status import status_payload, database_status, filing_status, filing_rows, operation_registry, system_status
from investment_assistant.services.watchlist import watchlist_rows, current_watchlist, add_watchlist_item, delete_watchlist_item
from investment_assistant.services.tickers import ticker_trend_rows, run_ticker_trend_scan
from investment_assistant.services.strategies import strategy_score_rows, run_strategy_score_scan
from investment_assistant.services.market import market_signal_rows, market_signal_trend, fetch_market_signals
from investment_assistant.services.hermes import hermes_macro_analysis, run_hermes_macro_llm_analysis, run_decision_evidence

HOST = os.environ.get("HERMES_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("HERMES_DASHBOARD_PORT", "8787"))
AUTH_USER = os.environ.get("HERMES_DASHBOARD_USER", "jianjustin")
AUTH_PASSWORD = os.environ.get("SERVER_PWD") or os.environ.get("HERMES_DASHBOARD_PASSWORD", "")
# Allow binding to a public interface only when an operator has *explicitly*
# opted in. This keeps the default deployment private (localhost) instead of
# silently exposing mutation endpoints on 0.0.0.0.
ALLOW_PUBLIC_BIND = os.environ.get("HERMES_DASHBOARD_ALLOW_PUBLIC", "").lower() in ("1", "true", "yes")
STATIC_DIR = Path(__file__).resolve().parents[2] / "web" / "dist"


def api_response_for_path(path: str) -> ApiResponse | None:
    parsed = urlparse(path)
    parsed_path = unquote(parsed.path)
    query = parse_qs(parsed.query)
    if parsed_path == "/api/status" or parsed_path == "/api/raw/status":
        return ApiResponse(status_payload())
    if parsed_path == "/api/health":
        return ApiResponse(health_report())
    if parsed_path == "/api/services":
        return ApiResponse(system_status())
    if parsed_path == "/api/watchlist":
        rows = watchlist_rows()
        return ApiResponse({"rows": rows, "count": len(rows)})
    if parsed_path == "/api/tickers/trends":
        rows = ticker_trend_rows()
        return ApiResponse({"rows": rows, "count": len(rows)})
    if parsed_path == "/api/strategies/scores":
        rows = strategy_score_rows()
        return ApiResponse({"rows": rows, "count": len(rows)})
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
    if parsed_path == "/api/watchlist":
        try:
            return ApiResponse({"item": add_watchlist_item(payload)})
        except ValueError as exc:
            return ApiResponse({"error": str(exc)}, status=400)
    if parsed_path == "/api/hermes/macro-analysis/run":
        try:
            return ApiResponse(run_hermes_macro_llm_analysis(payload))
        except ValueError as exc:
            return ApiResponse({"error": str(exc)}, status=400)
    if parsed_path == "/api/hermes/decision-evidence/run":
        try:
            return ApiResponse(run_decision_evidence(payload))
        except ValueError as exc:
            return ApiResponse({"error": str(exc)}, status=400)
    if parsed_path == "/api/market/signals/fetch":
        try:
            return ApiResponse(fetch_market_signals(payload))
        except ValueError as exc:
            return ApiResponse({"error": str(exc)}, status=400)
    if parsed_path == "/api/tickers/trends/scan":
        try:
            return ApiResponse(run_ticker_trend_scan(payload))
        except ValueError as exc:
            return ApiResponse({"error": str(exc)}, status=400)
    if parsed_path == "/api/strategies/scores/run":
        try:
            return ApiResponse(run_strategy_score_scan(payload))
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


def api_delete_response_for_path(path: str) -> ApiResponse | None:
    parsed_path = unquote(urlparse(path).path)
    if parsed_path.startswith("/api/watchlist/"):
        ticker = parsed_path.rsplit("/", 1)[-1]
        try:
            return ApiResponse(delete_watchlist_item(ticker))
        except ValueError as exc:
            return ApiResponse({"error": str(exc)}, status=400)
    if parsed_path.startswith("/api/"):
        return None
    return None


def static_response_for_path(path: str) -> StaticResponse | None:
    parsed_path = unquote(urlparse(path).path)
    if parsed_path == "/status":
        return StaticResponse(200, "text/html; charset=utf-8", STATUS_PAGE_HTML.encode("utf-8"))
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

    def do_DELETE(self):
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Basic realm=\"Hermes Investment Assistant\"")
            self.end_headers()
            return
        api_response = api_delete_response_for_path(self.path)
        if api_response is not None:
            self._send_json(api_response.payload, api_response.status)
            return
        self._send_json({"error": "not found"}, 404)


def _resolve_bind_host() -> str:
    """Refuse to expose the dashboard publicly without auth (fail closed)."""
    public = HOST not in ("127.0.0.1", "localhost", "::1")
    if public and not ALLOW_PUBLIC_BIND:
        raise SystemExit(
            f"Refusing to bind dashboard to public host {HOST!r}. "
            "Set HERMES_DASHBOARD_ALLOW_PUBLIC=1 to opt in (and front it with TLS)."
        )
    if public and not AUTH_PASSWORD:
        raise SystemExit(
            f"Refusing to bind dashboard to public host {HOST!r} without auth. "
            "Set SERVER_PWD (or HERMES_DASHBOARD_PASSWORD) first."
        )
    return HOST


def main() -> None:
    host = _resolve_bind_host()
    ThreadingHTTPServer((host, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
