# 起步指南

## 前置条件

- Python 3.10+
- Discord 服务器管理权限（创建 webhook）
- Obsidian vault（可选，用于笔记存档）
- SEC EDGAR 用户标识（免费，填邮箱即可）

---

## 安装

```bash
# 克隆仓库
git clone <repo-url>
cd earnings-agent

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装测试依赖
pip install pytest
```

---

## 配置 .env

在项目根目录创建 `.env`（已在 `.gitignore` 中，不会提交）：

```env
# SEC EDGAR — 必填，格式固定
SEC_USER_AGENT=YourName your@email.com

# 路径配置
VAULT_PATH=/Users/you/your-obsidian-vault
WATCHLIST_PATH=/Users/you/your-obsidian-vault/02-项目/美股投资项目/watchlist.md

# Discord webhooks — 见下方"配置 Discord"章节
DISCORD_WEBHOOK_EARNINGS=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_SIGNALS=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_DAILY=https://discord.com/api/webhooks/...
```

---

## 配置 watchlist.md

watchlist.md 使用 markdown 代码块格式存放股票代码（与 Obsidian 兼容）：

```markdown
# Watchlist

```
AAPL
NVDA
MSFT
TSLA
RKLB
```
```

程序会解析代码块内的每一行，大小写不敏感，空行和 `#` 注释行自动跳过。

---

## 配置 Discord

### 创建频道和 Webhook

1. 在 Discord 服务器创建三个文本频道：
   - `#earnings-alerts`
   - `#trade-signals`
   - `#daily-scan`

2. 每个频道：**频道设置 → 整合 → Webhook → 新建 Webhook**

3. 复制 Webhook URL，分别填入 `.env` 对应字段

### 验证连接

```bash
python scripts/test_discord.py
```

成功输出：`✅ Discord #earnings-alerts 发送成功`，并在频道中看到测试消息。

---

## 子流程独立运行

每个子流程都可以单独调用，无需启动完整的调度链。适用于调试、回测或按需触发。

---

### 子流程 1：拉取财报（SEC EDGAR 下载）

#### 单次模式：下载指定日期附近最近的 8-K

```bash
# 拉取 AAPL 今天附近最近的 8-K（默认）
python data/sec.py AAPL

# 指定财报日期
python data/sec.py AAPL --date 2026-05-01

# 指定输出目录（默认：data/earnings_reports）
python data/sec.py AAPL --date 2026-05-01 --out /tmp/my-reports
```

输出示例：
```
INFO AAPL: using 8-K dated 2026-05-01 (accession 0000320193-26-000056)
INFO Downloaded: data/earnings_reports/AAPL/0000320193-26-000056.htm
Downloaded: data/earnings_reports/AAPL/0000320193-26-000056.htm
```

#### 批量模式：拉取过去 N 年的 8-K 和 10-Q

```bash
# 过去 3 年的 8-K 和 10-Q（默认表单）
python data/sec.py AAPL --years 3

# 只拉 10-Q
python data/sec.py NVDA --years 3 --form 10-Q

# 指定起始日期
python data/sec.py TSLA --since 2023-01-01 --form 8-K,10-Q

# 指定输出目录
python data/sec.py AAPL --years 3 --out /tmp/aapl-filings
```

文件落盘结构：
```
data/earnings_reports/
└── AAPL/
    ├── 8-K/
    │   ├── 0000320193-26-000056.htm   # Q1 2026
    │   ├── 0000320193-25-000089.htm   # Q4 2025
    │   └── ...
    └── 10-Q/
        ├── 0000320193-25-000123.htm   # Q3 2025
        └── ...
```

输出示例：
```
INFO AAPL: 35 filing(s) since 2023-05-20 (8-K, 10-Q)
INFO Downloaded: data/earnings_reports/AAPL/8-K/0000320193-26-000056.htm
INFO Downloaded: data/earnings_reports/AAPL/10-Q/0000320193-25-000123.htm
...
Downloaded 35 filing(s) to data/earnings_reports/AAPL/
```

---

### 子流程 2：发送 Discord 消息

```bash
# 发送测试消息到 #earnings-alerts（默认）
python notify/discord.py

# 指定频道
python notify/discord.py --channel signals
python notify/discord.py --channel daily
```

需要 `.env` 中已填入真实 Webhook URL。输出：
```
✅ 测试消息已发送至 #earnings
```

---

### 子流程 3：财报监听（检测 + 下载 + 推送）

```bash
# 检查上一个交易日的财报（自动模式）
python ops/earnings_monitor.py

# 检查指定日期
python ops/earnings_monitor.py --date 2026-05-07

# 仅检测，不下载 8-K（不发 Discord）
python ops/earnings_monitor.py --dry-run
```

运行后生成：
- `data/earnings_today.json` — 命中结果（供后续 Claude 分析读取）
- `data/earnings_reports/{TICKER}/` — 下载的 8-K 文件
- `logs/earnings_monitor.log` — 运行日志
- Discord `#earnings-alerts` — 推送通知（如已配置）

---

### 子流程 4：每日技术面扫描

```bash
# 正常运行（扫描 + 发 Discord）
python ops/daily_scan.py

# 仅扫描，不发送 Discord 消息
python ops/daily_scan.py --dry-run
```

运行后生成：
- `data/daily_scan.json` — 当日候选列表
- `logs/daily_scan.log` — 运行日志
- Discord `#trade-signals` — 有信号的个股通知（非 dry-run）
- Discord `#daily-scan` — 每日摘要（非 dry-run）

---

### 子流程验证脚本（仅检测，无副作用）

| 脚本 | 用途 | 所需配置 |
|---|---|---|
| `python scripts/test_market.py` | 检测大盘环境（SPY/VIX） | 无（yfinance） |
| `python scripts/test_vcp.py [TICKER]` | 检测个股技术信号 | 无（yfinance） |
| `python scripts/test_discord.py` | 验证 Discord webhook 连通性 | `.env` Webhook URL |

`test_market.py` 示例输出：
```
大盘环境:
  Status      : GREEN
  VIX         : 17.3
  SPY > 200MA : True
```

`test_vcp.py AAPL` 示例输出：
```
AAPL 技术信号:
  RS Score    : 1.85  ✅ 强势 (≥1.2)
  VCP         : —
  MA Reclaim  : —
  Has Signal  : ✅ 是
```

---

## 配置定时任务（Cowork Scheduled Task）

### 财报监听 — 每天 06:03 北京时间

```
Task ID: earnings-monitor-daily
Cron:    3 6 * * 1-5
命令:    cd /path/to/earnings-agent && source .venv/bin/activate && python ops/earnings_monitor.py
```

### 每日扫描 — 每天 21:00 北京时间

```
Task ID: daily-scan
Cron:    0 21 * * 1-5
命令:    cd /path/to/earnings-agent && source .venv/bin/activate && python ops/daily_scan.py
```

---

## 运行测试

```bash
# 运行所有单元测试
python -m pytest tests/ -v

# 运行特定模块测试
python -m pytest tests/test_technicals.py -v
```

所有测试均使用 mock，不调用真实网络接口，可离线运行。

---

## 常见问题

**Q: `No price data returned for ^VIX`**  
A: yfinance 有时对 VIX 返回空数据，重试通常可以解决。如果持续失败，检查网络连接。

**Q: `Discord notification skipped`**  
A: `.env` 中的 Webhook URL 是占位符，需替换为真实 URL。这是非致命错误，其他功能不受影响。

**Q: `Watchlist not found`**  
A: `WATCHLIST_PATH` 路径不存在或路径错误，检查 `.env` 配置。

**Q: SEC EDGAR 下载失败**  
A: SEC EDGAR 有访问频率限制，重试或检查 `SEC_USER_AGENT` 格式（必须包含邮箱）。

---

## 项目结构快速参考

```
investment_assistant/   生产包（api / services / tasks / filings / …）
web/                    Svelte 5 前端（工具 / 数据 / 策略 / 交易 / 设置 五层 IA）
migrations/             PostgreSQL schema 迁移（001-008）
tests/                  单元测试
docs/                   项目文档
```

完整架构说明见 [architecture.md](architecture.md)。
