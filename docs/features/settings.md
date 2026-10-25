# 功能验证 — 设置区（Settings）

> 前端入口：侧边栏「⚙️ 设置」。

## 1. 系统（system）

**功能**：数据库/filings/系统服务状态总览 + 运维操作注册表（各操作的风险级别与对应端点）。

- **API**：
  ```bash
  curl -s "localhost:8787/api/status"          # {database, filings, system}
  curl -s "localhost:8787/api/health"          # 多项健康检查（延迟/详情）
  curl -s "localhost:8787/api/services"        # 进程级服务状态
  curl -s "localhost:8787/api/operations"      # {"operations": [...]}
  curl -s "localhost:8787/api/filings/records" # 财报索引 {"records": [...], "tickers": [...]}
  ```
- **如何验证**：`database.ok` 反映 `INVESTMENT_ASSISTANT_DATABASE_URL` 连通性；拔掉 DB URL 重启后各端点应降级（空数据 + degraded）而非 500。

## 2. 关注列表（watchlist）

**功能**：管理 watchlist 标的（ticker/状态/论点）；无 DB 时回退到 config 内置清单（source: config）。

- **手动入口**：设置 → 关注列表 → 「+ 添加」（侧抽屉表单）/ 每行「删除」
- **API**：
  ```bash
  curl -s "localhost:8787/api/watchlist"
  curl -s -X POST "localhost:8787/api/watchlist" -H 'content-type: application/json' -d '{"ticker": "AMD", "status": "watch", "thesis": "测试"}'
  curl -s -X DELETE "localhost:8787/api/watchlist/AMD"
  ```
- **如何验证**：添加后 GET 的 rows 含新行（source: db）；非法 payload → 400 `{"error": ...}`。

## 3. Discord 推送（discord）

**功能**：三频道（earnings/signals/daily）webhook 配置、任务-频道映射、启停；「验证」按钮实发测试消息。配置存 `notify_settings` 表，优先级高于环境变量。

- **手动入口**：设置 → Discord 推送 → 填 URL → 「验证 {频道}」→ 「保存」
- **API**：
  ```bash
  curl -s "localhost:8787/api/settings/notify"     # webhook 只返回 configured 布尔，明文永不回显
  curl -s -X PATCH "localhost:8787/api/settings/notify" -H 'content-type: application/json' -d '{"discord_enabled": true}'
  curl -s -X POST "localhost:8787/api/settings/notify/test" -H 'content-type: application/json' -d '{"channel": "daily"}'
  ```
- **CLI**：`python -m investment_assistant.notify.discord --channel daily`
- **如何验证**：「验证」后 Discord 频道收到测试消息；GET 响应确认无明文 URL（安全契约）。缺 channel 的 test → 400 `{"error": "channel required"}`。

## 4. 定时任务（jobs）

**功能**：启停各调度任务、修改执行时间（`HH:MM` 本地时区）。

- **手动入口**：设置 → 定时任务 → 启用 checkbox / 时间输入框
- **API**：
  ```bash
  curl -s -X PATCH "localhost:8787/api/jobs/scheduled/metrics" -H 'content-type: application/json' -d '{"enabled": false}'
  curl -s -X PATCH "localhost:8787/api/jobs/scheduled/metrics" -H 'content-type: application/json' -d '{"time_local": "08:30"}'
  ```
- **如何验证**：PATCH 后 `GET /api/jobs/scheduled` 反映新值，`next_run_at` 重算。

## 5. 环境变量（env）

**功能**：关键环境变量的配置状态检查（只返回是否已配置的布尔，不回显值）。

- **API**：
  ```bash
  curl -s "localhost:8787/api/settings/env"
  ```
- **如何验证**：与部署实际所配 env 一致（`SEC_USER_AGENT` / `INVESTMENT_ASSISTANT_DATABASE_URL` / `DISCORD_WEBHOOK_*`）。

## 认证（全站机制）

配置 `SERVER_PWD`（或 `HERMES_DASHBOARD_PASSWORD`，前者优先）后，全部路径（含 `/docs`、静态页、SSE）要求 HTTP Basic：

```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:8787/api/status              # 401
curl -s -i localhost:8787/api/status | grep -i www-authenticate                 # Basic realm="Hermes Investment Assistant"
curl -su "jianjustin:<密码>" localhost:8787/api/status                          # 200
```

密码为空 = 无认证模式（仅限本机使用）；公网绑定强制要求密码（fail-closed，见部署文档（已于 v2.0.0 删除））。
