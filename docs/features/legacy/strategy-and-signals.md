# 市场信号、个股趋势与策略评分

> v1 遗留，保留但不再演进，见 [遗留功能清单](README.md)。工作台的市场环境改用池内广度（见 [观察池与市场环境](../pool-and-context.md)），不读这里的表。

## 功能

| 功能 | 写入的表 | 来源任务 |
| --- | --- | --- |
| SPY/VIX/MA200 市场信号（红绿灯状态）与近 N 日趋势判断 | `market_signals` | `metrics`（美东 08:00） |
| 关注列表个股的技术面趋势快照（均线结构、量比、相对收益） | `ticker_signal_snapshots` | `metrics` 顺带扫描；也可手动扫描 |
| 策略评分（趋势 + 相对强度） | `strategy_scores` | `scores`（美东 18:00，模块 `tasks.nightly_scores`） |

趋势扫描和宏观分析取观察名单中 active 且代码有效的美股（无数据库时退回配置文件的 `watchlist`）；`filings` 下载器读配置文件的 `watchlist`。

## 入口与验证

- 页面：「更多 → 数据 → 信号总览 / 趋势分析」「更多 → 技术面趋势」「更多 → 策略 → 策略评分」。
- API：

  ```bash
  curl -s "localhost:8787/api/market/signals?limit=60"
  curl -s "localhost:8787/api/market/signals/latest"
  curl -s "localhost:8787/api/market/signals/trend?window=30"
  curl -s -X POST "localhost:8787/api/market/signals/fetch" -H 'content-type: application/json' -d '{}'
  curl -s "localhost:8787/api/tickers/trends"
  curl -s -X POST "localhost:8787/api/tickers/trends/scan" -H 'content-type: application/json' -d '{}'
  curl -s "localhost:8787/api/tickers/MU/ohlcv"
  curl -s "localhost:8787/api/strategies/scores"
  curl -s -X POST "localhost:8787/api/strategies/scores/run" -H 'content-type: application/json' -d '{}'
  ```

- 命令行：`python -m investment_assistant.tasks.metrics`、`python -m investment_assistant.tasks.nightly_scores`。
- 验证一次：手动抓取一次信号后，「信号总览」出现当日行；运行一次评分后，表格出现各股票的分数。

## 已知限制

- `^VIX` 有时返回空数据，此时 `compute_market_signal` 抛 `ValueError`，`metrics` 记为非致命错误，下一次运行通常恢复。
- 技术信号 `has_signal` 必须用 `bool(...)` 包一层：`numpy.bool_(False) is False` 的结果是 `False`。
- 旧的「EPS/Revenue/Guidance + VCP/RS/MA 全部叠加才推送」并不代表已验收的能力：EPS surprise 和 VCP 的事件源不可用；`rs_strong` 的旧阈值单位未确认，已挂起；`ma_reclaim` 是 SMA20 上穿，不是 21EMA。
