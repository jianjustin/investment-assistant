from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from investment_assistant.api import auth


class CompatJSONResponse(JSONResponse):
    """对齐旧 server 的序列化：ensure_ascii=False, default=str, indent=2。"""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=str, indent=2).encode("utf-8")


class AuthMiddleware(BaseHTTPMiddleware):
    """检查 HTTP Basic 认证的 middleware。"""

    async def dispatch(self, request: Request, call_next):
        if not auth.authorize(request.headers.get("Authorization")):
            return CompatJSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Hermes Investment Assistant"'},
            )
        return await call_next(request)


def create_app() -> FastAPI:
    from investment_assistant.api.routes import ALL_ROUTERS

    app = FastAPI(
        title="Hermes Investment Assistant",
        default_response_class=CompatJSONResponse,
    )

    # Add auth middleware
    app.add_middleware(AuthMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "error"
        if exc.status_code == 404 and detail == "Not Found":
            detail = "not found"  # 旧契约
        return CompatJSONResponse({"error": detail}, status_code=exc.status_code,
                                  headers=getattr(exc, "headers", None))

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):
        return CompatJSONResponse({"error": str(exc)}, status_code=400)  # 旧 router 契约

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        return CompatJSONResponse({"error": f"invalid request: {exc}"}, status_code=400)  # 旧 400 契约（非 422）

    for router in ALL_ROUTERS:
        app.include_router(router)

    return app
