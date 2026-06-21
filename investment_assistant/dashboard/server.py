from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import os
import subprocess
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from investment_assistant.db import connect, get_latest_market_signal
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
        if self.path == "/api/status":
            self._send_json(status_payload())
            return
        static_response = static_response_for_path(self.path)
        if static_response is not None:
            self._send(static_response.body, static_response.content_type, static_response.status)
            return
        self._send_json({"error": "not found"}, 404)


def main() -> None:
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
