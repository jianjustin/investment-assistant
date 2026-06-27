from __future__ import annotations

import base64
import hmac
import os

HOST = os.environ.get("HERMES_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("HERMES_DASHBOARD_PORT", "8787"))
AUTH_USER = os.environ.get("HERMES_DASHBOARD_USER", "jianjustin")
AUTH_PASSWORD = os.environ.get("SERVER_PWD") or os.environ.get("HERMES_DASHBOARD_PASSWORD", "")
ALLOW_PUBLIC_BIND = os.environ.get("HERMES_DASHBOARD_ALLOW_PUBLIC", "").lower() in ("1", "true", "yes")


def authorize(header: str | None) -> bool:
    if not AUTH_PASSWORD:
        return True
    if not header or not header.startswith("Basic "):
        return False
    try:
        username, password = base64.b64decode(header[6:]).decode("utf-8").split(":", 1)
    except Exception:
        return False
    return hmac.compare_digest(username, AUTH_USER) and hmac.compare_digest(password, AUTH_PASSWORD)


def resolve_bind_host() -> str:
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
