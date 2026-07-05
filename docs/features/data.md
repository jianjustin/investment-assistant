# 功能验证 — 数据区（Data）

> 前端入口：侧边栏「📊 数据」。本页所有 curl 示例假设本机运行（`localhost:8787`）且未设密码；配置了 `SERVER_PWD` 时加 `-u <用户名>:<密码>`。

## 1. 信号总览（signals）

**功能**：展示最近的市场信号记录（VIX / SPY / MA200 衍生的红绿灯状态）与趋势摘要。

- **手动入口**：数据 → 信号总览（进入即加载，无按钮）
- **API**：
  ```bash
  curl -s "localhost:8787/api/market/signals?limit=60"      # {"rows": [...], "count": N}
  curl -s "localhost:8787/api/market/signals/latest"         # 最新一条信号或 null
  ```
- **数据来源**：`metrics` 定时任务（每交易日 08:00 ET）写入 `market_signals` 表；也可手动抓取（见工具区「任务中心」或 `POST /api/market/signals/fetch`）。
- **如何验证**：先手动触发一次抓取，再刷新本页应看到当日行；无数据库时返回 `{"rows": [], "count": 0}` 级降级，页面为空但不报错。

## 2. 趋势分析（trend）

**功能**：近 N 日（默认 30）信号窗口统计与趋势判断（`latest_status` / `judgement`）。

- **手动入口**：数据 → 趋势分析
- **API**：
  ```bash
  curl -s "localhost:8787/api/market/signals/trend?window=30"
  ```
- **如何验证**：`market_signals` 表有 ≥2 天数据后，响应含窗口统计字段；只有一天数据时趋势字段可能为空——正常。

## 3. 技术面趋势（tickers）

**功能**：watchlist 内各标的的技术面趋势状态快照（均线结构等）。

- **手动入口**：数据 → 技术面趋势
- **API**：
  ```bash
  curl -s "localhost:8787/api/tickers/trends"                          # {"rows": [...], "count": N}
  curl -s -X POST "localhost:8787/api/tickers/trends/scan" -H 'content-type: application/json' -d '{}'
  ```
- **数据来源**：`metrics` 任务顺带触发扫描，写 `ticker_signal_snapshots` 表；POST scan 可即时重扫（需要网络访问 yfinance）。
- **如何验证**：POST scan 后 GET 应返回 watchlist 各 ticker 一行；离线/无 DB 时 scan 的 `failures` 列表会说明原因。

## 4. 财报（filings）

**功能**：已下载 SEC 财报文件的索引列表（`filings` 表），支持按标的 / 类型（10-Q · 10-K）/ 披露日期范围筛选，每行可单独下载原始 htm。

- **手动入口**：数据 → 财报
- **API**：
  ```bash
  curl -s "localhost:8787/api/filings/records?ticker=AAPL&form=10-Q&from=2026-01-01&to=2026-06-30&limit=50"
  # → {"records": [...], "tickers": [...], "degraded": bool}
  curl -sOJ "localhost:8787/api/filings/records/1/download"    # 记录不存在或文件丢失 → 404
  ```
- **数据来源**：`filings` 定时任务（09:00 ET，默认拉 T-1）下载文件并写索引；对历史日期范围重跑任务可为存量文件补建索引（已存在的文件只补索引，不重复下载）。
- **如何验证**：在「工具 → 任务中心」对 filings 按日期回补一次 → 本页出现记录；点「下载 htm」浏览器应下载原始文件。
