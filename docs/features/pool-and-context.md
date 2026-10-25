# 观察池与市场环境

观察池决定批处理跑哪些股票、推送哪些；市场环境是每份计划都附带的背景，**只作提示，不改价位**。上线前检查（`backcheck-2`）用库里已有的数据，检查规则是否触发过频、止损是否总被扫掉。

设计：[P2 观察池扩展与市场环境](../specs/2026-10-23-p2-pool-and-market-context-design.md)。

## 观察池与分层

| 层 | 规模 | 规则、计划、Agent | 推送与「今日」 |
| --- | --- | --- | --- |
| 核心池（`core` 标签） | ≤ 15 只 | 运行 | 推送；进入待决定列表 |
| 扩展池 | 其余，总数 ≤ 100 只 | 运行，影子跟踪（仓位照算） | 不推送；只在「今日」底部的折叠区只读显示，进入周度复盘 |
| 持仓股 | 不论在哪一层 | 运行，按核心池对待 | 推送 |

- 观察池 = 数据库观察名单中 `active` 且是有效美股代码的行。代码无效的行（例如迁移前遗留的旧数据）会被跳过，在列表里标出「证券身份无效」，可以删除。
- `sector:<ETF>` 标签把个股映射到行业 ETF（SMH / XLK / QQQ）。
- 每次批处理把分层变化追加进 `pool_tiers`（`effective_session` 为本次交易日）。某只股票某一天属于哪一层，按「`effective_session <= 该日` 且 `recorded_at <= 截止时间`」的最新一行还原。
- 超过上限时，写入观察名单和批处理都会报错，不会悄悄截断。

## 市场环境 `regime-1`

每次批处理在采集之后、规则之前，生成一份快照写入 `market_regimes`：

- **池内广度**：观察池中当日有 K 线的股票，按 `adj_close` 计算站上 MA50 / MA200 的占比，以及 52 周新高、新低数量。持仓股如果不在观察池里，不计入广度。
- **区制标签**：MA200 合格样本 < 20 只时为「样本不足」；站上 MA200 占比 ≥ 60% 且站上 MA50 占比 ≥ 50% 为「进攻」；分别 < 40% 且 < 30% 为「防守」；其余为「中性」。
- **行业强弱**：SMH、XLK、QQQ 相对 SPY 的 20 日 / 60 日强弱，分为弱、强、分化、数据不足。
- **利差背景**（FRED）：`BAMLH0A0HYM2`（HY OAS）和 `T10Y2Y`，各取 120 天，附 20 个观测前的变化；数据修订时追加记录。
- **对计划的影响**：分层、区制、行业和下次财报日冻结进计划的 `inputs.context`；防守区制、快照失败、行业弱势分别加提示 `regime_risk_off` / `regime_unavailable` / `sector_weak`，价位、仓位和有效性都不变。

## 上线前检查 `backcheck-2`

新规则上线前手动运行。只读库里已有的 K 线（当前修订）和 SEC 文件，不联网、不补采：

- 每只股票的前 200 根 K 线只用来预热指标；评估区内的每个交易日，只用截至当日的 K 线跑规则（假设无持仓）。买入候选按 `plan-1` 算价位，再用 `plan-shadow-1` 模拟结果。
- 按规则逐条统计，再给合计：触发数、每 100 个股票日的触发数、同一天 ≥ 3 只股票同时触发的天数、成交数与过期数、5 个交易日内止损的占比、到达 T1 的占比、R 的均值 / 中位数 / 四分位。
- 信号后超额（`backcheck-2` 新增）：每条信号、每个 h ∈ {5, 10, 20} 个交易日，`close(标的, t+h) / close(标的, t) − close(SPY, t+h) / close(SPY, t)`，按收盘价对收盘价。第 h 日在最后一根日线之后计 `immature`；个股或 SPY 缺任一端点计 `missing`，都不进统计、不用邻近值替代。每行给出 n、均值、中位数、正超额占比、immature 与 missing 计数。超额不代表可成交。
- 标记：`too_frequent`（每 100 个股票日触发 > 5 次）、`stops_swept`（成交 ≥ 10 且 5 日内止损 ≥ 50%）、`insufficient`（成交 < 10）。
- 结果冻结进 `rule_backchecks`（已冻结的 `backcheck-1` 旧记录保留，前端超额列显示「—」）。这只是描述性检查，不调参，也不代表规则有效。

## 入口与验证

- 页面：「设置 → 关注列表」（核心池勾选、行业 ETF 下拉，「下一事件」列显示今天及以后最近的财报日，表头显示「美股池 n/100 · 核心 m/15」；超限或标签不规范时返回 400，观察名单不变）；「今日」顶部的市场环境卡片，以及计划卡片上的「区制 · 下次财报 · 行业」一行；「复盘 → 上线前检查」。
- API：`GET/POST /api/watchlist`、`DELETE /api/watchlist/{ticker}`、`GET /api/watchlist/resolve?symbol=`；`GET/POST /api/workbench/backchecks`（body 可以带 `tickers`）。
- 命令行：`python -m investment_assistant.workbench.backcheck [--tickers A,B]`。
- 运行报告：`summary.pool`（`core` / `extended` / `holdings` / `changes`）、`summary.regime`、`summary.etfs`、`summary.macro`（未配置 FRED 时记 `not_configured`）、`summary.timings`（总耗时 > 1800 秒时记 `batch_over_budget`）。
- 验证一次：给某只股票勾选「核心」，下一次批处理的 `pool.changes` 里应出现一条 `tier: core`；运行报告里有 `regime: {status: inserted, label: …}`，配置了 FRED 时还有 `macro.BAMLH0A0HYM2.inserted > 0`。

## 已知限制

- 观察池里有 200 根 K 线的股票不足 20 只时，区制一直显示「样本不足」。
- 当前观察池历史成交太少，上线前检查通常标为 `insufficient`，这是正常现象。
