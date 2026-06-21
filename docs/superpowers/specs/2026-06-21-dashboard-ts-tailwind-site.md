# Dashboard TS Tailwind Site Spec

## Decision

Use 方案 1: keep the existing Python dashboard service as the single runtime service, add a Vite + TypeScript + Tailwind frontend under `web/`, build it to `web/dist`, and have `investment_assistant.dashboard.server` serve the static site plus `/api/status`.

## Goals

- Replace the current JSON-only `/` response with a usable dashboard page.
- Keep `/api/status` as the source of truth for frontend data.
- Show Postgres state, latest market signal, filing storage count/path, and service/timer health.
- Preserve Basic Auth on both page and API.
- Keep business output data outside Git.

## Non-Goals

- No config editing in the first site version.
- No trading actions or investment recommendations.
- No separate Node runtime service in production.
- No persistence of frontend runtime state.

## Frontend Information Architecture

The page is an operational dashboard, not a marketing page.

First viewport:

- top bar with product name, last refreshed time, and refresh button.
- status cards for database, latest market signal, filing files, and scheduled timer.

Main content:

- latest market signal panel with SPY close, SPY 200MA, VIX, status, and run id.
- filings panel with storage path, count, and sync hint.
- service panel with Postgres, dashboard, and Hermes timer status.
- raw JSON/details panel for debugging.

## Technical Shape

```text
web/
├── package.json
├── index.html
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.ts
├── postcss.config.js
└── src/
    ├── main.ts
    └── styles.css
```

`investment_assistant/dashboard/server.py` serves:

- `/api/status`: JSON status.
- `/`: `web/dist/index.html` when present.
- `/assets/*`: static Vite assets.

If `web/dist` is missing, `/` returns a clear JSON message explaining that the frontend has not been built.

## Acceptance Criteria

- `npm run build` succeeds in `web/`.
- `python -m pytest tests/ -q` succeeds.
- `/api/status` still returns JSON.
- `/` returns HTML after build.
- `hermes-investment-dashboard.service` serves the page from `/opt/hermes-investment-assistant/app`.
- Browser verification confirms the page renders and includes database, market, filings, and timer status.
