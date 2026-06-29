# 子项目 A：Dashboard 五层 IA 重构 + 工具层任务可视化 + 文档清理 设计

> 日期：2026-06-29 ｜ 范围：前端信息架构（IA）重构 + 工具层任务/日志/指标可视化 + 配套只读/触发 API + 文档清理
> 关联：本设计是更大方案的**子项目 A**。回测引擎（策略层）= 子项目 B、LLM 交易指令（交易层）= 子项目 C，均不在本 spec 范围内，仅留占位页。
> 上游计划：`docs/superpowers/plans/2026-06-29-scheduled-ingestion-discord.md`（已落地 `job_reports`/`scheduled_jobs`/`_harness`/`notifier`，是本设计的数据源）。

---

## 1. 目标与背景

当前前端是 6 个一级区（`总览 / 市场 / 关注 / 策略 / Hermes / 系统`），按"功能模块"组织。本子项目把它重组为按**投资流水线分层**的 5 层结构，并把上游计划已落库、但前端尚未消费的任务调度数据（`job_reports` / `scheduled_jobs`）可视化出来。

**非目标（明确排除）：**
- 不实现回测引擎（策略层「回测」仅占位页）。
- 不实现 LLM 交易指令生成（交易层「交易指令」仅占位页）。
- 不新增「总览」落地页——总览本期**关闭**，后续以"通知"形式实现。
- 不改 Discord 接入模型：维持现有 **Webhook 模式**（每频道一条 webhook URL），不引入 Bot Token/Channel ID 模式。

**成功标准：**
1. 前端导航变为 5 层；旧 6 区内容无丢失地归位到新结构；默认落地工具层。
2. 工具层四个二级页能查看定时任务、运行历史、运维指标、业务数据结果，并能手动触发任务。
3. 设置层能在 UI 上开关定时任务、修改其运行时间（写 `scheduled_jobs`），以及配置 Discord 各频道 webhook、任务→频道路由、每任务开关，并对每个频道点「验证」发测试消息。
4. `architecture.md` / `README.md` 反映新结构；过时文档删除。
5. 新增逻辑均有单测，外部依赖（DB）全 mock，离线可跑。

---

## 2. 信息架构（最终）

```
🔧 工具层 (默认落地)   📊 数据层          🎯 策略层         🤖 交易层            ⚙️ 设置层
├ 任务中心             ├ 信号总览         ├ 策略评分        ├ 宏观分析           ├ 系统
├ 运行记录             ├ 趋势分析         ├ 运行历史        ├ 决策证据           ├ 关注列表 (查+改)
├ 运维指标             └ 技术面趋势       └ 回测 (占位)     └ 交易指令 (占位)    ├ Discord 推送 (只读)
└ 数据结果                                                                       ├ 定时任务管理 (开关/改时间)
                                                                                 └ 环境变量 (只读)
```

### 2.1 旧 → 新 归位映射

| 旧区/页 | 旧路由 | 新层 | 新二级 | 处理 |
|---------|--------|------|--------|------|
| 总览 | `#dashboard` | — | — | **移除**（`Dashboard.svelte` 删除，路由删除） |
| 市场/信号总览 | `#market/overview` | 数据层 | 信号总览 | 平移 |
| 市场/趋势分析 | `#market/trend` | 数据层 | 趋势分析 | 平移 |
| 市场/手动抓取 | `#market/fetch` | 工具层 | 任务中心 | 并入手动抓取入口 |
| 关注/技术面趋势 | `#watchlist/tickers` | 数据层 | 技术面趋势 | 平移 |
| 关注/关注列表 | `#watchlist/list` | 设置层 | 关注列表 | 平移（查看+增删一起） |
| 策略/策略评分 | `#strategy/scores` | 策略层 | 策略评分 | 平移 |
| 策略/运行历史 | `#strategy/runs` | 策略层 | 运行历史 | 平移 |
| Hermes/宏观分析 | `#hermes/macro` | 交易层 | 宏观分析 | 平移 |
| Hermes/决策证据 | `#hermes/decision` | 交易层 | 决策证据 | 平移 |
| Hermes/总览 | `#hermes/overview` | 交易层 | （并入宏观分析顶部摘要） | 合并 |
| 系统 | `#system` | 设置层 | 系统 | 平移 |
| —（新增） | — | 工具层 | 任务中心 / 运行记录 / 运维指标 / 数据结果 | 新建 |
| —（新增） | — | 策略层 | 回测 | 占位页 |
| —（新增） | — | 交易层 | 交易指令 | 占位页 |
| —（新增） | — | 设置层 | Discord 推送 / 定时任务管理 / 环境变量 | 新建 |

### 2.2 路由方案

沿用现有 hash 路由（`#<zone>/<sub>`），改动：
- `zones` 数组：`['tools', 'data', 'strategy', 'trade', 'settings']`（去掉 `dashboard`）。
- `parseHash` 默认 zone 由 `dashboard` 改为 `tools`。
- 各 zone 的合法 `sub` 白名单（用于非法子路由回退到该层首个二级页）：

| zone | subs（首个为默认） |
|------|--------------------|
| `tools` | `tasks`(任务中心) · `runs`(运行记录) · `ops`(运维指标) · `results`(数据结果) |
| `data` | `signals`(信号总览) · `trend`(趋势分析) · `tickers`(技术面趋势) |
| `strategy` | `scores`(策略评分) · `runs`(运行历史) · `backtest`(回测·占位) |
| `trade` | `macro`(宏观分析) · `decision`(决策证据) · `orders`(交易指令·占位) |
| `settings` | `system`(系统) · `watchlist`(关注列表) · `discord`(Discord) · `jobs`(定时任务管理) · `env`(环境变量) |

> 注：`strategy` 与 `tools` 都有 `runs` 子键，但分属不同 zone，命名不冲突（`#strategy/runs` vs `#tools/runs`）。

---

## 3. 工具层四分页（核心新功能）

数据源全部来自上游已落地的两张表 + run_log。前端通过新增只读 API 消费。

### 3.1 任务中心（`#tools/tasks`）
- **定时任务清单（只读）**：表格列 = 任务名 / 计划（`time_local` + `weekday_mask` + `timezone`）/ 下次运行（`next_run_at`）/ 上次运行（`last_run_at`）/ 启用状态（`enabled`）。数据来自 `GET /api/jobs/scheduled`。
- **「立即运行」按钮**：每行一个，调 `POST /api/jobs/{name}/run` → 复用 `tasks.runner.submit` 后台线程 + `/api/events` SSE 实时回显完成。
- **手动抓取入口**：保留旧 `市场/手动抓取` 的市场信号 fetch 触发（`POST /api/market/signals/fetch`），与任务触发并列放在本页顶部「手动操作」区。
- **编辑入口提示**：本页只读；启用开关/改时间引导到设置层「定时任务管理」。

### 3.2 运行记录（`#tools/runs`）
- **历史表**：`GET /api/jobs/reports?task=&limit=`。列 = 任务 / run_id / 状态(success|error) / 开始 / 结束 / 耗时。状态用 `StatusPill`。
- **行展开**：点击行展开 `summary`(JSONB) 原文 + 该次日志摘要。错误时高亮 `summary.error`。
- 顶部按任务名筛选（`metrics`/`filings`/`scores`/全部）。

### 3.3 运维指标（`#tools/ops`）
- `GET /api/jobs/metrics?task=&window=`。展示：
  - 每任务**成功率**（窗口内 success / total）。
  - **平均耗时**（`finished_at - started_at`）。
  - **失败趋势**：按天的 error 计数折线/柱图（复用 `LineChart`/`EChart`）。
- 窗口默认近 7 天，可切 30 天。

### 3.4 数据结果（`#tools/results`）
- 每个任务取**最新一条** `job_reports.summary`（`GET /api/jobs/reports?task=X&limit=1`），按任务类型渲染：
  - `metrics` → 市场状态 + VIX + 个股趋势表。
  - `filings` → 昨日财报清单（ticker/form/path）。
  - `scores` → 评分表（ticker/score）。
- 这是"任务拉回了什么数据"的面板，与运维健康分离。

---

## 4. 设置层

| 二级页 | 来源 | 可写？ |
|--------|------|--------|
| 系统（`#settings/system`） | 现有 `System.svelte` 平移 | 维持现状 |
| 关注列表（`#settings/watchlist`） | 现有 `Watchlist.svelte` 平移 | 是（沿用现有增删 API） |
| Discord 推送（`#settings/discord`） | `notify_settings`（DB） overlay 到 `NotifyConfig` | **可写**：见 §4.1 |
| 定时任务管理（`#settings/jobs`） | `scheduled_jobs` | **可写**：`enabled` 开关、`time_local` 修改 → `PATCH /api/jobs/scheduled/{name}` |
| 环境变量（`#settings/env`） | 关键环境变量的"是否已设置"布尔速查（`SEC_USER_AGENT` / `INVESTMENT_ASSISTANT_DATABASE_URL`），**只显示存在性，不显示值** | 只读 |

### 4.1 Discord 推送页（可编辑 + 验证）

Webhook 模式，三个频道 `earnings / signals / daily`，外加任务→频道路由与每任务开关。

- **表单字段**：每频道一个 webhook URL 输入框（password 型）+ `discord_enabled` 总开关 + 每任务（`metrics/filings/scores`）的"启用"勾选与"路由到哪个频道"下拉。
- **保存**：`PATCH /api/settings/notify`。webhook 字段**仅在传入非空字符串时覆盖**该频道（留空 = 不动现有值，避免误清空）。
- **验证按钮**：每频道一个，`POST /api/settings/notify/test`，body `{channel, url?}`——传 `url` 时用刚输入的值预验证（保存前即可测），不传则用库里已存值；后端发一条测试 embed，返回 `{ok, status_code, error}`，前端就地显示 ✅/❌。
- **读取**：`GET /api/settings/notify` 返回 `discord_enabled`、`task_channels`、`task_enabled`，webhook **按掩码返回**（`{channel: {configured: bool}}`，不回显 URL 明文）。

> 安全约束：webhook URL/env 值一律不回显明文；GET 只返回 `configured: true|false`，明文仅在 PATCH/test 的请求方向单向写入。

---

## 5. 后端改动

### 5.0 迁移 `008_notify_settings`（Discord 可编辑所需）

```sql
CREATE TABLE IF NOT EXISTS notify_settings (
  id             SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- 单行
  discord_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  webhooks       JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {channel: url}
  task_channels  JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {task: channel}
  task_enabled   JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {task: bool}
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO notify_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
```

> **编号协调**：写本 spec 时迁移到 `007`，故占 `008`。上游 `docs/superpowers/plans/2026-06-27-phase2-data-layer.md` 也声明从 `008` 起——两者需在实施时择一顺延（先落地者占 008，另一方 +1）。JSONB 单行结构与 `NotifyConfig` 字段一一对应，overlay 逻辑最简。

### 5.1 `investment_assistant/db.py` 新增仓储函数

| 函数 | 行为 |
|------|------|
| `list_scheduled_jobs(conn) -> list[dict]` | `SELECT name,time_local,weekday_mask,timezone,enabled,next_run_at,last_run_at FROM scheduled_jobs ORDER BY name` |
| `list_job_reports(conn, *, task=None, limit=50) -> list[dict]` | `SELECT ... FROM job_reports [WHERE task=%s] ORDER BY created_at DESC LIMIT %s` |
| `job_report_metrics(conn, *, task=None, since) -> list[dict]` | 按任务聚合：total、success 数、平均耗时秒、按天 error 计数 |
| `update_scheduled_job(conn, name, *, enabled=None, time_local=None) -> None` | 部分更新 + `updated_at=now()` + `commit()`；**当 `time_local` 改变时一并置 `next_run_at=NULL`**，由调度器下一 tick 重算下次运行 |
| `get_notify_settings(conn) -> dict` | 读单行 `notify_settings`，返回 `{discord_enabled, webhooks, task_channels, task_enabled}` |
| `update_notify_settings(conn, *, discord_enabled=None, webhooks=None, task_channels=None, task_enabled=None) -> None` | 部分更新单行（id=1）；webhooks 等 JSONB 字段做**合并覆盖**（传入键覆盖、未传保留），`updated_at=now()` + `commit()` |

所有函数沿用现有写法（`with conn.cursor() as cur` + 具名参数）；读函数返回 `dict(zip(keys, row))` 列表，与 `due_scheduled_jobs` 一致。时间字段序列化为 ISO 字符串由 API 层负责。

### 5.2 `investment_assistant/api/routes/jobs.py`（新文件）

| 方法/路径 | 服务 | 说明 |
|-----------|------|------|
| `GET /api/jobs/scheduled` | `list_scheduled_jobs` | 任务清单 |
| `GET /api/jobs/reports` | `list_job_reports`（解析 `task`/`limit` query） | 运行历史 |
| `GET /api/jobs/metrics` | `job_report_metrics`（解析 `task`/`window` query） | 运维聚合 |
| `POST /api/jobs/{name}/run` | `runner.submit(name, lambda: REGISTRY[name].run(config))` | 手动触发，返回 `{run_id, status:"pending"}`；未注册任务名 → 404 |
| `PATCH /api/jobs/scheduled/{name}` | `update_scheduled_job` | body `{enabled?, time_local?}`，设置层用 |

### 5.3 `investment_assistant/api/routes/settings.py`（新文件，Discord 可编辑）

| 方法/路径 | 服务（`services/settings.py`） | 说明 |
|-----------|------|------|
| `GET /api/settings/notify` | `read_notify_view` | 返回 `discord_enabled / task_channels / task_enabled` + webhooks **掩码**（`{channel: {configured}}`） |
| `PATCH /api/settings/notify` | `update_notify` | body 任意子集；webhook 仅非空覆盖；调 `update_notify_settings` |
| `POST /api/settings/notify/test` | `test_notify_channel` | body `{channel, url?}`；用候选 `url` 或库存值发测试 embed；返回 `{ok, status_code, error}` |
| `GET /api/settings/env` | `read_env_status` | 关键 env 的存在性布尔（不回显值） |

- `services/settings.py`（新文件）封装：DB overlay 合成 `NotifyConfig`、掩码、test 发送（注入 `DiscordClient`，测试可 mock）。
- **配置 overlay**：`config.load_config()` 仍从文件读基线 `NotifyConfig`；新增 `services.settings.effective_notify_config(base)`——有 DB 时把 `notify_settings` 行 overlay 到 base（webhooks/task_channels/task_enabled 合并、discord_enabled 覆盖），无 DB 时原样返回。`_harness`/`notifier` 与 API 统一经此取生效配置，保证"UI 改了就生效"。

### 5.4 公共约定

- 复用 `api/router.py` 的 `@register` 装饰器与 `ApiResponse`。
- 触发端点复用 `tasks.scheduler.REGISTRY`（上游计划 Task 8 产出的任务注册表）映射任务名→`run(config)`。无 DB 时（无 `INVESTMENT_ASSISTANT_DATABASE_URL`）：只读端点返回空列表/基线配置 + `{"degraded": true}`，不崩。
- 业务逻辑落在 `services/jobs.py` 与 `services/settings.py`（新文件），路由层薄封装，对齐现有 `api/routes/*` → `services/*` 分层。

### 5.5 与既有基建的关系
- 手动触发链路（`runner.submit` → `/api/runs/{id}` 轮询 + `/api/events` SSE）**已存在**，本设计仅新增"按任务名触发"的入口，不改 runner。
- `job_reports`(006)/`scheduled_jobs`(007) 已由上游计划建好；本设计仅新增 `008_notify_settings`（§5.0）。
- `DiscordClient.from_config` 已支持 webhook 优先 config 回退 env（上游 Task 3），overlay 后的 `NotifyConfig.webhooks` 直接复用该链路。

---

## 6. 前端组件改动

| 文件 | 改动 |
|------|------|
| `web/src/lib/components/SideNav.svelte` | `nav` 数组改为 5 层结构 + 新二级；图标 🔧📊🎯🤖⚙️ |
| `web/src/app.svelte` | `Zone` 类型与 `zones` 改为 5 个；路由 `{#if}` 分支改为 5 层组件；移除 `Dashboard` import |
| `web/src/routes/Tools.svelte` | **新建**：工具层容器，按 `sub` 渲染任务中心/运行记录/运维指标/数据结果 |
| `web/src/routes/Data.svelte` | **新建/由 `Market.svelte` 改造**：信号总览/趋势分析/技术面趋势 |
| `web/src/routes/Strategy.svelte` | 增加 `backtest` 占位子页 |
| `web/src/routes/Trade.svelte` | **新建/由 `Hermes.svelte` 改造**：宏观分析/决策证据/交易指令(占位) |
| `web/src/routes/Settings.svelte` | **新建/由 `System.svelte` 扩展**：系统/关注列表/Discord(可编辑+验证)/定时任务管理/环境变量 |
| `web/src/routes/Dashboard.svelte` | **删除** |
| `web/src/lib/api.ts` | 增加 `jobs.*`（scheduled/reports/metrics/run/patch）与 `settings.*`（getNotify/patchNotify/testNotify/envStatus）客户端方法 |

- 复用现有 `DataTable` / `StatusPill` / `LineChart` / `EChart` / `Skeleton` / `Drawer`，不新增基础组件。
- 占位页（回测、交易指令）：统一一个 `Placeholder.svelte`，接收标题 + 一句话说明 + 「计划于子项目 B/C」标注。

---

## 7. 文档清理

| 文档 | 处理 |
|------|------|
| `docs/architecture.md` | **重写**：删除旧 earnings-agent 内容，改为新 5 层 IA + 调度/通知架构 + 后端分层（api/services/tasks/db） |
| `docs/getting-started.md` | 保留，更新到新结构/新任务（metrics/filings/scores）入口 |
| `docs/sec-downloader.md` | 保留（修正过时的 `SECDownloader` 指向新 `filings/sec_downloader.py`） |
| `docs/hermes-usage.md` | 保留（交易层引用） |
| `docs/scheduling-and-notifications.md` | 保留（上游计划产出） |
| `docs/audit-and-redesign-2026-06.md` | **删除** |
| `docs/test-report.md` | **删除**（"14 用例"早已过时） |
| `docs/execution-plan-2026-06.md` | **确认删除**（git 中已标记 D） |
| `docs/superpowers/plans·specs/*` | 原样保留 |
| `README.md` | 同步：目录结构与导航说明改为 5 层；移除旧 `ops/earnings_monitor.py`/`daily_scan.py` 手动运行段，替换为新任务入口 |

---

## 8. 测试策略

- **后端**：
  - `tests/test_db_sql.py` 追加 `008_notify_settings` 迁移断言。
  - `tests/test_jobs_repository.py`（jobs 4 函数 + notify 2 函数，`FakeConn`/`FakeCursor` 风格对齐现有）。
  - `tests/test_jobs_routes.py` / `test_services_jobs.py`（端点解析 query、404、degraded 降级、PATCH 部分更新）。
  - `tests/test_settings_service.py`（notify overlay 合成、webhook 掩码不回显明文、test 端点经注入的 FakeClient 返回 ok/error、PATCH 留空不清空、`effective_notify_config` 无 DB 时原样返回）。
  - 外部 DB / Discord 全 mock。
- **前端**：`web` 下沿用 vitest，对 `api.ts` 新方法（jobs.* + settings.*）+ 工具层渲染（任务清单/运行记录）+ Discord 表单（验证按钮调用 testNotify、掩码字段不显明文）补测；复用 `EChart.test.ts` 风格对运维指标图表做存在性断言。
- 全部离线可跑，无网络。

---

## 9. 实施顺序（建议拆 PR）

1. **后端 jobs API**：`db.py` jobs 仓储 + `services/jobs.py` + `api/routes/jobs.py` + 测试。
2. **后端 notify settings**：迁移 `008` + `db.py` notify 仓储 + `services/settings.py`（overlay/掩码/test）+ `api/routes/settings.py` + 测试。
3. **前端 IA 骨架**：SideNav + app.svelte 5 层路由 + 占位页 + 旧页平移（不含工具层/设置层新页）。
4. **工具层四分页**：消费 1 的 API。
5. **设置层**：Discord 可编辑+验证（消费 2）/ 定时任务管理（PATCH）/ 环境变量 / 关注列表归位。
6. **文档清理**：architecture 重写 + README + 删除过时文档。

---

## 10. 风险与决策记录

- **总览关闭**：本期不做落地总览，默认入工具层；后续以通知形式补。若用户后续要总览页，是独立增量。
- **Discord 可编辑（webhook 模式）**：用户暂无法立即提供 webhook，故设置层支持 UI 配置 + 验证按钮。持久化落 DB 单行 `notify_settings`，overlay 到文件基线配置；明文不回显（GET 掩码），仅 PATCH/test 单向写入。维持 webhook 模式、不引入 Bot Token。
- **迁移编号 008 与 Phase 2 冲突**：见 §5.0，先落地者占 008。
- **`scheduled_jobs` 是唯一 UI 可写配置**：因其本就是 DB 表，`time_local`/`enabled` 列可安全更新；改时间时 `update_scheduled_job` 一并置 `next_run_at=NULL`，由调度器下一 tick 重算下次运行（见 §5.1）。
- **REGISTRY 依赖上游 Task 8**：手动触发依赖 `tasks.scheduler.REGISTRY`；若上游该任务未完成，触发端点先以 `{metrics,filings,scores}` 局部映射兜底。
