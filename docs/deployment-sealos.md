# 部署指南 — Sealos（Starter Plan）

目标平台：[Sealos Cloud](https://sealos.io)，Starter Plan（$7/月）：**2 vCPU / 2Gi 内存 / 10Gi 磁盘 / 10GB 流量/月 / 4 个 NodePort / 100 AI Credits**。

本项目部署形态为「一库一进程」：

| 组件 | 启动命令 | 说明 |
|------|---------|------|
| PostgreSQL | —（Sealos 数据库应用托管） | 唯一持久状态源 |
| API 服务 | 镜像默认 CMD（migrate → uvicorn :8787） | 前端静态页 + `/api/*` + 内嵌调度线程（按 `scheduled_jobs` 表触发任务） |

## 资源规划（总额 2C / 2Gi / 10Gi）

| 组件 | CPU | 内存 | 磁盘 |
|------|-----|------|------|
| PostgreSQL（Sealos 数据库） | 0.5C | 512Mi | 3Gi |
| API 应用 | 0.5C | 768Mi | 挂 1–2Gi 持久卷（filings） |
| 余量 | 1.0C | ~512Mi | ~5Gi |

> 流量注意：前端页面 + JSON API 很轻，但 `/api/events` 是 SSE 常连接（15 秒一次心跳，流量可忽略）。10GB/月对单人使用足够。
> NodePort 不需要：App Launchpad 的公网访问走平台 Ingress（自带 HTTPS 域名）。
> 100 AI Credits 与本项目无关——LLM 功能用的是外部 `DEEPSEEK_API_KEY`。

## 第 0 步：构建并推送镜像

仓库根目录已提供 [Dockerfile](../Dockerfile)（多阶段：node 构建 `web/dist` → python:3.14-slim 运行时）。Registry 用 **Docker Hub**（用户 `jianjustin`），一条命令构建+推送：

```bash
docker login -u jianjustin        # 首次一次即可
scripts/build-push.sh             # → docker.io/jianjustin/investment-assistant:latest + :<git-sha>
```

脚本（[scripts/build-push.sh](../scripts/build-push.sh)）内部用 `docker buildx --platform linux/amd64` 交叉构建——**Sealos 节点是 amd64，Apple Silicon 本机直接 `docker build` 出来的 arm64 镜像在云端无法运行**。每次推送同时打 `latest` 与 git short-sha 两个 tag，后者供回滚。

私有镜像需在 Sealos 部署表单里配置 registry 凭证（或把 Docker Hub 仓库设为 public）。

## 第 1 步：创建数据库

Sealos 控制台 →「数据库」→ 新建 → 类型选 **PostgreSQL**，规格 0.5C/512Mi/3Gi。

创建后在详情页拿到内网连接信息，拼成 psycopg URL：

```
postgresql://<user>:<password>@<内网host>:5432/<database>
```

这个值就是下面两处的 `INVESTMENT_ASSISTANT_DATABASE_URL`。数据库与应用同区域内网互通，不消耗公网流量。

## 第 2 步：部署 API 应用

Sealos 控制台 →「应用管理」（App Launchpad）→ 新建应用：

- **镜像**：`docker.io/jianjustin/investment-assistant:latest`
- **启动命令**：留空（镜像 CMD 自带：先幂等 migrate，再起 uvicorn）
- **CPU/内存**：0.5C / 768Mi
- **端口**：容器端口 `8787`，开启「公网访问」（平台分配 HTTPS 域名）
- **持久卷**：挂载 `/srv/investment-assistant/filings`，1–2Gi（SEC filings 下载目录；定时与手动下载都由本进程执行，文件统一落此卷）

**环境变量（API 应用）**：

| 变量 | 必填 | 值/说明 |
|------|------|---------|
| `INVESTMENT_ASSISTANT_DATABASE_URL` | ✅ | 第 1 步的 postgres URL |
| `SERVER_PWD` | ✅ | HTTP Basic 密码。**不设则服务拒绝启动**（fail-closed：镜像内绑定 0.0.0.0 必须配密码） |
| `HERMES_DASHBOARD_USER` | 建议 | Basic 用户名（默认 `jianjustin`） |
| `SEC_USER_AGENT` | 建议 | SEC EDGAR 要求格式：`名字 邮箱`，缺失则 filings 下载会被限流 |
| `DEEPSEEK_API_KEY` | 可选 | 不设则 LLM 宏观分析/决策证据降级返回错误（不崩） |
| `DISCORD_WEBHOOK_EARNINGS` / `_SIGNALS` / `_DAILY` | 可选 | 也可部署后在「设置 → Discord 推送」页面配置（存数据库，优先级高于 env） |
| `SCHEDULER_TICK_SECONDS` | 可选 | 调度轮询间隔秒数，默认 60 |
| `SCHEDULER_ENABLED` | 可选 | `0` 关闭内嵌调度线程（调试用），默认 `1` |

> `HERMES_DASHBOARD_HOST=0.0.0.0`、`HERMES_DASHBOARD_PORT=8787`、`HERMES_DASHBOARD_ALLOW_PUBLIC=1` 已内置在镜像中，无需再设。

默认调度（migration 007 内置，America/New_York 时区，周一至五）：`metrics` 08:00、`filings` 09:00、`scores` 18:00。调度线程随 API 进程启动（`SCHEDULER_ENABLED=0` 可关闭，调试用）。

> ⚠️ `event_study` 任务已在调度器注册表中，但 **没有默认调度行**。要让它每日自动跑，在数据库里补一行（Sealos 数据库详情页有 SQL 终端）：
>
> ```sql
> INSERT INTO scheduled_jobs (name, time_local, weekday_mask, timezone)
> VALUES ('event_study', '19:00', '1-5', 'America/New_York')
> ON CONFLICT (name) DO NOTHING;
> ```
>
> 之后可在前端「设置 → 定时任务」里启停/改时间。

## 第 3 步：部署后验证清单

```bash
BASE=https://<平台分配的域名>
AUTH="<用户名>:<SERVER_PWD>"

curl -su "$AUTH" $BASE/api/health | head -20        # 各健康检查项
curl -su "$AUTH" $BASE/api/status | head -10        # database.ok 应为 true（degraded 说明 DB URL 没配对）
curl -su "$AUTH" $BASE/api/does-not-exist            # {"error": "not found"}
curl -su "$AUTH" -o /dev/null -w "%{http_code}\n" $BASE/docs   # 200，OpenAPI 文档页
```

浏览器打开 `https://<域名>`（会弹 Basic 认证）：

1. 「工具 → 任务中心」→ 点某任务的「立即运行」→「工具 → 运行记录」应出现一条报告
2. 「设置 → Discord 推送」→ 填 webhook → 「验证」按钮应收到测试消息
3. 「设置 → 环境变量」→ 核对各 env 配置状态
4. 「策略 → 事件研究」→ 选 kind → 「运行」→ 出结果表（首次为 computed，之后 cache）

## 升级与回滚

```bash
scripts/build-push.sh             # 推 latest + 新 git-sha tag
scripts/build-push.sh v2          # 或显式版本 tag
```

在 API 应用的设置里改镜像 tag 即可滚动更新；回滚 = 改回旧 git-sha tag。migrate 幂等（内部 ledger 记录已应用版本），升级自动补增量 schema；**不支持自动降级 schema**，回滚跨 migration 版本时需人工处理。

## 已知限制

- 单副本部署：任务运行状态（`/api/runs/{id}`）存于 API 进程内存，重启后丢失（`job_reports` 表里的历史不受影响）。API 应用副本数保持 1（防止调度线程双跑）。
- `hermes/run_log` JSONL 写在容器 `/opt/hermes-investment-assistant/logs`，未挂卷时重启即清（只是本地冗余日志，权威记录在 `job_reports`）。
- Obsidian vault 相关路径（`/srv/vault-*`）是本机工作流遗留，容器内不存在也不影响核心功能。
- 调度线程随 API 重启中断，恢复后 `next_run_at <= now` 的过期任务在首个 tick 自动补跑。

## 从两进程形态迁移

1. `scripts/build-push.sh` 构建推送新镜像。
2. **先删除调度器应用**（避免旧调度进程与新 API 调度线程双跑；删除到 API 更新完成之间错过的触发点由补跑覆盖）。
3. API 应用更新镜像 tag；内存建议提到 768Mi；核对原调度器侧的 env（`SEC_USER_AGENT`、`DEEPSEEK_API_KEY`、`DISCORD_WEBHOOK_*`）在 API 侧已配置。
4. 前端任务中心手动回补 filings（按日期范围重下，单次 ≤92 天），`file_path` 随 upsert 自动改指 API 卷。
5. 确认列表页下载正常后，删除调度器应用遗留的 PVC。
