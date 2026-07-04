# 事件研究（Event Study）— 功能说明与验证

## 这是什么

统计某类信号事件（如 rs_strong / ma_reclaim / score_high / eps_beat / eps_miss）发生后
5/10/20 个交易日的超额收益分布（相对 SPY），带样本量与统计诚实性 caveats。
这是回测三层严肃度中的 A 层（见 docs/roadmap/00 §2）。

结果字段（每个 horizon 对应一行）：

| 字段 key | 含义 |
|----------|------|
| `horizon` | 持有窗口（交易日数） |
| `n` | 有效样本数 |
| `mean_excess` | 平均超额收益 |
| `median` | 中位超额收益 |
| `hit_rate` | 胜率（超额 > 0 的比例） |
| `t_stat` | t 统计量 |
| `ci95` | 95% 置信区间 `[lower, upper]` |
| `std` | 超额收益标准差 |

样本不足（< 30）时 `caveats` 包含 `n<30, 结论不可信` 警告。

---

## 如何验证

### 路径一：CLI（离线可跑，无 DB 也可）

事件研究 CLI 入口在 `tasks.event_study`，`--kind` 可多次传入（缺省跑 rs_strong / ma_reclaim / score_high 全部）：

```bash
# 跑单个 kind（--no-record 仅打印不落 job_reports）
.venv/bin/python -m investment_assistant.tasks.event_study --kind rs_strong --no-record

# 跑多个 kind
.venv/bin/python -m investment_assistant.tasks.event_study --kind rs_strong --kind ma_reclaim --no-record

# 指定历史 as-of 日期（回放用）
.venv/bin/python -m investment_assistant.tasks.event_study --kind rs_strong --asof 2025-01-01 --no-record

# 完整参数列表
.venv/bin/python -m investment_assistant.tasks.event_study --help
```

期望输出：JSON，`--no-record` 模式下顶层为 `{"task": "event_study", "status": "manual", "summary": {...}}`，
结果在 `summary` 内：`results`（各 kind 的 horizons 与 caveats）、`params`（本次运行的 kinds/asof/since/horizons 参数回显）、`skipped_total`；
样本不足时 caveats 含 `n<30, 结论不可信` 警告。不带 `--no-record` 时输出为 `run_task` 的 job report 结构（结果同样在 `summary` 内）。

> 注意：`python -m investment_assistant.research.event_study` 是内部委托入口，
> 同样有效但参数接口以 `tasks.event_study` 为准。

### 路径二：API

服务器启动（`python -m investment_assistant.api.server`，默认端口 8787）后：

```bash
# 查询所有支持的 kind 列表
curl -s "http://localhost:8787/api/research/event-study/kinds"
# 响应示例：{"kinds": ["rs_strong", "ma_reclaim", "score_high", "eps_beat", "eps_miss"]}

# 计算单个 kind 的事件研究结果
curl -s "http://localhost:8787/api/research/event-study?kind=rs_strong"
# 响应结构：{"result": {...}, "degraded": bool, "source": "cache"|"computed"}
# 无 INVESTMENT_ASSISTANT_DATABASE_URL 时 degraded: true，不报错（优雅降级）

# 支持可选参数 since / asof（YYYY-MM-DD）
curl -s "http://localhost:8787/api/research/event-study?kind=rs_strong&since=2024-01-01"
```

OpenAPI 文档（含参数说明与响应示例）：`http://localhost:8787/docs`

### 路径三：前端

面板「**策略 → 事件研究**」（SideNav id: `event-study`）：

1. 顶部下拉选择 kind（rs_strong / ma_reclaim / …）
2. 点「运行」
3. 展示各 horizon 超额收益表（窗口 / 样本数 / 平均超额 / 中位超额 / 胜率 / t 统计）
4. caveats 区展示统计诚实性警告（如样本不足）

---

## 定时任务

调度器每日跑 `event_study` 任务，结果落入 `event_studies` 缓存表。

执行记录查询：

```bash
# API 方式
curl -s "http://localhost:8787/api/jobs/reports?task=event_study"

# 前端方式：「工具 → 运行记录」筛选 task=event_study
```

手动触发（不等调度器）：

```bash
.venv/bin/python -m investment_assistant.tasks.event_study
# 落 job_reports + 按配置推 Discord
```

调度守护进程配置见 [scheduling-and-notifications.md](scheduling-and-notifications.md)。

---

## 统计诚实性 caveats

| 情形 | caveats 内容 |
|------|-------------|
| 样本量 < 30 | `n<30, 结论不可信` |
| 事件来源含占位数据 | `事件来源含占位数据（yfinance earnings_dates），不作去留结论依据` |
| 价格或区制取价缺失 | `N 个事件/horizon 因取价或区制缺失被跳过` |

即使 caveats 非空，API 仍正常返回结果（不报 500）；caveats 由调用方自行决定是否展示给用户。
