# 05 — 横切关注点（贯穿各阶段）

> 这些不属于某个单一阶段，而是贯穿始终。按「与核心闭环的耦合度」排序。

---

## C1 — 组合 / 敞口视角（最大的结构性补强）

**为什么是横切**：投研的第一视角是「我现在整体暴露在什么风险上」，而这个数据藏在 Phase 2 的 `trade_journal` 里（日志 = 真实持仓）。它依赖 Phase 2，但服务于所有阶段的展示。

**做什么**（`services/portfolio.py` 之上）：
- **当前持仓**：数量、均价、未实现盈亏（用最新 `ohlcv_bars` 收盘价）。
- **敞口分解**：净敞口 / 总敞口 / 现金比例、按行业 / 按因子集中度。
- **相关性与集中度**：持仓两两相关性矩阵（用 `ohlcv_bars` 收益算），暴露「看似分散实则同涨同跌」的风险。
- **组合 Beta**：相对 SPY 的整体 Beta。
- **回撤监控**：组合权益曲线的当前回撤 vs 历史最大。

**价值**：从「单股信号」升级到「组合健康」，这是把工具变成投研系统的视角差异。

---

## C2 — 可视化（兑现数据价值）

**现状**：全站只有一条手搓 SVG 折线（`market.ts`），对投资工具而言可视化几乎为零。已有 `EChart.svelte` / `LineChart.svelte` / `CandleChart.svelte` 组件基础。

**按阶段补的图**（数据就绪即接，不单列阶段）：

| 图 | 数据源 | 阶段 |
|----|--------|------|
| K 线 + 均线叠加 + 信号标记 | `ohlcv_bars` + 信号 | Phase 1 |
| 市场广度时序（% 站上 200MA 等） | `market_breadth` | Phase 1 |
| 事件研究前瞻收益分布（柱/箱线，按区制分面） | `EventStudyResult` | Phase 0→可视化 |
| 三方权益曲线（你 / SPY / 理论） | Phase 3.2 | Phase 3 |
| 行为偏差雷达 | Phase 3.1 | Phase 3 |
| LLM 校准曲线 | Phase 3.4 | Phase 3 |
| 组合敞口饼/树图 + 相关性热力 | C1 | Phase 2+ |

> 复用现有 `EChart` 封装与五层 IA 的「数据层 / 交易层」承载，不新增图表库（ECharts 已够；K 线若要专业级再评估 Lightweight Charts）。

---

## C3 — 文档对齐（立刻可做，零依赖）

**问题**：`README.md` 和 `docs/architecture.md` 严重过时——仍在描述已删除的 `ops/earnings_monitor.py` / `daily_scan.py` 旧 earnings-agent 结构，会误导任何接手者（包括未来的你和我）。

**做什么**（已在五层 IA plan 的 Task 9 规划，可并入或独立先做）：
- 重写 `architecture.md`：删旧 earnings-agent 内容，改为「五层 IA + 后端分层（api/services/tasks/db）+ 调度通知 + 本 roadmap 的数据/闭环架构」。
- 更新 `README.md`：目录结构 / 手动运行入口改为新任务（`tasks.metrics/filings/nightly_scores/scheduler`）。
- 删除已被取代的过时文档（`audit-and-redesign` 完成历史使命后可归档，`test-report` 的「14 用例」早已失真）。

> 优先级：**高且便宜**。建议在 Phase 0 期间穿插做掉，避免文档债继续误导。

---

## C4 — 安全（需立即核实）

审计曾指出两个问题，**需先核实当前是否已修**（代码可能已变）：
- 仪表盘鉴权是否 **fail-closed**（无密码拒绝启动），还是默认放行。
- 是否绑 `0.0.0.0` 明文，应改为仅绑 `127.0.0.1` + 反代 TLS。

> 引入交易日志后，系统开始存**你的真实持仓和交易**——安全等级要求上升。Phase 2 落地前必须确认鉴权与绑定收敛。核实点：`api/auth.py`、`api/server.py` 的 `resolve_bind_host` / `authorize`。

---

## C5 — CI（工程化收尾）

- GitHub Actions：lint（ruff，已配 `pyproject.toml`）+ pytest + 前端 vitest。
- 加 Postgres service 容器跑**真实 DB 迁移测试**（现有 `test_db_sql.py` 只断言 SQL 含子串，从不执行）——随着迁移增多（009–015），真实执行迁移的回归价值上升。
- 依赖锁定（uv / pip-tools），`pytest` 移到 dev 依赖。

> 优先级：随迁移数量增长而上升。建议 Phase 1（开始大量加表）时引入真实 DB 迁移测试。

---

## 横切优先级建议

```
立刻:        C3 文档对齐（便宜、止损误导）
Phase 2 前:  C4 安全核实（存真实交易数据前必须）
Phase 1 起:  C5 真实DB迁移测试（加表变多）
Phase 2 起:  C1 组合敞口（依赖 trade_journal）
数据就绪即:  C2 可视化（逐图接入）
```
