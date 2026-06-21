from __future__ import annotations

import base64
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from investment_assistant.db import connect, get_latest_market_signal
from investment_assistant.runtime_paths import DEFAULT_FILINGS_DIR

HOST = os.environ.get("HERMES_DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("HERMES_DASHBOARD_PORT", "8787"))
AUTH_USER = os.environ.get("HERMES_DASHBOARD_USER", "jianjustin")
AUTH_PASSWORD = os.environ.get("SERVER_PWD") or os.environ.get("HERMES_DASHBOARD_PASSWORD", "")


def status_payload() -> dict[str, Any]:
    return {"database": database_status(), "filings": filing_status()}


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

    def _send_json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False, default=str, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Hermes Investment Assistant"')
            self.end_headers()
            return
        if self.path == "/api/status":
            self._send_json(status_payload())
        elif self.path == "/":
            self._send_json({"name": "Hermes Investment Assistant", "status_url": "/api/status"})
        else:
            self._send_json({"error": "not found"}, 404)


def main() -> None:
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
