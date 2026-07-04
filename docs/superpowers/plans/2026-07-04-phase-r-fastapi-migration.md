# Phase R — FastAPI 迁移 + DoD 欠账收尾 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 API 层从 stdlib http.server + 手写路由迁到 FastAPI + Pydantic + uvicorn，路由/services/前端契约不变；并补齐 Phase 0 事件研究的前端入口与验证文档（DoD 欠账）。

**Architecture:** 新建 `api/app.py`（`create_app()`），10 个 `api/routes/*.py` 逐域从 `register()` 风格重写为 `APIRouter`；迁移期间新旧路由共存（旧 dispatch 只服务未迁移域的测试），每域迁移时同步把该域测试从 `dispatch(...)` 转为 `TestClient`，断言不变。最后切换 `api/server.py` 入口为 uvicorn 并删除旧路由机。`services/*`、`db.py`、`migrate.py`、`tasks/*`、前端框架不动。

**Tech Stack:** FastAPI、Pydantic v2、uvicorn、httpx（仅测试）、既有 psycopg/pytest/Svelte 5。

## Global Constraints

- 36 条路由路径与响应 JSON 契约不变；前端 `web/src/lib/api.ts` 既有函数零改动（Task 9 只新增）。
- 无 `INVESTMENT_ASSISTANT_DATABASE_URL` 时只读端点返回空 + `{"degraded": true}`，不崩（由 services 保证，路由不得吞掉）。
- 新增依赖仅 `fastapi`、`uvicorn`、`httpx`；禁止引入 SQLModel/alembic/APScheduler。
- 测试离线可跑（无网络、无 DB），外部依赖全 mock；每个 task 结束 `pytest` 全绿再 commit。
- 认证是 **HTTP Basic**（`auth.authorize`），非 token；401 必须带 `WWW-Authenticate: Basic realm="Hermes Investment Assistant"`。
- 序列化契约：`json.dumps(..., ensure_ascii=False, default=str, indent=2)`（services 会返回 date/Decimal，必须保 `default=str`）。
- 错误契约：未知路径 404 `{"error": "not found"}`；处理器抛 `ValueError` → 400 `{"error": "<msg>"}`。
- 文档一律中文。
- DoD（roadmap 00 §6）：每个功能点交付含手动入口 + 验证入口 + 功能说明 + 如何验证示例。

**测试转换通则**（Task 3-8 反复使用，此处定义一次，各任务引用）：

| 旧（dispatch 风格） | 新（TestClient 风格） |
|---|---|
| `from investment_assistant.api.router import dispatch` | 删除；测试函数加 `client` fixture 参数 |
| `dispatch("GET", "/api/x?a=1", None)` | `client.get("/api/x?a=1")` |
| `dispatch("POST", "/api/x", {...})` | `client.post("/api/x", json={...})` |
| `dispatch("PATCH"/"DELETE", ...)` | `client.patch(path, json=...)` / `client.delete(path)` |
| `resp.payload` | `resp.json()` |
| `resp.status` | `resp.status_code` |
| `dispatch(...) is None`（未注册路径） | `resp.status_code == 404` 且 `resp.json() == {"error": "not found"}` |

---

### Task 1: 依赖 + FastAPI app 骨架（认证 / 序列化 / 错误契约）

**Files:**
- Modify: `requirements.txt`
- Create: `investment_assistant/api/app.py`
- Create: `investment_assistant/api/params.py`（`query_lists`，避免 routes↔app 循环 import）
- Modify: `investment_assistant/api/auth.py`（追加 `require_auth`）
- Modify: `investment_assistant/api/routes/__init__.py`（追加 `ALL_ROUTERS` 空列表，后续任务逐域填充）
- Create: `tests/conftest.py`（`client` fixture）
- Test: `tests/test_api_app.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI`（`api/app.py`）；`auth.require_auth(request)` dependency；`routes.ALL_ROUTERS: list[APIRouter]`；pytest fixture `client`（每次调用 `create_app()` 新建 `TestClient`）。
- 后续所有任务向 `ALL_ROUTERS` 追加 router，测试用 `client` fixture。

- [ ] **Step 1: 加依赖并安装**

`requirements.txt` 在 `psycopg-pool` 行后追加：

```
fastapi>=0.115.0
uvicorn>=0.30.0
httpx>=0.27.0
```

Run: `.venv/bin/pip install -r requirements.txt`

- [ ] **Step 2: 写失败测试** — `tests/test_api_app.py`：

```python
from investment_assistant.api import auth


def test_unknown_api_path_returns_legacy_404_shape(client):
    resp = client.get("/api/does-not-exist-xyz")
    assert resp.status_code == 404
    assert resp.json() == {"error": "not found"}


def test_no_password_configured_allows_anonymous(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "")
    resp = client.get("/api/does-not-exist-xyz")
    assert resp.status_code == 404  # 通过认证，走到 404


def test_password_configured_rejects_anonymous_with_basic_challenge(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "secret")
    resp = client.get("/api/does-not-exist-xyz")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == 'Basic realm="Hermes Investment Assistant"'


def test_password_configured_accepts_valid_basic(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "secret")
    resp = client.get("/api/does-not-exist-xyz", auth=(auth.AUTH_USER, "secret"))
    assert resp.status_code == 404
```

`tests/conftest.py`：

```python
import pytest
from fastapi.testclient import TestClient

from investment_assistant.api.app import create_app


@pytest.fixture()
def client():
    return TestClient(create_app())
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_api_app.py -v`
Expected: FAIL（`No module named 'investment_assistant.api.app'`）

- [ ] **Step 4: 实现**

`investment_assistant/api/auth.py` 末尾追加：

```python
def require_auth(request) -> None:
    """FastAPI dependency：HTTP Basic 校验，失败抛 401 + Basic challenge。"""
    from fastapi import HTTPException

    if authorize(request.headers.get("Authorization")):
        return
    raise HTTPException(
        status_code=401,
        detail="unauthorized",
        headers={"WWW-Authenticate": 'Basic realm="Hermes Investment Assistant"'},
    )
```

`investment_assistant/api/routes/__init__.py` 改为（保留旧 import 触发 register，迁移完成前两套共存）：

```python
from . import status, market, tickers, strategies, hermes, watchlist, runs, jobs, settings, research  # noqa: F401

# FastAPI 路由表：后续任务逐域把重写为 APIRouter 的模块追加进来
ALL_ROUTERS = []
```

`investment_assistant/api/params.py`：

```python
from __future__ import annotations

from fastapi import Request


def query_lists(request: Request) -> dict[str, list[str]]:
    """复刻 parse_qs 的 dict[str, list[str]] 形状，供沿用旧签名的 services 使用。"""
    return {k: request.query_params.getlist(k) for k in request.query_params}
```

`investment_assistant/api/app.py`：

```python
from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from investment_assistant.api import auth


class CompatJSONResponse(JSONResponse):
    """对齐旧 server 的序列化：ensure_ascii=False, default=str, indent=2。"""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=str, indent=2).encode("utf-8")


def create_app() -> FastAPI:
    from investment_assistant.api.routes import ALL_ROUTERS

    app = FastAPI(
        title="Hermes Investment Assistant",
        default_response_class=CompatJSONResponse,
        dependencies=[Depends(auth.require_auth)],
    )

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
```

- [ ] **Step 5: 运行确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/test_api_app.py tests/ -q`
Expected: 新测试 4 PASS，全量绿

- [ ] **Step 6: Commit**

```bash
git add requirements.txt investment_assistant/api/app.py investment_assistant/api/params.py investment_assistant/api/auth.py investment_assistant/api/routes/__init__.py tests/conftest.py tests/test_api_app.py
git commit -m "feat(api): FastAPI app skeleton — Basic auth dependency, legacy JSON/error contracts"
```

---

### Task 2: 静态文件 catch-all + SSE /api/events

**Files:**
- Modify: `investment_assistant/api/app.py`（`create_app` 内追加两个路由）
- Modify: `tests/test_dashboard_server.py`（静态测试转 client）
- Test: `tests/test_api_app.py`（追加 SSE 测试）

**Interfaces:**
- Consumes: `static_files.static_response_for_path(path) -> StaticResponse | None`；`tasks.runner.subscribe()/unsubscribe(q)`。
- Produces: `GET /{path:path}` 静态兜底；`GET /api/events` SSE 流。catch-all 必须在 `include_router` 之后注册。

- [ ] **Step 1: 写失败测试**

`tests/test_dashboard_server.py` 的 `test_static_response_serves_index_html` 改为走 HTTP（保留原断言语义）：

```python
def test_static_route_serves_index_html(tmp_path, monkeypatch, client):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>Hermes Dashboard</body></html>", encoding="utf-8")
    monkeypatch.setattr(static_files_mod, "STATIC_DIR", dist)

    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert b"Hermes Dashboard" in resp.content
```

（文件顶部去掉 `dispatch` import 之前先保留——本文件其余 dispatch 测试 Task 3 转换。）

`tests/test_api_app.py` 追加：

```python
def test_sse_events_streams_runner_events(client, monkeypatch):
    import queue as _queue
    from investment_assistant.tasks import runner

    q = _queue.Queue()
    q.put({"run_id": "r1", "status": "done", "kind": "metrics"})
    monkeypatch.setattr(runner, "subscribe", lambda: q)
    monkeypatch.setattr(runner, "unsubscribe", lambda _q: None)

    with client.stream("GET", "/api/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        first_chunk = next(resp.iter_lines())
        assert first_chunk.startswith("data: ")
        assert '"run_id": "r1"' in first_chunk
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_api_app.py::test_sse_events_streams_runner_events "tests/test_dashboard_server.py::test_static_route_serves_index_html" -v`
Expected: FAIL（404 not found）

- [ ] **Step 3: 实现** — `create_app()` 内、`include_router` 循环之后追加：

```python
    from fastapi.responses import Response, StreamingResponse

    @app.get("/api/events")
    def _events():
        import queue as _queue

        from investment_assistant.tasks import runner

        q = runner.subscribe()

        def stream():
            try:
                while True:
                    try:
                        event = q.get(timeout=15)
                    except _queue.Empty:
                        yield ": keep-alive\n\n"  # 心跳，客户端断开时借此退出
                        continue
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            finally:
                runner.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/{full_path:path}")
    def _static(full_path: str):
        from fastapi import HTTPException

        from investment_assistant.api import static_files

        resp = static_files.static_response_for_path("/" + full_path)
        if resp is None:
            raise HTTPException(status_code=404, detail="not found")
        return Response(content=resp.body, media_type=resp.content_type, status_code=resp.status)
```

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/api/app.py tests/test_api_app.py tests/test_dashboard_server.py
git commit -m "feat(api): static catch-all + SSE /api/events on FastAPI (legacy behavior preserved)"
```

---

### Task 3: status 域路由（/api/status /raw/status /health /services /filings /operations）

**Files:**
- Rewrite: `investment_assistant/api/routes/status.py`
- Modify: `investment_assistant/api/routes/__init__.py`（ALL_ROUTERS 追加）
- Modify: `tests/test_dashboard_server.py`、`tests/test_api_contract.py`（status/operations 相关函数转 client）

**Interfaces:**
- Consumes: `services.status` 的 `status_payload/system_status/filing_status/filing_rows/operation_registry`；`services.health.health_report`。
- Produces: APIRouter `status.router`，路径与响应形状同旧版（`/api/filings` → `{"summary":..., "files":...}`；`/api/operations` → `{"operations": [...]}`）。

- [ ] **Step 1: 转换测试（即本任务的失败测试）**

按 Global Constraints 的转换通则改写：
- `tests/test_dashboard_server.py::test_api_response_for_path_returns_feature_payloads`：全部 `dispatch("GET", p, None).payload` → `client.get(p).json()`；末行 `dispatch("GET","/api/missing",None) is None` → `client.get("/api/missing").status_code == 404`。加 `client` 参数，删 dispatch import。
- `tests/test_api_contract.py`：`test_unknown_api_get_returns_none` 改名 `test_unknown_api_get_returns_404` 用 client；`test_status_get_route_resolves`、`test_operations_registry_shape` 转 client（断言不变）。其余函数（watchlist/market）暂留 dispatch —— Task 4/6 处理。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_dashboard_server.py tests/test_api_contract.py -v`
Expected: 转换过的函数 FAIL（404 —— app 尚无 status 路由）；未转换的 PASS

- [ ] **Step 3: 重写** `investment_assistant/api/routes/status.py`：

```python
from fastapi import APIRouter

import investment_assistant.services.status as _status
from investment_assistant.services.health import health_report

router = APIRouter()


@router.get("/api/status")
@router.get("/api/raw/status")
def status_route():
    return _status.status_payload()


@router.get("/api/health")
def health():
    return health_report()


@router.get("/api/services")
def services():
    return _status.system_status()


@router.get("/api/filings")
def filings():
    return {"summary": _status.filing_status(), "files": _status.filing_rows()}


@router.get("/api/operations")
def operations():
    return {"operations": _status.operation_registry()}
```

`routes/__init__.py`：`ALL_ROUTERS = [status.router]`（status 已无 register 调用，import 行保留其余模块）。

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全绿（旧 dispatch 测试里 status 域已不存在——确认没有遗漏未转换的 status 断言）

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/api/routes/status.py investment_assistant/api/routes/__init__.py tests/test_dashboard_server.py tests/test_api_contract.py
git commit -m "refactor(api): migrate status domain routes to FastAPI APIRouter"
```

---

### Task 4: market + tickers + strategies 域

**Files:**
- Rewrite: `investment_assistant/api/routes/market.py`、`tickers.py`、`strategies.py`
- Modify: `investment_assistant/api/routes/__init__.py`
- Modify: `tests/test_market_signal_admin_api.py`（market/tickers/strategies 函数）、`tests/test_api_contract.py`（market fetch）、`tests/test_api_router.py`（整文件删除见 Step 1 说明）

**Interfaces:**
- Consumes: `services.market.market_signal_rows(query)/market_signal_trend(query)`（**接收 parse_qs 形状 dict**，用 `app.query_lists` 透传）、`fetch_market_signals(payload)`；`services.tickers.ticker_trend_rows()/run_ticker_trend_scan(payload)`；`services.strategies.strategy_score_rows()/run_strategy_score_scan(payload)`。
- Produces: `market.router`、`tickers.router`、`strategies.router`。

- [ ] **Step 1: 转换测试**

- `tests/test_market_signal_admin_api.py`：market 列表/趋势/fetch、tickers trends/scan、strategies scores/run 相关函数按通则转 client。hermes 与 watchlist 相关函数暂留。
- `tests/test_api_contract.py::test_market_fetch_*`（POST /api/market/signals/fetch）转 client。
- `tests/test_api_router.py` 测的是旧 dispatch 机制本身（query 解析/ValueError→400）：其中 ValueError→400 的契约已由 `tests/test_api_app.py` 的 app 级 handler 覆盖不到具体路由——把该文件改写为 app 级等价测试并入 `tests/test_api_app.py`：

```python
def test_value_error_from_handler_returns_400(client, monkeypatch):
    import investment_assistant.services.market as _market
    monkeypatch.setattr(_market, "fetch_market_signals", lambda payload: (_ for _ in ()).throw(ValueError("bad date")))
    resp = client.post("/api/market/signals/fetch", json={})
    assert resp.status_code == 400
    assert resp.json() == {"error": "bad date"}
```

然后 `git rm tests/test_api_router.py`。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_market_signal_admin_api.py tests/test_api_contract.py tests/test_api_app.py -v`
Expected: 转换过的函数 404 FAIL

- [ ] **Step 3: 重写三个模块**

`investment_assistant/api/routes/market.py`：

```python
from typing import Any

from fastapi import APIRouter, Body, Depends

import investment_assistant.services.market as _market
import investment_assistant.services.status as _status
from investment_assistant.api.params import query_lists

router = APIRouter()


@router.get("/api/market/signals")
def signals(query: dict[str, list[str]] = Depends(query_lists)):
    rows = _market.market_signal_rows(query)
    return {"rows": rows, "count": len(rows)}


@router.get("/api/market/signals/latest")
def latest():
    return _status.database_status().get("latest_market_signal")


@router.get("/api/market/signals/trend")
def trend(query: dict[str, list[str]] = Depends(query_lists)):
    return _market.market_signal_trend(query)


@router.post("/api/market/signals/fetch")
def fetch(payload: dict[str, Any] = Body(default_factory=dict)):
    return _market.fetch_market_signals(payload)
```

`investment_assistant/api/routes/tickers.py`：

```python
from typing import Any

from fastapi import APIRouter, Body

import investment_assistant.services.tickers as _tickers

router = APIRouter()


@router.get("/api/tickers/trends")
def trends():
    rows = _tickers.ticker_trend_rows()
    return {"rows": rows, "count": len(rows)}


@router.post("/api/tickers/trends/scan")
def scan(payload: dict[str, Any] = Body(default_factory=dict)):
    return _tickers.run_ticker_trend_scan(payload)
```

`investment_assistant/api/routes/strategies.py`：同 tickers 模式，`GET /api/strategies/scores` → `{"rows": rows, "count": len(rows)}`（`strategy_score_rows()`），`POST /api/strategies/scores/run` → `run_strategy_score_scan(payload)`。

`routes/__init__.py`：`ALL_ROUTERS = [status.router, market.router, tickers.router, strategies.router]`。

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/api/routes/ investment_assistant/api/params.py investment_assistant/api/app.py tests/
git commit -m "refactor(api): migrate market/tickers/strategies domains to FastAPI"
```

---

### Task 5: hermes 域

**Files:**
- Rewrite: `investment_assistant/api/routes/hermes.py`
- Modify: `investment_assistant/api/routes/__init__.py`
- Modify: `tests/test_hermes_agent_registry.py`、`tests/test_hermes_macro_analyst.py`、`tests/test_market_signal_admin_api.py`（hermes 相关函数）

**Interfaces:**
- Consumes: `hermes.agents.hermes_overview()/list_agents()/save_agent(payload)`；`services.hermes.hermes_macro_analysis(query)`（parse_qs 形状，用 `params.query_lists`）、`submit_macro_llm(payload)`、`submit_decision_evidence(payload)`。
- Produces: `hermes.router`。

- [ ] **Step 1: 转换测试**（三个文件中 hermes 相关函数按通则转 client；注意 `save_agent` 抛 `ValueError` 时旧契约 400 `{"error": ...}` 由 app 级 handler 保证，断言不变）

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_hermes_agent_registry.py tests/test_hermes_macro_analyst.py -v`
Expected: 404 FAIL

- [ ] **Step 3: 重写** `investment_assistant/api/routes/hermes.py`：

```python
from typing import Any

from fastapi import APIRouter, Body, Depends

import investment_assistant.services.hermes as _hermes
from investment_assistant.api.params import query_lists
from investment_assistant.hermes import agents as hermes_agents

router = APIRouter()


@router.get("/api/hermes")
def overview():
    return hermes_agents.hermes_overview()


@router.get("/api/hermes/agents")
def agents_list():
    return {"agents": hermes_agents.list_agents()}


@router.get("/api/hermes/macro-analysis")
@router.get("/api/hermes/market-signals/interpretation")
def macro_analysis(query: dict[str, list[str]] = Depends(query_lists)):
    return _hermes.hermes_macro_analysis(query)


@router.post("/api/hermes/macro-analysis/run")
def macro_run(payload: dict[str, Any] = Body(default_factory=dict)):
    return _hermes.submit_macro_llm(payload)


@router.post("/api/hermes/decision-evidence/run")
def decision_run(payload: dict[str, Any] = Body(default_factory=dict)):
    return _hermes.submit_decision_evidence(payload)


@router.post("/api/hermes/agents")
def agents_save(payload: dict[str, Any] = Body(default_factory=dict)):
    return {"agent": hermes_agents.save_agent(payload)}
```

`routes/__init__.py` ALL_ROUTERS 追加 `hermes.router`。

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q` → 全绿

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/api/routes/ tests/
git commit -m "refactor(api): migrate hermes domain to FastAPI"
```

---

### Task 6: research + watchlist + settings 域

**Files:**
- Rewrite: `investment_assistant/api/routes/research.py`、`watchlist.py`、`settings.py`
- Modify: `investment_assistant/api/routes/__init__.py`
- Modify: `tests/test_research_api.py`、`tests/test_market_signal_admin_api.py`（watchlist）、`tests/test_api_contract.py`（watchlist fallback）、`tests/test_settings_service.py`（若有 dispatch 断言则转换，否则不动）

**Interfaces:**
- Consumes: `services.research.available_kinds()/event_study_view(kind, since=, asof=)`；`services.watchlist.watchlist_rows()/add_watchlist_item(payload)/delete_watchlist_item(ticker)`；`services.settings.read_notify_view()/update_notify(payload)/test_notify_channel(channel, url=)/read_env_status()`。
- Produces: `research.router`、`watchlist.router`、`settings.router`。

- [ ] **Step 1: 转换测试**（按通则；`DELETE /api/watchlist/NVDA` → `client.delete("/api/watchlist/NVDA")`）

- [ ] **Step 2: 运行确认失败** — Run 上述测试文件，Expected: 404 FAIL

- [ ] **Step 3: 重写**

`investment_assistant/api/routes/research.py`（保留旧手工校验契约：缺 kind → 400 `{"error": "kind is required"}`）：

```python
from datetime import date

from fastapi import APIRouter, HTTPException

from investment_assistant.services import research

router = APIRouter()


@router.get("/api/research/event-study/kinds")
def kinds():
    return research.available_kinds()


@router.get("/api/research/event-study")
def event_study(kind: str | None = None, since: str | None = None, asof: str | None = None):
    if not kind:
        raise HTTPException(status_code=400, detail="kind is required")
    return research.event_study_view(
        kind,
        since=date.fromisoformat(since) if since else None,
        asof=date.fromisoformat(asof) if asof else None,
    )
```

`investment_assistant/api/routes/watchlist.py`：

```python
from typing import Any

from fastapi import APIRouter, Body

import investment_assistant.services.watchlist as _watchlist

router = APIRouter()


@router.get("/api/watchlist")
def list_items():
    rows = _watchlist.watchlist_rows()
    return {"rows": rows, "count": len(rows)}


@router.post("/api/watchlist")
def add(payload: dict[str, Any] = Body(default_factory=dict)):
    return {"item": _watchlist.add_watchlist_item(payload)}


@router.delete("/api/watchlist/{ticker}")
def delete(ticker: str):
    return _watchlist.delete_watchlist_item(ticker)
```

`investment_assistant/api/routes/settings.py`：

```python
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from investment_assistant.services import settings

router = APIRouter()


@router.get("/api/settings/notify")
def get_notify():
    return settings.read_notify_view()


@router.patch("/api/settings/notify")
def patch_notify(payload: dict[str, Any] = Body(default_factory=dict)):
    return settings.update_notify(payload)


@router.post("/api/settings/notify/test")
def test_notify(payload: dict[str, Any] = Body(default_factory=dict)):
    channel = payload.get("channel")
    if not channel:
        raise HTTPException(status_code=400, detail="channel required")
    return settings.test_notify_channel(channel, url=payload.get("url"))


@router.get("/api/settings/env")
def env_status():
    return settings.read_env_status()
```

`routes/__init__.py` ALL_ROUTERS 追加三个 router。

- [ ] **Step 4: 全量回归** — `pytest tests/ -q` 全绿
- [ ] **Step 5: Commit**

```bash
git add investment_assistant/api/routes/ tests/
git commit -m "refactor(api): migrate research/watchlist/settings domains to FastAPI"
```

---

### Task 7: jobs + runs 域

**Files:**
- Rewrite: `investment_assistant/api/routes/jobs.py`、`runs.py`
- Modify: `investment_assistant/api/routes/__init__.py`
- Test: 相关既有测试转换（grep `dispatch(` 确认残余；jobs/runs 若无 dispatch 测试则为其在 `tests/test_api_app.py` 补最小 client 测试）

**Interfaces:**
- Consumes: `services.jobs.scheduled_jobs()/job_reports(task=, limit=)/job_metrics(task=, days=)/trigger_job(name)/patch_scheduled_job(name, enabled=, time_local=)`；`tasks.runner.get(run_id)`；`api.http.parse_int`（保留使用——钳位语义是旧契约）。
- Produces: `jobs.router`、`runs.router`。

- [ ] **Step 1: 写失败测试** — `tests/test_api_app.py` 追加（jobs/runs 旧测试若存在则转换替代）：

```python
def test_get_unknown_run_returns_404(client):
    resp = client.get("/api/runs/nope-123")
    assert resp.status_code == 404
    assert resp.json() == {"error": "unknown run"}


def test_jobs_run_requires_run_suffix_contract(client, monkeypatch):
    from investment_assistant.services import jobs as jobs_svc
    monkeypatch.setattr(jobs_svc, "trigger_job", lambda name: {"run_id": f"{name}-1", "status": "pending"})
    resp = client.post("/api/jobs/metrics/run", json={})
    assert resp.status_code == 200
    assert resp.json()["run_id"] == "metrics-1"
```

- [ ] **Step 2: 运行确认失败** — Expected: 404 `{"error": "not found"}`（路由未注册）

- [ ] **Step 3: 重写**

`investment_assistant/api/routes/runs.py`：

```python
from fastapi import APIRouter, HTTPException

from investment_assistant.tasks import runner

router = APIRouter()


@router.get("/api/runs/{run_id}")
def get_run(run_id: str):
    rec = runner.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return rec
```

`investment_assistant/api/routes/jobs.py`（保留 `parse_int` 钳位契约；`trigger_job` 未知任务抛 ValueError → 旧契约是 404，需局部捕获）：

```python
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from investment_assistant.api.http import parse_int
from investment_assistant.services import jobs

router = APIRouter()


@router.get("/api/jobs/scheduled")
def scheduled():
    return jobs.scheduled_jobs()


@router.get("/api/jobs/reports")
def reports(task: str | None = None, limit: str | None = None):
    return jobs.job_reports(task=task, limit=parse_int(limit, default=50, minimum=1, maximum=200))


@router.get("/api/jobs/metrics")
def metrics(task: str | None = None, window: str | None = None):
    return jobs.job_metrics(task=task, days=parse_int(window, default=7, minimum=1, maximum=90))


@router.post("/api/jobs/{name}/run")
def run_job(name: str, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return jobs.trigger_job(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))  # 旧契约：未知任务 404


@router.patch("/api/jobs/scheduled/{name}")
def patch_job(name: str, payload: dict[str, Any] = Body(default_factory=dict)):
    return jobs.patch_scheduled_job(name, enabled=payload.get("enabled"), time_local=payload.get("time_local"))
```

`routes/__init__.py` ALL_ROUTERS 追加 `jobs.router, runs.router`。

- [ ] **Step 4: 全量回归** — `pytest tests/ -q` 全绿
- [ ] **Step 5: Commit**

```bash
git add investment_assistant/api/routes/ tests/
git commit -m "refactor(api): migrate jobs/runs domains to FastAPI"
```

---

### Task 8: 入口切换 uvicorn + 拆除旧路由机

**Files:**
- Rewrite: `investment_assistant/api/server.py`
- Delete: `investment_assistant/api/router.py`
- Modify: `investment_assistant/api/http.py`（删 `ApiResponse`/`json_body`；保留 `StaticResponse` 与全部 parse 助手——services 仍依赖）
- Modify: `investment_assistant/api/routes/__init__.py`（删旧 import 行，只留 ALL_ROUTERS）
- Modify: `tests/test_api_http.py`（删 `json_body`/`ApiResponse` 相关断言，保 parse 助手测试）

**Interfaces:**
- Produces: `python -m investment_assistant.api.server` 起 uvicorn；`create_app()` 不再依赖任何 register 机制。

- [ ] **Step 1: 确认无残余引用**

Run: `grep -rn "api.router\|ApiResponse\|register(" investment_assistant tests --include="*.py"`
Expected: 仅 `api/router.py` 自身与 `api/http.py` 定义处（如有其它残余，先回到对应任务补转换）

- [ ] **Step 2: 重写** `investment_assistant/api/server.py`：

```python
"""uvicorn entry point. `python -m investment_assistant.api.server`."""
from __future__ import annotations

from investment_assistant.api import auth
from investment_assistant.api.app import create_app

app = create_app()


def main() -> None:
    import uvicorn

    host = auth.resolve_bind_host()  # fail-closed：公网绑定无认证直接拒绝启动
    uvicorn.run(app, host=host, port=auth.PORT, log_level="warning")


if __name__ == "__main__":
    main()
```

删除与瘦身：

```bash
git rm investment_assistant/api/router.py
```

`api/http.py`：删除 `ApiResponse` dataclass 与 `json_body`，文件其余保留。`routes/__init__.py` 变为：

```python
from . import status, market, tickers, strategies, hermes, watchlist, runs, jobs, settings, research

ALL_ROUTERS = [
    status.router, market.router, tickers.router, strategies.router,
    hermes.router, watchlist.router, runs.router, jobs.router,
    settings.router, research.router,
]
```

- [ ] **Step 3: 全量回归 + 手动验证（DoD 验证入口）**

```bash
.venv/bin/python -m pytest tests/ -q                     # 全绿
.venv/bin/python -m investment_assistant.api.server &    # 本机起服务
curl -s localhost:8787/api/status | head -5              # JSON 返回（degraded 可为 true）
curl -s localhost:8787/api/does-not-exist                # {"error": "not found"}
curl -s localhost:8787/docs -o /dev/null -w "%{http_code}\n"   # 200 —— OpenAPI 文档页
kill %1
```

- [ ] **Step 4: Commit**

```bash
git add -A investment_assistant/api tests/test_api_http.py
git commit -m "refactor(api): switch entry to uvicorn, remove legacy router/http machinery"
```

---

### Task 9: 前端事件研究面板（Phase 0 DoD 欠账 · 手动入口）

**Files:**
- Modify: `web/src/lib/api.ts`（追加两个函数）
- Modify: `web/src/lib/components/SideNav.svelte:27`（`backtest` 子项改为 `event-study`）
- Modify: `web/src/routes/Strategy.svelte`（`backtest` 占位分支替换为事件研究面板）
- Modify: `tests/test_dashboard_frontend_source.py`（追加断言）

**Interfaces:**
- Consumes: `GET /api/research/event-study/kinds` → `{"kinds": ["rs_strong", ...]}`；`GET /api/research/event-study?kind=X` → `{"result": {...horizons/caveats...}, "degraded": bool, "source": "cache"|"computed"}`。
- Produces: `api.ts` 导出 `getEventStudyKinds`、`getEventStudy(kind, since?, asof?)`。

- [ ] **Step 1: 写失败测试** — `tests/test_dashboard_frontend_source.py` 追加：

```python
def test_api_client_exports_event_study_functions():
    api = Path("web/src/lib/api.ts").read_text(encoding="utf-8")
    for fn in ["getEventStudyKinds", "getEventStudy"]:
        assert fn in api, f"missing: {fn}"


def test_strategy_zone_has_event_study_panel():
    nav = Path("web/src/lib/components/SideNav.svelte").read_text(encoding="utf-8")
    assert "event-study" in nav and "事件研究" in nav
    strategy = Path("web/src/routes/Strategy.svelte").read_text(encoding="utf-8")
    assert "getEventStudy" in strategy
```

Run: `.venv/bin/python -m pytest tests/test_dashboard_frontend_source.py -v` → 新增两条 FAIL

- [ ] **Step 2: 实现**

`web/src/lib/api.ts` 末尾追加：

```typescript
// research
export const getEventStudyKinds = () => get<{ kinds: string[] }>('/api/research/event-study/kinds')
export const getEventStudy = (kind: string, since?: string, asof?: string) =>
  get<{ result: any; degraded: boolean; source: string }>(
    `/api/research/event-study?kind=${kind}${since ? `&since=${since}` : ''}${asof ? `&asof=${asof}` : ''}`,
  )
```

`SideNav.svelte` 第 27 行：`{ id: 'backtest', label: '回测' }` → `{ id: 'event-study', label: '事件研究' }`。

`Strategy.svelte`：`{#if sub === 'backtest'}` 分支替换为：

```svelte
  {#if sub === 'event-study'}
    <div class="flex justify-between items-center mb-4">
      <h2 class="text-lg font-semibold">事件研究</h2>
      <div class="flex gap-2 items-center">
        <select bind:value={esKind} class="text-sm border rounded px-2 py-1 bg-surface">
          {#each esKinds as k}<option value={k}>{k}</option>{/each}
        </select>
        <button onclick={runEventStudy} disabled={esLoading} class="px-3 py-1 bg-accent text-white rounded text-sm disabled:opacity-50">
          {esLoading ? '计算中…' : '运行'}
        </button>
      </div>
    </div>
    <p class="text-sm text-muted mb-3">统计某类信号事件后 N 个交易日的超额收益分布（A 层回测）。结果可能来自缓存（source=cache）。</p>
    {#if esResult}
      {#if esResult.result?.caveats?.length}
        <div class="bg-surface rounded p-3 mb-3 text-sm text-warning">
          {#each esResult.result.caveats as c}<div>⚠ {c}</div>{/each}
        </div>
      {/if}
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <DataTable rows={esResult.result?.horizons ?? []} columns={esCols} />
      </div>
      <p class="text-xs text-muted mt-2">source: {esResult.source}{esResult.degraded ? ' · degraded（无数据库）' : ''}</p>
    {:else if !esLoading}
      <Placeholder title="事件研究" note="选择信号类型后点「运行」。" planned="" />
    {/if}
  {:else}
```

`<script>` 内追加状态与逻辑（列名以 `research/event_study.py` 的 `to_dict()` 输出为准，执行时核对后调整 `esCols`）：

```typescript
  let esKinds = $state<string[]>([])
  let esKind = $state('rs_strong')
  let esResult = $state<any>(null)
  let esLoading = $state(false)
  const esCols = [
    { key: 'horizon', label: '窗口(交易日)' },
    { key: 'n', label: '样本数' },
    { key: 'mean_excess', label: '平均超额' },
    { key: 'median_excess', label: '中位超额' },
    { key: 'win_rate', label: '胜率' },
  ]
  async function loadEventStudyKinds() {
    try { esKinds = (await api.getEventStudyKinds()).kinds } catch { esKinds = [] }
  }
  async function runEventStudy() {
    esLoading = true
    try { esResult = await api.getEventStudy(esKind) } finally { esLoading = false }
  }
  onMount(() => { load(); loadEventStudyKinds() })
```

（原 `onMount(load)` 合并进上式，避免重复注册。）

- [ ] **Step 3: 验证**

```bash
.venv/bin/python -m pytest tests/test_dashboard_frontend_source.py -q   # 全绿
cd web && npm test && npm run build                                      # vitest + svelte-check 绿
```

- [ ] **Step 4: Commit**

```bash
git add web/src tests/test_dashboard_frontend_source.py
git commit -m "feat(web): event-study panel in strategy zone (replaces backtest placeholder)"
```

---

### Task 10: 事件研究验证文档 + 架构文档对齐 + 收尾回归

**Files:**
- Create: `docs/research-event-study.md`
- Modify: `docs/architecture.md`、`docs/getting-started.md`（HTTP 层描述改 FastAPI/uvicorn，快速开始加 `/docs`）
- Modify: `README.md`（依赖清单加 fastapi/uvicorn）

**Interfaces:** 无代码；DoD 文档件。

- [ ] **Step 1: 写 `docs/research-event-study.md`**（功能说明 + 三条验证路径，DoD 第 3 条）：

````markdown
# 事件研究（Event Study）— 功能说明与验证

## 这是什么

统计某类信号事件（如 rs_strong / ma_reclaim / score_high / eps_beat / eps_miss）发生后
5/10/20 个交易日的超额收益分布（相对 SPY），带样本量与统计诚实性 caveats。
这是回测三层严肃度中的 A 层（见 docs/roadmap/00 §2）。

## 如何验证

**路径一：CLI（离线可跑，无 DB 也可）**
```bash
.venv/bin/python -m investment_assistant.research.event_study --kind rs_strong
# 期望：输出 JSON，含 horizons 数组与 caveats；样本不足时 caveats 含 n<min_sample 警告
```

**路径二：API**
```bash
curl -s "localhost:8787/api/research/event-study/kinds"          # {"kinds": [...]}
curl -s "localhost:8787/api/research/event-study?kind=rs_strong" # {"result": ..., "source": "cache|computed"}
# 无 INVESTMENT_ASSISTANT_DATABASE_URL 时返回 degraded: true，不报错
```

**路径三：前端**
面板「策略 → 事件研究」：选 kind → 点「运行」→ 展示各窗口超额收益表 + caveats。

**定时任务**：调度器每日跑 `event_study` 任务（结果入 `event_studies` 缓存表），
执行记录见「设置 → 任务」或 `GET /api/jobs/reports?task=event_study`。
````

（CLI 参数名执行时以 `research/event_study.py` `__main__` 实际 argparse 为准核对，不符则修文档。）

- [ ] **Step 2: 更新 architecture/getting-started/README** — HTTP 层描述从「stdlib http.server + 手写路由」改为「FastAPI + uvicorn（`api/app.py` create_app）」；getting-started 快速开始追加：浏览 `http://localhost:8787/docs` 可查看全部 API 的 OpenAPI 文档（每个端点的功能说明与参数）。

- [ ] **Step 3: 收尾全量回归（Phase R 完成标志）**

```bash
.venv/bin/python -m pytest tests/ -q     # 全绿
cd web && npm test && npm run build      # 绿
grep -rn "http.server\|BaseHTTPRequestHandler" investment_assistant   # 无输出
```

- [ ] **Step 4: Commit**

```bash
git add docs README.md
git commit -m "docs: event-study verification guide + FastAPI architecture alignment (Phase R done)"
```

---

## Self-Review 记录

- **Spec 覆盖**：迁移边界（T1-T8）、行为契约 5 条（401 挑战 T1、404/ValueError T1、degraded 由 services 保证并在 T8 手动验证、SSE T2、static T2）、入口不变（T8）、事件研究前端（T9）、验证文档（T10）——齐。
- **占位符**：无 TBD；仅两处「执行时核对」（T9 esCols 列名、T10 CLI 参数名）为事实核对指令而非缺失设计。
- **类型一致性**：`query_lists` 自 Task 1 起即在 `api/params.py`，T4/T5 直接 import；`ALL_ROUTERS` 各任务追加顺序与 T8 终态一致。
