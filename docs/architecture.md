# earning-agent — 架构与产品文档

> ⚠️ 已废弃（2026-06-27）：本文描述的 earnings-agent 旧代码库（data/ signals/ notify/ ops/ vault/）已删除。
> 当前生产架构见 docs/audit-and-redesign-2026-06.md 与 docs/execution-plan-2026-06.md。

> 美股量化分析系统：从市场信号到 Discord 通知的自动化投资辅助工具。

---

## 产品定位

earning-agent 不预测价格，而是在**信号叠加充分**时降低决策成本：

- 财报超预期 → 短期事件驱动机会
- VCP 收缩 + RS 强势 → 技术面突破前兆
- 大盘环境 → 门控所有个股信号，熊市不开多

输出形式：Discord 多频道推送 + Obsidian 结构化存档。

---

## 系统路线图

| Phase | 状态 | 核心功能 |
|-------|------|----------|
| Phase 1 | ✅ 已完成 | 财报监听：yfinance 检测 + SEC EDGAR 下载 + Obsidian 写入 |
| **Phase 2** | **✅ 已完成** | 分层架构重组 + Discord 多频道通知 + 市场门控 + 技术面信号 |
| Phase 3 | 📋 规划中 | 基本面质量评分 + Claude 决策引擎 + 综合评分 |
| Phase 4 | 📋 规划中 | 历史信号回测 + 准确率统计 |

---

## 信号流

```
┌──────────────────────────────────────────────────────────┐
│  Layer 0: 大盘环境门控                                    │
│  SPY 200MA 趋势 + VIX 水平                               │
│  → green / yellow / red                                  │
│  red 状态：个股信号全部暂停，仅发送每日摘要               │
└───────────────────────────┬──────────────────────────────┘
                            ↓ (green / yellow)
┌──────────────────────────────────────────────────────────┐
│  Layer 1: 个股信号并行计算                                │
│  ┌─────────────────┐  ┌─────────────────┐               │
│  │   财报事件信号   │  │   技术面信号     │               │
│  │  EPS beat/miss  │  │  VCP / RS / MA  │               │
│  │  指引变化       │  │  Reclaim        │               │
│  └─────────────────┘  └─────────────────┘               │
│  (Phase 3: 基本面质量信号 — EPS加速/ROE/FCF)             │
└───────────────────────────┬──────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────┐
│  Layer 2: 决策引擎 (Phase 3)                              │
│  信号聚合评分 → Claude 叙事分析 → Long/Short/Watch/Wait  │
└───────────────────────────┬──────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────┐
│  Layer 3: Discord 多频道通知                              │
│  #earnings-alerts  #trade-signals  #daily-scan           │
└───────────────────────────┬──────────────────────────────┘
                            ↓
                      Obsidian 存档
                  (04-知识/投资/财报分析/)
```

---

## 目录结构

```
earnings-agent/
├── data/                    # 数据获取层
│   ├── price.py             # yfinance OHLCV 历史数据
│   ├── earnings.py          # yfinance 财报日历检测
│   └── sec.py               # SEC EDGAR 8-K 下载
│
├── signals/                 # 信号计算层
│   ├── market.py            # 大盘环境门控 (SPY/VIX)
│   └── technicals.py        # 技术面信号 (VCP/RS/MA)
│
├── notify/                  # 通知层
│   ├── discord.py           # Discord webhook 客户端
│   └── templates.py         # Discord embed 消息模板
│
├── vault/                   # Obsidian 输出层
│   └── writer.py            # 财报分析笔记写入
│
├── ops/                     # 调度入口
│   ├── earnings_monitor.py  # 财报监听主程序 (Phase 1+2)
│   ├── daily_scan.py        # 每日技术面扫描 (Phase 2)
│   └── diagnose.py          # EDGAR API 调试工具
│
├── scripts/                 # 小脚本验证目录
│   ├── test_discord.py      # 验证 Discord webhook 连接
│   ├── test_market.py       # 验证大盘环境检测
│   └── test_vcp.py          # 验证技术面信号计算
│
├── tests/                   # 单元测试
│   ├── test_discord.py
│   ├── test_market.py
│   ├── test_price.py
│   └── test_technicals.py
│
├── docs/                    # 项目文档
├── .env                     # 环境变量 (不提交)
└── requirements.txt
```

---

## 各层详细设计

### data/ — 数据获取层

所有模块只负责获取原始数据，不做任何信号计算。

| 模块 | 接口 | 数据源 |
|------|------|--------|
| `price.py` | `get_price_history(ticker, days) → DataFrame` | yfinance OHLCV |
| `earnings.py` | `scan_watchlist(tickers, date)` / `check_earnings_on_date(ticker, date)` | yfinance earnings_dates |
| `sec.py` | `SECDownloader.get_latest_8k_for_earnings(ticker, date, dir)` | SEC EDGAR API |

**`price.py` 是信号层的基础依赖**：`signals/market.py` 和 `signals/technicals.py` 均通过 `get_price_history` 获取 SPY/VIX/个股数据，不直接调用 yfinance。

---

### signals/ — 信号计算层

**`signals/market.py` — 大盘环境门控**

```
输入: SPY (300天) + ^VIX (5天)
输出: MarketCondition(status, vix, spy_above_200ma)

逻辑:
  VIX > 30          → "red"   (高恐慌，停止所有个股操作)
  SPY < 200MA 或 VIX > 20 → "yellow" (谨慎)
  其他              → "green"  (正常)
```

**`signals/technicals.py` — 技术面信号**

```
输入: 个股 (200天) + SPY (200天，用于 RS 计算)
输出: TechnicalSignal(rs_score, vcp, ma_reclaim)

RS Score = 个股126日涨幅 / SPY126日涨幅
  ≥ 1.2 = 强势

VCP (Volatility Contraction Pattern):
  ATR_20 < ATR_60 × 0.70  (近期波幅收窄)
  AND
  Volume_20 < Volume_60 × 0.70  (近期成交量萎缩)

MA Reclaim:
  昨日收盘 < 21-EMA
  AND
  今日收盘 > 21-EMA  (价格重新站上短期均线)

has_signal = vcp OR ma_reclaim OR rs_score ≥ 1.2
```

---

### notify/ — 通知层

**三个 Discord 频道**

| 频道 | 触发时机 | 消息内容 |
|------|---------|---------|
| `#earnings-alerts` | 财报监听发现新财报 | Ticker、EPS/Revenue/Guidance、置信度、亮点 |
| `#trade-signals` | 个股 `has_signal=True` | 触发的信号类型、RS Score、市场状态 |
| `#daily-scan` | 每日 21:00 必发 | 大盘状态 (VIX)、当日候选列表 |

**消息颜色编码**

| 方向 | 颜色 |
|------|------|
| Long | 绿色 `#2ecc71` |
| Short | 红色 `#e74c3c` |
| Watch | 黄色 `#ffff00` |
| Wait / 未知 | 灰色 `#955f66` |

---

### ops/ — 调度入口

**`ops/earnings_monitor.py`** — 财报监听

```
触发: Cowork Scheduled Task，cron 3 6 * * 1-5 (北京时间 06:03)
流程:
  1. 读取 watchlist.md
  2. yfinance 批量检测是否有财报 (±2天窗口)
  3. SEC EDGAR 下载对应 8-K (Exhibit 99.1)
  4. 写入 data/earnings_today.json
  5. Discord #earnings-alerts 推送 (非致命，失败仅记录警告)
```

**`ops/daily_scan.py`** — 每日技术面扫描

```
触发: cron 0 21 * * 1-5 (北京时间 21:00，美股收盘后约2小时)
流程:
  1. 读取 watchlist.md
  2. get_market_condition() — red 则跳过个股扫描
  3. 逐个 compute_technicals() — has_signal → Discord #trade-signals
  4. 写入 data/daily_scan.json (先写文件，再推 Discord)
  5. Discord #daily-scan 发送每日摘要 (必发)
```

---

## 调度计划

| 任务 | Cron | 北京时间 | 对应美东时间 |
|------|------|---------|------------|
| earnings-monitor | `3 6 * * 1-5` | 周一至五 06:03 | 前一日 18:03 EDT |
| daily-scan | `0 21 * * 1-5` | 周一至五 21:00 | 当日 09:00 EDT |

---

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `SEC_USER_AGENT` | ✅ | SEC EDGAR 要求，格式：`Name email@example.com` |
| `VAULT_PATH` | ✅ | Obsidian vault 根目录路径 |
| `WATCHLIST_PATH` | ✅ | watchlist.md 的绝对路径 |
| `DISCORD_WEBHOOK_EARNINGS` | ✅ | `#earnings-alerts` webhook URL |
| `DISCORD_WEBHOOK_SIGNALS` | ✅ | `#trade-signals` webhook URL |
| `DISCORD_WEBHOOK_DAILY` | ✅ | `#daily-scan` webhook URL |

---

## Phase 3 设计预告

Phase 3 将在 Phase 2 稳定后单独规划，核心新增：

| 模块 | 功能 |
|------|------|
| `data/financials.py` | 8季度 EPS/Revenue/Margins、年度 ROE/FCF |
| `signals/fundamentals.py` | EPS 加速度评分、ROE 趋势、FCF Margin |
| `engine/scorer.py` | 信号聚合评分（财报40% + 技术35% + 基本面25%） |
| `engine/claude_client.py` | Claude API 结构化分析调用 |
| `engine/prompts.py` | 分析提示词模板 |

---

## 依赖清单

| 包 | 版本要求 | 用途 |
|----|---------|------|
| `requests` | ≥ 2.31.0 | SEC EDGAR 下载 + Discord webhook |
| `python-dotenv` | ≥ 1.0.0 | 环境变量加载 |
| `yfinance` | ≥ 0.2.40 | 价格数据 + 财报日历 |
| `lxml` | ≥ 5.0.0 | SEC EDGAR HTML 解析 |
| `pandas` | (yfinance 依赖) | 数据处理 |
| `numpy` | (yfinance 依赖) | 数值计算 |
| `pytest` | 开发依赖 | 单元测试 |
