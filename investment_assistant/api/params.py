from __future__ import annotations

from fastapi import Request


def query_lists(request: Request) -> dict[str, list[str]]:
    """复刻 parse_qs 的 dict[str, list[str]] 形状，供沿用旧签名的 services 使用。"""
    return {k: request.query_params.getlist(k) for k in request.query_params}
