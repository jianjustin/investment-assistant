from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import investment_assistant.api.routes  # noqa: F401 — triggers route registration
from investment_assistant.api import auth
from investment_assistant.api import static_files
from investment_assistant.api.router import dispatch


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _send(self, body: bytes, content_type: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, code: int = 200):
        body = json.dumps(payload, ensure_ascii=False, default=str, indent=2).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", code)

    def _reject_unauthorized(self) -> bool:
        if auth.authorize(self.headers.get("Authorization")):
            return False
        self.send_response(401)
        self.send_header("WWW-Authenticate", "Basic realm=\"Hermes Investment Assistant\"")
        self.end_headers()
        return True

    def do_GET(self):
        if self._reject_unauthorized():
            return
        from urllib.parse import unquote, urlparse
        if unquote(urlparse(self.path).path) == "/api/events":
            self._handle_sse()
            return
        api_response = dispatch("GET", self.path, None)
        if api_response is not None:
            self._send_json(api_response.payload, api_response.status)
            return
        static_response = static_files.static_response_for_path(self.path)
        if static_response is not None:
            self._send(static_response.body, static_response.content_type, static_response.status)
            return
        self._send_json({"error": "not found"}, 404)

    def _handle_sse(self):
        from investment_assistant.tasks.runner import subscribe, unsubscribe
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = subscribe()
        try:
            while True:
                event = q.get()
                data = json.dumps(event, ensure_ascii=False, default=str)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            unsubscribe(q)

    def do_POST(self):
        if self._reject_unauthorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception as exc:
            self._send_json({"error": f"invalid json: {exc}"}, 400)
            return
        api_response = dispatch("POST", self.path, payload)
        if api_response is not None:
            self._send_json(api_response.payload, api_response.status)
            return
        self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        if self._reject_unauthorized():
            return
        api_response = dispatch("DELETE", self.path, None)
        if api_response is not None:
            self._send_json(api_response.payload, api_response.status)
            return
        self._send_json({"error": "not found"}, 404)

    def do_PATCH(self):
        if self._reject_unauthorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception as exc:
            self._send_json({"error": f"invalid json: {exc}"}, 400)
            return
        api_response = dispatch("PATCH", self.path, payload)
        if api_response is not None:
            self._send_json(api_response.payload, api_response.status)
            return
        self._send_json({"error": "not found"}, 404)


def main() -> None:
    host = auth.resolve_bind_host()
    ThreadingHTTPServer((host, auth.PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
