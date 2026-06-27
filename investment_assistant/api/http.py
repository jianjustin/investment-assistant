from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class StaticResponse:
    status: int
    content_type: str
    body: bytes


@dataclass(frozen=True)
class ApiResponse:
    payload: Any
    status: int = 200


def json_body(payload: Any, code: int = 200) -> tuple[bytes, str]:
    body = json.dumps(payload, ensure_ascii=False, default=str, indent=2).encode("utf-8")
    return body, "application/json; charset=utf-8"


def first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def parse_optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def parse_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def parse_payload_watchlist(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return parse_csv(value)
    if isinstance(value, list):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    raise ValueError("watchlist must be a list or comma-separated string")


def parse_payload_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError("boolean payload value is invalid")


def parse_payload_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError("tags must be a list or comma-separated string")
