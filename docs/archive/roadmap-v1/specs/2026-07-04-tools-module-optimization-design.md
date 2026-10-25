# 工具模块优化设计

日期：2026-07-04
状态：已确认（用户批准方案 A）

## 背景与目标

工具模块当前有 4 个子页（任务中心 / 运行记录 / 运维指标 / 数据结果），信息入口分散；定时任务中仅 filings 和 event_study 支持日期参数；通知文案写死"昨日财报"；财报只存文件系统、无结构化索引，无法按标的筛选和单个下载。

本次优化四项目标：

1. 删除"运维指标"、"数据结果"子页，数据结果统一以"运行记录"为入口。
2. 所有定时任务（metrics / filings / scores / event_study）支持指定日期 / 日期范围运行；通知同步展示实际日期。
3. "运行记录"改为表格展示，弹窗查看运行详情；区分"运行时间"与"指定日期"。
4. 数据模块新增"财报"Tab，支持按标的筛选和单个财报 htm 下载；新建 `filings` 表存储索引。

已确认的语义决定：

- metrics / scores 的日期参数语义为**历史回补重算**：用该日历史行情重算信号 / 评分并幂等写库。
- 运行记录弹窗展示现有 summary JSON 详情，不新增日志采集。
- 财报"美股标的过滤"= Tab 内按 ticker 筛选（另支持 form、日期范围筛选）。
- 手动触发（含范围回补）只发**一条汇总通知**，标题带实际日期；定时任务通知同样改为实际日期。

## 第 1 节：工具模块 UI 收敛

`web/src/routes/Tools.svelte` 从 4 个子页收敛为 2 个：**任务中心（tasks）+ 运行记录（runs）**。

- 删除 ops（运维指标）、results（数据结果）子页及对应侧边栏 / hash 路由入口。
- 后端同步删除不再被引用的 `GET /api/jobs/metrics`、`jobs.job_metrics()`、`db.job_report_metrics()`，前端删除 `getJobMetrics()`。
- "数据结果"原展示的"各任务最新一次运行摘要"由运行记录表格覆盖：按任务筛选后首行即最新一次运行，点详情弹窗查看 summary。

## 第 2 节：全任务日期支持（后端核心）

### 任务签名统一

REGISTRY 中 4 个任务统一为：

```python
def run(config, *, start_date: date | None = None, end_date: date | None = None) -> dict
```

不传参数维持现有默认行为（metrics / scores 算当天，filings 抓 T-1）。

- **metrics**：对 `[start_date, end_date]` 内每个交易日，用历史行情重算 SPY/VIX/200MA 信号与关注列表快照，upsert 写入 `market_signals`（UNIQUE signal_date）与 `ticker_signal_snapshots`（UNIQUE (ticker, signal_date)），天然幂等可重复回补。
- **scores**：对范围内每天，基于该日 `ticker_signal_snapshots` 重算策略评分，upsert 写入 `strategy_scores`（UNIQUE (ticker, score_date, strategy)）。某日缺快照时该日跳过并计入 summary。
- **filings**：已支持 start/end，仅做参数名与校验统一。
- **event_study**：已有 asof/since 参数，映射到统一的 start_date/end_date 语义。

### API 与校验

`POST /api/jobs/{name}/run` 对全部 4 个任务接受 `date`（单日）或 `from`/`to`（范围），统一校验：

- 拒绝未来日期；
- `from <= to`；
- 范围上限 92 天。

### 收敛重复入口

metrics 支持日期后，Tools 页"手动抓取市场信号"入口改走统一的 `runJob('metrics', payload)`（metrics 任务是 `fetch_market_signals` 的超集，还多算关注列表快照）。`POST /api/market/signals/fetch` 及前端 `fetchMarketSignals()` 在确认无其他调用方后删除。

### 前端

任务中心每个任务行都提供"按日期运行"入口，复用 `FetchDateModal`（今日 / 单日 / 日期范围三种模式，各任务默认标签按其自然目标日显示，如 filings 默认"昨日 T-1"）。

## 第 3 节：job_reports 记录"指定日期"（migration 010）

`job_reports` 新增三列：

| 列 | 类型 | 含义 |
|---|---|---|
| `target_start_date` | DATE | 本次运行的目标起始日 |
| `target_end_date` | DATE | 本次运行的目标结束日（单日时等于起始日） |
| `trigger` | TEXT | `scheduled` \| `manual` |

`_harness.run_task()` 签名扩展，接收目标日期与触发方式并写入 job_reports：

- 定时触发：填任务的自然目标日（metrics/scores = 当日，filings = T-1），trigger = `scheduled`；
- 手动触发：填用户所选日期，trigger = `manual`。

加 `trigger` 的原因：回补运行与日常定时运行混在同一张表，不标来源无法正确解读记录。

## 第 4 节：运行记录表格 + 详情弹窗

运行记录子页改为表格，列：

**任务 / 状态 / 触发方式 / 运行时间（started_at，精确到秒）/ 耗时 / 指定日期 / 操作**

- "指定日期"单日显示 `YYYY-MM-DD`，范围显示 `YYYY-MM-DD ~ YYYY-MM-DD`；
- "操作"列"详情"按钮弹窗（复用 `Modal.svelte`），展示 run_id、开始 / 结束时间、格式化的 summary JSON（含错误信息）；
- 保留现有按任务筛选；
- `GET /api/jobs/reports` 返回体补充新增三字段。

## 第 5 节：通知改造（实际日期 + 汇总）

- `notify.dispatch()` 扩展接收目标日期区间（start/end）。
- 模板标题改用实际日期，去掉写死的"昨日"/固定时刻：
  - 定时单日："📄 财报 · 2026-07-03"；
  - 范围回补："📄 财报 · 2026-06-01 ~ 2026-06-30"；
  - metrics / scores 模板同理。
- 一次触发（无论单日还是范围）只发**一条汇总通知**：范围回补时任务 summary 按天聚合计数（如各日下载数 / 信号状态），通知取聚合结果，不逐日发送。

## 第 6 节：数据模块"财报"Tab（migration 011 + 新 API）

### 新表 `filings`

```sql
CREATE TABLE IF NOT EXISTS filings (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  form TEXT NOT NULL,
  filing_date DATE NOT NULL,
  accession_number TEXT NOT NULL,
  primary_document TEXT NOT NULL,
  file_path TEXT NOT NULL,
  run_id TEXT,
  downloaded_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (accession_number, primary_document)
);
CREATE INDEX IF NOT EXISTS idx_filings_ticker_date ON filings (ticker, filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_filings_date ON filings (filing_date DESC);
```

### 写入路径

`sec_downloader` 每成功下载一份文件即 upsert 一行索引；**"文件已存在跳过下载"的分支同样 upsert**。这样对历史日期范围重跑 filings 任务即可为存量文件补建索引，无需一次性回填脚本。

### 新 API

| 端点 | 说明 |
|---|---|
| `GET /api/filings/records?ticker=&form=&from=&to=&limit=` | 查 `filings` 表，支持按标的 / 类型 / 日期范围筛选，limit 分页（默认 50） |
| `GET /api/filings/records/{id}/download` | 按 file_path 以 FileResponse 回传 htm；文件在磁盘上不存在时返回 404 |

旧的 `GET /api/filings`（实时扫文件系统）被新 Tab 取代后，确认无其他引用即删除（连同 `status.filing_rows()`）。

### 前端

`web/src/routes/Data.svelte` 新增第 4 个 Tab"财报"：

- 表格列：标的 / 类型 / 财报日期 / 下载时间 / 下载按钮（触发浏览器下载 htm）；
- 筛选器：ticker 下拉（取表中 distinct 值）、form 下拉（10-Q / 10-K）、日期范围。

## 错误处理

- 日期校验失败（未来日期、from > to、超 92 天）返回 400 及明确错误信息；
- metrics / scores 回补中某日数据源缺失：跳过该日、计入 summary 的错误明细，不中断整个范围；
- 财报下载接口对索引存在但文件丢失的情况返回 404；
- 任务失败仍按现有 harness 逻辑写 error 状态的 job_report 并通知。

## 测试

遵循现有 `tests/` 结构：

- metrics / scores 日期参数解析与幂等 upsert（mock 数据源）；
- `POST /api/jobs/{name}/run` 日期校验各分支；
- `filings` 表 upsert 去重（重复 accession 不重复插入）；
- 下载接口正常回传与文件丢失 404 分支；
- 通知模板：单日 / 范围两种标题格式。

## 实施顺序建议

1. Migration 010（job_reports 加列）+ harness / dispatch 签名扩展；
2. metrics / scores 日期支持 + API 统一校验；
3. 通知模板实际日期 + 汇总；
4. Migration 011（filings 表）+ downloader 写索引 + 新 API；
5. 前端：Tools 收敛与运行记录表格 / 弹窗；
6. 前端：Data 财报 Tab；
7. 清理：删除 /api/jobs/metrics、/api/market/signals/fetch、旧 /api/filings 及对应前端函数。
