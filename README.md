# Hermes Investment Assistant

`investment-assistant` 是 Hermes 投资助手的源代码仓库：仓库存储逻辑、业务规则、数据库 schema、部署模板、测试和文档；业务运行产生的数据存入 Postgres、/srv/investment-assistant/filings 和 /opt/hermes-investment-assistant，不存入 Git。

## Legacy: earnings-agent

> 美股财报与技术面信号的自动化监听系统：每日扫描 watchlist，组合大盘门控、财报事件和技术形态，推送到 Discord 并存档到 Obsidian Vault。

不预测价格，只在**信号叠加充分**时降低决策成本——所有交易判断仍由用户完成。

早期实现依赖 Obsidian Vault（`VAULT_PATH` / `WATCHLIST_PATH`）存档财报、通过 `watchlist.md` 管理关注列表，以及 `scripts/` 目录下的验证脚本（`test_discord.py` / `test_market.py` / `test_vcp.py`）。这些能力已随重构迁移到数据库（`watchlist_items` 表）与面板 UI，原 Vault 路径和验证脚本不再使用。

---

## 当前状态

当前系统基于 FastAPI + uvicorn，使用 PostgreSQL 存储调度状态、任务报告、市场信号和策略评分。FastAPI、邮件渠道与六入口 UI 已实现。详细架构与设计见 [docs/architecture.md](docs/architecture.md)；Roadmap 见 [docs/roadmap/](docs/roadmap/)。

**2026-10-17，基线 `6fd63f8`**：本轮扫描/历史评分/事件研究修复及来源补强正在最终复核，最终测试数字待补，不以基线后端 526 passed / 52 skipped、前端 129 passed 冒充最终结果。Phase 0 全部正式 Gate HOLD；当前 DB 回环不可达（当前行数 unknown，不是 0），HTTP/UI 未验收。长期通用 OHLCV/广度/FRED/EPS surprise、计划—执行—复盘闭环及 Phase 3 均未完成。详见 [实施状态与验收边界](docs/implementation-status-2026-10-17.md)和 [Phase 0 只读评审](docs/roadmap/reports/2026-10-17-phase0-review.md)。本轮未补采、未写真实 DB/执行迁移、未通知、交易、部署或 commit/push。

A 股研究现已接入“数据 → A 股研究数据”和“策略 → 研究观察卡”，首个真实样本为澜起科技 `688008.SH`。只在本地运行，A 股研究不发通知，定时开关沿用本机既有配置；使用独立上海交易日历。局部复用 CNEquity 0.16.0，严格历史 PIT、公告全文解析和产品分部提取尚未实现。详见 [A 股接入与验证报告](docs/ashare-research.md)。下述 SPY/VIX 信号流仅适用于既有美股流程。

A 股多股票关注与美股研究数据已完成本地实现和 Agent 验证，支持现有 8 只美股的实际财季、来源追溯、跨市场观察卡及版本化指引。12 行财季不代表指标完整或连续；TSLA 有既有来源规则导致的缺口，无法核实的估值保持为空，仍保留一项旧值提示误报，用户手动验收待完成。详见 [跨市场研究与本地验证](docs/cross-market-research.md)。

---

## 现有信号与研究链路

SPY/VIX 市场状态、个股均线/量比/相对收益与策略评分已有工程实现；SEC 监控保留正文事实和公司指引来源，A 股/美股研究通过独立数据与观察卡工作流展示。通知按配置选择 Discord 或邮件，不代表本轮已发送。

原“EPS/Revenue/Guidance + VCP/RS/MA 全部叠加后推送”的图不能代表当前已验收能力：EPS surprise/VCP 事件源不可用，`rs_strong` 旧阈值 1.2 的收益差单位未确认而挂起，`ma_reclaim` 为 SMA20 上穿，不是 21EMA。事件研究目前只有受限探索证据，全部正式 Gate HOLD；不要把市场门控、分数或未校正 CI 解释为交易指令。

---

## 目录结构

```
investment-assistant/
├── investment_assistant/  # 生产包
│   ├── api/               # HTTP 传输层（FastAPI：app / auth / server / static_files / routes）
│   ├── services/          # 业务逻辑层（market / tickers / strategies / hermes / watchlist）
│   ├── tasks/             # 定时任务入口（_harness / scheduler / runner / metrics / filings / nightly_scores）
│   ├── filings/           # SEC EDGAR 下载（SecEdgarDownloader）
│   ├── hermes/            # Hermes 宏观分析与决策证据
│   ├── market/            # 大盘信号
│   ├── tickers/           # 个股趋势
│   └── strategies/        # 策略评分
├── web/                   # Svelte 5（六入口：工具/数据/技术面趋势/策略/交易/设置）
├── deploy/                # systemd service 文件
├── migrations/            # PostgreSQL schema 迁移（001-014）
├── tests/                 # pytest 离线回归与显式临时表集成测试
├── docs/                  # 架构文档
├── .env                   # 环境变量（不入库）
└── requirements.txt
```

---

## 快速开始

### 1. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest  # 仅在跑测试时需要
```

依赖：`fastapi`、`uvicorn`、`requests`、`python-dotenv`、`yfinance`、`lxml`，以及 yfinance 自带的 `pandas` / `numpy`。

### 2. 配置 `.env`

```env
# SEC EDGAR 要求 User-Agent 必须包含可联系邮箱
SEC_USER_AGENT=YourName your@email.com

# PostgreSQL — 可选；不配置时报告/快照路径跳过，不影响离线运行
INVESTMENT_ASSISTANT_DATABASE_URL=postgresql://user:pass@localhost:5432/investment

# Discord Webhooks（每个频道一个）
DISCORD_WEBHOOK_EARNINGS=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_SIGNALS=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_DAILY=https://discord.com/api/webhooks/...
SMTP_PASSWORD=<Gmail 应用专用密码；邮件渠道启用时必需>
```

`.env` 已在 `.gitignore` 中。Discord 配置缺失时只会记录警告，不会中断主流程。

### 3. 配置关注列表

在面板「设置 · 关注列表」页通过 UI 添加/删除 ticker（`POST /api/watchlist` / `DELETE /api/watchlist/{ticker}`），或在配置文件 `watchlist` 字段中指定默认列表（无 DB 时使用）。

---

## 手动运行

```bash
python -m investment_assistant.api.server             # API server（FastAPI + uvicorn，默认 8787 端口）
python -m investment_assistant.tasks.metrics          # 08:00 指标采集
python -m investment_assistant.tasks.filings          # 09:00 SEC 财报下载
python -m investment_assistant.tasks.nightly_scores   # 18:00 策略评分
```

调度线程随 API 服务启动（`SCHEDULER_ENABLED=0` 可关）。

macOS 本地使用仓库根目录的 `./start.command`：它先加载本地 `.env`，以文件中的 `SCHEDULER_ENABLED` 为准，避免继承旧值 `0`，并只监听 `127.0.0.1`。本机已配置的 `local.investment-assistant` 用户 LaunchAgent 在登录时启动此入口；日志位于 `~/Library/Application Support/investment-assistant/logs/service.stdout.log` 和 `service.stderr.log`。已有服务运行时不重复启动入口，修改 `.env` 后用 `launchctl kickstart -k gui/$(id -u)/local.investment-assistant` 重启。

任务中心及运行记录显示服务级调度状态；“任务启用”仅表示该任务自己的开关。运行记录每 15 秒刷新，也可手动刷新。下次运行时间为空的任务会在开启调度后立即执行一次，不会自动逐日重放历史缺口。电脑需要保持运行和唤醒，用户退出登录后此用户服务也会退出。

API server 启动后可访问 `http://localhost:8787/docs` 查看全部端点的 OpenAPI 文档。

每个任务执行结果写入 `job_reports` 表，并按通知配置推送 Discord。

---

## 调度计划

本机已迁移的 SEC 监控沿用美东工作日 **20:30**，直接通知 Discord `#investment`；下面是其他实例的默认种子计划。监控每轮重读正式 SEC 观察名单，从 2026-10-01 扫描到美东当日，保留 TSLA、8-K 筛选和历史去重。新报告提取正文财务事实和公司指引原文，保留期间、口径及来源；不支持的格式标记待核验。见 [SEC 监控接管说明](docs/sec-monitor-migration.md)。

| 任务 | 时间（US/Eastern，周一~五） | 说明 |
|------|-----------------------------|------|
| `metrics` | 08:00 | 指标采集（大盘信号 + 个股趋势快照） |
| `filings` | 09:00 | SEC 财报下载（T-1 当天 filed） |
| `scores` | 18:00 | 策略评分扫描（模块：tasks.nightly_scores） |
| `event_study` | 无默认调度行 | 事件研究（需手动 INSERT 或经「设置 → 定时任务」启用） |

调度线程内嵌于 API 进程，读取 `scheduled_jobs` 表（迁移 007），支持通过设置层界面启用/禁用单个任务。详见 [docs/scheduling-and-notifications.md](docs/scheduling-and-notifications.md)。

---

## 验证

```bash
# 普通离线回归：移除数据库环境，数据库测试按条件跳过
env -u INVESTMENT_ASSISTANT_DATABASE_URL -u INVESTMENT_ASSISTANT_TEST_DATABASE_URL -u TEST_DATABASE_URL .venv/bin/python -m pytest tests/ -q

# 验证 API 可访问（需先启动服务）
curl -u "$HERMES_DASHBOARD_USER:$SERVER_PWD" http://localhost:8787/api/status

# 验证 Discord 推送：在面板「设置 · Discord 推送」页点「验证」按钮即时测试
```

---

## 单元测试

```bash
env -u INVESTMENT_ASSISTANT_DATABASE_URL -u INVESTMENT_ASSISTANT_TEST_DATABASE_URL -u TEST_DATABASE_URL .venv/bin/python -m pytest tests/ -v
```

普通回归隔离外部网络及数据库依赖，可离线运行；真实 SQL 行为由单独审查的 TEMP 表测试覆盖。不要给完整套件配置生产 `TEST_DATABASE_URL`，旧迁移集成测试会写业务表；安全边界与最终结果见 [跨市场验证报告](docs/cross-market-research.md)。

---

## 关键技术注意点

**SEC EDGAR 路径中的 CIK**。EDGAR accession `{filer_cik}-{year}-{sequence}` 的前缀是**报送方**（Filing Agent）的 CIK，而归档路径必须使用**注册方**（Registrant）的 CIK。代码统一从 `company_tickers.json` 解析注册方 CIK，避免对使用 Toppan Merrill 等代理报送的公司（如 RKLB）404。

**yfinance VIX 偶发空数据**。`^VIX` 历史接口有时返回空 DataFrame，`investment_assistant/market/service.py` 的 `compute_market_signal` 在该情形下抛出 `ValueError`；指标任务将其作为非致命错误记入 `job_reports`，下一周期会自动恢复。

**numpy 标量与 `is False`**。技术信号 `has_signal` 必须 `bool(...)` 包装，否则 `numpy.bool_(False) is False` 为 `False`，会让 identity 断言失败。

---

## 环境变量速查

| 变量 | 必需 | 说明 |
|------|------|------|
| `SEC_USER_AGENT` | ✅ | 格式 `Name email@example.com`；本机 SEC 监控缺失时记录错误并告警 |
| `INVESTMENT_ASSISTANT_DATABASE_URL` | ✅（生产） | PostgreSQL 连接 URL；缺失时大多数端点降级（`degraded:true`），内嵌调度线程不启动 |
| `HERMES_DASHBOARD_USER` | ⚠️ | HTTP Basic 认证用户名，默认 `jianjustin` |
| `SERVER_PWD` | ⚠️ | HTTP Basic 认证密码（高优先级）；空字符串 = 无认证 |
| `DEEPSEEK_API_KEY` | ⚠️ | DeepSeek LLM；缺失时 macro-analysis/run 等 LLM 功能降级 |
| `DISCORD_WEBHOOK_EARNINGS` | ⚠️ | 缺失时跳过通知，不中断 |
| `DISCORD_WEBHOOK_SIGNALS`  | ⚠️ | 同上 |
| `DISCORD_WEBHOOK_DAILY`    | ⚠️ | 同上 |
| `SMTP_PASSWORD`            | ⚠️ | 邮件渠道启用时必需；缺失时跳过邮件通知，不中断 |

---

## 相关文档

完整文档索引见 [docs/README.md](docs/README.md)，包含架构说明、起步指南、调度配置、SEC 下载器、事件研究等各主题链接。
