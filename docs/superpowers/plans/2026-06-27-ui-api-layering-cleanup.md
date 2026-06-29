# 前置三件套实施计划：老旧代码删除 → API 架构分层（拆 API + 定时任务）→ UI 重做

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改动数据库 schema 的前提下，删除并行的旧 earnings-agent 代码、把 860 行的 `dashboard/server.py` 单体拆成分层 API + 独立定时任务，并把 vanilla-TS 前端重做为 Svelte 5 + 真实图表的 6 区信息架构。

**Architecture:** 三部分按依赖顺序执行 —— 先 **删旧码**（缩小面、消除死引用，并把唯一仍被生产依赖的 `data/price.py` 与可复用的 `notify/` 折进 `investment_assistant`），再 **分层 API + 拆定时任务**（路由表 / 服务层 / 仓储层 + 后台任务 runner + 独立 systemd 定时入口），最后 **重做 UI**（消费已稳定的 API，加 SSE 自动刷新与 Lightweight Charts / ECharts）。每个任务都有特征化测试或单测兜底，保证逐 commit 可上线。

**Tech Stack:** Python 3.11（stdlib `http.server` + psycopg3 + PostgreSQL 16），前端 Svelte 5 + Vite 6 + Tailwind 3 + TradingView Lightweight Charts + ECharts + Vitest；部署 systemd + Docker Postgres。

## 为什么是这个顺序（覆盖用户点名的三部分）

用户要求「UI 重做 + API 架构分层（拆 API + 定时任务）+ 老旧代码删除」三部分**先做**。三者技术上相互独立，但执行有最优序：

1. **Part A 老旧代码删除（先）** —— 风险最低；删除前必须先把生产唯一依赖的 `data/price.py` 折进包内（否则后两步会踩到 `from data.price import ...` 的跨库死引用）。先清场，后两步面对的就是单一代码库。
2. **Part B API 架构分层（中）** —— 在干净代码上把单体 `server.py` 拆为路由/服务/仓储三层，并将定时任务与后台 LLM 调用从请求线程中分离。产出**稳定的 API 契约 + SSE/轮询端点**，正好是 UI 要消费的。
3. **Part C UI 重做（后）** —— 体量最大，消费 Part B 的分层 API 与 SSE。

> 若执行者更偏好用户列出的字面顺序，也可先做 Part C；但 Part C 的 T5.4（SSE 自动刷新 / 真实端点）依赖 Part B 的后台 runner，分层后实现更顺。本计划按 A→B→C 编排。

---

## Global Constraints

以下为 `docs/execution-plan-2026-06.md` 的横切验收门槛 + 本计划全局约束，**每个任务隐式包含**：

- **每个 PR**：新增/改动逻辑必须有单测；外部调用（yfinance / SMTP / DeepSeek / Discord / `systemctl` / `subprocess`）**全部 mock**，测试离线可跑。
- **不引入新的裸 `except Exception` 吞错**；外部失败需结构化上报（沿用现有 `{"ok": false, "error": ...}` / `ApiResponse(..., status=4xx)` 形态）。
- **本三件套不触碰数据库 schema**：不新增/修改 `migrations/*.sql`。仅消费现有 4 张表（`market_signals` / `watchlist_items` / `ticker_signal_snapshots` / `strategy_scores`）。后台任务状态用进程内 registry + 现有 `run_log` jsonl，不建表。
- **行为保持优先**：API 重构是「搬代码 + 加测试钉契约」，对外 JSON 响应形状在 Part B 内除「LLM 端点改异步」外**保持不变**；该一处变更同步更新前端轮询逻辑，保证每个 commit 可上线。
- **真实模型 ID 已在 config**：`cfg.llm.model="deepseek-chat"` / `cfg.llm.deep_research_model="deepseek-reasoner"`（见 `config.py:30-39`）。重构时若搬动 `server.py:497,521` 的 `"deepseek-v4-pro"` 兜底字符串，**保持原样**（其修正属 Phase 0 T0.1，不在本计划范围）。
- **默认绑定 `127.0.0.1`**，公网绑定 fail-closed 行为（`server.py:838-851`）在重构后必须逐字保留并有测试覆盖。
- **分支**：从 `main` 切 `feat/ui-api-cleanup` 工作分支；除非用户要求，不直接在 `main` 提交，不主动 push。
- **提交信息结尾**：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **已知前置缺陷（不在本计划修复，仅需绕过）**：`hermes/daily.py:61` 引用的 `investment_assistant.filings.service` 模块**当前不存在**，`tests/test_filing_service.py` 因此 import 失败 —— 非 dry-run 的 daily filing step 当前是坏的。Part B 的定时任务封装必须对该 step **失败容错**（捕获 `ImportError`/异常并结构化记录，不让整个 daily run 崩），真正的 filings 实现属 Phase 2 T2.2。

---

## File Structure（三部分目标布局）

**Part A 删除后（保留并迁移的）：**
```
investment_assistant/
  data/__init__.py            # 新：包标记
  data/price.py               # 新：从根 data/price.py 原样迁入（yfinance OHLCV 包装）
  notify/__init__.py          # 新
  notify/discord.py           # 新：从根 notify/discord.py 迁入（Phase 1 复用）
  notify/templates.py         # 新：从根 notify/templates.py 迁入
```
**删除：** 根 `data/`（除已迁出的 price）、`signals/`、`notify/`、`ops/`、`vault/`、根脚本 `diagnose_edgar.py`/`earnings_calendar.py`/`earnings_monitor.py`/`sec_downloader.py`/`vault_writer.py`、`scripts/test_*.py`、旧测试 `tests/test_market.py`/`test_technicals.py`，并把 `tests/test_price.py`→`tests/test_data_price.py`、`tests/test_discord.py`→`tests/test_notify_discord.py`（更新 import）。

**Part B 后端目标布局：**
```
investment_assistant/
  api/
    __init__.py
    http.py            # ApiResponse/StaticResponse + send 助手 + 解析助手(_first/_parse_int/...)
    auth.py            # AUTH_* 读取 + authorize(header)->bool + resolve_bind_host()
    static_files.py    # static_response_for_path（服务 web/dist）
    router.py          # ROUTES 注册表 + dispatch(method, path, payload)
    server.py          # 薄 Handler(do_GET/POST/DELETE) + main() + ThreadingHTTPServer
    routes/
      __init__.py      # 汇总 register() 调用
      status.py market.py tickers.py strategies.py hermes.py watchlist.py runs.py
  services/
    __init__.py status.py market.py tickers.py strategies.py hermes.py watchlist.py
  tasks/
    __init__.py runner.py daily.py nightly_scores.py
  dashboard/server.py  # 改为薄 shim：from investment_assistant.api.server import main（保 systemd 不变）
```

**Part C 前端目标布局：**
```
web/
  package.json vite.config.ts svelte.config.js tsconfig.json tailwind.config.ts vitest.config.ts
  src/
    main.ts app.svelte
    lib/
      api.ts            # 类型化 fetch 客户端（所有 /api/*）
      sse.ts            # SSE store（/api/events）
      theme.ts          # data-theme 暗色切换
      format.ts i18n.ts
      charts/LineChart.svelte CandleChart.svelte EChart.svelte
      components/AppShell.svelte SideNav.svelte Skeleton.svelte DataTable.svelte Drawer.svelte StatusPill.svelte
    routes/
      Dashboard.svelte Market.svelte Watchlist.svelte Strategy.svelte Hermes.svelte System.svelte
    styles/tokens.css app.css
```

---

# Part A — 老旧代码删除

> 目标：消除两套并行代码库，留下单一生产路径。先迁移生产仍依赖的 `data/price.py` 与 Phase 1 要复用的 `notify/`，再删其余死码。`grep` 验证无死引用。

**已确认的跨库依赖（删除安全性的关键）：**
- 生产包 `investment_assistant/` 对旧码的**唯一**依赖是 `data.price.get_price_history`，出现在两处惰性 import：`investment_assistant/tickers/trend.py:148` 与 `investment_assistant/market/service.py:89`。
- `notify/discord.py` + `notify/templates.py` 当前只被旧 `ops/` 与旧测试引用，但 Phase 1 (T1.2) 计划复用 → **迁移保留**，不删。
- 其余 `data/sec.py`、`data/earnings.py`、`signals/`、`ops/`、`vault/`、根脚本均**未被生产包 import**，可删。

### Task A1：迁移 `data/price.py` 进生产包

**Files:**
- Create: `investment_assistant/data/__init__.py`
- Create: `investment_assistant/data/price.py`
- Create: `tests/test_data_price.py`（由旧 `tests/test_price.py` 改 import 而来）
- Modify: `investment_assistant/tickers/trend.py:147-149`
- Modify: `investment_assistant/market/service.py:88-91`

**Interfaces:**
- Produces: `investment_assistant.data.price.get_price_history(ticker: str, days: int = 90) -> pandas.DataFrame`（OHLCV 列：Open/High/Low/Close/Volume；空数据抛 `ValueError`）。

- [ ] **Step 1: 写失败测试** —— 新建 `tests/test_data_price.py`：

```python
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from investment_assistant.data.price import get_price_history


def test_get_price_history_returns_ohlcv_columns():
    frame = pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100], "Dividends": [0]}
    )
    fake = MagicMock()
    fake.history.return_value = frame
    with patch("investment_assistant.data.price.yf.Ticker", return_value=fake) as ticker:
        result = get_price_history("NVDA", days=30)
    ticker.assert_called_once_with("NVDA")
    fake.history.assert_called_once_with(period="30d")
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_get_price_history_raises_on_empty():
    fake = MagicMock()
    fake.history.return_value = pd.DataFrame()
    with patch("investment_assistant.data.price.yf.Ticker", return_value=fake):
        with pytest.raises(ValueError):
            get_price_history("ZZZZ")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_data_price.py -q`
Expected: FAIL（`ModuleNotFoundError: investment_assistant.data.price`）

- [ ] **Step 3: 创建迁移模块** —— `investment_assistant/data/__init__.py` 写空文件；`investment_assistant/data/price.py` 内容（与根 `data/price.py` 逐字一致）：

```python
import yfinance as yf
import pandas as pd


def get_price_history(ticker: str, days: int = 90) -> pd.DataFrame:
    """Return OHLCV DataFrame for ticker over the last `days` calendar days."""
    df = yf.Ticker(ticker).history(period=f"{days}d")
    if df.empty:
        raise ValueError(f"No price data returned for {ticker}")
    return df[["Open", "High", "Low", "Close", "Volume"]]
```

- [ ] **Step 4: 切换生产惰性 import** —— `investment_assistant/tickers/trend.py:148` 与 `investment_assistant/market/service.py:89` 把 `from data.price import get_price_history` 改为：

```python
    from investment_assistant.data.price import get_price_history
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_data_price.py tests/test_ticker_trend.py tests/test_market_signal_service.py -q`
Expected: PASS

- [ ] **Step 6: 删除旧测试文件** —— `git rm tests/test_price.py`（其逻辑已迁入 `test_data_price.py`）。

- [ ] **Step 7: Commit**

```bash
git add investment_assistant/data tests/test_data_price.py investment_assistant/tickers/trend.py investment_assistant/market/service.py
git rm tests/test_price.py
git commit -m "refactor: fold data/price into investment_assistant.data.price"
```

### Task A2：迁移 `notify/`（discord + templates）进生产包

**Files:**
- Create: `investment_assistant/notify/__init__.py`, `investment_assistant/notify/discord.py`, `investment_assistant/notify/templates.py`
- Create: `tests/test_notify_discord.py`（由旧 `tests/test_discord.py` 改 import）

**Interfaces:**
- Produces: `investment_assistant.notify.discord.DiscordClient`、`DiscordChannel`（枚举 EARNINGS/SIGNALS/DAILY），以及 `investment_assistant.notify.templates` 内现有模板函数（Phase 1 复用）。

- [ ] **Step 1: 复制模块文件** —— 将根 `notify/discord.py`、`notify/templates.py` 逐字复制到 `investment_assistant/notify/` 下；新建空 `investment_assistant/notify/__init__.py`。

- [ ] **Step 2: 迁移测试并改 import** —— 复制旧 `tests/test_discord.py` 为 `tests/test_notify_discord.py`，把首行 `from notify.discord import DiscordClient, DiscordChannel` 改为：

```python
from investment_assistant.notify.discord import DiscordClient, DiscordChannel
```

- [ ] **Step 3: 运行确认通过**

Run: `python -m pytest tests/test_notify_discord.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add investment_assistant/notify tests/test_notify_discord.py
git commit -m "refactor: fold notify (discord+templates) into investment_assistant.notify"
```

### Task A3：删除旧并行代码库与根脚本

**Files (delete):** 根 `data/`、`signals/`、`notify/`、`ops/`、`vault/`、`diagnose_edgar.py`、`earnings_calendar.py`、`earnings_monitor.py`、`sec_downloader.py`、`vault_writer.py`、`scripts/test_discord.py`、`scripts/test_market.py`、`scripts/test_vcp.py`、`tests/test_market.py`、`tests/test_technicals.py`。

- [ ] **Step 1: 删除前 grep 验证生产包零依赖**

Run:
```bash
grep -rn "^from data\b\|^import data\b\|from data\.\|from signals\|import signals\|from notify\b\|import notify\b\|from vault\|import vault\|from ops\b\|import ops\b\|sec_downloader\|vault_writer" investment_assistant/
```
Expected: 无任何命中（迁移后生产包只 import `investment_assistant.data.price` / `investment_assistant.notify.*`，不匹配上式）。若有命中，先修复再继续。

- [ ] **Step 2: 执行删除**

```bash
git rm -r data signals notify ops vault scripts/test_discord.py scripts/test_market.py scripts/test_vcp.py \
  diagnose_edgar.py earnings_calendar.py earnings_monitor.py sec_downloader.py vault_writer.py \
  tests/test_market.py tests/test_technicals.py
```

- [ ] **Step 3: 全仓死引用扫描**

Run: `grep -rn "from data\.\|from signals\|from notify\b\|from vault\|from ops\b\|sec_downloader\|vault_writer\|earnings_monitor\|earnings_calendar\|daily_scan" . --include="*.py" | grep -v investment_assistant/notify | grep -v investment_assistant/data`
Expected: 无命中（`docs/` 内 markdown 不计；只看 `.py`）。

- [ ] **Step 4: 运行全测试套件**

Run: `python -m pytest -q`
Expected: PASS（全绿；不再有引用旧模块的测试）。

- [ ] **Step 5: Commit**

```bash
git commit -m "chore: delete legacy earnings-agent codebase (data/signals/notify/ops/vault + root scripts)"
```

### Task A4：文档与 `architecture.md` 对齐删除

**Files:**
- Modify: `docs/architecture.md`（该文整篇描述已删除的 earnings-agent；加置顶 deprecation banner 或替换为指向 `docs/audit-and-redesign-2026-06.md` 的真实架构）。
- Modify: `README.md`（移除对 `data/ signals/ notify/ ops/ vault/` 的目录描述）。

- [ ] **Step 1:** 在 `docs/architecture.md` 顶部加：

```markdown
> ⚠️ 已废弃（2026-06-27）：本文描述的 earnings-agent 旧代码库（data/ signals/ notify/ ops/ vault/）已删除。
> 当前生产架构见 docs/audit-and-redesign-2026-06.md 与 docs/execution-plan-2026-06.md。
```

- [ ] **Step 2:** 在 README 中删除/更新引用旧目录的小节（grep `README.md` 中 `data/`、`signals/`、`vault/`、`ops/` 段落）。

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md README.md
git commit -m "docs: mark legacy architecture deprecated after codebase deletion"
```

---

# Part B — API 架构分层（拆 API + 定时任务）

> 目标：把 860 行单体 `dashboard/server.py` 拆为 **路由表 + 服务层 + 仓储层**；把 **定时任务** 与 **长耗时 LLM 调用** 从 HTTP 请求线程中分离（后台 runner + run_id 轮询 / SSE）。重构期间用特征化测试钉住对外契约。

**当前单体结构（`investment_assistant/dashboard/server.py`，860 行）：**
- 路由：`api_response_for_path`(GET, 行 133-173)、`api_post_response_for_path`(POST, 176-215)、`api_delete_response_for_path`(DELETE, 218-228) 三条 if 链。
- 业务逻辑：约 30 个模块级函数（watchlist/ticker/strategy/market/hermes/status 各类 rows + run/fetch/persist）。
- 传输：`ApiResponse`/`StaticResponse` dataclass、`Handler`、`_authorized`(766)、`static_response_for_path`(725)、`_resolve_bind_host`(838)、`main`(854)。

### Task B0：特征化测试（重构安全网）

**Files:**
- Create: `tests/test_api_contract.py`

**Interfaces:**
- Consumes: `investment_assistant.dashboard.server`（当前模块路径，重构中保持可 import）。
- Produces: 钉住 GET/POST/DELETE 路由分发与无 DB 兜底行为的测试集；后续每个 B 任务都必须保持其全绿。

- [ ] **Step 1: 写契约测试** —— 覆盖路由分发与无 DB 行为（离线、`monkeypatch` 清除 DB 环境变量）：

```python
import importlib
import pytest

server = importlib.import_module("investment_assistant.dashboard.server")


@pytest.fixture(autouse=True)
def no_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)


def test_unknown_api_get_returns_none():
    assert server.api_response_for_path("/api/does-not-exist") is None


def test_status_get_route_resolves():
    resp = server.api_response_for_path("/api/status")
    assert resp is not None and resp.status == 200
    assert set(resp.payload.keys()) == {"database", "filings", "system"}


def test_operations_registry_shape():
    resp = server.api_response_for_path("/api/operations")
    ids = {op["id"] for op in resp.payload["operations"]}
    assert ids == {"fetch_market_signals", "sync_filings", "health_check"}


def test_watchlist_get_falls_back_to_config_without_db():
    resp = server.api_response_for_path("/api/watchlist")
    assert resp.payload["count"] >= 1
    assert all(row["source"] == "config" for row in resp.payload["rows"])


def test_post_market_fetch_requires_date():
    resp = server.api_post_response_for_path("/api/market/signals/fetch", {})
    assert resp.status == 400 and "error" in resp.payload


def test_delete_route_resolves():
    assert server.api_delete_response_for_path("/api/watchlist/NVDA") is not None
    assert server.api_delete_response_for_path("/api/nope") is None


def test_authorize_three_paths(monkeypatch):
    import base64
    monkeypatch.setattr(server, "AUTH_PASSWORD", "secret")
    monkeypatch.setattr(server, "AUTH_USER", "jianjustin")

    class H:
        def __init__(self, header):
            self.headers = {"Authorization": header} if header else {}
    good = "Basic " + base64.b64encode(b"jianjustin:secret").decode()
    bad = "Basic " + base64.b64encode(b"jianjustin:nope").decode()
    assert server.Handler._authorized.__get__(_Fake(server, good))() is True
    assert server.Handler._authorized.__get__(_Fake(server, bad))() is False


class _Fake:
    def __init__(self, mod, header):
        self.headers = {"Authorization": header}
    def get(self, *a):  # pragma: no cover
        return None
```

> 注：若 `_authorized` 直接构造 Handler 较繁，可改为先在 B4 提取 `auth.authorize(header)` 纯函数后再补齐该断言；本步至少先钉路由分发与无 DB 兜底。

- [ ] **Step 2: 运行确认通过（基线）**

Run: `python -m pytest tests/test_api_contract.py -q`
Expected: PASS（钉住当前行为）。

- [ ] **Step 3: Commit**

```bash
git add tests/test_api_contract.py
git commit -m "test: pin dashboard API routing/behavior contract before layering"
```

### Task B1：提取传输与解析助手 → `api/http.py`

**Files:**
- Create: `investment_assistant/api/__init__.py`, `investment_assistant/api/http.py`
- Modify: `investment_assistant/dashboard/server.py`（删本地定义，改为 re-import）

**Interfaces:**
- Produces: `api.http` 导出 `ApiResponse`、`StaticResponse`、解析助手 `first`、`parse_optional_date`、`parse_int`、`parse_csv`、`parse_payload_watchlist`、`parse_payload_bool`、`parse_payload_tags`，以及 send 助手 `json_body(payload, code) -> (bytes, content_type)`。

- [ ] **Step 1: 写 http 助手单测** —— `tests/test_api_http.py`：

```python
from datetime import date
from investment_assistant.api.http import ApiResponse, parse_int, parse_csv, parse_payload_bool, json_body


def test_parse_int_clamps():
    assert parse_int("999", default=10, minimum=1, maximum=100) == 100
    assert parse_int(None, default=10, minimum=1, maximum=100) == 10
    assert parse_int("abc", default=7, minimum=1, maximum=100) == 7


def test_parse_csv_upper():
    assert parse_csv("nvda, mu ,") == ["NVDA", "MU"]


def test_parse_payload_bool():
    assert parse_payload_bool("yes", default=False) is True
    assert parse_payload_bool(None, default=True) is True


def test_json_body_roundtrip():
    body, ctype = json_body({"a": 1}, 200)
    assert b'"a": 1' in body and ctype.startswith("application/json")


def test_api_response_default_status():
    assert ApiResponse({"ok": True}).status == 200
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_api_http.py -q`
Expected: FAIL（无 `investment_assistant.api.http`）。

- [ ] **Step 3: 创建 `api/http.py`** —— 把 `server.py` 的 `ApiResponse`(48-51)、`StaticResponse`(41-45) dataclass 与解析助手 `_first`(670)、`_parse_optional_date`(675)、`_parse_int`(679)、`_parse_csv`(687)、`_parse_payload_watchlist`(693)、`_parse_payload_bool`(703)、`_parse_payload_tags`(430) **原样搬入**（去掉前导下划线公开为 `first`/`parse_int`/...），并新增 send 助手：

```python
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

# first / parse_optional_date / parse_int / parse_csv /
# parse_payload_watchlist / parse_payload_bool / parse_payload_tags
# —— 由 server.py 原样搬入（公开命名）
```

- [ ] **Step 4: server.py 改为 re-import** —— 在 `server.py` 顶部加 `from investment_assistant.api.http import (ApiResponse, StaticResponse, first as _first, parse_int as _parse_int, ...)`，删除其本地重复定义，保留旧私有别名以免改动其余调用处。

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_api_http.py tests/test_api_contract.py -q`
Expected: PASS（契约不变）。

- [ ] **Step 6: Commit**

```bash
git add investment_assistant/api tests/test_api_http.py investment_assistant/dashboard/server.py
git commit -m "refactor: extract api/http transport+parse helpers"
```

### Task B2：提取服务层 → `services/`

> 把业务逻辑函数从 `server.py` 搬到 `services/` 各模块（按域拆分），`server.py` 改为从 services re-import。**行为零变化**，由 B0 契约 + 各服务新单测保证。

**Files:**
- Create: `investment_assistant/services/__init__.py` 及 `status.py` / `market.py` / `tickers.py` / `strategies.py` / `hermes.py` / `watchlist.py`
- Modify: `investment_assistant/dashboard/server.py`（删本体，re-import）
- Create: `tests/test_services_status.py`, `tests/test_services_watchlist.py`

**Interfaces（搬动映射，全部保持签名与返回形状）：**
- `services/status.py`：`status_payload`、`database_status`、`filing_status`、`filing_rows`、`operation_registry`、`system_status`（原 server.py 54-130, 717-722, 754-759 的 `_run_cmd`）。
- `services/watchlist.py`：`watchlist_rows`、`current_watchlist`、`add_watchlist_item`、`delete_watchlist_item`、`_config_watchlist_rows`（231-269）。
- `services/tickers.py`：`ticker_trend_rows`、`run_ticker_trend_scan`、`_persist_ticker_trend_snapshots`（272-299, 551-608）。
- `services/strategies.py`：`strategy_score_rows`、`strategy_input_snapshots`、`latest_strategy_market_context`、`run_strategy_score_scan`、`_persist_strategy_scores`（302-427）。
- `services/market.py`：`market_signal_rows`、`market_signal_trend`、`fetch_market_signals`、`_persist_manual_market_signal`、`_plain_signal`、`_manual_fetch_range`（440-482, 611-667）。
- `services/hermes.py`：`hermes_macro_analysis`、`run_hermes_macro_llm_analysis`、`run_decision_evidence`（485-548）。

- [ ] **Step 1: 写 status 服务单测** —— `tests/test_services_status.py`（mock `subprocess.run` 与文件系统）：

```python
from unittest.mock import patch
from investment_assistant.services import status as status_svc


def test_operation_registry_ids():
    ids = {op["id"] for op in status_svc.operation_registry()}
    assert ids == {"fetch_market_signals", "sync_filings", "health_check"}


def test_system_status_uses_systemctl(monkeypatch):
    with patch("investment_assistant.services.status.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "active"
        out = status_svc.system_status()
    assert out["postgres_service"]["ok"] is True


def test_database_status_without_url(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    assert status_svc.database_status()["ok"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_services_status.py -q`
Expected: FAIL（无 `investment_assistant.services.status`）。

- [ ] **Step 3: 建 services 各模块** —— 按上面映射，把对应函数从 `server.py` **逐字搬入**新模块，修正其内部相互调用为新模块路径（如 `services/hermes.py` 调用 `market_signal_rows` 改为 `from investment_assistant.services.market import market_signal_rows`；`run_decision_evidence` 调用 `ticker_trend_rows`/`strategy_score_rows` 同理）。所有 `connect`/`upsert_*`/`list_*` 等 DB 调用仍从 `investment_assistant.db` import（仓储层）。

- [ ] **Step 4: server.py 改为 re-import** —— `server.py` 顶部统一：

```python
from investment_assistant.services.status import status_payload, database_status, filing_status, filing_rows, operation_registry, system_status
from investment_assistant.services.watchlist import watchlist_rows, current_watchlist, add_watchlist_item, delete_watchlist_item
from investment_assistant.services.tickers import ticker_trend_rows, run_ticker_trend_scan
from investment_assistant.services.strategies import strategy_score_rows, run_strategy_score_scan
from investment_assistant.services.market import market_signal_rows, market_signal_trend, fetch_market_signals
from investment_assistant.services.hermes import hermes_macro_analysis, run_hermes_macro_llm_analysis, run_decision_evidence
```
删除 server.py 内已搬出的函数体。`api_*_response_for_path` 路由函数暂留 server.py（B3 处理）。

- [ ] **Step 5: 写 watchlist 服务单测** —— `tests/test_services_watchlist.py`：

```python
from investment_assistant.services import watchlist as wl


def test_config_fallback_without_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    rows = wl.watchlist_rows()
    assert rows and all(r["source"] == "config" for r in rows)


def test_add_requires_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    import pytest
    with pytest.raises(ValueError):
        wl.add_watchlist_item({"ticker": "NVDA"})
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_services_status.py tests/test_services_watchlist.py tests/test_api_contract.py tests/test_market_signal_admin_api.py -q`
Expected: PASS（契约 + 既有 admin API 测试不变）。

- [ ] **Step 7: Commit**

```bash
git add investment_assistant/services tests/test_services_status.py tests/test_services_watchlist.py investment_assistant/dashboard/server.py
git commit -m "refactor: extract business logic into services/ layer"
```

### Task B3：路由表 → `api/router.py` + `api/routes/*`

> 用注册表替换三条 if 链。每个 route 模块在 import 时把 `(method, matcher) -> handler` 注册进 `router.ROUTES`。

**Files:**
- Create: `investment_assistant/api/router.py`、`investment_assistant/api/routes/__init__.py` 及 `status.py`/`market.py`/`tickers.py`/`strategies.py`/`hermes.py`/`watchlist.py`
- Modify: `investment_assistant/dashboard/server.py`（路由函数改为委托 router）
- Create: `tests/test_api_router.py`

**Interfaces:**
- Produces: `router.dispatch(method: str, path: str, payload: dict | None) -> ApiResponse | None`；`router.register(method, exact=None, prefix=None)(handler)` 装饰器；handler 签名 `(path: str, query: dict, payload: dict | None) -> ApiResponse`。

- [ ] **Step 1: 写 router 单测** —— `tests/test_api_router.py`：

```python
from investment_assistant.api import routes  # noqa: F401  触发注册
from investment_assistant.api.router import dispatch


def test_dispatch_unknown_returns_none():
    assert dispatch("GET", "/api/nope", None) is None


def test_dispatch_status_get(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    resp = dispatch("GET", "/api/status", None)
    assert resp is not None and resp.status == 200


def test_dispatch_delete_prefix():
    resp = dispatch("DELETE", "/api/watchlist/NVDA", None)
    assert resp is not None


def test_dispatch_post_validation():
    resp = dispatch("POST", "/api/market/signals/fetch", {})
    assert resp.status == 400
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_api_router.py -q`
Expected: FAIL（无 router）。

- [ ] **Step 3: 实现 `api/router.py`：**

```python
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
```

- [ ] **Step 4: 实现各 route 模块** —— 例如 `api/routes/market.py`（把 server.py 三条 if 链里 market 相关分支转为注册）：

```python
from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register
from investment_assistant.services.market import market_signal_rows, market_signal_trend, fetch_market_signals
from investment_assistant.services.status import database_status


@register("GET", exact="/api/market/signals")
def _signals(path, query, payload):
    rows = market_signal_rows(query)
    return ApiResponse({"rows": rows, "count": len(rows)})


@register("GET", exact="/api/market/signals/latest")
def _latest(path, query, payload):
    return ApiResponse(database_status().get("latest_market_signal"))


@register("GET", exact="/api/market/signals/trend")
def _trend(path, query, payload):
    return ApiResponse(market_signal_trend(query))


@register("POST", exact="/api/market/signals/fetch")
def _fetch(path, query, payload):
    return ApiResponse(fetch_market_signals(payload or {}))
```
其余 `status.py`/`tickers.py`/`strategies.py`/`hermes.py`/`watchlist.py` 同法，**逐一覆盖 server.py 原三条 if 链里的每个分支**（GET：status/raw/status、health、services、watchlist、tickers/trends、strategies/scores、market/*、hermes*、filings、operations；POST：watchlist、hermes/macro-analysis/run、hermes/decision-evidence/run、market/signals/fetch、tickers/trends/scan、strategies/scores/run、hermes/agents；DELETE：watchlist/ 前缀）。`api/routes/__init__.py` 内 `from . import status, market, tickers, strategies, hermes, watchlist` 触发全部注册。

- [ ] **Step 5: server.py 路由委托 router** —— 把 `api_response_for_path`/`api_post_response_for_path`/`api_delete_response_for_path` 改写为：

```python
import investment_assistant.api.routes  # noqa: F401 触发注册
from investment_assistant.api.router import dispatch

def api_response_for_path(path):
    return dispatch("GET", path, None)
def api_post_response_for_path(path, payload):
    return dispatch("POST", path, payload)
def api_delete_response_for_path(path):
    return dispatch("DELETE", path, None)
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_api_router.py tests/test_api_contract.py tests/test_market_signal_admin_api.py tests/test_dashboard_server.py -q`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add investment_assistant/api/router.py investment_assistant/api/routes tests/test_api_router.py investment_assistant/dashboard/server.py
git commit -m "refactor: replace if-chain dispatch with route registry"
```

### Task B4：薄化 `api/server.py`（Handler/auth/static/main）

**Files:**
- Create: `investment_assistant/api/auth.py`, `investment_assistant/api/static_files.py`, `investment_assistant/api/server.py`
- Modify: `investment_assistant/dashboard/server.py` → 改为 shim
- Create: `tests/test_api_auth.py`

**Interfaces:**
- Produces: `api.auth.authorize(auth_header: str | None) -> bool`、`api.auth.resolve_bind_host() -> str`（保留 fail-closed `SystemExit`）；`api.static_files.static_response_for_path(path) -> StaticResponse | None`；`api.server.Handler`、`api.server.main()`。

- [ ] **Step 1: 写 auth 单测** —— `tests/test_api_auth.py`（覆盖三鉴权路径 + fail-closed）：

```python
import base64
import pytest
from investment_assistant.api import auth


def _basic(u, p):
    return "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()


def test_no_password_allows(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "")
    assert auth.authorize(None) is True


def test_correct_password(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "secret")
    monkeypatch.setattr(auth, "AUTH_USER", "jianjustin")
    assert auth.authorize(_basic("jianjustin", "secret")) is True
    assert auth.authorize(_basic("jianjustin", "wrong")) is False
    assert auth.authorize(None) is False


def test_public_bind_without_auth_refused(monkeypatch):
    monkeypatch.setattr(auth, "HOST", "0.0.0.0")
    monkeypatch.setattr(auth, "ALLOW_PUBLIC_BIND", True)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "")
    with pytest.raises(SystemExit):
        auth.resolve_bind_host()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_api_auth.py -q`
Expected: FAIL。

- [ ] **Step 3: 建 `api/auth.py`** —— 把 server.py 的 `HOST/PORT/AUTH_USER/AUTH_PASSWORD/ALLOW_PUBLIC_BIND`(30-37)、`_authorized` 逻辑(766-776) 提为纯函数 `authorize(header)`、`_resolve_bind_host`(838-851) → `resolve_bind_host()`，逐字保留 fail-closed 文案与 `hmac.compare_digest` 比较。

- [ ] **Step 4: 建 `api/static_files.py`** —— 搬入 `STATIC_DIR`(38) 与 `static_response_for_path`(725-751)，含 `/status` → `STATUS_PAGE_HTML`、目录穿越防护、`frontend_not_built` 503 兜底。

- [ ] **Step 5: 建 `api/server.py`** —— 薄 `Handler`：do_GET/POST/DELETE 调 `auth.authorize(self.headers.get("Authorization"))` + `router.dispatch` + `static_files`；`main()` 调 `resolve_bind_host()` 起 `ThreadingHTTPServer`。

- [ ] **Step 6: `dashboard/server.py` 改 shim：**

```python
"""Backwards-compat entry point. Implementation moved to investment_assistant.api."""
from investment_assistant.api.server import Handler, main  # noqa: F401
from investment_assistant.api.router import dispatch as _dispatch

def api_response_for_path(path):
    return _dispatch("GET", path, None)
def api_post_response_for_path(path, payload):
    return _dispatch("POST", path, payload)
def api_delete_response_for_path(path):
    return _dispatch("DELETE", path, None)

if __name__ == "__main__":
    main()
```
（systemd `ExecStart=... -m investment_assistant.dashboard.server` 因此无需改动。）

- [ ] **Step 7: 运行确认通过**

Run: `python -m pytest tests/test_api_auth.py tests/test_api_contract.py tests/test_dashboard_server.py -q`
Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add investment_assistant/api/auth.py investment_assistant/api/static_files.py investment_assistant/api/server.py tests/test_api_auth.py investment_assistant/dashboard/server.py
git commit -m "refactor: thin api/server (Handler+auth+static) with dashboard shim"
```

### Task B5：后台任务 runner + `/api/runs/{id}` + LLM 端点改异步（T1.3）

> 把 macro-LLM / decision-evidence 两个长耗时 POST 从请求线程移到后台 runner，立即返回 `run_id`；新增 `GET /api/runs/{id}` 轮询；并加 `GET /api/events`(SSE) 推送任务完成。完成时仍写现有 `run_log` jsonl。

**Files:**
- Create: `investment_assistant/tasks/__init__.py`, `investment_assistant/tasks/runner.py`
- Create: `investment_assistant/api/routes/runs.py`（含 SSE）
- Modify: `investment_assistant/services/hermes.py`（run 函数支持后台提交）
- Modify: `web/src/app/state.ts`（三个 run 函数改轮询，保持旧 UI 可用到 Part C 替换）
- Create: `tests/test_tasks_runner.py`

**Interfaces:**
- Produces: `tasks.runner.submit(kind: str, fn: Callable[[], dict]) -> str`（返回 run_id，后台线程执行）；`tasks.runner.get(run_id) -> dict | None`（`{run_id, kind, status: pending|done|error, result?, error?, created_at, finished_at?}`）；`tasks.runner.subscribe() -> queue`（SSE 用）。
- API：`POST /api/hermes/macro-analysis/run` 与 `/api/hermes/decision-evidence/run` 返回 `{run_id, status: "pending"}`；`GET /api/runs/{id}` 返回 runner 状态；`GET /api/events` 为 `text/event-stream`。

- [ ] **Step 1: 写 runner 单测** —— `tests/test_tasks_runner.py`：

```python
import time
from investment_assistant.tasks import runner


def test_submit_runs_in_background_and_completes():
    rid = runner.submit("demo", lambda: {"value": 42})
    for _ in range(50):
        rec = runner.get(rid)
        if rec and rec["status"] == "done":
            break
        time.sleep(0.02)
    assert rec["status"] == "done" and rec["result"]["value"] == 42


def test_failure_recorded_structured():
    def boom():
        raise RuntimeError("kaboom")
    rid = runner.submit("demo", boom)
    for _ in range(50):
        rec = runner.get(rid)
        if rec and rec["status"] == "error":
            break
        time.sleep(0.02)
    assert rec["status"] == "error" and "kaboom" in rec["error"]


def test_get_unknown_returns_none():
    assert runner.get("nope") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_tasks_runner.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 `tasks/runner.py`：**

```python
from __future__ import annotations
import threading
import uuid
from datetime import UTC, datetime
from queue import Queue, Full
from typing import Any, Callable

_LOCK = threading.Lock()
_RUNS: dict[str, dict[str, Any]] = {}
_SUBSCRIBERS: list[Queue] = []


def _now() -> str:
    return datetime.now(UTC).isoformat()


def submit(kind: str, fn: Callable[[], dict[str, Any]]) -> str:
    run_id = f"{kind}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    with _LOCK:
        _RUNS[run_id] = {"run_id": run_id, "kind": kind, "status": "pending", "created_at": _now()}

    def _worker() -> None:
        try:
            result = fn()
            update = {"status": "done", "result": result, "finished_at": _now()}
        except Exception as exc:  # 结构化记录而非吞错
            update = {"status": "error", "error": str(exc), "finished_at": _now()}
        with _LOCK:
            _RUNS[run_id].update(update)
        _publish({"run_id": run_id, "status": update["status"], "kind": kind})

    threading.Thread(target=_worker, name=f"run-{run_id}", daemon=True).start()
    return run_id


def get(run_id: str) -> dict[str, Any] | None:
    with _LOCK:
        rec = _RUNS.get(run_id)
        return dict(rec) if rec else None


def subscribe() -> Queue:
    q: Queue = Queue(maxsize=100)
    with _LOCK:
        _SUBSCRIBERS.append(q)
    return q


def unsubscribe(q: Queue) -> None:
    with _LOCK:
        if q in _SUBSCRIBERS:
            _SUBSCRIBERS.remove(q)


def _publish(event: dict[str, Any]) -> None:
    with _LOCK:
        subs = list(_SUBSCRIBERS)
    for q in subs:
        try:
            q.put_nowait(event)
        except Full:
            pass
```

- [ ] **Step 4: hermes 服务支持异步提交** —— 在 `services/hermes.py` 增加薄封装，把现有 `run_hermes_macro_llm_analysis`/`run_decision_evidence` 的「计算 + append_run」主体抽成 `_macro_llm_job(payload)` / `_decision_evidence_job(payload)`，并新增：

```python
from investment_assistant.tasks import runner

def submit_macro_llm(payload: dict) -> dict:
    rid = runner.submit("macro-llm", lambda: _macro_llm_job(payload))
    return {"run_id": rid, "status": "pending"}

def submit_decision_evidence(payload: dict) -> dict:
    rid = runner.submit("decision-evidence", lambda: _decision_evidence_job(payload))
    return {"run_id": rid, "status": "pending"}
```
`api/routes/hermes.py` 的两个 `/run` 端点改调 `submit_*`。

- [ ] **Step 5: 实现 `api/routes/runs.py`** —— 注册 `GET /api/runs/` 前缀 handler（解析尾段 run_id → `runner.get`，None → 404 `ApiResponse({"error":"unknown run"},404)`）。SSE `/api/events` 因需流式写出，特例在 `api/server.py` 的 `do_GET` 中拦截：`subscribe()` 后循环 `q.get()` 写 `data: {json}\n\n`，断开时 `unsubscribe`。

- [ ] **Step 6: 前端轮询过渡** —— `web/src/app/state.ts` 的 `runMacroAnalystLlm`/`runDecisionEvidence`：POST 拿 `run_id` 后轮询 `/api/runs/{id}` 直到 `status==='done'|'error'`，再取 `result.analysis`/`result.decision_evidence`。保证旧 UI 在 Part C 前仍可用。

- [ ] **Step 7: 运行确认通过**

Run: `python -m pytest tests/test_tasks_runner.py tests/test_api_contract.py tests/test_hermes_macro_analyst.py tests/test_decision_evidence.py -q`
Expected: PASS（注意：若既有测试断言 `/run` 返回完整 analysis，需更新为断言 `{run_id, status}` + 单独测 job 函数）。

- [ ] **Step 8: Commit**

```bash
git add investment_assistant/tasks investment_assistant/api/routes/runs.py investment_assistant/services/hermes.py web/src/app/state.ts tests/test_tasks_runner.py
git commit -m "feat: background task runner + /api/runs + SSE; move LLM runs off request thread"
```

### Task B6：定时任务独立入口 + systemd 对齐

> 把定时任务从 ad-hoc `ops/hermes_daily.py` 形式化到 `tasks/`，新增夜间评分任务，二者均写 `run_log`；timer 钉死 US/Eastern。

**Files:**
- Create: `investment_assistant/tasks/daily.py`, `investment_assistant/tasks/nightly_scores.py`
- Modify: `investment_assistant/ops/hermes_daily.py` → shim 到 `tasks.daily`
- Modify: `deploy/systemd/hermes-investment-daily.timer`、新增 `deploy/systemd/hermes-investment-scores.{service,timer}`
- Create: `tests/test_tasks_daily.py`

**Interfaces:**
- Produces: `tasks.daily.run(config) -> dict`（调 `hermes.daily.run_daily`，对 filing step 失败容错，结果 `append_run`）；`tasks.nightly_scores.run() -> dict`（调 `services.strategies.run_strategy_score_scan({"mode":"nightly"})` 并 `append_run`）。CLI：`python -m investment_assistant.tasks.daily`、`... .tasks.nightly_scores`。

- [ ] **Step 1: 写 daily 任务单测** —— `tests/test_tasks_daily.py`（注入 step、断言 filing 失败被容错、run_log 被写）：

```python
from unittest.mock import patch
from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import daily


def test_daily_writes_run_log_and_tolerates_filing_failure():
    cfg = AssistantConfig()
    with patch("investment_assistant.tasks.daily.append_run") as append, \
         patch("investment_assistant.hermes.daily.run_daily", return_value={"run_id": "x", "status": "success"}) as rd:
        out = daily.run(cfg)
    assert out["status"] == "success"
    append.assert_called_once()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_tasks_daily.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现 `tasks/daily.py`：**

```python
from __future__ import annotations
import argparse, json
from typing import Any
from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.hermes.daily import run_daily
from investment_assistant.hermes.run_log import append_run


def run(config: AssistantConfig, *, dry_run: bool = False) -> dict[str, Any]:
    result = run_daily(config, dry_run=dry_run)
    append_run({"type": "hermes_daily", **result})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes daily scheduled task")
    parser.add_argument("--config", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(load_config(args.config), dry_run=args.dry_run), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
```
> filing step 的 `ImportError`（缺 `filings.service`）容错：在 `hermes/daily.py` 的 `_download_filings_step` 外层或 `tasks/daily.run` 内 try/except 结构化记录为 `{"filings": {"error": ...}}`，不让整 run 崩（见 Global Constraints 已知缺陷）。

- [ ] **Step 4: 实现 `tasks/nightly_scores.py`** —— `run()` 调 `run_strategy_score_scan({"mode": "nightly"})`，`append_run({"type": "nightly_scores", ...})`；`main()` CLI。

- [ ] **Step 5: ops shim** —— `investment_assistant/ops/hermes_daily.py` 改为 `from investment_assistant.tasks.daily import main` + `if __name__=="__main__": main()`（systemd ExecStart 不变）。

- [ ] **Step 6: systemd 对齐 US/Eastern** —— `hermes-investment-daily.timer` 改：

```ini
[Timer]
OnCalendar=Mon..Fri *-*-* 08:30:00 America/New_York
Persistent=true
Unit=hermes-investment-daily.service
```
新增 `hermes-investment-scores.service`（ExecStart=`... -m investment_assistant.tasks.nightly_scores`）与 `.timer`（`OnCalendar=Mon..Fri *-*-* 18:00:00 America/New_York`）。

- [ ] **Step 7: 运行确认通过**

Run: `python -m pytest tests/test_tasks_daily.py tests/test_hermes_daily.py -q`
Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add investment_assistant/tasks/daily.py investment_assistant/tasks/nightly_scores.py investment_assistant/ops/hermes_daily.py deploy/systemd tests/test_tasks_daily.py
git commit -m "feat: dedicated tasks/ entrypoints + US/Eastern timers; run_log on scheduled runs"
```

### Task B7：全套件回归 + 后端文档

- [ ] **Step 1: 全测试**

Run: `python -m pytest -q`
Expected: PASS（全绿）。

- [ ] **Step 2:** 更新 `docs/architecture.md`（或新增 `docs/backend-layering.md`）记录 `api/ services/ tasks/` 分层与 `/api/runs`、`/api/events`、新 timer。

- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "docs: document layered API + scheduled tasks architecture"
```

---

# Part C — UI 重做（Svelte 5 + 图表 + 6 区）

> 目标：vanilla-TS 全量 `innerHTML` 重渲染 → Svelte 5 响应式；18 路由 → 6 区；接入 Lightweight Charts + ECharts；设计 token + 暗色；骨架屏 + SSE 自动刷新。后端 JSON 无需改（已在 Part B 稳定）。

**6 区信息架构（审计 §3.2）：** Dashboard / Market / Watchlist&Tickers / Strategy / Hermes / System。
**设计 token（CSS 变量）：** `--bg --surface --surface-2 --border --text --text-muted --accent --success --warn --danger`，`data-theme` 暗色，自托管 Inter + `font-variant-numeric: tabular-nums`。
**图表：** 市场时序/K 线 → Lightweight Charts；评分分布/宏观时序/热力 → ECharts。

### Task C0：Svelte 5 工具链

**Files:**
- Modify: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`
- Create: `web/svelte.config.js`, `web/vitest.config.ts`
- Create: `web/src/app.svelte`（占位）、改 `web/src/main.ts`

**Interfaces:**
- Produces: 可 `npm run build`（输出 `web/dist` 仍由 `api/static_files.py` 服务）与 `npm run test`（Vitest）的 Svelte 5 工程。

- [ ] **Step 1: 安装依赖**

```bash
cd web
npm install svelte@^5 @sveltejs/vite-plugin-svelte@^5 svelte-check @fontsource/inter \
  lightweight-charts@^4 echarts@^5
npm install -D vitest @testing-library/svelte @testing-library/jest-dom jsdom @vitest/ui
```

- [ ] **Step 2: vite.config.ts** 加 svelte 插件：

```ts
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: { host: '0.0.0.0', port: 5173 },
})
```

- [ ] **Step 3: svelte.config.js + vitest.config.ts**

```js
// svelte.config.js
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte'
export default { preprocess: vitePreprocess() }
```
```ts
// vitest.config.ts
import { defineConfig } from 'vitest/config'
import { svelte } from '@sveltejs/vite-plugin-svelte'
export default defineConfig({
  plugins: [svelte({ hot: false })],
  test: { environment: 'jsdom', globals: true, setupFiles: ['./vitest-setup.ts'] },
})
```
`web/vitest-setup.ts`：`import '@testing-library/jest-dom'`。

- [ ] **Step 4: main.ts 挂载 Svelte：**

```ts
import { mount } from 'svelte'
import App from './app.svelte'
import './styles/app.css'

mount(App, { target: document.querySelector('#app')! })
```
`app.svelte` 暂放 `<h1>Hermes</h1>` 占位。

- [ ] **Step 5: package.json scripts**

```json
"scripts": {
  "dev": "vite --host 0.0.0.0",
  "build": "svelte-check --tsconfig ./tsconfig.json && vite build",
  "preview": "vite preview --host 0.0.0.0",
  "test": "vitest run"
}
```

- [ ] **Step 6: 构建冒烟**

Run: `cd web && npm run build`
Expected: 成功生成 `web/dist/index.html`。

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/package-lock.json web/vite.config.ts web/svelte.config.js web/vitest.config.ts web/vitest-setup.ts web/tsconfig.json web/src/main.ts web/src/app.svelte web/src/styles/app.css
git commit -m "build: migrate web toolchain to Svelte 5 + Vitest"
```

### Task C1：设计 token + 暗色主题

**Files:**
- Create: `web/src/styles/tokens.css`, `web/src/lib/theme.ts`
- Modify: `web/src/styles/app.css`, `web/tailwind.config.ts`
- Create: `web/src/lib/theme.test.ts`

**Interfaces:**
- Produces: `theme.getTheme(): 'light'|'dark'`、`theme.toggleTheme(): void`（写 `document.documentElement[data-theme]` + localStorage）。CSS 变量全集见下。

- [ ] **Step 1: 写 theme 单测** —— `web/src/lib/theme.test.ts`：

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { getTheme, toggleTheme, applyTheme } from './theme'

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute('data-theme') })

describe('theme', () => {
  it('defaults to light', () => { applyTheme(); expect(getTheme()).toBe('light') })
  it('toggles and persists', () => {
    applyTheme(); toggleTheme()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npx vitest run src/lib/theme.test.ts`
Expected: FAIL（无 theme.ts）。

- [ ] **Step 3: tokens.css**（完整 token，金融涨跌红绿 + 中性阶 + elevation）：

```css
:root {
  --bg: #f6f8fa; --surface: #ffffff; --surface-2: #f0f3f6;
  --border: #d9e2ec; --text: #111827; --text-muted: #6b7280;
  --accent: #0f766e; --success: #16a34a; --warn: #b45309; --danger: #dc2626;
  --up: #16a34a; --down: #dc2626;
  --elev-1: 0 1px 2px rgba(15,23,42,.06); --elev-2: 0 14px 35px rgba(15,23,42,.08);
}
[data-theme='dark'] {
  --bg: #0b0f14; --surface: #121822; --surface-2: #1a2330;
  --border: #243040; --text: #e5e9f0; --text-muted: #94a3b8;
  --accent: #2dd4bf; --success: #22c55e; --warn: #f59e0b; --danger: #f87171;
  --up: #22c55e; --down: #f87171;
  --elev-1: 0 1px 2px rgba(0,0,0,.4); --elev-2: 0 14px 35px rgba(0,0,0,.5);
}
.tabular { font-variant-numeric: tabular-nums; }
```

- [ ] **Step 4: app.css** 顶部 `@import '@fontsource/inter';` + `@import './tokens.css';` + `@tailwind base/components/utilities;`；`body { background: var(--bg); color: var(--text); font-family: Inter, ui-sans-serif, system-ui; }`。

- [ ] **Step 5: tailwind.config.ts** colors 改引用 CSS 变量：

```ts
colors: {
  bg: 'var(--bg)', surface: 'var(--surface)', 'surface-2': 'var(--surface-2)',
  border: 'var(--border)', ink: 'var(--text)', muted: 'var(--text-muted)',
  accent: 'var(--accent)', success: 'var(--success)', warn: 'var(--warn)', danger: 'var(--danger)',
},
```
`darkMode: ['selector', '[data-theme="dark"]']`。

- [ ] **Step 6: theme.ts**

```ts
type Theme = 'light' | 'dark'
export function getTheme(): Theme {
  return (document.documentElement.getAttribute('data-theme') as Theme) ?? 'light'
}
export function applyTheme(): void {
  const saved = (localStorage.getItem('theme') as Theme) ?? 'light'
  document.documentElement.setAttribute('data-theme', saved)
}
export function toggleTheme(): void {
  const next: Theme = getTheme() === 'dark' ? 'light' : 'dark'
  document.documentElement.setAttribute('data-theme', next)
  localStorage.setItem('theme', next)
}
```

- [ ] **Step 7: 运行确认通过**

Run: `cd web && npx vitest run src/lib/theme.test.ts`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add web/src/styles web/src/lib/theme.ts web/src/lib/theme.test.ts web/tailwind.config.ts
git commit -m "feat(ui): design tokens + dark theme"
```

### Task C2：类型化 API 客户端 `lib/api.ts`

**Files:**
- Create: `web/src/lib/api.ts`, `web/src/lib/api.test.ts`

**Interfaces:**
- Produces: `api.get<T>(path)`、`api.post<T>(path, body)`、`api.del<T>(path)`，以及对每个端点的便捷函数（`getStatus/getMarketSignals/getTickerTrends/getStrategyScores/getMacroAnalysis/getHermes/getFilings/getOperations/getWatchlist/addWatchlistItem/deleteWatchlistItem/fetchMarketSignals/scanTickerTrends/runStrategyScores/runMacroLlm/runDecisionEvidence/getRun`）；run 函数返回 `{run_id, status}`，配 `pollRun(run_id)`。

- [ ] **Step 1: 写 api 单测**（mock `fetch`）—— `web/src/lib/api.test.ts`：

```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { get, post, pollRun } from './api'

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('get parses json', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })))
    expect(await get<{ ok: boolean }>('/api/status')).toEqual({ ok: true })
  })
  it('throws on non-ok', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"error":"x"}', { status: 400 })))
    await expect(post('/api/x', {})).rejects.toThrow()
  })
  it('pollRun resolves when done', async () => {
    const seq = [{ status: 'pending' }, { status: 'done', result: { v: 1 } }]
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(seq.shift()), { status: 200 })))
    const rec = await pollRun('rid', { intervalMs: 1 })
    expect(rec.status).toBe('done')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现 `lib/api.ts`**（核心 + 便捷封装）：

```ts
export async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: 'application/json' }, cache: 'no-store' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<T>
}
export async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const data = await r.json()
  if (!r.ok) throw new Error(data?.error ?? `HTTP ${r.status}`)
  return data as T
}
export async function del<T>(path: string): Promise<T> {
  const r = await fetch(path, { method: 'DELETE', headers: { Accept: 'application/json' } })
  const data = await r.json()
  if (!r.ok) throw new Error(data?.error ?? `HTTP ${r.status}`)
  return data as T
}
export interface RunRecord { run_id: string; status: 'pending' | 'done' | 'error'; result?: any; error?: string }
export async function pollRun(runId: string, opts: { intervalMs?: number; timeoutMs?: number } = {}): Promise<RunRecord> {
  const interval = opts.intervalMs ?? 1500, deadline = Date.now() + (opts.timeoutMs ?? 120000)
  for (;;) {
    const rec = await get<RunRecord>(`/api/runs/${runId}`)
    if (rec.status !== 'pending') return rec
    if (Date.now() > deadline) throw new Error('run timeout')
    await new Promise((res) => setTimeout(res, interval))
  }
}
// 便捷封装（示例）
export const getStatus = () => get('/api/status')
export const getMarketSignals = (limit = 90) => get(`/api/market/signals?limit=${limit}`)
export const runMacroLlm = (b: object) => post<{ run_id: string }>('/api/hermes/macro-analysis/run', b)
// ...其余端点同法补齐
```

- [ ] **Step 4: 运行确认通过**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "feat(ui): typed API client with run polling"
```

### Task C3：SSE store `lib/sse.ts`

**Files:**
- Create: `web/src/lib/sse.ts`, `web/src/lib/sse.test.ts`

**Interfaces:**
- Produces: `createEventStream(path='/api/events'): { subscribe }`（Svelte store，推送后台任务完成事件；底层 `EventSource`，断线自动重连）。

- [ ] **Step 1: 写单测**（mock `EventSource`）—— `web/src/lib/sse.test.ts` 断言订阅后收到 `onmessage` JSON 事件会更新 store 值。
- [ ] **Step 2:** 运行确认失败 `cd web && npx vitest run src/lib/sse.test.ts`。
- [ ] **Step 3:** 实现 `lib/sse.ts`：用 Svelte `readable` 包 `new EventSource(path)`，`onmessage` → `JSON.parse` → set；`onerror` → 关闭并 `setTimeout` 重连。
- [ ] **Step 4:** 运行确认通过。
- [ ] **Step 5: Commit** `git commit -m "feat(ui): SSE event store for auto-refresh"`。

### Task C4：图表封装组件

**Files:**
- Create: `web/src/lib/charts/LineChart.svelte`, `CandleChart.svelte`, `EChart.svelte`
- Create: `web/src/lib/charts/EChart.test.ts`

**Interfaces:**
- Produces：`LineChart`(props: `data: {time, value}[]`)、`CandleChart`(props: `data: {time,open,high,low,close}[]`) 基于 lightweight-charts；`EChart`(props: `option: EChartsOption`) 基于 echarts，随 `data-theme` 切换、`ResizeObserver` 自适应、`onDestroy` 释放。

- [ ] **Step 1: 写 EChart 单测**（mock echarts `init`/`setOption`/`dispose`）—— 断言挂载调用 `init`、props 变化调用 `setOption`、卸载调用 `dispose`。
- [ ] **Step 2:** 运行确认失败。
- [ ] **Step 3: 实现 `EChart.svelte`：**

```svelte
<script lang="ts">
  import * as echarts from 'echarts'
  import { onMount, onDestroy } from 'svelte'
  let { option }: { option: echarts.EChartsOption } = $props()
  let el: HTMLDivElement
  let chart: echarts.ECharts | undefined
  let ro: ResizeObserver | undefined
  onMount(() => {
    const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : undefined
    chart = echarts.init(el, theme)
    chart.setOption(option)
    ro = new ResizeObserver(() => chart?.resize()); ro.observe(el)
  })
  $effect(() => { chart?.setOption(option) })
  onDestroy(() => { ro?.disconnect(); chart?.dispose() })
</script>
<div bind:this={el} style="width:100%;height:320px"></div>
```

- [ ] **Step 4: 实现 `LineChart.svelte` / `CandleChart.svelte`**（lightweight-charts `createChart`，`addLineSeries`/`addCandlestickSeries`，`$effect` 更新 `setData`，`onDestroy` `remove()`，颜色取 CSS 变量 `--up`/`--down`/`--accent`）。
- [ ] **Step 5:** 运行确认通过。
- [ ] **Step 6: Commit** `git commit -m "feat(ui): chart wrappers (lightweight-charts + echarts)"`。

### Task C5：共享组件 + 应用骨架 + 路由

**Files:**
- Create: `web/src/lib/components/AppShell.svelte`, `SideNav.svelte`, `Skeleton.svelte`, `DataTable.svelte`, `Drawer.svelte`, `StatusPill.svelte`
- Create: `web/src/lib/i18n.ts`, `web/src/lib/format.ts`（从旧 `shared/format.ts` 迁逻辑）
- Modify: `web/src/app.svelte`（hash 路由 → 6 区）
- Create: `web/src/app.test.ts`

**Interfaces:**
- Produces：6 区路由 `dashboard|market|watchlist|strategy|hermes|system`，`SideNav` 细窄可折叠图标栏（替代 288px 手风琴），`AppShell` 顶栏含主题/语言切换 + SSE「最近更新」指示，`Skeleton` per-panel 骨架屏，`DataTable`（粘性表头/斑马/可排序），`Drawer` 右侧详情抽屉，`StatusPill`。

- [ ] **Step 1: 写 app 路由单测** —— `web/src/app.test.ts`（@testing-library/svelte 渲染 App，断言默认渲染 Dashboard 区标题；改 `location.hash='#/market'` 后渲染 Market 区）。mock `lib/api` 各 get 返回空壳。
- [ ] **Step 2:** 运行确认失败。
- [ ] **Step 3: 实现 6 区路由 app.svelte：**

```svelte
<script lang="ts">
  import { onMount } from 'svelte'
  import AppShell from './lib/components/AppShell.svelte'
  import Dashboard from './routes/Dashboard.svelte'
  import Market from './routes/Market.svelte'
  import Watchlist from './routes/Watchlist.svelte'
  import Strategy from './routes/Strategy.svelte'
  import Hermes from './routes/Hermes.svelte'
  import System from './routes/System.svelte'
  import { applyTheme } from './lib/theme'

  const ROUTES = { dashboard: Dashboard, market: Market, watchlist: Watchlist, strategy: Strategy, hermes: Hermes, system: System }
  let route = $state(parse())
  function parse(): keyof typeof ROUTES {
    const r = location.hash.replace(/^#\/?/, '') as keyof typeof ROUTES
    return r in ROUTES ? r : 'dashboard'
  }
  onMount(() => { applyTheme(); const h = () => (route = parse()); addEventListener('hashchange', h); return () => removeEventListener('hashchange', h) })
  const Current = $derived(ROUTES[route])
</script>
<AppShell {route}><Current /></AppShell>
```

- [ ] **Step 4: 实现共享组件**（SideNav 6 项图标 + label；AppShell 顶栏 + slot；Skeleton 动画占位；DataTable 泛型列定义 + 排序；Drawer + StatusPill；i18n 从旧 `messages.ts` 取需要的键精简，format 迁旧函数）。
- [ ] **Step 5:** 运行确认通过。
- [ ] **Step 6: Commit** `git commit -m "feat(ui): app shell, 6-zone router, shared components"`。

### Task C6：Dashboard 区（完整范例）

**Files:**
- Create: `web/src/routes/Dashboard.svelte`, `web/src/routes/Dashboard.test.ts`

**Interfaces:**
- Consumes：`getStatus`、`getMarketSignals`、`getMacroAnalysis`、`getTickerTrends`（宏观 hero + 市场信号图 + 关注热力 + KPI 条；合并旧 workbench + market-overview）。
- Produces：默认区，per-panel 骨架屏 + SSE 自动刷新。

- [ ] **Step 1: 写测试** —— 渲染 Dashboard（mock 4 个 api get），断言初始显示骨架屏、数据到达后显示宏观 hero 文案与 KPI；mock `EChart`/`LineChart` 为存根。
- [ ] **Step 2:** 运行确认失败。
- [ ] **Step 3: 实现 Dashboard.svelte** —— 用 `$state` + 每面板独立 `await` Promise（非全量 `Promise.all`），骨架屏占位；宏观 hero 取 `getMacroAnalysis().macro_state/stance_label`；市场信号图用 `LineChart`（VIX 序列）+ 状态色带；关注热力用 `EChart`（ticker attention）；KPI 条（绿/黄/红计数来自 `getMarketSignals` trend）。订阅 SSE：收到完成事件即重拉相关面板。
- [ ] **Step 4:** 运行确认通过。
- [ ] **Step 5: Commit** `git commit -m "feat(ui): Dashboard zone with skeletons + SSE refresh"`。

### Task C7：Market / Watchlist&Tickers / Strategy 三区

> 每区一组：写测试 → 失败 → 实现 → 通过 → commit（与 C6 同结构，各自独立 commit）。

**Files（每区 `.svelte` + `.test.ts`）：** `routes/Market.svelte`、`routes/Watchlist.svelte`、`routes/Strategy.svelte`。

- [ ] **Market 区** —— Consumes `getMarketSignals`、`getMarketSignals trend`、`fetchMarketSignals`(POST)。信号时序用 `CandleChart`/`LineChart` + 状态色带（复刻并升级旧 `market.ts:155-182` 手搓 SVG）；含手动 fetch 表单（沿用旧 `marketFetchForm` 字段：single/range + date/from/to）。表格用 `DataTable`。TDD 五步。
- [ ] **Watchlist & Tickers 区** —— Consumes `getWatchlist`、`addWatchlistItem`、`deleteWatchlistItem`、`getTickerTrends`、`scanTickerTrends`(POST)。`DataTable` 列表 + 右侧 `Drawer` 个股详情（均线堆叠图、RS vs SPY/QQQ 用 `LineChart`）。含 watchlist 表单 + 删除。TDD 五步。
- [ ] **Strategy 区** —— Consumes `getStrategyScores`、`runStrategyScores`(POST)。评分分布用 `EChart` 柱状（0–40/40–70/70–100 分桶）+ 证据/限制表 `DataTable`；为 Phase 3 净值曲线预留 `EChart` 容器（数据未就绪时显占位）。TDD 五步。

每区完成后单独 commit：`feat(ui): Market zone` / `feat(ui): Watchlist & Tickers zone` / `feat(ui): Strategy zone`。

### Task C8：Hermes / System 两区 + 删除旧前端

**Files:**
- Create: `routes/Hermes.svelte`(+test)、`routes/System.svelte`(+test)
- Delete: `web/src/app/`、`web/src/features/`、`web/src/shared/`、`web/src/i18n/messages.ts`（旧 vanilla 实现，迁移所需逻辑已入 `lib/`）

- [ ] **Step 1: Hermes 区** —— Consumes `getHermes`、`getMacroAnalysis`、`runMacroLlm`(POST→pollRun)、`runDecisionEvidence`(POST→pollRun)、agents CRUD。子视图：overview/agents/ideas/decision-evidence/human-gate（用内部 tab，不再是顶层路由）。decision-evidence 用结构化卡片替代旧裸对象 dump。run 按钮走 `pollRun` 显示 pending→done。TDD 五步。
- [ ] **Step 2: System 区** —— Consumes `getStatus`、`getOperations`、`getFilings`、`getServices`、`/api/raw/status`。services/operations/filings/raw 管理区，operations 走确认弹窗。TDD 五步。
- [ ] **Step 3: 删除旧前端**

```bash
git rm -r web/src/app web/src/features web/src/shared web/src/i18n web/src/styles.css 2>/dev/null
```
（确认 `lib/i18n.ts`、`lib/format.ts` 已覆盖所需；`main.ts` 不再 import 旧路径。）

- [ ] **Step 4: 构建 + 前端测试**

Run: `cd web && npm run test && npm run build`
Expected: Vitest 全绿；`web/dist` 生成成功。

- [ ] **Step 5: Commit** `git commit -m "feat(ui): Hermes & System zones; remove legacy vanilla frontend"`。

### Task C9：更新 pytest 前端契约测试 + 端到端冒烟

**Files:**
- Modify: `tests/test_dashboard_frontend_source.py`（现断言 vanilla 文件结构，会因迁移失败）

**Interfaces:**
- Consumes: 新 Svelte 文件结构。

- [ ] **Step 1: 改写前端结构断言** —— 把 `test_dashboard_frontend_source.py` 的 `expected_files` 改为新结构（断言存在）：

```python
expected_files = [
    "web/src/main.ts",
    "web/src/app.svelte",
    "web/src/lib/api.ts",
    "web/src/lib/sse.ts",
    "web/src/lib/theme.ts",
    "web/src/lib/charts/EChart.svelte",
    "web/src/routes/Dashboard.svelte",
    "web/src/routes/Market.svelte",
    "web/src/routes/Watchlist.svelte",
    "web/src/routes/Strategy.svelte",
    "web/src/routes/Hermes.svelte",
    "web/src/routes/System.svelte",
]
for filename in expected_files:
    assert Path(filename).exists(), filename
main_source = Path("web/src/main.ts").read_text(encoding="utf-8")
assert "app.svelte" in main_source
```
删除 / 替换该文件中针对旧 `navigation.ts`/`features` 的断言函数。

- [ ] **Step 2: 后端全套件**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 3: 端到端冒烟（手动）** —— `python -m investment_assistant.dashboard.server` 启动，浏览器开 `http://127.0.0.1:8787/`：六区可达、暗色切换、图表渲染真实数据、骨架屏渐进加载、触发一次 decision-evidence 看 pending→done。记录结果于 PR 描述。

- [ ] **Step 4: Commit** `git commit -m "test: update frontend source contract for Svelte structure"`。

---

## 环境准备（执行任何任务前一次性）

> 本机当前无 venv、无 Python 依赖、无 node_modules；测试命令需可跑环境。

- [ ] 创建 venv 并装依赖：
```bash
cd /Users/jianjustin/workspaces/investment-assistant
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 含 pytest/psycopg/yfinance/...
```
- [ ] 前端依赖：`cd web && npm install`
- [ ] 建立基线：`python -m pytest -q`（记录当前红/绿；注意 `tests/test_filing_service.py` 因缺 `investment_assistant.filings.service` 模块预期 import 失败 —— 这是已知前置缺陷，不在本计划修复，跑套件时可 `--ignore=tests/test_filing_service.py` 或先确认其状态）。
- [ ] 切分支：`git checkout -b feat/ui-api-cleanup`

---

## Self-Review（对照 spec）

**1. Spec 覆盖：**
- 老旧代码删除（审计 §4 / T6.4）：Part A 全覆盖（迁移 price+notify、删 data/signals/notify/ops/vault/根脚本、文档对齐）。✅
- API 架构分层（用户新增项 + 审计 §1 单体 server.py + T1.3 LLM 移出请求线程 + T6.2 调度对齐）：Part B 覆盖（http/services/router/server 分层 + 后台 runner + /api/runs + SSE + tasks/ 独立入口 + US/Eastern timer）。✅
- UI 重做（Phase 5 / 审计 §3）：Part C 覆盖（Svelte 5 + token + 暗色 + 6 区 + Lightweight Charts/ECharts + 骨架屏 + SSE）。✅
- 横切门槛：Global Constraints 逐条纳入；不动 schema（本三件套无迁移）。✅

**2. Placeholder 扫描：** 关键新代码（router、runner、theme、api、EChart、app 路由）均给完整代码；重构搬动类步骤给出「具体函数名 + 现行号 + 新模块 + 内部调用修正」而非「TBD」。C7/C8 的同构区给出每区 Consumes/Produces + 图表/组件选型 + TDD 五步骨架（非「类似 Task N」，而是逐区列明数据源与控件）。

**3. 类型/命名一致性：** 后端 `ApiResponse`/`StaticResponse`、`dispatch(method,path,payload)`、`register(method,exact=,prefix=)`、`runner.submit/get/subscribe`、`tasks.daily.run`/`nightly_scores.run` 全程一致；前端 `get/post/del/pollRun`、`getTheme/toggleTheme/applyTheme`、6 区路由键 `dashboard|market|watchlist|strategy|hermes|system` 全程一致；构建输出 `web/dist` 与后端 `static_files` 契约一致。

**已知风险（执行时留意）：** ① `test_filing_service.py` 前置失败需绕过；② B5 改 LLM 端点为异步会改既有 `test_hermes_macro_analyst.py`/`test_decision_evidence.py` 对 `/run` 返回值的断言 —— 已在 B5 Step 7 标注需同步更新；③ SSE 在 stdlib `ThreadingHTTPServer` 下需长连接特例处理（B5 Step 5）。
