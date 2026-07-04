# 功能验证 — 工具区（Tools）

> 前端入口：侧边栏「🔧 工具」。调度与通知机制详见 [scheduling-and-notifications.md](../scheduling-and-notifications.md)。

## 1. 任务中心（tasks）

**功能**：查看全部定时任务（名称/时间/时区/启停/上次与下次运行）并手动「立即运行」；另有「手动抓取市场信号」快捷按钮。

- **手动入口**：工具 → 任务中心
- **API**：
  ```bash
  curl -s "localhost:8787/api/jobs/scheduled"                            # {"jobs": [...], "degraded": bool}
  curl -s -X POST "localhost:8787/api/jobs/metrics/run" -H 'content-type: application/json' -d '{}'
  # → {"run_id": "...", "status": "pending"}；未知任务名 → 404
  curl -s -X POST "localhost:8787/api/market/signals/fetch" -H 'content-type: application/json' -d '{}'
  ```
- **任务清单**：`metrics`（08:00 ET）/ `filings`（09:00 ET）/ `scores`（18:00 ET）/ `event_study`（需手动建调度行）。
- **如何验证**：点某任务「立即运行」→ 切到「运行记录」子页应出现新一条报告（status: ok/error）。

## 2. 运行记录（runs）

**功能**：`job_reports` 表的历史运行报告（任务/状态/起止时间/摘要），支持按任务筛选。

- **手动入口**：工具 → 运行记录（任务筛选下拉框）
- **API**：
  ```bash
  curl -s "localhost:8787/api/jobs/reports?task=metrics&limit=10"        # limit 钳位 1–200，默认 50
  ```
- **如何验证**：手动触发任务后本页 5 秒内出现记录；报告保留 30 天（TTL 清理）。

## 3. 运维指标（ops）

**功能**：按任务聚合的运行指标（总次数/成功数/平均耗时/出错天数），窗口可调。

- **API**：
  ```bash
  curl -s "localhost:8787/api/jobs/metrics?window=7"                     # window 钳位 1–90 天，默认 7
  ```
- **如何验证**：跑过几次任务后，`metrics` 数组按任务各一行统计。

## 4. 数据结果（results）

**功能**：各核心任务（metrics/filings/scores）最近一次运行摘要的横向速览。

- **API**：复用 `GET /api/jobs/reports?task=<name>&limit=1`。
- **如何验证**：与「运行记录」最新条目一致。

## 实时事件流（SSE，页面底层机制）

任务运行状态变化通过 `GET /api/events`（`text/event-stream`）推送，前端借此免刷新更新。

```bash
curl -sN "localhost:8787/api/events" &          # 挂着；15 秒一条 ": keep-alive" 心跳
curl -s -X POST "localhost:8787/api/jobs/metrics/run" -d '{}' -H 'content-type: application/json'
# SSE 终端应出现 data: {"run_id": ..., "status": ...} 事件；Ctrl-C 结束
```
