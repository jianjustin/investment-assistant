# Hermes Investment Assistant

`investment-assistant` 是 Hermes 投资助手的源代码仓库：仓库存储逻辑、业务规则、数据库 schema、部署模板、测试和文档；业务运行产生的数据存入 Postgres、/srv/investment-assistant/filings 和 /opt/hermes-investment-assistant，不存入 Git。

## Legacy: earnings-agent

> 美股财报与技术面信号的自动化监听系统：每日扫描 watchlist，组合大盘门控、财报事件和技术形态，推送到 Discord 并存档到 Obsidian Vault。

不预测价格，只在**信号叠加充分**时降低决策成本——所有交易判断仍由用户完成。

---

## 当前状态

| Phase | 状态 | 内容 |
|-------|------|------|
| Phase 1 | 已完成 | 财报监听：yfinance 检测 + SEC EDGAR 8-K 下载 + Obsidian 写入 |
| Phase 2 | 已完成 | 分层重构（data/signals/notify/vault/ops）+ Discord 三频道 + 大盘门控 + 技术信号 |
| Phase 3 | 规划中 | 基本面质量评分 + Claude 决策引擎 + 综合评分 |
| Phase 4 | 规划中 | 历史信号回测与准确率统计 |

详细架构与设计见 [docs/architecture.md](docs/architecture.md)。

---

## 核心信号流

```
大盘环境门控 (SPY / VIX)
        │  green / yellow / red
        ▼
个股信号并行计算
  ├─ 财报事件 (EPS / Revenue / Guidance via 8-K)
  └─ 技术面 (VCP / RS / MA Reclaim)
        ▼
Discord 三频道推送  +  Obsidian Vault 存档
  #earnings-alerts · #trade-signals · #daily-scan
```

`red` 状态下，所有个股操作暂停，仅发送每日大盘摘要。

---

## 目录结构

```
investment-assistant/
├── investment_assistant/  # 生产包
│   ├── api/               # HTTP 传输层（router / handler / auth / static / routes）
│   ├── services/          # 业务逻辑层（market / tickers / strategies / hermes / watchlist）
│   ├── tasks/             # 定时任务入口（_harness / scheduler / runner / metrics / filings / nightly_scores）
│   ├── filings/           # SEC EDGAR 下载（SecEdgarDownloader）
│   ├── hermes/            # Hermes 宏观分析与决策证据
│   ├── market/            # 大盘信号
│   ├── tickers/           # 个股趋势
│   └── strategies/        # 策略评分
├── web/                   # Svelte 5 前端（5层 IA：工具/数据/策略/交易/设置）
├── deploy/                # systemd service / timer 文件
├── migrations/            # PostgreSQL schema 迁移（001-008）
├── tests/                 # pytest 单元测试（全 mock，无网络）
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

依赖：`requests`、`python-dotenv`、`yfinance`、`lxml`，以及 yfinance 自带的 `pandas` / `numpy`。

### 2. 配置 `.env`

```env
# SEC EDGAR 要求 User-Agent 必须包含可联系邮箱
SEC_USER_AGENT=YourName your@email.com

# Obsidian Vault 路径
VAULT_PATH=/Users/you/your-obsidian-vault
WATCHLIST_PATH=/Users/you/your-obsidian-vault/02-项目/美股投资项目/watchlist.md

# Discord Webhooks（每个频道一个）
DISCORD_WEBHOOK_EARNINGS=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_SIGNALS=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_DAILY=https://discord.com/api/webhooks/...
```

`.env` 已在 `.gitignore` 中。Discord 配置缺失时只会记录警告，不会中断主流程。

### 3. 配置 watchlist.md

Vault 中的 `watchlist.md` 用 markdown 代码块存放股票代码（与 Obsidian 兼容）：

````markdown
# Watchlist

```
AAPL
NVDA
MSFT
TSLA
RKLB
```
````

代码块内每行一个 ticker；空行与 `#` 注释行会被忽略，大小写不敏感。

---

## 手动运行

```bash
python -m investment_assistant.tasks.metrics          # 08:00 指标采集
python -m investment_assistant.tasks.filings          # 09:00 SEC 财报下载
python -m investment_assistant.tasks.nightly_scores   # 18:00 策略评分
python -m investment_assistant.tasks.scheduler        # 常驻调度守护进程
```

每个任务执行结果写入 `job_reports` 表，并按通知配置推送 Discord。

---

## 调度计划

| 任务 | Cron（US/Eastern） | 说明 |
|------|--------------------|------|
| `metrics` | `0 8 * * 1-5` | 08:00 ET 指标采集 |
| `filings` | `0 9 * * 1-5` | 09:00 ET SEC 财报下载 |
| `nightly_scores` | `0 18 * * 1-5` | 18:00 ET 策略评分 |

调度守护进程读取 `scheduled_jobs` 表（迁移 007），支持通过设置层界面启用/禁用单个任务。详见 [docs/scheduling-and-notifications.md](docs/scheduling-and-notifications.md)。

---

## 验证脚本

`scripts/` 下的脚本无需完整流程即可单独验证模块：

```bash
python scripts/test_discord.py        # 验证 Webhook 连接
python scripts/test_market.py         # 输出当前 SPY / VIX 状态
python scripts/test_vcp.py [TICKER]   # 默认 NVDA，可指定其他 ticker
```

---

## 单元测试

```bash
python -m pytest tests/ -v
```

全部使用 `unittest.mock` 隔离外部依赖（yfinance / SEC EDGAR / Discord / DB），无任何网络调用，可离线运行。

---

## 关键技术注意点

**SEC EDGAR 路径中的 CIK**。EDGAR accession `{filer_cik}-{year}-{sequence}` 的前缀是**报送方**（Filing Agent）的 CIK，而归档路径必须使用**注册方**（Registrant）的 CIK。代码统一从 `company_tickers.json` 解析注册方 CIK，避免对使用 Toppan Merrill 等代理报送的公司（如 RKLB）404。

**yfinance VIX 偶发空数据**。`^VIX` 历史接口有时返回空 DataFrame，`investment_assistant/market/service.py` 的 `compute_market_signal` 在该情形下抛出 `ValueError`；指标任务将其作为非致命错误记入 `job_reports`，下一周期会自动恢复。

**numpy 标量与 `is False`**。技术信号 `has_signal` 必须 `bool(...)` 包装，否则 `numpy.bool_(False) is False` 为 `False`，会让 identity 断言失败。

---

## 环境变量速查

| 变量 | 必需 | 说明 |
|------|------|------|
| `SEC_USER_AGENT` | ✅ | 格式 `Name email@example.com` |
| `VAULT_PATH` | ✅ | Obsidian Vault 根目录 |
| `WATCHLIST_PATH` | ✅ | watchlist.md 的绝对路径 |
| `DISCORD_WEBHOOK_EARNINGS` | ⚠️ | 缺失时跳过通知，不中断 |
| `DISCORD_WEBHOOK_SIGNALS`  | ⚠️ | 同上 |
| `DISCORD_WEBHOOK_DAILY`    | ⚠️ | 同上 |

---

## 相关文档

- [docs/architecture.md](docs/architecture.md) — 五层 IA、后端分层、API 端点映射、迁移清单
- [docs/getting-started.md](docs/getting-started.md) — 安装与配置步骤
- [docs/scheduling-and-notifications.md](docs/scheduling-and-notifications.md) — 调度与 Discord 通知配置
- [docs/sec-downloader.md](docs/sec-downloader.md) — SEC EDGAR 下载器使用说明
