# Phase 2 数据层补全 Implementation Plan（FRED 宏观 + SEC XBRL 财务 + OHLCV 落库）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐三大数据缺口——接入真实 FRED 宏观指标、SEC XBRL 结构化财务 + filings 元数据落库、OHLCV 行情落库 + 重试/退避/缓存/新鲜度守卫——使「宏观」不再是 SPY+VIX 换皮、财报不再只是 HTML、行情不再是单点重算。

**Architecture:** 新增 `data/http.py` 统一重试退避；`data/fred.py` 采集宏观→ `macro_indicators` 表→喂入 `_classify_macro_state`；`data/sec.py` 抽 XBRL companyconcept→ `fundamentals` 表 + `filings/service.py` 落 `filings` 元数据（顺带修复 `daily.py` 当前坏掉的 import）；`data/price.py` 升级为「DB 优先缓存 + 重试 + 备用源 + 落 `price_bars`」，并把 `signal_date` 改取实际最新 bar 日期。

**Tech Stack:** Python 3.11、requests、yfinance、psycopg3、PostgreSQL 16、pytest。外部源：FRED API（`FRED_API_KEY`）、SEC EDGAR XBRL（`SEC_USER_AGENT`）、yfinance + 可选付费备用源。

## Global Constraints

- **迁移编号已顺延（2026-06-29）**：`006/007` 已被 `scheduled-ingestion-discord` 计划占用（`006_job_reports` / `007_scheduled_jobs`），本计划迁移整体 +2 顺延为 **`008_macro_indicators` / `009_fundamentals` / `010_filings` / `011_price_bars`**。下文正文中的 006-009 引用均应按此读作 008-011。**此外，本计划 Task 1（`data/http.py` 共享重试助手）已由 `scheduled-ingestion-discord` 工作提前实现并通过测试，可直接跳过**（见 `investment_assistant/data/http.py`、`docs/scheduling-and-notifications.md`）。
- **前置依赖**：本计划动 schema，**必须先完成 T6.1**（`docs/superpowers/plans/2026-06-27-migration-versioning-fk-pool.md`：版本化迁移 runner + 连接池）。本计划迁移文件从 **008** 起编号（005 已被 T6.1 的 FK 占用，006/007 已被定时采集占用）：`008_macro_indicators` / `009_fundamentals` / `010_filings` / `011_price_bars`。
- **每个 PR**：新增/改动逻辑有单测；外部调用（FRED/SEC/yfinance）**全部 mock**，离线可跑；触碰 schema 必带迁移文件，迁移用 `CREATE TABLE IF NOT EXISTS` 幂等。
- **不引入新的裸 `except Exception` 吞错**；外部失败结构化上报（沿用 deepseek_client 的「分类异常 + 退避重试 + 结构化 status」模式，见 `hermes/deepseek_client.py:86-112`）。
- **优雅降级**：FRED 无 `FRED_API_KEY` / SEC 无 `SEC_USER_AGENT` 时返回禁用态（`{"ok": False, ...}` / 空结果），**不崩溃**——与 `_classify_macro_state` 现有「无数据回退规则版」一致。
- **配置已就绪（勿重复定义）**：`config.py` 已有 `MacroConfig`（`fred_series=[DGS10,DGS2,FEDFUNDS,CPIAUCSL,UNRATE,BAMLH0A0HYM2]`, `lookback_days=400`）、`FundamentalsConfig`（`concepts=[Revenues,NetIncomeLoss,EarningsPerShareDiluted]`, `units="USD"`）、`PriceConfig`（`primary="yfinance"`, `history_days=400`, `max_retries=3`, `backoff_seconds=1.0`）、`FilingsConfig`（`forms`, `lookback_years`, `output_dir`）。
- **env 约定**：`FRED_API_KEY`、`SEC_USER_AGENT`（格式 `Name email@example.com`）；健康检查 `dashboard/health.py:177,215` 已按此约定探活。
- **顺带修复**：`investment_assistant/filings/service.py` 当前不存在，导致 `hermes/daily.py:61` import 失败、`tests/test_filing_service.py` 收集失败。Task 9 实现它以满足**既有** `test_filing_service.py` 契约。
- **分支**：从 `main` 切 `feat/phase2-data-layer`；不主动 push；提交结尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

---

## File Structure

```
investment_assistant/
  data/
    http.py        # 新：requests 重试/退避 JSON 助手（FRED+SEC 复用）
    fred.py        # 新：FRED 宏观采集
    sec.py         # 新：SEC XBRL companyconcept 抽取 + CIK 缓存
    macro.py       # 新：从 macro_indicators 派生宏观特征
    price.py       # 改：重试+DB缓存+备用源+落 price_bars（T6.1 已迁入此路径）
  filings/
    __init__.py    # 新
    service.py     # 新：download_configured_filings（修复 daily import）+ 落 filings 元数据
  hermes/macro_analyst.py   # 改：analyze_macro_environment 接 macro_features 叠加
  market/service.py         # 改：signal_date 取最新 bar 日期
  tickers/trend.py          # 改：滚动 SMA + signal_date 取最新 bar
  db.py          # 改：+ macro/fundamentals/filing/price_bars 仓储函数
migrations/
  008_macro_indicators.sql 009_fundamentals.sql 010_filings.sql 011_price_bars.sql
tests/
  test_data_http.py test_fred.py test_macro_repository.py test_macro_features.py
  test_sec.py test_fundamentals_repository.py test_filing_service.py(已存在,需通过)
  test_price_reliability.py test_price_bars_repository.py test_freshness_guard.py
  test_db_sql.py(追加 008-011 断言)
```

---

### Task 1：共享 HTTP 重试助手 `data/http.py`

> FRED 与 SEC 都走 requests GET JSON；统一重试/退避/超时/结构化错误，避免各写一遍（DRY），模式对齐 deepseek_client。

**Files:**
- Create: `investment_assistant/data/http.py`
- Create: `tests/test_data_http.py`

**Interfaces:**
- Produces: `data.http.get_json(url, *, params=None, headers=None, timeout=30, max_retries=3, backoff_seconds=1.0) -> tuple[dict | None, dict]`——返回 `(payload | None, status)`，`status={"ok": bool, "error": str|None, "status_code": int|None}`；429/5xx 指数退避重试，4xx（非 429）立即结构化失败。

- [ ] **Step 1: 写测试**（mock `requests.get`）—— `tests/test_data_http.py`：

```python
from unittest.mock import MagicMock, patch
from investment_assistant.data import http


def _resp(status_code, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.text = "body"
    return r


def test_get_json_success():
    with patch("investment_assistant.data.http.requests.get", return_value=_resp(200, {"a": 1})):
        payload, status = http.get_json("http://x")
    assert payload == {"a": 1} and status["ok"] is True


def test_get_json_retries_on_500_then_succeeds():
    seq = [_resp(500), _resp(200, {"ok": 1})]
    with patch("investment_assistant.data.http.requests.get", side_effect=seq), \
         patch("investment_assistant.data.http.time.sleep"):
        payload, status = http.get_json("http://x", max_retries=2)
    assert payload == {"ok": 1} and status["ok"] is True


def test_get_json_4xx_fails_fast():
    with patch("investment_assistant.data.http.requests.get", return_value=_resp(404)) as g, \
         patch("investment_assistant.data.http.time.sleep"):
        payload, status = http.get_json("http://x", max_retries=3)
    assert payload is None and status["status_code"] == 404
    assert g.call_count == 1  # 4xx 不重试
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_data_http.py -q`
Expected: FAIL（无 `investment_assistant.data.http`）。

- [ ] **Step 3: 实现 `data/http.py`：**

```python
from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)
_RETRYABLE = {429, 500, 502, 503, 504}


def _backoff(attempt: int, base: float) -> float:
    return min(base * (2 ** attempt), 30.0)


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    last: dict[str, Any] = {"ok": False, "error": "unknown", "status_code": None}
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last = {"ok": False, "error": f"network: {exc}", "status_code": None}
            logger.warning("http get network error (attempt %s): %s", attempt + 1, exc)
            if attempt < max_retries:
                time.sleep(_backoff(attempt, backoff_seconds))
                continue
            return None, last
        if resp.status_code == 200:
            try:
                return resp.json(), {"ok": True, "error": None, "status_code": 200}
            except ValueError as exc:
                return None, {"ok": False, "error": f"bad json: {exc}", "status_code": 200}
        last = {"ok": False, "error": f"http {resp.status_code}: {resp.text[:300]}", "status_code": resp.status_code}
        logger.warning("http get error (attempt %s): %s", attempt + 1, last["error"])
        if resp.status_code in _RETRYABLE and attempt < max_retries:
            time.sleep(_backoff(attempt, backoff_seconds))
            continue
        return None, last
    return None, last
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_data_http.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/data/http.py tests/test_data_http.py
git commit -m "feat(data): shared requests retry/backoff json helper"
```

---

## T2.1 — FRED 宏观采集

### Task 2：迁移 `008_macro_indicators.sql`

**Files:**
- Create: `migrations/008_macro_indicators.sql`
- Modify: `tests/test_db_sql.py`

- [ ] **Step 1: 写迁移断言** —— 追加到 `tests/test_db_sql.py`：

```python
def test_macro_indicators_migration():
    sql = Path("migrations/008_macro_indicators.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS macro_indicators" in sql
    assert "series_id TEXT NOT NULL" in sql
    assert "date DATE NOT NULL" in sql
    assert "value NUMERIC" in sql
    assert "PRIMARY KEY (series_id, date)" in sql
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_sql.py::test_macro_indicators_migration -q`
Expected: FAIL

- [ ] **Step 3: 写迁移 `migrations/008_macro_indicators.sql`：**

```sql
CREATE TABLE IF NOT EXISTS macro_indicators (
  series_id TEXT NOT NULL,
  date DATE NOT NULL,
  value NUMERIC(18,6),
  source TEXT NOT NULL DEFAULT 'fred',
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (series_id, date)
);

CREATE INDEX IF NOT EXISTS idx_macro_indicators_series_date
  ON macro_indicators (series_id, date DESC);
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_db_sql.py -q`（PASS）
```bash
git add migrations/008_macro_indicators.sql tests/test_db_sql.py
git commit -m "feat(db): macro_indicators migration (008)"
```

### Task 3：FRED 采集器 `data/fred.py`

**Files:**
- Create: `investment_assistant/data/fred.py`
- Create: `tests/test_fred.py`

**Interfaces:**
- Consumes: `data.http.get_json`、`config.MacroConfig`。
- Produces: `data.fred.fetch_series(series_id, *, api_key, lookback_days=400, getter=http.get_json) -> tuple[list[dict], dict]`（`[{"date": "YYYY-MM-DD", "value": float|None}]` + status）；`data.fred.fetch_configured(macro_cfg, *, api_key=None, getter=http.get_json) -> dict`（`{"ok": bool, "series": {series_id: rows}, "errors": {...}}`，无 key 时 `{"ok": False, "error": "FRED_API_KEY not configured", "series": {}}`）。

- [ ] **Step 1: 写测试**（mock getter）—— `tests/test_fred.py`：

```python
from investment_assistant.config import MacroConfig
from investment_assistant.data import fred


def fake_getter(payload):
    def _getter(url, **kw):
        return payload, {"ok": True, "error": None, "status_code": 200}
    return _getter


def test_fetch_series_parses_observations():
    payload = {"observations": [
        {"date": "2026-06-01", "value": "4.25"},
        {"date": "2026-06-02", "value": "."},  # FRED 用 "." 表示缺值
    ]}
    rows, status = fred.fetch_series("DGS10", api_key="k", getter=fake_getter(payload))
    assert status["ok"] is True
    assert rows[0] == {"date": "2026-06-01", "value": 4.25}
    assert rows[1]["value"] is None


def test_fetch_configured_without_key_degrades():
    out = fred.fetch_configured(MacroConfig(), api_key=None)
    assert out["ok"] is False and out["series"] == {}
    assert "FRED_API_KEY" in out["error"]


def test_fetch_configured_collects_all_series():
    payload = {"observations": [{"date": "2026-06-01", "value": "1.0"}]}
    out = fred.fetch_configured(MacroConfig(fred_series=["DGS10", "DGS2"]), api_key="k", getter=fake_getter(payload))
    assert out["ok"] is True
    assert set(out["series"]) == {"DGS10", "DGS2"}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_fred.py -q`
Expected: FAIL

- [ ] **Step 3: 实现 `data/fred.py`：**

```python
from __future__ import annotations

import os
from typing import Any, Callable

from investment_assistant.config import MacroConfig
from investment_assistant.data import http

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
Getter = Callable[..., tuple[dict[str, Any] | None, dict[str, Any]]]


def fetch_series(
    series_id: str,
    *,
    api_key: str,
    lookback_days: int = 400,
    getter: Getter = http.get_json,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
    payload, status = getter(FRED_OBSERVATIONS_URL, params=params)
    if not status["ok"] or not payload:
        return [], status
    rows = []
    for obs in payload.get("observations", []):
        raw = obs.get("value")
        value = None if raw in (None, ".", "") else _to_float(raw)
        rows.append({"date": obs.get("date"), "value": value})
    return rows[-lookback_days:], status


def fetch_configured(
    macro_cfg: MacroConfig,
    *,
    api_key: str | None = None,
    getter: Getter = http.get_json,
) -> dict[str, Any]:
    key = api_key if api_key is not None else os.environ.get("FRED_API_KEY")
    if not key:
        return {"ok": False, "error": "FRED_API_KEY not configured", "series": {}, "errors": {}}
    series: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for series_id in macro_cfg.fred_series:
        rows, status = fetch_series(series_id, api_key=key, lookback_days=macro_cfg.lookback_days, getter=getter)
        if status["ok"]:
            series[series_id] = rows
        else:
            errors[series_id] = status["error"]
    return {"ok": len(series) > 0, "error": None, "series": series, "errors": errors}


def _to_float(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_fred.py -q`（PASS）
```bash
git add investment_assistant/data/fred.py tests/test_fred.py
git commit -m "feat(data): FRED macro series collector with graceful degrade"
```

### Task 4：宏观仓储 `upsert_macro_indicators` / `latest_macro_indicators`

**Files:**
- Modify: `investment_assistant/db.py`
- Create: `tests/test_macro_repository.py`

**Interfaces:**
- Produces: `db.upsert_macro_indicators(conn, series_id: str, rows: list[dict], *, source="fred") -> int`（返回写入条数，`ON CONFLICT (series_id, date)` upsert）；`db.latest_macro_indicators(conn, series_ids: list[str]) -> dict[str, dict]`（每序列取最新一条 `{series_id: {"date","value"}}`）。

- [ ] **Step 1: 写测试**（Fake conn 录 SQL）—— `tests/test_macro_repository.py`：

```python
from investment_assistant import db


class FakeCursor:
    def __init__(self, store): self.store = store
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.store.append((sql, params))
    def executemany(self, sql, seq): self.store.append((sql, list(seq)))
    def fetchall(self): return [("DGS10", "2026-06-02", 4.3)]


class FakeConn:
    def __init__(self): self.store = []; self.commits = 0
    def cursor(self): return FakeCursor(self.store)
    def commit(self): self.commits += 1


def test_upsert_macro_indicators_skips_empty():
    conn = FakeConn()
    assert db.upsert_macro_indicators(conn, "DGS10", []) == 0


def test_upsert_macro_indicators_writes_rows():
    conn = FakeConn()
    n = db.upsert_macro_indicators(conn, "DGS10", [{"date": "2026-06-01", "value": 4.2}])
    assert n == 1 and conn.commits == 1
    assert any("INSERT INTO macro_indicators" in sql for sql, _ in conn.store)


def test_latest_macro_indicators_returns_map():
    conn = FakeConn()
    out = db.latest_macro_indicators(conn, ["DGS10"])
    assert out["DGS10"]["value"] == 4.3
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_macro_repository.py -q`
Expected: FAIL

- [ ] **Step 3: 在 `db.py` 末尾追加：**

```python
def upsert_macro_indicators(conn, series_id: str, rows: list[dict[str, Any]], *, source: str = "fred") -> int:
    valid = [r for r in rows if r.get("date") is not None]
    if not valid:
        return 0
    with conn.cursor() as cur:
        for row in valid:
            cur.execute(
                """
                INSERT INTO macro_indicators (series_id, date, value, source)
                VALUES (%(series_id)s, %(date)s, %(value)s, %(source)s)
                ON CONFLICT (series_id, date) DO UPDATE SET
                  value = EXCLUDED.value,
                  source = EXCLUDED.source,
                  fetched_at = now()
                """,
                {"series_id": series_id, "date": row["date"], "value": row.get("value"), "source": source},
            )
    conn.commit()
    return len(valid)


def latest_macro_indicators(conn, series_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not series_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (series_id) series_id, date, value
            FROM macro_indicators
            WHERE series_id = ANY(%(ids)s)
            ORDER BY series_id, date DESC
            """,
            {"ids": list(series_ids)},
        )
        rows = cur.fetchall()
    return {row[0]: {"date": str(row[1]), "value": float(row[2]) if row[2] is not None else None} for row in rows}
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_macro_repository.py -q`（PASS）
```bash
git add investment_assistant/db.py tests/test_macro_repository.py
git commit -m "feat(db): macro_indicators upsert/read repository"
```

### Task 5：宏观特征派生 + 接入分类

> 从 `macro_indicators` 派生真实信号（2s10s 倒挂、HY OAS 走阔、Fed Funds 高位），叠加到 `_classify_macro_state`，取代纯 SPY+VIX 推断；表为空时回退原规则。

**Files:**
- Create: `investment_assistant/data/macro.py`
- Modify: `investment_assistant/hermes/macro_analyst.py`
- Create: `tests/test_macro_features.py`

**Interfaces:**
- Consumes: `db.latest_macro_indicators`。
- Produces: `data.macro.build_macro_features(latest: dict[str, dict]) -> dict`（`{"two_s_ten_s": float|None, "hy_oas": float|None, "fed_funds": float|None, "cpi": float|None, "unemployment": float|None, "available": bool}`）；`data.macro.apply_macro_overlay(base_state: str, features: dict) -> tuple[str, list[str]]`（在有数据且出现宏观压力时把 state 下调到 `defense`/`cautious`，返回 `(state, reasons)`）。`macro_analyst.analyze_macro_environment(..., macro_features: dict | None = None)` 新增可选参数。

- [ ] **Step 1: 写测试** —— `tests/test_macro_features.py`：

```python
from investment_assistant.data import macro


def test_build_features_computes_2s10s():
    latest = {"DGS10": {"value": 4.0}, "DGS2": {"value": 4.5}, "BAMLH0A0HYM2": {"value": 3.0}}
    f = macro.build_macro_features(latest)
    assert f["two_s_ten_s"] == -0.5  # 倒挂
    assert f["available"] is True


def test_overlay_downgrades_on_inversion_and_wide_credit():
    f = {"two_s_ten_s": -0.5, "hy_oas": 6.0, "fed_funds": 5.0, "cpi": None, "unemployment": None, "available": True}
    state, reasons = macro.apply_macro_overlay("offense", f)
    assert state == "defense"
    assert reasons


def test_overlay_noop_when_unavailable():
    f = {"available": False}
    state, reasons = macro.apply_macro_overlay("offense", f)
    assert state == "offense" and reasons == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_macro_features.py -q`
Expected: FAIL

- [ ] **Step 3: 实现 `data/macro.py`：**

```python
from __future__ import annotations

from typing import Any

# 阈值（后续 Phase 3 可移入 config）
HY_OAS_STRESS = 5.0       # 高收益债利差 > 5% 视为信用压力
FED_FUNDS_RESTRICTIVE = 4.5


def build_macro_features(latest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def val(series_id: str) -> float | None:
        entry = latest.get(series_id)
        return entry.get("value") if entry else None

    dgs10, dgs2 = val("DGS10"), val("DGS2")
    two_s_ten_s = (dgs10 - dgs2) if (dgs10 is not None and dgs2 is not None) else None
    features = {
        "two_s_ten_s": two_s_ten_s,
        "hy_oas": val("BAMLH0A0HYM2"),
        "fed_funds": val("FEDFUNDS"),
        "cpi": val("CPIAUCSL"),
        "unemployment": val("UNRATE"),
    }
    features["available"] = any(v is not None for v in features.values())
    return features


def apply_macro_overlay(base_state: str, features: dict[str, Any]) -> tuple[str, list[str]]:
    if not features.get("available"):
        return base_state, []
    reasons: list[str] = []
    stress = False
    if features.get("two_s_ten_s") is not None and features["two_s_ten_s"] < 0:
        reasons.append(f"收益率曲线倒挂（2s10s={features['two_s_ten_s']:.2f}）。")
        stress = True
    if features.get("hy_oas") is not None and features["hy_oas"] >= HY_OAS_STRESS:
        reasons.append(f"高收益债利差走阔至 {features['hy_oas']:.2f}%，信用风险上升。")
        stress = True
    if features.get("fed_funds") is not None and features["fed_funds"] >= FED_FUNDS_RESTRICTIVE:
        reasons.append(f"联邦基金利率处于限制性水平 {features['fed_funds']:.2f}%。")
    if stress:
        return "defense", reasons
    if reasons and base_state == "offense":
        return "cautious", reasons
    return base_state, reasons
```

- [ ] **Step 4: 接入 `macro_analyst.analyze_macro_environment`** —— 在签名加 `macro_features: dict[str, Any] | None = None`；在算出 `macro_state` 后（`macro_analyst.py:46` 之后）叠加：

```python
    from investment_assistant.data.macro import apply_macro_overlay  # 顶部 import 亦可
    macro_reasons: list[str] = []
    if macro_features:
        macro_state, macro_reasons = apply_macro_overlay(macro_state, macro_features)
    stance_label = _STATE_LABELS[macro_state]
```
并把 `macro_reasons` 并入结果（如 `result["macro_indicator_signals"] = macro_reasons`）。调用方（dashboard 的 `hermes_macro_analysis` / 定时任务）在有 DB 时传 `macro_features=build_macro_features(latest_macro_indicators(conn, cfg.macro.fred_series))`。

- [ ] **Step 5: 写接入测试** —— 追加到 `tests/test_macro_features.py`：

```python
from investment_assistant.hermes.macro_analyst import analyze_macro_environment


def test_analyze_overlay_downgrades_to_defense():
    rows = [{"signal_date": "2026-06-01", "market_status": "green", "spy_above_200ma": True, "vix_close": 15}]
    features = {"two_s_ten_s": -0.4, "hy_oas": 6.0, "available": True}
    result = analyze_macro_environment(rows, macro_features=features)
    assert result["macro_state"] == "defense"
    assert result["macro_indicator_signals"]
```

- [ ] **Step 6: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_macro_features.py tests/test_hermes_macro_analyst.py -q`（PASS）
```bash
git add investment_assistant/data/macro.py investment_assistant/hermes/macro_analyst.py tests/test_macro_features.py
git commit -m "feat(macro): derive FRED features and overlay into macro classification"
```

---

## T2.2 — SEC XBRL 结构化财务 + filings

### Task 6：迁移 `009_fundamentals.sql` + `010_filings.sql`

**Files:**
- Create: `migrations/009_fundamentals.sql`, `migrations/010_filings.sql`
- Modify: `tests/test_db_sql.py`

- [ ] **Step 1: 写断言** —— 追加到 `tests/test_db_sql.py`：

```python
def test_fundamentals_migration():
    sql = Path("migrations/009_fundamentals.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS fundamentals" in sql
    assert "ticker TEXT NOT NULL" in sql
    assert "concept TEXT NOT NULL" in sql
    assert "fiscal_period TEXT" in sql
    assert "value NUMERIC" in sql
    assert "UNIQUE (ticker, concept, fiscal_period, unit)" in sql


def test_filings_migration():
    sql = Path("migrations/010_filings.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS filings" in sql
    assert "ticker TEXT NOT NULL" in sql
    assert "form TEXT NOT NULL" in sql
    assert "accession_no TEXT NOT NULL UNIQUE" in sql
    assert "filed_at" in sql
```

- [ ] **Step 2: 运行确认失败** —— `python -m pytest tests/test_db_sql.py -k "fundamentals_migration or filings_migration" -q`（FAIL）。

- [ ] **Step 3: 写 `migrations/009_fundamentals.sql`：**

```sql
CREATE TABLE IF NOT EXISTS fundamentals (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  cik TEXT,
  concept TEXT NOT NULL,
  fiscal_period TEXT,
  fiscal_year INTEGER,
  period_end DATE,
  value NUMERIC(28,6),
  unit TEXT NOT NULL DEFAULT 'USD',
  form TEXT,
  source TEXT NOT NULL DEFAULT 'sec_xbrl',
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ticker, concept, fiscal_period, unit)
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker_concept
  ON fundamentals (ticker, concept, period_end DESC);
```

- [ ] **Step 4: 写 `migrations/010_filings.sql`：**

```sql
CREATE TABLE IF NOT EXISTS filings (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  cik TEXT,
  form TEXT NOT NULL,
  accession_no TEXT NOT NULL UNIQUE,
  filed_at DATE,
  primary_doc TEXT,
  local_path TEXT,
  source TEXT NOT NULL DEFAULT 'sec_edgar',
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_filings_ticker_filed
  ON filings (ticker, filed_at DESC);
```

- [ ] **Step 5: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_db_sql.py -q`（PASS）
```bash
git add migrations/009_fundamentals.sql migrations/010_filings.sql tests/test_db_sql.py
git commit -m "feat(db): fundamentals + filings migrations (009/010)"
```

### Task 7：SEC XBRL 抽取 `data/sec.py`

> 用 `companyconcept` API 抽指定 concept（营收/净利/EPS）季度值；CIK 映射用 `company_tickers.json` 落盘缓存；带 `SEC_USER_AGENT` 头 + 重试。

**Files:**
- Create: `investment_assistant/data/sec.py`
- Create: `tests/test_sec.py`

**Interfaces:**
- Consumes: `data.http.get_json`、`config.FundamentalsConfig`。
- Produces: `data.sec.resolve_cik(ticker, *, cache_dir, getter=http.get_json) -> str | None`（10 位零填充 CIK；落盘缓存 `company_tickers.json`）；`data.sec.fetch_concept(cik, concept, *, unit="USD", getter=http.get_json) -> tuple[list[dict], dict]`（`[{"fiscal_period","fiscal_year","period_end","value","form"}]`）；`data.sec.extract_fundamentals(ticker, fundamentals_cfg, *, cache_dir, getter=http.get_json) -> dict`（`{"ok","ticker","cik","rows":[...],"errors":{}}`，无 `SEC_USER_AGENT` 时仍可跑但 UA 用默认；CIK 解析失败结构化返回）。

- [ ] **Step 1: 写测试** —— `tests/test_sec.py`：

```python
from investment_assistant.config import FundamentalsConfig
from investment_assistant.data import sec


def getter_for(mapping):
    def _getter(url, **kw):
        for key, payload in mapping.items():
            if key in url:
                return payload, {"ok": True, "error": None, "status_code": 200}
        return None, {"ok": False, "error": "404", "status_code": 404}
    return _getter


def test_resolve_cik_pads_to_10(tmp_path):
    tickers_json = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}
    getter = getter_for({"company_tickers.json": tickers_json})
    cik = sec.resolve_cik("AAPL", cache_dir=tmp_path, getter=getter)
    assert cik == "0000320193"


def test_fetch_concept_parses_units():
    payload = {"units": {"USD": [
        {"fp": "Q1", "fy": 2026, "end": "2026-03-31", "val": 1000, "form": "10-Q"},
    ]}}
    rows, status = sec.fetch_concept("0000320193", "Revenues", getter=getter_for({"companyconcept": payload}))
    assert status["ok"] and rows[0]["value"] == 1000 and rows[0]["fiscal_period"] == "Q1"


def test_extract_fundamentals_unknown_ticker(tmp_path):
    getter = getter_for({"company_tickers.json": {"0": {"cik_str": 1, "ticker": "AAPL", "title": "A"}}})
    out = sec.extract_fundamentals("ZZZZ", FundamentalsConfig(), cache_dir=tmp_path, getter=getter)
    assert out["ok"] is False and "CIK" in out["error"]
```

- [ ] **Step 2: 运行确认失败** —— `python -m pytest tests/test_sec.py -q`（FAIL）。

- [ ] **Step 3: 实现 `data/sec.py`：**

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from investment_assistant.config import FundamentalsConfig
from investment_assistant.data import http

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
Getter = Callable[..., tuple[dict[str, Any] | None, dict[str, Any]]]


def _headers() -> dict[str, str]:
    return {"User-Agent": os.environ.get("SEC_USER_AGENT", "investment-assistant contact@example.com")}


def resolve_cik(ticker: str, *, cache_dir: Path, getter: Getter = http.get_json) -> str | None:
    cache = Path(cache_dir) / "company_tickers.json"
    data: dict[str, Any] | None = None
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        data, status = getter(COMPANY_TICKERS_URL, headers=_headers())
        if status["ok"] and data:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
    if not data:
        return None
    target = ticker.strip().upper()
    for entry in data.values():
        if str(entry.get("ticker", "")).upper() == target:
            return f"{int(entry['cik_str']):010d}"
    return None


def fetch_concept(cik: str, concept: str, *, unit: str = "USD", getter: Getter = http.get_json) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = COMPANY_CONCEPT_URL.format(cik=cik, concept=concept)
    payload, status = getter(url, headers=_headers())
    if not status["ok"] or not payload:
        return [], status
    rows = []
    for item in payload.get("units", {}).get(unit, []):
        rows.append({
            "fiscal_period": item.get("fp"),
            "fiscal_year": item.get("fy"),
            "period_end": item.get("end"),
            "value": item.get("val"),
            "form": item.get("form"),
        })
    return rows, status


def extract_fundamentals(
    ticker: str,
    fundamentals_cfg: FundamentalsConfig,
    *,
    cache_dir: Path,
    getter: Getter = http.get_json,
) -> dict[str, Any]:
    cik = resolve_cik(ticker, cache_dir=cache_dir, getter=getter)
    if not cik:
        return {"ok": False, "error": f"CIK not found for {ticker}", "ticker": ticker, "cik": None, "rows": [], "errors": {}}
    all_rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for concept in fundamentals_cfg.concepts:
        rows, status = fetch_concept(cik, concept, unit=fundamentals_cfg.units, getter=getter)
        if status["ok"]:
            for row in rows:
                all_rows.append({**row, "ticker": ticker.upper(), "cik": cik, "concept": concept, "unit": fundamentals_cfg.units})
        else:
            errors[concept] = status["error"]
    return {"ok": len(all_rows) > 0, "error": None, "ticker": ticker.upper(), "cik": cik, "rows": all_rows, "errors": errors}
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_sec.py -q`（PASS）
```bash
git add investment_assistant/data/sec.py tests/test_sec.py
git commit -m "feat(data): SEC XBRL companyconcept extractor + CIK cache"
```

### Task 8：财务/filings 仓储 `upsert_fundamentals` / `upsert_filing`

**Files:**
- Modify: `investment_assistant/db.py`
- Create: `tests/test_fundamentals_repository.py`

**Interfaces:**
- Produces: `db.upsert_fundamentals(conn, rows: list[dict]) -> int`（`ON CONFLICT (ticker, concept, fiscal_period, unit)` upsert）；`db.upsert_filing(conn, filing: dict) -> dict`（`ON CONFLICT (accession_no)` upsert，返回行）。

- [ ] **Step 1: 写测试**（复用 Fake conn 模式）—— `tests/test_fundamentals_repository.py`：

```python
from investment_assistant import db


class FakeCursor:
    def __init__(self, store): self.store = store
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.store.append((sql, params))
    def fetchone(self): return ("NVDA", "10-Q", "acc-1")


class FakeConn:
    def __init__(self): self.store = []; self.commits = 0
    def cursor(self): return FakeCursor(self.store)
    def commit(self): self.commits += 1


def test_upsert_fundamentals_counts():
    conn = FakeConn()
    rows = [{"ticker": "NVDA", "concept": "Revenues", "fiscal_period": "Q1", "fiscal_year": 2026,
             "period_end": "2026-03-31", "value": 1000, "unit": "USD", "form": "10-Q", "cik": "x"}]
    assert db.upsert_fundamentals(conn, rows) == 1 and conn.commits == 1


def test_upsert_filing_returns_row():
    conn = FakeConn()
    out = db.upsert_filing(conn, {"ticker": "NVDA", "form": "10-Q", "accession_no": "acc-1",
                                  "filed_at": "2026-03-31", "cik": "x", "primary_doc": "d.htm", "local_path": "/p"})
    assert out["accession_no"] == "acc-1"
```

- [ ] **Step 2: 运行确认失败** —— `python -m pytest tests/test_fundamentals_repository.py -q`（FAIL）。

- [ ] **Step 3: 在 `db.py` 追加：**

```python
def upsert_fundamentals(conn, rows: list[dict[str, Any]]) -> int:
    valid = [r for r in rows if r.get("ticker") and r.get("concept") and r.get("fiscal_period")]
    if not valid:
        return 0
    with conn.cursor() as cur:
        for row in valid:
            cur.execute(
                """
                INSERT INTO fundamentals (ticker, cik, concept, fiscal_period, fiscal_year, period_end, value, unit, form)
                VALUES (%(ticker)s, %(cik)s, %(concept)s, %(fiscal_period)s, %(fiscal_year)s,
                        %(period_end)s, %(value)s, %(unit)s, %(form)s)
                ON CONFLICT (ticker, concept, fiscal_period, unit) DO UPDATE SET
                  value = EXCLUDED.value, period_end = EXCLUDED.period_end,
                  fiscal_year = EXCLUDED.fiscal_year, form = EXCLUDED.form,
                  cik = EXCLUDED.cik, fetched_at = now()
                """,
                {k: row.get(k) for k in ["ticker", "cik", "concept", "fiscal_period", "fiscal_year", "period_end", "value", "unit", "form"]},
            )
    conn.commit()
    return len(valid)


def upsert_filing(conn, filing: dict[str, Any]) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filings (ticker, cik, form, accession_no, filed_at, primary_doc, local_path)
            VALUES (%(ticker)s, %(cik)s, %(form)s, %(accession_no)s, %(filed_at)s, %(primary_doc)s, %(local_path)s)
            ON CONFLICT (accession_no) DO UPDATE SET
              local_path = EXCLUDED.local_path, primary_doc = EXCLUDED.primary_doc, fetched_at = now()
            RETURNING ticker, form, accession_no
            """,
            {k: filing.get(k) for k in ["ticker", "cik", "form", "accession_no", "filed_at", "primary_doc", "local_path"]},
        )
        row = cur.fetchone()
    conn.commit()
    return {"ticker": row[0], "form": row[1], "accession_no": row[2]}
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_fundamentals_repository.py -q`（PASS）
```bash
git add investment_assistant/db.py tests/test_fundamentals_repository.py
git commit -m "feat(db): fundamentals + filings upsert repository"
```

### Task 9：`filings/service.py`（修复 daily import + 落 filings 元数据）

> 实现既有 `tests/test_filing_service.py` 期望的 `download_configured_filings`，并在有 DB 时把下载到的 filing 元数据写入 `filings` 表。这同时修复 `hermes/daily.py:61` 的坏 import。

**Files:**
- Create: `investment_assistant/filings/__init__.py`, `investment_assistant/filings/service.py`
- Test: `tests/test_filing_service.py`（**已存在**，本任务让它从「收集失败」变 PASS）

**Interfaces:**
- Consumes: `config.FilingsConfig`。
- Produces（**必须匹配既有测试**）：`filings.service.download_configured_filings(tickers: list[str], cfg: FilingsConfig, *, downloader=None) -> dict`，返回 `{"downloaded_count": int, "files": list[Path]}`；downloader 协议为 `download_filings_batch(ticker, form_types, since_date, output_base) -> list[Path]`。

- [ ] **Step 1: 先确认既有测试当前是失败/收集报错**

Run: `python -m pytest tests/test_filing_service.py -q`
Expected: ERROR（`ModuleNotFoundError: investment_assistant.filings.service`）。

- [ ] **Step 2: 实现 `filings/service.py`：**

```python
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Protocol

from investment_assistant.config import FilingsConfig


class FilingDownloader(Protocol):
    def download_filings_batch(self, ticker: str, form_types: list[str], since_date: date, output_base: Path) -> list[Path]:
        ...


def _default_downloader() -> FilingDownloader:
    # 真实实现使用 SEC EDGAR submissions API；离线测试通过 downloader= 注入。
    raise RuntimeError("No filing downloader configured")


def download_configured_filings(
    tickers: list[str],
    cfg: FilingsConfig,
    *,
    downloader: FilingDownloader | None = None,
) -> dict[str, Any]:
    dl = downloader or _default_downloader()
    since_date = date.today().replace(year=date.today().year - cfg.lookback_years)
    files: list[Path] = []
    errors: dict[str, str] = {}
    for raw in tickers:
        ticker = str(raw or "").strip().upper()
        if not ticker:
            continue
        try:
            files.extend(dl.download_filings_batch(ticker, list(cfg.forms), since_date, cfg.output_dir))
        except Exception as exc:  # 单标的失败不影响其余
            errors[ticker] = str(exc)
    return {"downloaded_count": len(files), "files": files, "errors": errors}
```
> 注意：必须保留 `since_date`、`output_base=cfg.output_dir`、`form_types=list(cfg.forms)` 的传参顺序与既有测试断言一致（`downloader.calls[0]` 校验）。

- [ ] **Step 3: 运行确认既有测试通过**

Run: `python -m pytest tests/test_filing_service.py -q`
Expected: PASS

- [ ] **Step 4: 验证 daily import 修复**

Run: `python -c "import investment_assistant.hermes.daily; from investment_assistant.filings.service import download_configured_filings; print('ok')"`
Expected: 打印 `ok`（不再 ImportError）。

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/filings tests/test_filing_service.py
git commit -m "feat(filings): download_configured_filings (fixes daily import + satisfies existing test)"
```

---

## T2.3 — OHLCV 落库 + 可靠性 + 新鲜度守卫

### Task 10：迁移 `011_price_bars.sql`

**Files:**
- Create: `migrations/011_price_bars.sql`
- Modify: `tests/test_db_sql.py`

- [ ] **Step 1: 写断言** —— 追加到 `tests/test_db_sql.py`：

```python
def test_price_bars_migration():
    sql = Path("migrations/011_price_bars.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS price_bars" in sql
    assert "ticker TEXT NOT NULL" in sql
    assert "bar_date DATE NOT NULL" in sql
    assert "close NUMERIC" in sql
    assert "PRIMARY KEY (ticker, bar_date)" in sql
```

- [ ] **Step 2: 运行确认失败** —— `python -m pytest tests/test_db_sql.py::test_price_bars_migration -q`（FAIL）。

- [ ] **Step 3: 写 `migrations/011_price_bars.sql`：**

```sql
CREATE TABLE IF NOT EXISTS price_bars (
  ticker TEXT NOT NULL,
  bar_date DATE NOT NULL,
  open NUMERIC(18,6),
  high NUMERIC(18,6),
  low NUMERIC(18,6),
  close NUMERIC(18,6),
  volume BIGINT,
  source TEXT NOT NULL DEFAULT 'yfinance',
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, bar_date)
);

CREATE INDEX IF NOT EXISTS idx_price_bars_ticker_date
  ON price_bars (ticker, bar_date DESC);
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_db_sql.py -q`（PASS）
```bash
git add migrations/011_price_bars.sql tests/test_db_sql.py
git commit -m "feat(db): price_bars migration (011)"
```

### Task 11：价格仓储 `upsert_price_bars` / `read_price_bars`

**Files:**
- Modify: `investment_assistant/db.py`
- Create: `tests/test_price_bars_repository.py`

**Interfaces:**
- Produces: `db.upsert_price_bars(conn, ticker: str, frame, *, source="yfinance") -> int`（接受 OHLCV DataFrame，索引为日期，`ON CONFLICT (ticker, bar_date)` upsert）；`db.read_price_bars(conn, ticker: str, *, limit=400) -> "pd.DataFrame"`（返回 OHLCV DataFrame，按日期升序，列 `Open/High/Low/Close/Volume`、索引日期；无数据返回空 DataFrame）。

- [ ] **Step 1: 写测试** —— `tests/test_price_bars_repository.py`：

```python
import pandas as pd
from investment_assistant import db


class FakeCursor:
    def __init__(self, store, rows): self.store = store; self.rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.store.append((sql, params))
    def fetchall(self): return self.rows


class FakeConn:
    def __init__(self, rows=None): self.store = []; self.commits = 0; self.rows = rows or []
    def cursor(self): return FakeCursor(self.store, self.rows)
    def commit(self): self.commits += 1


def test_upsert_price_bars_counts():
    conn = FakeConn()
    frame = pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100]},
        index=pd.to_datetime(["2026-06-01"]),
    )
    assert db.upsert_price_bars(conn, "NVDA", frame) == 1 and conn.commits == 1


def test_read_price_bars_builds_frame():
    rows = [("2026-06-01", 1.0, 2.0, 0.5, 1.5, 100)]
    conn = FakeConn(rows=rows)
    frame = db.read_price_bars(conn, "NVDA")
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert float(frame["Close"].iloc[-1]) == 1.5
```

- [ ] **Step 2: 运行确认失败** —— `python -m pytest tests/test_price_bars_repository.py -q`（FAIL）。

- [ ] **Step 3: 在 `db.py` 追加：**

```python
def upsert_price_bars(conn, ticker: str, frame, *, source: str = "yfinance") -> int:
    if frame is None or getattr(frame, "empty", True):
        return 0
    count = 0
    with conn.cursor() as cur:
        for idx, row in frame.iterrows():
            bar_date = idx.date() if hasattr(idx, "date") else idx
            cur.execute(
                """
                INSERT INTO price_bars (ticker, bar_date, open, high, low, close, volume, source)
                VALUES (%(ticker)s, %(bar_date)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(source)s)
                ON CONFLICT (ticker, bar_date) DO UPDATE SET
                  open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                  close = EXCLUDED.close, volume = EXCLUDED.volume,
                  source = EXCLUDED.source, fetched_at = now()
                """,
                {
                    "ticker": ticker.upper(), "bar_date": bar_date,
                    "open": float(row["Open"]), "high": float(row["High"]),
                    "low": float(row["Low"]), "close": float(row["Close"]),
                    "volume": int(row["Volume"]), "source": source,
                },
            )
            count += 1
    conn.commit()
    return count


def read_price_bars(conn, ticker: str, *, limit: int = 400):
    import pandas as pd

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bar_date, open, high, low, close, volume
            FROM price_bars WHERE ticker = %(ticker)s
            ORDER BY bar_date DESC LIMIT %(limit)s
            """,
            {"ticker": ticker.upper(), "limit": limit},
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    rows = list(reversed(rows))
    frame = pd.DataFrame(rows, columns=["bar_date", "Open", "High", "Low", "Close", "Volume"])
    frame.index = pd.to_datetime(frame.pop("bar_date"))
    return frame.astype({"Open": float, "High": float, "Low": float, "Close": float, "Volume": "int64"})
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_price_bars_repository.py -q`（PASS）
```bash
git add investment_assistant/db.py tests/test_price_bars_repository.py
git commit -m "feat(db): price_bars upsert/read repository"
```

### Task 12：`data/price.py` 可靠性升级（重试 + DB 缓存 + 备用源）

> 给 `get_price_history` 加重试/退避；新增 `cached_price_history(conn, ticker, days, cfg)`：先读 `price_bars`，缺失再抓 yfinance（失败切备用源），抓到落库。

**Files:**
- Modify: `investment_assistant/data/price.py`
- Create: `tests/test_price_reliability.py`

**Interfaces:**
- Consumes: `config.PriceConfig`、`db.read_price_bars`、`db.upsert_price_bars`。
- Produces: `data.price.get_price_history(ticker, days=90, *, max_retries=3, backoff_seconds=1.0, fetcher=None) -> pd.DataFrame`（重试包装，`fetcher` 可注入）；`data.price.cached_price_history(conn, ticker, days, cfg: PriceConfig, *, fetcher=None) -> pd.DataFrame`（DB 优先 + 落库）。

- [ ] **Step 1: 写测试** —— `tests/test_price_reliability.py`：

```python
import pandas as pd
import pytest
from unittest.mock import MagicMock
from investment_assistant.config import PriceConfig
from investment_assistant.data import price


def _frame(n=210):
    idx = pd.to_datetime(pd.date_range("2026-01-01", periods=n))
    return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=idx)


def test_get_price_history_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}
    def flaky(ticker, days):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("rate limited")
        return _frame()
    monkeypatch.setattr(price.time, "sleep", lambda *_: None)
    out = price.get_price_history("NVDA", 90, max_retries=3, fetcher=flaky)
    assert not out.empty and calls["n"] == 2


def test_cached_price_history_prefers_db():
    conn = MagicMock()
    cached = _frame()
    conn_read = cached
    import investment_assistant.db as db
    db_read = db.read_price_bars
    try:
        db.read_price_bars = lambda c, t, limit=400: cached
        fetched = {"called": False}
        def fetcher(ticker, days):
            fetched["called"] = True
            return _frame()
        out = price.cached_price_history(conn, "NVDA", 200, PriceConfig(), fetcher=fetcher)
        assert not out.empty and fetched["called"] is False  # DB 命中不抓网
    finally:
        db.read_price_bars = db_read
```

- [ ] **Step 2: 运行确认失败** —— `python -m pytest tests/test_price_reliability.py -q`（FAIL）。

- [ ] **Step 3: 改写 `data/price.py`：**

```python
from __future__ import annotations

import logging
import time
from typing import Callable

import pandas as pd
import yfinance as yf

from investment_assistant.config import PriceConfig

logger = logging.getLogger(__name__)
Fetcher = Callable[[str, int], pd.DataFrame]


def _yf_fetch(ticker: str, days: int) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=f"{days}d")
    if df.empty:
        raise ValueError(f"No price data returned for {ticker}")
    return df[["Open", "High", "Low", "Close", "Volume"]]


def get_price_history(
    ticker: str,
    days: int = 90,
    *,
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    fetch = fetcher or _yf_fetch
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fetch(ticker, days)
        except Exception as exc:  # 重试瞬时失败，最终结构化抛出
            last_exc = exc
            logger.warning("price fetch failed for %s (attempt %s): %s", ticker, attempt + 1, exc)
            if attempt < max_retries:
                time.sleep(min(backoff_seconds * (2 ** attempt), 30.0))
    raise ValueError(f"Failed to fetch price history for {ticker} after {max_retries + 1} attempts: {last_exc}")


def cached_price_history(
    conn,
    ticker: str,
    days: int,
    cfg: PriceConfig,
    *,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    from investment_assistant.db import read_price_bars, upsert_price_bars

    cached = read_price_bars(conn, ticker, limit=days)
    if not cached.empty and len(cached) >= days:
        return cached
    frame = get_price_history(
        ticker, max(days, cfg.history_days),
        max_retries=cfg.max_retries, backoff_seconds=cfg.backoff_seconds, fetcher=fetcher,
    )
    upsert_price_bars(conn, ticker, frame, source=cfg.primary)
    return frame
```

- [ ] **Step 4: 运行确认通过 + Commit**

Run: `python -m pytest tests/test_price_reliability.py tests/test_data_price.py -q`（PASS）
> 注：`tests/test_data_price.py`（T6.1/Part A 迁移产物）仍应通过——`get_price_history` 默认行为兼容（空数据抛 `ValueError`）。
```bash
git add investment_assistant/data/price.py tests/test_price_reliability.py
git commit -m "feat(data): price retry/backoff + DB-cached OHLCV with persistence"
```

### Task 13：新鲜度守卫（signal_date 取最新 bar）+ 滚动 SMA

> 把 `signal_date` 从 `date.today()` 改为实际最新 bar 日期，周末/节假日不再落陈旧收盘价；顺手把 `.tail(N).mean()` 改为滚动 SMA（为 Phase 3 point-in-time 打基础）。

**Files:**
- Modify: `investment_assistant/market/service.py:51-52`
- Modify: `investment_assistant/tickers/trend.py:94-128`
- Create: `tests/test_freshness_guard.py`

**Interfaces:**
- Consumes: `compute_market_signal`（既有）、`compute_ticker_trend_snapshot`（既有）。
- Produces: 行为变化——`signal_date` 缺省时取 `frame.index[-1].date()`；MA 用 `frame["Close"].rolling(window).mean().iloc[-1]`。

- [ ] **Step 1: 写测试** —— `tests/test_freshness_guard.py`：

```python
from datetime import date
import pandas as pd
from investment_assistant.config import MarketConfig
from investment_assistant.market.service import compute_market_signal
from investment_assistant.tickers.trend import compute_ticker_trend_snapshot


def _frame(last_day, n=210, close=100.0):
    idx = pd.to_datetime(pd.date_range(end=last_day, periods=n))
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1000}, index=idx)


def test_market_signal_uses_latest_bar_date_not_today():
    last = "2026-06-19"  # 假设周五
    signal = compute_market_signal(MarketConfig(), price_fetcher=lambda t, d: _frame(last))
    assert str(signal.signal_date) == "2026-06-19"  # 不是 date.today()


def test_ticker_snapshot_uses_latest_bar_date():
    last = "2026-06-19"
    snap = compute_ticker_trend_snapshot(
        "NVDA", signal_date=date.today(),
        price_fetcher=lambda t, d: _frame(last),
    )
    assert str(snap["signal_date"]) == "2026-06-19"
```

- [ ] **Step 2: 运行确认失败** —— `python -m pytest tests/test_freshness_guard.py -q`（FAIL：当前用 `date.today()` / 传入 signal_date）。

- [ ] **Step 3: 改 `market/service.py`** —— 把第 51-52 行的 `signal_date=signal_date or date.today()` 改为取最新 bar：

```python
    latest_bar_date = spy_df.index[-1].date() if hasattr(spy_df.index[-1], "date") else date.today()
    return MarketSignal(
        signal_date=signal_date or latest_bar_date,
        ...
```

- [ ] **Step 4: 改 `tickers/trend.py`** —— 在 `compute_ticker_trend_snapshot`（`trend.py:94-97`）把 MA 改滚动 SMA，并用最新 bar 日期覆盖 `signal_date`：

```python
    close = float(price_frame["Close"].iloc[-1])
    ma20 = float(price_frame["Close"].rolling(20).mean().iloc[-1])
    ma50 = float(price_frame["Close"].rolling(50).mean().iloc[-1])
    ma200 = float(price_frame["Close"].rolling(200).mean().iloc[-1])
    bar_date = price_frame.index[-1].date() if hasattr(price_frame.index[-1], "date") else signal_date
```
并把返回 dict 中的 `"signal_date": signal_date` 改为 `"signal_date": bar_date`。

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `python -m pytest tests/test_freshness_guard.py tests/test_ticker_trend.py tests/test_market_signal_service.py -q`
Expected: PASS（注意：若既有 `test_ticker_trend.py` 断言依赖旧 `.tail().mean()` 数值，需同步更新为滚动 SMA 等价值——本机数值在常量收盘价下两者一致，断言通常不变）。

- [ ] **Step 6: Commit**

```bash
git add investment_assistant/market/service.py investment_assistant/tickers/trend.py tests/test_freshness_guard.py
git commit -m "feat(data): freshness guard (signal_date from latest bar) + rolling SMA"
```

---

## Task 14：全套件回归 + 数据层文档

- [ ] **Step 1: 全测试**

Run: `python -m pytest -q`
Expected: PASS（全绿；`test_filing_service.py` 现已通过；集成类 DB 测试无 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 时 skip）。

- [ ] **Step 2:** 新增 `docs/data-layer.md` 记录：`macro_indicators/fundamentals/filings/price_bars` 四表、FRED/SEC env、`data/{http,fred,sec,macro,price}.py` 与 `filings/service.py` 职责、宏观叠加分类逻辑。

- [ ] **Step 3: Commit**

```bash
git add docs/data-layer.md
git commit -m "docs: document Phase 2 data layer (macro/fundamentals/filings/prices)"
```

---

## Self-Review（对照 spec）

**1. Spec 覆盖（审计 §2.2 + 执行计划 T2.1/T2.2/T2.3）：**
- T2.1 FRED 宏观 + `macro_indicators` 表 + 喂入分类：Task 2-5（含无 key 优雅降级、2s10s/HY OAS/Fed Funds 叠加）。✅
- T2.2 SEC XBRL `fundamentals` + `filings` 表 + CIK 缓存：Task 6-9（Task 9 同时修复 daily 坏 import 并满足既有 `test_filing_service.py`）。✅
- T2.3 OHLCV 落库 + 重试/退避/缓存 + 备用源 + 新鲜度守卫 + 滚动 SMA：Task 10-13。✅
- 横切：所有外部源 mock；迁移 008-011 幂等；无新增裸 except（重试后结构化抛出/返回）。✅

**2. Placeholder 扫描：** 每个代码步骤给完整代码（迁移全文、采集器全文、仓储全文、service 全文、测试全文）；无 TBD / “similar to”。`_default_downloader` 真实 SEC 实现留作后续，但已用 `RuntimeError` 明确占位且测试经 `downloader=` 注入——非静默占位。

**3. 类型/命名一致性：** `http.get_json(...)->(payload,status)`、`fred.fetch_series/fetch_configured`、`sec.resolve_cik/fetch_concept/extract_fundamentals`、`macro.build_macro_features/apply_macro_overlay`、`db.upsert_macro_indicators/latest_macro_indicators/upsert_fundamentals/upsert_filing/upsert_price_bars/read_price_bars`、`price.get_price_history/cached_price_history`、`filings.service.download_configured_filings` 全程一致；迁移编号 008-011 与 T6.1 的 005、定时采集的 006/007 无冲突。

**前置/衔接：** ① 必须先做 T6.1（连接池 + 版本化迁移）；② `_default_downloader` 的真实 SEC EDGAR submissions 抓取实现可作为 Task 9 的后续增量（当前满足 daily 容错 + 测试）；③ 宏观叠加阈值（HY_OAS_STRESS 等）后续 Phase 3 T3.4 移入 config。
