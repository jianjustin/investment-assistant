# Hermes Investment Assistant — 架构

> 美股量化分析系统：从市场信号到 Discord 通知的自动化投资辅助工具。

---

## 五层信息架构（前端）

前端采用五层导航，每层对应一组业务职责：

| 层 | 路由 | 职责 |
|----|------|------|
| 工具层 | `/tools` | 任务运维：调度任务管理（支持按日期回补）、运行记录 |
| 数据层 | `/data` | 市场数据：信号总览、趋势、技术面、财报 |
| 策略层 | `/strategy` | 策略评分：评分总览、运行历史、事件研究 |
| 交易层 | `/trade` | 交易决策：宏观分析、决策证据、交易指令（占位） |
| 设置层 | `/settings` | 系统配置：Discord 通知、定时任务开关、环境变量、关注列表 |

### 工具层二级页

- **任务中心**（TaskCenter）：展示所有 scheduled_jobs，支持「立即运行」与「按日期运行」（单日/范围回补，上限 92 天）
- **运行记录**（RunHistory）：job_reports 表格（状态/触发来源/运行时间/耗时/指定日期），详情弹窗展示摘要 JSON

### 设置层二级页

- **系统**（默认落地页）：状态卡片 + operations 注册表（GET `/api/status` · `/api/operations`）
- **关注列表**：watchlist 增删（GET / POST / DELETE）
- **Discord 通知**：effective_notify_config 预览 + 覆盖配置（notify_settings 008）
- **定时任务**：scheduled_jobs 启用/禁用切换（PATCH）
- **环境变量**：env 状态只读面板

---

## 后端分层

HTTP 传输层基于 **FastAPI + uvicorn**（Phase R 迁移完成），入口 `python -m investment_assistant.api.server`；
`api/app.py` 的 `create_app()` 组装所有路由，OpenAPI 文档自动生成于 `/docs`。

```
investment_assistant/
  api/                       # HTTP 传输层（FastAPI + uvicorn）
    app.py                   # create_app()：组装路由、鉴权 middleware、异常处理器
    auth.py                  # 鉴权（authorize / resolve_bind_host），fail-closed 公网绑定
    http.py                  # ApiResponse / StaticResponse + 解析助手
    server.py                # uvicorn 入口：main() 调用 uvicorn.run(create_app)
    static_files.py          # 服务 web/dist 静态资源 + /status HTML
    routes/
      status.py              # /api/status · /api/health · /api/services · /api/operations
      filings.py             # /api/filings/records · /api/filings/records/{id}/download
      market.py              # /api/market/signals/*
      tickers.py             # /api/tickers/trends
      strategies.py          # /api/strategies/scores
      hermes.py              # /api/hermes/*
      watchlist.py           # /api/watchlist
      jobs.py                # /api/jobs/*
      settings.py            # /api/settings/*
      runs.py                # /api/runs/{id}（兼容旧轮询接口）
      research.py            # /api/research/event-study/kinds · /api/research/event-study
  services/                  # 业务逻辑层
    market.py  tickers.py  strategies.py  hermes.py  watchlist.py  research.py
  db.py                      # psycopg_pool 连接池 + 所有 DB 函数
  tasks/                     # 定时任务入口
    _harness.py              # 通用任务 harness：写 job_reports，推 Discord
    scheduler.py             # 常驻调度守护进程，读 scheduled_jobs 表
    runner.py                # 后台任务线程池（submit / get / subscribe）
    metrics.py               # 08:00 指标采集任务
    filings.py               # 09:00 SEC 财报下载任务
    nightly_scores.py        # 18:00 策略评分任务
    event_study.py           # 每日事件研究任务（结果入 event_studies 缓存表）
  research/                  # 事件研究核心计算
    event_study.py           # run_event_study()：超额收益统计 + HorizonStat
    event_sources.py         # collect_events()：各 kind 的事件采集
  filings/
    sec_downloader.py        # SecEdgarDownloader：CIK 解析 + 8-K/10-Q 下载
```

---

## 调度与通知

```
scheduled_jobs 表（迁移 007）
        │  scheduler.py 守护进程每分钟检查
        ▼
  tasks/_harness.py
        │  执行具体任务（metrics / filings / nightly_scores）
        │  写入 job_reports 表（迁移 006）
        ▼
  effective_notify_config
        │  文件基线配置 ⊕ notify_settings 表（迁移 008）覆盖
        ▼
  Discord 推送（成功/失败通知）
```

调度与通知的完整配置说明见 [docs/scheduling-and-notifications.md](scheduling-and-notifications.md)。

---

## 数据与 API 映射表

| 层 | 二级页 | 方法 | 端点 |
|----|--------|------|------|
| 工具 | 任务中心 | GET | `/api/jobs/scheduled` |
| 工具 | 任务中心（触发） | POST | `/api/jobs/{name}/run` |
| 工具 | 任务中心（开关） | PATCH | `/api/jobs/scheduled/{name}` |
| 工具 | 运行记录 | GET | `/api/jobs/reports` |
| 数据 | 信号总览 | GET | `/api/market/signals` |
| 数据 | 信号最新 | GET | `/api/market/signals/latest` |
| 数据 | 信号趋势 | GET | `/api/market/signals/trend` |
| 数据 | 信号抓取 | POST | `/api/market/signals/fetch` |
| 数据 | 个股趋势 | GET | `/api/tickers/trends` |
| 数据 | 个股扫描 | POST | `/api/tickers/trends/scan` |
| 数据 | 财报索引 | GET | `/api/filings/records` |
| 数据 | 财报下载 | GET | `/api/filings/records/{id}/download` |
| 策略 | 评分总览 | GET | `/api/strategies/scores` |
| 策略 | 触发评分 | POST | `/api/strategies/scores/run` |
| 策略 | 事件研究 kinds | GET | `/api/research/event-study/kinds` |
| 策略 | 事件研究结果 | GET | `/api/research/event-study?kind=X` |
| 交易 | 宏观分析 | GET | `/api/hermes/macro-analysis` |
| 交易 | 市场解读 | GET | `/api/hermes/market-signals/interpretation` |
| 交易 | 触发宏观 | POST | `/api/hermes/macro-analysis/run` |
| 交易 | 触发决策 | POST | `/api/hermes/decision-evidence/run` |
| 设置 | Discord 通知 | GET | `/api/settings/notify` |
| 设置 | Discord 通知（更新） | PATCH | `/api/settings/notify` |
| 设置 | Discord 通知（测试） | POST | `/api/settings/notify/test` |
| 设置 | 环境变量 | GET | `/api/settings/env` |
| 设置 | 关注列表 | GET / POST | `/api/watchlist` |
| 设置 | 关注列表（删除） | DELETE | `/api/watchlist/{ticker}` |
| 通用 | 系统状态 | GET | `/api/status` · `/api/health` · `/api/services` |
| 通用 | 运维操作注册表 | GET | `/api/operations` |

---

## 迁移清单

| 编号 | 内容 |
|------|------|
| 001 | market_snapshots（市场快照） |
| 002 | watchlist（关注列表） |
| 003 | snapshots 扩展字段 |
| 004 | strategy_scores（策略评分） |
| 005 | 外键约束 |
| 006 | job_reports（任务运行记录） |
| 007 | scheduled_jobs（调度配置） |
| 008 | notify_settings（通知覆盖配置） |
| 009 | event_studies（事件研究结果缓存） |
| 010 | job_reports 增加目标日期与触发来源（target_start/end_date · trigger_source） |
| 011 | filings（财报文件索引，UNIQUE accession_number+primary_document） |

---

## 后续子项目

| 子项目 | 对应层 | 核心功能 |
|--------|--------|----------|
| B：回测引擎 | 策略层 | 历史信号回测、准确率统计 |
| C：LLM 交易指令 | 交易层 | Claude 结构化决策 → 可执行交易指令 |
| 总览通知 | 通知机制 | 跨层汇总，以 Discord 推送形式实现 |
