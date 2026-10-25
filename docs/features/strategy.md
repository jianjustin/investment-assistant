# 功能验证 — 策略区（Strategy）

> 前端入口：侧边栏「🎯 策略」。curl 示例同 [data.md](data.md) 约定。

## 1. 策略评分（scores）

**功能**：对 watchlist 标的按策略规则打分（写 `strategy_scores` 表），页面展示最新分数并可手动触发重算。

- **手动入口**：策略 → 策略评分 → 「运行评分」按钮（异步：提交后前端轮询 `/api/runs/{run_id}` 直至 done）
- **API**：
  ```bash
  curl -s "localhost:8787/api/strategies/scores"                        # {"rows": [...], "count": N}
  curl -s -X POST "localhost:8787/api/strategies/scores/run" -H 'content-type: application/json' -d '{}'
  # → {"run_id": "...", "status": "pending"}；用 run_id 查询：
  curl -s "localhost:8787/api/runs/<run_id>"
  ```
- **CLI / 调度**：`python -m investment_assistant.tasks.nightly_scores`；定时任务 `scores` 每交易日 18:00 ET。
- **如何验证**：点「运行评分」→ 按钮转为进行中 → 完成后表格刷新出现各 ticker 分数；`GET /api/runs/<不存在的id>` 应返 404 `{"error": "unknown run"}`。

## 2. 事件研究（event-study）

**功能**：统计某类信号事件后 5/10/20 个交易日的超额收益分布（相对 SPY），带统计诚实性 caveats。回测三层严肃度中的 A 层。

- **手动入口**：策略 → 事件研究 → 选信号类型 → 「运行」
- **详细验证手册**：[research-event-study.md](../research-event-study.md)（CLI / API / 前端三条路径 + 字段说明）
- **快速验证**：
  ```bash
  curl -s "localhost:8787/api/research/event-study/kinds"               # 5 种 kind
  curl -s "localhost:8787/api/research/event-study?kind=rs_strong"      # {"result": ..., "source": "cache|computed"}
  ```
- **调度**：任务 `event_study` 已注册但**无默认调度行**，需手动补（SQL 见部署文档（已于 v2.0.0 删除））。

## 3. 运行历史（runs）子页 — 当前状态说明

SideNav 中声明了「运行历史」子页，但目前 Strategy 页面对该子页**复用策略评分视图**，没有独立的运行历史渲染。查看任务运行历史请用「工具 → 运行记录」（`GET /api/jobs/reports`）。
