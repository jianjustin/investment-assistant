# Hermes Admin Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the Hermes dashboard from a status page into an extensible admin platform shell with modular frontend features and narrower backend API endpoints.

**Architecture:** Keep the current Python single-service deployment, but add an API router and feature-specific JSON endpoints. Split the Vite/TypeScript frontend into app shell, route registry, i18n, shared components, and feature modules so future dashboards, tables, and manual operation views can be added without editing one large file.

**Tech Stack:** Python `http.server`, pytest, Vite, TypeScript, Tailwind, lucide icons.

---

## File Structure

Create or modify these files:

- Modify `investment_assistant/dashboard/server.py`: add `api_response_for_path`, new API payload helpers, and route `Handler.do_GET` through that function.
- Modify `tests/test_dashboard_server.py`: add API router tests for services, latest market signal, filings, operations, and raw status.
- Modify `tests/test_dashboard_frontend_source.py`: update source tests for modular architecture instead of the old single-file nav assertions.
- Replace `web/src/main.ts`: boot the app shell only.
- Create `web/src/app/types.ts`: shared frontend types.
- Create `web/src/app/navigation.ts`: grouped route metadata.
- Create `web/src/app/state.ts`: app state, API fetch, and reload orchestration.
- Create `web/src/app/app.ts`: shell render, event binding, hash route selection.
- Create `web/src/i18n/messages.ts`: Chinese-default bilingual copy.
- Create `web/src/shared/html.ts`: `escapeHtml` and small utility helpers.
- Create `web/src/shared/format.ts`: boolean, date, number, service, market formatting.
- Create `web/src/shared/components.ts`: reusable panel, metric, table, badge, and service row renderers.
- Create `web/src/features/workbench.ts`: homepage workspace summary.
- Create `web/src/features/market.ts`: latest market signal page.
- Create `web/src/features/filings.ts`: filing table page.
- Create `web/src/features/services.ts`: service/timer page.
- Create `web/src/features/operations.ts`: operation registry page.
- Create `web/src/features/raw.ts`: raw JSON page.

## Task 1: Backend API Router

**Files:**
- Modify: `investment_assistant/dashboard/server.py`
- Test: `tests/test_dashboard_server.py`

- [ ] **Step 1: Write failing tests**

Add tests that call `server.api_response_for_path` and verify:

```python
def test_api_response_for_path_returns_feature_payloads(monkeypatch):
    monkeypatch.setattr(server, "database_status", lambda: {"ok": True, "latest_market_signal": {"market_status": "green"}})
    monkeypatch.setattr(server, "filing_status", lambda: {"path": "/srv/filings", "exists": True, "file_count": 2})
    monkeypatch.setattr(server, "filing_rows", lambda: [{"name": "a.htm", "size": 10}])
    monkeypatch.setattr(server, "system_status", lambda: {"dashboard_service": {"ok": True, "output": "active"}})

    assert server.api_response_for_path("/api/services").payload == {"dashboard_service": {"ok": True, "output": "active"}}
    assert server.api_response_for_path("/api/market/signals/latest").payload == {"market_status": "green"}
    assert server.api_response_for_path("/api/filings").payload["files"] == [{"name": "a.htm", "size": 10}]
    assert server.api_response_for_path("/api/operations").payload["operations"][0]["id"] == "run_daily_scan"
    assert sorted(server.api_response_for_path("/api/raw/status").payload) == ["database", "filings", "system"]
    assert server.api_response_for_path("/api/missing") is None
```

- [ ] **Step 2: Run test and verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_server.py -q`

Expected: fail because `api_response_for_path` and `filing_rows` do not exist.

- [ ] **Step 3: Implement router and payload helpers**

Add:

```python
@dataclass(frozen=True)
class ApiResponse:
    payload: Any
    status: int = 200


def operation_registry() -> list[dict[str, Any]]:
    return [{
        "id": "run_daily_scan",
        "label": "运行每日扫描",
        "description": "启动 hermes-investment-daily.service，重新执行每日市场与 filing 流程。",
        "risk": "medium",
        "enabled": False,
        "requires_confirmation": True,
        "method": "POST",
        "endpoint": "/api/operations/run_daily_scan/run",
    }]
```

Add `filing_rows(limit=100)` that reads `DEFAULT_FILINGS_DIR`, returns sorted file rows with `name`, `path`, `size`, and `modified_at`, newest first.

Add `api_response_for_path(path)` mapping the endpoints listed in the spec.

Update `Handler.do_GET` to call `api_response_for_path(self.path)` before static handling.

- [ ] **Step 4: Run backend tests**

Run: `.venv/bin/python -m pytest tests/test_dashboard_server.py -q`

Expected: pass.

## Task 2: Frontend Architecture Skeleton

**Files:**
- Modify: `tests/test_dashboard_frontend_source.py`
- Create: all `web/src/app`, `web/src/i18n`, `web/src/shared`, and `web/src/features` files listed above.
- Modify: `web/src/main.ts`

- [ ] **Step 1: Write failing source tests**

Update `tests/test_dashboard_frontend_source.py` to assert these files exist and that:

- `web/src/main.ts` imports `./app/app`.
- `web/src/app/navigation.ts` contains `routeGroups` and route ids `workbench`, `market`, `filings`, `services`, `operations`, `raw`.
- `web/src/i18n/messages.ts` exports `defaultLanguage = 'zh'`.
- `web/src/shared/components.ts` contains `renderTable`.
- `web/src/features/operations.ts` contains `requires_confirmation`.

- [ ] **Step 2: Run test and verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_frontend_source.py -q`

Expected: fail because the files do not exist yet.

- [ ] **Step 3: Create modular frontend files**

Move the existing types/copy/render helpers into the new structure. Keep behavior equivalent but route-based:

- `#/workbench`
- `#/market`
- `#/filings`
- `#/services`
- `#/operations`
- `#/raw`

Use `fetch('/api/status')` for aggregate state and feature-specific endpoints for tables/operations.

- [ ] **Step 4: Build TypeScript**

Run: `cd web && npm run build`

Expected: TypeScript and Vite build pass.

## Task 3: Platform Experience Verification

**Files:**
- No new source files unless fixing issues found by verification.

- [ ] **Step 1: Run full tests**

Run: `.venv/bin/python -m pytest tests -q`

Expected: all tests pass.

- [ ] **Step 2: Build frontend**

Run: `cd web && npm run build`

Expected: production build succeeds.

- [ ] **Step 3: Deploy**

Run `deploy/install.sh` through sudo using `SERVER_PWD`, then restart `hermes-investment-dashboard.service`.

- [ ] **Step 4: Verify HTTP endpoints**

Check:

- `/` returns `text/html`.
- `/api/status` returns JSON.
- `/api/services` returns JSON.
- `/api/market/signals/latest` returns JSON.
- `/api/filings` returns JSON with `files`.
- `/api/operations` returns JSON with `operations`.

- [ ] **Step 5: Browser QA**

Use a temporary localhost auth proxy. Verify desktop and mobile:

- left navigation renders;
- route switching works;
- Chinese is default;
- language toggle switches copy;
- filing table renders rows;
- operation center renders disabled actions;
- no horizontal overflow;
- browser console has no errors.

## Self-Review

Spec coverage:

- Platform shell: Task 2.
- Backend API split: Task 1.
- Tables: Task 2 filings feature and shared `renderTable`.
- Manual operations entry point: Task 1 registry and Task 2 operations feature.
- Chinese default and bilingual copy: Task 2.
- Verification: Task 3.

Placeholder scan: no TBD/TODO placeholders remain in the executable task list.

Type consistency: route ids are `workbench`, `market`, `filings`, `services`, `operations`, and `raw` across tests, navigation, and feature modules.
