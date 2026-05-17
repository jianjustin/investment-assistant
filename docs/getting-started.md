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

## 手动运行

### 财报监听

```bash
# 检查上一个交易日的财报（自动模式）
python ops/earnings_monitor.py

# 检查指定日期
python ops/earnings_monitor.py --date 2026-05-07

# 仅检测，不下载 8-K
python ops/earnings_monitor.py --dry-run
```

运行后生成：
- `data/earnings_today.json` — 命中结果（供后续 Claude 分析读取）
- `data/earnings_reports/{TICKER}/` — 下载的 8-K 文件
- `logs/earnings_monitor.log` — 运行日志
- Discord `#earnings-alerts` — 推送通知（如已配置）

### 每日技术面扫描

```bash
python ops/daily_scan.py
```

运行后生成：
- `data/daily_scan.json` — 当日候选列表
- `logs/daily_scan.log` — 运行日志
- Discord `#trade-signals` — 有信号的个股通知
- Discord `#daily-scan` — 每日摘要（必发）

---

## 验证脚本

`scripts/` 目录下的脚本用于独立验证各模块，不需要完整配置即可运行部分功能。

### 验证大盘环境检测

```bash
python scripts/test_market.py
```

示例输出：
```
大盘环境:
  Status      : GREEN
  VIX         : 17.3
  SPY > 200MA : True
```

### 验证技术面信号

```bash
# 默认检测 NVDA
python scripts/test_vcp.py

# 指定 ticker
python scripts/test_vcp.py AAPL
```

示例输出：
```
NVDA 技术信号:
  RS Score    : 1.85  ✅ 强势 (≥1.2)
  VCP         : —
  MA Reclaim  : —
  Has Signal  : ✅ 是
```

### 验证 Discord 连接

```bash
python scripts/test_discord.py
```

需要 `.env` 中已填入真实 Webhook URL。

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
data/           数据获取 (yfinance, SEC EDGAR)
signals/        信号计算 (大盘门控, VCP/RS/MA)
notify/         Discord 通知
vault/          Obsidian 写入
ops/            调度入口 (earnings_monitor, daily_scan)
scripts/        手动验证脚本
tests/          单元测试
docs/           项目文档
```

完整架构说明见 [architecture.md](architecture.md)。
