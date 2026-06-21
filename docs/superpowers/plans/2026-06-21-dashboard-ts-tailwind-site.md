# Dashboard TS Tailwind Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Hermes dashboard from a JSON-only endpoint into a Vite + TypeScript + Tailwind status site served by the existing Python dashboard service.

**Architecture:** Add a static frontend in `web/` that fetches `/api/status`. Extend `investment_assistant.dashboard.server` to serve `web/dist` for `/` and `/assets/*`, while keeping `/api/status` and Basic Auth behavior intact.

**Tech Stack:** Python `http.server`, pytest, Vite, TypeScript, Tailwind CSS, npm.

---

## Task 1: Static Serving Contract

- Write a failing Python test for `/` serving `web/dist/index.html`.
- Add static file helpers for `/`, `/assets/*`, content type, and frontend-missing fallback.
- Re-run the test and confirm it passes.

## Task 2: Frontend Project

- Add Vite + TypeScript + Tailwind project under `web/`.
- Implement a single-page dashboard that fetches `/api/status`.
- Render loading, error, ready states, and cards for DB, market, filings, and timer.
- Use dense operational styling, not a marketing layout.

## Task 3: API Enrichment

- Add `system_status()` to report service activity and timer text using bounded `systemctl` commands.
- Include `system` in `/api/status`.
- Test status payload has `database`, `filings`, and `system` keys without requiring systemd in unit tests.

## Task 4: Build and Deploy

- Update install script to run `npm install` and `npm run build` inside `web/` when npm exists.
- Build the frontend in the repo.
- Run Python tests.
- Sync to `/opt/hermes-investment-assistant/app` and restart dashboard.

## Task 5: Verification

- Verify `/` returns HTML.
- Verify `/api/status` returns database, filings, and system JSON.
- Use browser/Playwright to inspect page rendering.
- Confirm the repository has no generated business data before commit.
- Commit the work.

## Self-Review

- Spec coverage: plan covers static serving, TS/Tailwind frontend, status API enrichment, deployment, and verification.
- Placeholder scan: no placeholder tasks remain.
- Type consistency: frontend fetches `/api/status`; Python server serves `web/dist` and `/api/status`.
