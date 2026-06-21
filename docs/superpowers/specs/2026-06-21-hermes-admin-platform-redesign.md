# Hermes Admin Platform Redesign

## Problem

The current Hermes dashboard has a useful backend shell, but the information model is still a status page: one page, one API payload, one large frontend file, and status cards as the primary structure. This will not scale to future dashboards, tables, details, and manual operation entry points.

## Product Goal

Turn Hermes into an admin platform that can absorb new operational and investment-assistant modules without rewriting the shell each time.

The platform must support:

- more data dashboards over time;
- table-heavy views for market signals, filings, runs, logs, and audits;
- manual operation entry points with confirmation and auditability;
- bilingual menu and descriptive text;
- a default Chinese experience;
- a stable backend API shape instead of a single `/api/status` payload.

## Non-Goals For The First Implementation

- No trading actions.
- No arbitrary shell command execution from the browser.
- No full user/role system beyond the existing Basic Auth gate.
- No separate Node production service.
- No database schema change for audit logs yet.
- No replacement of the Python `http.server` deployment model in this pass.

## Information Architecture

The left navigation is organized by product capability, not by current cards:

```text
工作台
  今日工作台
  今日状态

市场数据
  市场信号
  历史信号
  Watchlist

Filings
  文件库
  下载任务
  公司详情

自动化
  定时任务
  服务状态
  运行日志

手动操作
  操作中心
  执行记录

系统
  配置
  API 状态
  原始数据
```

The first implementation keeps the active modules limited to:

- 今日工作台
- 市场信号
- Filing 文件库
- 服务状态
- 操作中心
- 原始数据

Inactive future items can appear later after the corresponding API exists.

## UX Direction

The first screen should feel like an admin workspace, not a monitoring poster.

The workspace home answers:

1. What needs attention today?
2. What is the current market gate?
3. Did automation run?
4. Are filings and services healthy?
5. What safe actions can I trigger next?

Status cards remain useful, but they become supporting summary widgets. Tables and action modules become first-class patterns.

## Frontend Architecture

The frontend moves from one large `web/src/main.ts` file to a small platform structure:

```text
web/src/
  main.ts
  app/
    app.ts
    navigation.ts
    state.ts
    types.ts
  i18n/
    messages.ts
  shared/
    components.ts
    format.ts
    html.ts
  features/
    workbench.ts
    market.ts
    filings.ts
    services.ts
    operations.ts
    raw.ts
```

Responsibilities:

- `main.ts`: boot only.
- `app/app.ts`: shell render, hash routing, event binding, refresh orchestration.
- `app/navigation.ts`: nav tree and route metadata.
- `app/state.ts`: app state and API loading.
- `i18n/messages.ts`: all bilingual copy.
- `shared/*`: escaping, formatting, reusable panels, badges, tables, empty states.
- `features/*`: page renderers. Each feature receives state and returns HTML.

The page model is route-based with hash routes. This keeps deployment simple while allowing future page-like modules.

## Backend API Architecture

Keep `/api/status` for compatibility, then add narrower endpoints:

```text
GET /api/status                 compatibility aggregate
GET /api/services               systemd service and timer state
GET /api/market/signals/latest  latest persisted market signal
GET /api/filings                filing storage summary and file rows
GET /api/operations             allowed operation registry
GET /api/raw/status             explicit raw aggregate for debugging
```

The backend should use a small API router function instead of adding more `if self.path == ...` checks inside `Handler.do_GET`.

## Manual Operation Architecture

Manual operations must be backend-defined, not browser-defined.

An operation record contains:

- `id`
- `label`
- `description`
- `risk`
- `enabled`
- `requires_confirmation`
- `method`
- `endpoint`

The first implementation exposes the operation registry only. Running operations is intentionally deferred until audit logging exists.

Future run endpoint:

```text
POST /api/operations/{id}/run
```

Future run behavior:

- validate operation id against allowlist;
- require confirmation token for medium/high risk operations;
- run bounded command or Python handler;
- capture stdout/stderr/result;
- persist audit log;
- return operation run id.

## Testing Strategy

Backend:

- test `/api/status` keeps compatibility keys;
- test new API router returns services, latest market signal, filings, operations, and raw status;
- test unknown API path returns no response and falls through to 404.

Frontend:

- source tests assert modular architecture files exist;
- source tests assert route registry, feature modules, table helpers, operation copy, and Chinese default are present;
- `npm run build` verifies TypeScript imports and Tailwind build.

Manual verification:

- `/` returns HTML;
- `/api/status` returns JSON;
- new API endpoints return JSON;
- desktop browser shows left navigation and route switching;
- mobile browser shows collapsible navigation;
- language toggle switches descriptive text;
- console has no errors.

## Rollout

This remains a single Python dashboard service. `deploy/install.sh` already builds the Vite app during install. The new frontend modules are built into the same `web/dist` directory and served by the existing service.
