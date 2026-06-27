from __future__ import annotations

from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from investment_assistant.api.http import ApiResponse

Handler = Callable[[str, dict[str, list[str]], dict[str, Any] | None], ApiResponse]

_EXACT: dict[tuple[str, str], Handler] = {}
_PREFIX: list[tuple[str, str, Handler]] = []


def register(method: str, *, exact: str | None = None, prefix: str | None = None):
    def wrap(fn: Handler) -> Handler:
        if exact is not None:
            _EXACT[(method, exact)] = fn
        if prefix is not None:
            _PREFIX.append((method, prefix, fn))
        return fn
    return wrap


def dispatch(method: str, path: str, payload: dict[str, Any] | None) -> ApiResponse | None:
    parsed = urlparse(path)
    parsed_path = unquote(parsed.path)
    query = parse_qs(parsed.query)
    handler = _EXACT.get((method, parsed_path))
    if handler is None:
        for m, prefix, fn in _PREFIX:
            if m == method and parsed_path.startswith(prefix):
                handler = fn
                break
    if handler is None:
        return None
    try:
        return handler(parsed_path, query, payload)
    except ValueError as exc:
        return ApiResponse({"error": str(exc)}, status=400)
