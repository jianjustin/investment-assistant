# 功能验证 — 工具区（Tools）

> 前端入口：侧边栏「🔧 工具」。调度与通知机制详见 [scheduling-and-notifications.md](../scheduling-and-notifications.md)。

## 1. 任务中心（tasks）

**功能**：查看全部定时任务（名称/时间/时区/启停/上次与下次运行），每行支持「立即运行」与「按日期运行」（单日或日期范围历史回补，上限 92 天；metrics/scores 回补自动跳过周末，单日失败不中断）。

- **手动入口**：工具 → 任务中心
- **API**：
  ```bash
  curl -s "localhost:8787/api/jobs/scheduled"                            # {"jobs": [...], "degraded": bool}
  curl -s -X POST "localhost:8787/api/jobs/metrics/run" -H 'content-type: application/json' -d '{}'
  # → {"run_id": "...", "status": "pending"}；未知任务名 → 404
  curl -s -X POST "localhost:8787/api/jobs/filings/run" -H 'content-type: application/json' \
    -d '{"from": "2026-06-01", "to": "2026-06-30"}'
  # 所有任务均接受 {"date": "YYYY-MM-DD"} 或 {"from","to"}；未来日期/倒序/超 92 天 → 400
  ```
- **任务清单**：`metrics`（08:00 ET）/ `filings`（09:00 ET）/ `scores`（18:00 ET）/ `event_study`（需手动建调度行）。
- **如何验证**：点某任务「立即运行」→ 切到「运行记录」子页应出现新一条报告（status: ok/error）。

## 2. 运行记录（runs）

**功能**：`job_reports` 历史运行表格，列：任务 / 状态 / 触发（手动·定时）/ 运行时间 / 耗时 / 指定日期（单日或 `A ~ B` 范围）；点「详情」弹窗展示 run_id、起止时间与摘要 JSON。支持按任务筛选。

- **手动入口**：工具 → 运行记录（任务筛选下拉框）
- **API**：
  ```bash
  curl -s "localhost:8787/api/jobs/reports?task=metrics&limit=10"        # limit 钳位 1–200，默认 50
  # 每行含 target_start_date / target_end_date / trigger_source（scheduled|manual）
  ```
- **如何验证**：手动触发任务后本页 5 秒内出现记录；报告保留 30 天（TTL 清理）。

## 3. 实时事件流（SSE，页面底层机制）

任务运行状态变化通过 `GET /api/events`（`text/event-stream`）推送，前端借此免刷新更新。

```bash
curl -sN "localhost:8787/api/events" &          # 挂着；15 秒一条 ": keep-alive" 心跳
curl -s -X POST "localhost:8787/api/jobs/metrics/run" -d '{}' -H 'content-type: application/json'
# SSE 终端应出现 data: {"run_id": ..., "status": ...} 事件；Ctrl-C 结束
```
