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
earnings-agent/
├── data/                  # 数据获取层（不含信号计算）
│   ├── price.py           # yfinance OHLCV 历史价
│   ├── earnings.py        # yfinance 财报日历
│   └── sec.py             # SEC EDGAR 8-K 下载（Exhibit 99.1 优先）
├── signals/               # 信号计算层
│   ├── market.py          # 大盘环境（SPY 200MA + VIX）
│   └── technicals.py      # 个股技术信号（VCP / RS / MA Reclaim）
├── notify/                # 通知层
│   ├── discord.py         # Discord Webhook 客户端
│   └── templates.py       # Embed 模板（含方向颜色编码）
├── vault/                 # Obsidian 输出层
│   └── writer.py          # 财报分析笔记写入
├── ops/                   # 调度入口
│   ├── earnings_monitor.py  # 财报监听主程序（cron 06:03）
│   ├── daily_scan.py        # 技术面每日扫描（cron 21:00）
│   └── diagnose.py          # SEC EDGAR 调试工具
├── scripts/               # 独立验证脚本
├── tests/                 # pytest 单元测试（全 mock，无网络）
├── docs/                  # architecture / getting-started / test-report
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

### 财报监听

```bash
python ops/earnings_monitor.py                  # 上一交易日
python ops/earnings_monitor.py --date 2026-05-07
python ops/earnings_monitor.py --dry-run        # 仅检测，不下载
```

产物：
- `data/earnings_today.json` — 命中清单 + 8-K 路径，供 Claude Scheduled Task 读取
- `data/earnings_reports/{TICKER}/{accession}.htm` — 下载的 8-K 原文
- `logs/earnings_monitor.log` — 运行日志
- Discord `#earnings-alerts` — 推送通知（已配置时）

### 每日技术面扫描

```bash
python ops/daily_scan.py
```

产物：
- `data/daily_scan.json` — 当日候选清单 + 大盘状态
- `logs/daily_scan.log`
- Discord `#trade-signals` — 个股触发信号
- Discord `#daily-scan` — 每日大盘摘要（必发）

---

## 调度计划（Cowork Scheduled Task）

| Task | Cron | 北京时间 | 美东对应 |
|------|------|----------|----------|
| `earnings-monitor-daily` | `3 6 * * 1-5` | 周一至五 06:03 | 前日 18:03 EDT |
| `daily-scan`             | `0 21 * * 1-5` | 周一至五 21:00 | 当日 09:00 EDT |

示例命令：

```bash
cd /Users/.../earnings-agent && source .venv/bin/activate && python ops/earnings_monitor.py
cd /Users/.../earnings-agent && source .venv/bin/activate && python ops/daily_scan.py
```

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

14 个用例，全部使用 `unittest.mock` 隔离 yfinance / SEC EDGAR / Discord，无任何网络调用，可离线运行。覆盖：
- `notify/discord.py` — 频道路由、HTTP 错误处理
- `data/price.py` — DataFrame 列过滤、空数据异常
- `signals/market.py` — green / yellow / red 三种状态及双触发路径
- `signals/technicals.py` — RS、MA Reclaim、VCP、平价无信号

测试报告详情见 [docs/test-report.md](docs/test-report.md)。

---

## 关键技术注意点

**SEC EDGAR 路径中的 CIK**。EDGAR accession `{filer_cik}-{year}-{sequence}` 的前缀是**报送方**（Filing Agent）的 CIK，而归档路径必须使用**注册方**（Registrant）的 CIK。代码统一从 `company_tickers.json` 解析注册方 CIK，避免对使用 Toppan Merrill 等代理报送的公司（如 RKLB）404。

**yfinance VIX 偶发空数据**。`^VIX` 历史接口有时返回空 DataFrame，`signals/market.py` 在该情形下抛出 `ValueError`；调度脚本将其作为非致命错误记入日志，下一周期会自动恢复。

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

- [docs/architecture.md](docs/architecture.md) — 完整架构、信号定义、Phase 3 预告
- [docs/getting-started.md](docs/getting-started.md) — 起步指南（更详细的安装与配置步骤）
- [docs/test-report.md](docs/test-report.md) — 测试用例与运行记录

Vault 项目计划：`02-项目/美股投资项目/交易Agent-财报监听系统.md`
