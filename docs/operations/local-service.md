# 本机服务

v2.0.0 只支持本机运行：一台 macOS，一个用户级 LaunchAgent，一个 PostgreSQL。

## 启动链路

```
~/Library/LaunchAgents/local.investment-assistant.plist（不在仓库里）
  RunAtLoad + KeepAlive，WorkingDirectory = 仓库根目录
  └─ ./start.command
       └─ .venv/bin/python scripts/start_local.py
            读取仓库 .env；SCHEDULER_ENABLED 以文件为准（默认 1）；强制监听 127.0.0.1
            └─ investment_assistant.api.server（uvicorn，端口 HERMES_DASHBOARD_PORT，默认 8787）
```

- 用户登录时启动，退出登录后停止；电脑需要保持开机和唤醒，定时任务才会按时跑。
- 调度线程随 API 进程启动；下次运行时间为空的任务在开启调度后立即执行一次，不会逐日补跑历史缺口。

## 常用操作

```bash
# 重启（改了 .env、拉了新代码、重建了前端之后）
launchctl kickstart -k gui/$(id -u)/local.investment-assistant
```

```bash
# 看服务是否在跑
launchctl print gui/$(id -u)/local.investment-assistant | grep -E 'state|pid'
```

```bash
# 健康检查
curl -s http://127.0.0.1:8787/api/status
```

前端改动后要先 `cd web && npm run build`，再重启服务。`web/dist` 不入库。

## 路径

| 用途 | 本机位置 |
| --- | --- |
| 服务日志 | `~/Library/Application Support/investment-assistant/logs/service.stdout.log`、`service.stderr.log` |
| 运行目录（`INVESTMENT_ASSISTANT_RUNTIME_BASE`） | `~/Library/Application Support/investment-assistant` |
| 配置文件（`INVESTMENT_ASSISTANT_CONFIG`） | `config/local.json` |
| SEC 下载（`filings.output_dir`）与正文报告（`FILINGS_REPORT_DIR`） | 配置文件与 `.env` 中指定的目录 |
| 迁移前备份、验收证据 | `.local/`（不入库） |

`investment_assistant/runtime_paths.py` 里的 `/opt/...`、`/srv/...` 是未设置环境变量时的默认值。本机都通过上表中的环境变量和配置覆盖掉了。

## 运行状态从哪里看

- 「工具 → 任务中心」：每个任务的启停、上次/下次运行、立即运行、按日期运行（单日或范围，上限 92 天）。
- 「工具 → 运行记录」：`job_reports`，每 15 秒刷新；点「详情」看 `summary`。
- 「设置 → 系统」：数据库、调度线程、各服务状态；`GET /api/health` 给出各项检查。
- 「设置 → 环境变量」：只显示是否已配置，不回显值。

## 认证

配置 `SERVER_PWD`（或 `HERMES_DASHBOARD_PASSWORD`，前者优先）后，全部路径都要 HTTP Basic，用户名取 `HERMES_DASHBOARD_USER`（默认 `jianjustin`）。密码为空即无认证，只适合只监听 `127.0.0.1` 的本机服务。
