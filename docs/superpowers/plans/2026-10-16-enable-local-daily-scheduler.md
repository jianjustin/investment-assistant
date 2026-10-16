---
title: 开启本地调度并让运行记录显示真实调度状态
tags: [调度, 本地运行, 故障修复]
created: 2026-10-16
---

# 开启本地调度并让运行记录显示真实调度状态

故障由本地服务的启动环境和 `.env` 中的 `SCHEDULER_ENABLED=0` 导致，自动调度线程未启动。修复同时恢复实际调度、展示服务级开关和心跳，并持续刷新运行记录。

## 修复前的证据

- `http://127.0.0.1:8787/api/jobs/reports` 只有 2026-10-14 的 7 条手动记录。
- 三个 `scheduled_jobs` 均为启用，但 `last_run_at`、`next_run_at` 均为空；`/api/health` 返回调度未启用。
- 任务中心只显示单个任务的 `enabled`，未显示全局调度器被关闭；运行记录页没有定期刷新。
- 原服务由 OpenClaw 子进程托管，没有独立的本地登录启动配置。修复后的本地服务需要保留明确的启动入口和日志位置。

## 修改方案

1. 在 `/api/jobs/scheduled` 增加轻量的 `scheduler` 状态，复用调度健康检查，不调用外部服务探测。明确区分总开关关闭、缺少数据库、首次轮询未完成、心跳超时和轮询失败。
2. 在任务中心和运行记录页显示调度状态、原因；任务计划显示所在时区。记录页每 15 秒刷新并提供手动刷新，请求失败时保留已有记录并提示。
3. 将本地 `.env` 中的 `SCHEDULER_ENABLED` 改为 `1`。增加 `start.command`，从本地 `.env` 读取配置并覆盖继承的旧配置，绑定 `127.0.0.1:8787`。
4. 使用独立的 macOS 用户 LaunchAgent 启动该入口并保存日志。替换前核对端口进程身份，仅停止已确认的旧投资助手进程，不停止 OpenClaw 或其他服务。

## 验证方式

- 后端回归：关闭总开关但单项任务启用、缺少数据库、正常心跳、轮询失败及恢复、计划接口返回状态。
- 前端回归：关闭原因可见、定时触发标签、定期刷新及组件卸载清理、刷新失败保留旧记录；通过类型检查和生产构建。
- 本地运行：读取新进程启动信息和计划接口，确认调度已启用；等待三个任务的真实自动执行报告进入数据库，来源为 `scheduled`，随后验证下一次运行时间已更新。
- 浏览器验证：任务中心展示时区和全局状态，运行记录展示真实自动报告及刷新入口。

## 执行范围与限制

- 沿用当前纽约时间周一至周五的计划：metrics 08:00、filings 09:00、scores 18:00。
- 当前下次运行时间为空，开启后的首次轮询会立即执行三任务。任务可能因外部数据服务失败产生真实错误报告，必须如实保留。
- 首次执行不等同于逐日补齐历史缺口，本次不改写已有记录，也不执行历史回补或交易。
- 当前通知目标和发送凭据均未配置；本次不增加外发目标或开启邮件通知。
- 服务仅本地运行；电脑关机、睡眠或用户退出登录期间无法持续执行，恢复后按现有过期任务规则执行一次，不逐日重放。

## 恢复方式

如需关闭自动调度，将本地 `.env` 的 `SCHEDULER_ENABLED` 设为 `0`，再重启此用户 LaunchAgent。保留数据库和历史报告；移除 LaunchAgent 只影响本地服务启动，不删除数据。

## 本机使用

- 页面入口：`http://127.0.0.1:8787/#tools/runs`。
- 登录服务：`~/Library/LaunchAgents/local.investment-assistant.plist`；入口为仓库根目录的 `start.command`，仅监听回环地址。
- 重启已安装服务：`launchctl kickstart -k gui/$(id -u)/local.investment-assistant`。服务正在运行时不重复执行 `start.command`。
- 停止服务并取消本次登录会话中的托管：`launchctl bootout gui/$(id -u)/local.investment-assistant`。下次登录仍会按保留的 plist 启动。
- 日志：`~/Library/Application Support/investment-assistant/logs/service.stdout.log`、`service.stderr.log`。沿用原进程的本机 HTTP/HTTPS 代理 `127.0.0.1:1082`；服务配置不保存数据库或通知凭据。

## 验证结果（2026-10-16）

- 后端全量：306 项通过、1 项跳过。前端全量：57 项通过；本机 Node 26 使用 `NODE_OPTIONS=--no-experimental-webstorage npm test -- --reporter=dot`，避免 Node 原生实验性存储覆盖 jsdom 测试环境。
- 生产构建成功，Svelte 类型检查无错误；保留既有 `FetchDateModal` 警告和构建包大小警告。独立只读审查未发现交付阻碍。
- 用户 LaunchAgent 已运行，服务 PID 为 73936，监听 `127.0.0.1:8787`；调度启用且首轮完成。
- 未调用手动运行接口，数据库新增以下真实记录；原 7 条手动记录保留，总计 10 条。

| 任务 | 自动执行记录 | 页面状态 | 耗时 |
| --- | --- | --- | --- |
| metrics | `metrics-20261016022711-3c9de97f` | success / 定时 | 13.2 秒 |
| filings | `filings-20261016022725-78a3c8d6` | success / 定时 | 105.1 秒 |
| scores | `scores-20261016022910-c0a62783` | success / 定时 | 0.0 秒 |

下一次计划（北京时间）：metrics 2026-10-16 20:00，filings 2026-10-16 21:00，scores 2026-10-17 06:00。浏览器已验证全局状态、计划时区、定时标签、自动刷新与手动刷新入口。

财报任务本轮返回下载 0 份，摘要没有错误，但服务日志存在 SEC `company_tickers.json` 的连接重置和 TLS EOF 错误。因此本轮只证明调度、执行与记录写入恢复，不能据此确认目标日无披露或 SEC 数据完整；SEC 连接及空结果错误呈现需独立排查。

## 代码依据

- `investment_assistant/api/app.py`：调度线程启动条件。
- `investment_assistant/tasks/scheduler.py`：到期任务执行、下一次计划和心跳。
- `investment_assistant/services/jobs.py`：计划及历史接口。
- `web/src/routes/Tools.svelte`：任务中心和运行记录展示。
- `migrations/007_scheduled_jobs.sql`：默认计划。
