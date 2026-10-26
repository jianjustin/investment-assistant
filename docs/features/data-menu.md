# 数据菜单：数据族状态与原始数据

v2.3.0 新增：让每类数据看得见。六个数据族（日线、SEC 申报、资讯、ATR、FRED 利差、纳指 100 范围）的用途、覆盖、最新时点、最近拉取成败在「数据」菜单可见，可单族手动拉取，可浏览原始值。设计见[数据基础 spec](../specs/2026-10-26-v2.3-data-foundation-design.md)。

## 做什么

- **六张卡**：每个数据族一张——用途、类型（采集 / 派生 / 手动维护）、覆盖 `covered / targets`（滞后目标点名）、最新时点、最近一次拉取（状态、触发来源、成败计数、失败原因前 5 条）、最近一次成功时间、所属任务（开关与下次运行）。覆盖与最新时点在读取时从数据表实算，不另存状态。
- **只追加的拉取记录**：每次拉取（定时批处理、手动批处理、数据菜单手动拉取、`filings` 任务）向 `data_fetch_runs` 追加一行，记录成败与逐只原因；失败原因截断 300 字，并去掉 `FRED_API_KEY` 等凭据。
- **单族手动拉取**：共用批处理的同一组采集函数，可全族或单只（`bars`、`news`、`sec_filings` 支持单只）；不跑规则、不生成计划或候选、不改池、不推送。同族并发用 advisory lock 互斥：正在采集时接口返回 409。
- **原始值浏览**（窗口固定）：日线最近 120 个交易日，附每日修订次数，OHLC 拆股调整、未分红调整，`adj_close` 全调整；ATR 现算最近 60 个（与 `plan-1` 同一函数，不入库）；资讯近 60 天；SEC 申报近 180 天（`filings` 行 + 未入库的 `sec_8k`）；FRED 每条序列最近 120 个观测；范围文件的元数据与成员表。
- **证据文案常驻**：「这里只展示采集事实。所有规则都未经验证（Phase 0 Gate HOLD）：数据完整不代表信号有效。」；ATR 卡与 ATR 浏览另标「`plan-1` 的计算输入，规则 `gate_hold`」。

## 页面

（前端页面随 v2.3 后续提交补充：总览与族详情、原始数据浏览。）

## API

| 接口 | 作用 |
| --- | --- |
| `GET /api/data/families` | 总览：六张卡 |
| `GET /api/data/families/{id}` | 族详情：卡片 + 最近 20 次拉取记录 + 逐目标覆盖表（每个目标的最新时点、是否滞后、最近失败原因） |
| `POST /api/data/families/{id}/fetch` | 手动拉取，body 可选 `{"ticker": "MU"}`；返回 `{run_id, status: "pending"}`，结果看「工具 → 运行记录」或 `GET /api/runs/{run_id}` |
| `GET /api/data/browse/{id}?ticker=&series=` | 原始值浏览：按标的的族传 `ticker`，FRED 传 `series`，范围族不传 |

错误体沿用 `{"error": "..."}`：数据库未配置 / 不可达 / 工作台表缺失 → 503；未知族 → 404；非法参数（派生族、族不支持单只、缺 `ticker` / `series`、未知序列）→ 400；该族正在采集 → 409。迁移 024 未执行时读取照常（无「最近拉取」一栏），拉取接口返回 503「需执行迁移 024」。

## 怎么验证一次

```bash
curl -s "localhost:8787/api/data/families"          # 六张卡，session 为最近已收盘交易日
curl -s -X POST "localhost:8787/api/data/families/bars/fetch" -H 'content-type: application/json' -d '{"ticker": "MU"}'
curl -s "localhost:8787/api/data/families/bars"     # 最近一条 trigger=manual_family、scope=ticker
curl -s "localhost:8787/api/data/browse/bars?ticker=MU"
```

- 拉取后 `trade_plans`、`signal_candidates`、`pool_tiers` 行数不变，Discord 无消息。
- 同族正在采集时再发拉取 → 409「该族正在采集」。
- 浏览一只从没采过数据的 ticker → 200、`has_data: false`，不是报错，也不触发采集。

## 已知限制

- 与 spec 的两处实现偏差（如实记录）：
  1. 批处理写的拉取记录 `run_id` 为空：记录在采集阶段末尾写入，此时拿不到任务的 `run_id`，靠 `job` + `started_at` 对应「工具 → 运行记录」里的运行报告（`filings` 任务在任务返回后写记录，能带上 `run_id`）。
  2. 手动拉取的记录带的是 `tasks/runner` 的 `run_id`（经 `runner.submit(..., with_run_id=True)` 传入），不是 `job_reports.run_id`；前端页面落地后两处都会给到「运行记录」入口。
- 覆盖口径与滞后阈值是展示定义，不是规则参数，不用历史数据去调。
- 浏览窗口固定（日线 120、ATR 60、资讯 60 天、SEC 180 天、FRED 120），不做日期筛选；画图是「标的」页的事。
