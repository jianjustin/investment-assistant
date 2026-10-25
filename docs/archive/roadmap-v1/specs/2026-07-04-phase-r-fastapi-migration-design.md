# Phase R — API 层迁移 FastAPI + roadmap 修订 设计

> 2026-07-04 ｜ 头脑风暴结论（技术选型、roadmap 修订方向、Phase 2 三个输入均已用户确认）

## 0. 决策记录

| 决策 | 结论 | 备选与否决理由 |
|------|------|----------------|
| 技术选型范围 | **后端 API 层迁 FastAPI**，保留 psycopg / 自研迁移器 / 自研调度器 / Svelte 5 前端 | 全保持现状（Phase 2 表单校验手写成本高）；大爆炸重写含 SQLModel/alembic（自研件有测试且在生产运行，替换无功能收益） |
| 重构路径 | **先迁移后功能**：Phase R 插在 Phase 0 与 Phase 1 之间 | 功能优先（新旧 HTTP 两套共存期长，Phase 1 路由要写两遍） |
| 宏观取舍 | **维持砍宏观**：市场广度 > HY 利差 > 2s10s，不接 FRED 全家桶 | 恢复宏观模块（用户否决） |
| 用户原则 | 「自动化提供手动入口 + 验证入口 + 功能说明 + 如何验证示例」升级为 **DoD 硬性标准**（00 §6 + 05 C6 模板） | — |

Phase 2 数据模型输入（原 README §6 待确认项）：①交易记录**表单从零录入**，CSV/Obsidian 路径按 YAGNI 删除；②**小池趋势波段 ≤20 只**，事件研究整池聚合、区制用大盘三态；③行为检测覆盖**四个坏习惯**（追高进场/过早止盈/死扛亏损/计划外交易），指标映射见 roadmap 03。

## 1. 迁移架构

**替换**：`api/http.py`、`api/router.py`（手写路由表）、`api/server.py`（stdlib http.server）、`api/auth.py` 的 token 校验 → FastAPI + Pydantic v2 + uvicorn。36 条路由按域拆 `APIRouter`：market / tickers / strategies / hermes / research / jobs / watchlist / settings / status / runs。

**保留**：`services/*` 全部业务层（路由仍是薄封装）、`db.py`（psycopg + 池）、`migrate.py`、`tasks/scheduler.py` 与 `tasks/runner.py`、`api/static_files.py`（路径穿越防护 / `/status` 页 / 前端未构建 503，挂 catch-all 路由）、Svelte 5 前端。

**新增依赖**：仅 `fastapi`、`uvicorn`、`httpx`（测试）。

**app 结构**：`api/app.py` 提供 `create_app()`；`api/server.py` 保留模块名作为入口（`python -m investment_assistant.api.server` 起 uvicorn），systemd 单元不变。

## 2. 行为契约（逐项对齐）

1. 36 条路由路径与响应 JSON 不变，前端 `web/src/lib/api.ts` 零改动。
2. 无 DATABASE_URL 时只读端点返回空 + `{"degraded": true}`。
3. `/api/runs/{id}` SSE：`StreamingResponse` 包装现有 `runner.subscribe()` 队列。
4. fail-closed：无认证拒绝绑定公网地址（启动前检查）；token 校验改 FastAPI dependency，行为不变。
5. 错误结构化返回 + 日志，不静默吞。

## 3. 测试策略

- 现有 API 测试从 `router.dispatch(...)` 改为 `TestClient`，**断言不变**（迁移验收契约）；services/db/tasks 测试不动。
- 完成标准：pytest 全绿 + `cd web && npm test` 绿 + 手动验证 `GET /api/status`、SSE、`/` 静态页。

## 4. Phase R 收尾（DoD 存量欠账）

1. 前端「策略」区加事件研究面板（调 `GET /api/research/event-study`，含手动触发）。
2. docs 补「事件研究：功能说明 + 如何验证示例」（CLI 与 API 两条路径）。

## 5. roadmap 修订（本次已落盘）

- README：Phase 0 标记完成、插入 Phase R、迁移编号表修正（event_studies=009，后续 010–015 顺延）、§6 改为已确认；
- 00 §5 优先级图加 Phase R，新增 §6 DoD 硬性标准；
- 03 「待你确认」改为「已确认」+ 坏习惯指标映射表；
- 05 新增 C6 DoD 检查清单模板；
- 新增 07-phase-r-fastapi-migration.md。

## 6. 范围外（明确不做）

- 不引入 SQLModel / alembic / APScheduler / 重型回测框架；
- 不做券商 CSV 导入、Obsidian 交易笔记解析；
- 不恢复 FRED 宏观采集；
- 前端框架不换。
