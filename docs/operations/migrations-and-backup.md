# 迁移与备份

## 迁移清单

迁移文件只增不改：已执行的文件不再编辑，改 schema 一律新增编号。业务表只追加，迁移不回填、不改写旧行（`021` 删除 A 股数据是唯一例外）。

| 编号 | 内容 | 组 |
| --- | --- | --- |
| 001 | `market_signals`：SPY/VIX 市场信号 | v1 遗留 |
| 002 | `watchlist_items`：观察名单 | 共享 |
| 003 | `ticker_signal_snapshots`：个股趋势快照 | v1 遗留 |
| 004–005 | `strategy_scores` 及指向快照的外键 | v1 遗留 |
| 006 | `job_reports`：运行报告（写入即剪枝，保留 30 天） | 共享 |
| 007 | `scheduled_jobs`：调度表，种子 `metrics`/`filings`/`scores` | 共享 |
| 008 | `notify_settings`：通知设置 | 共享 |
| 009 | `event_studies`：事件研究 | v1 遗留 |
| 010 | `job_reports` 加指定日期与触发来源 | 共享 |
| 011 | `filings`：SEC 文件索引 | 共享 |
| 012 | 通知渠道单选（Discord / 邮件）与邮件配置 | 共享 |
| 013 | 研究观察卡表（及已删除的 A 股表，见 021） | v1 遗留 |
| 014 | `us_research_*`：美股财季数据与指引 | v1 遗留 |
| 015 | `ticker_signal_snapshots`、`strategy_scores` 加来源元数据（可空） | v1 遗留 |
| 016 | 工作台 P0：日线、资讯、候选、解读、决定、成交、周度复盘；`workbench` 任务（北京 06:30，周二至周六） | 主线 |
| 017 | P1：交易计划、财报日、资金快照、出入金、月度复盘；`signal_decisions.plan_id` | 主线 |
| 018 | P2：`pool_tiers`、`macro_observations`、`market_regimes`、`rule_backchecks` | 主线 |
| 019 | P3：`agent_runs`、`agent_tool_calls`；`trade_plans.kind` 放宽为含 `agent` | 主线 |
| 020 | P4：`agent_runs.mode`、`signal_briefs.agent_run_id`、`review_pushes`；`workbench_review` 任务（北京 08:00，插入为关闭） | 主线 |
| 021 | 删除 A 股：`cn_*` 两张表、CN 观察名单行、`CN:` 研究卡、`ashares` 任务行；`job_reports` 历史保留 | 共享 |

另需一次：`python -m investment_assistant.workbench.agent setup` 由 LangGraph `PostgresSaver.setup()` 建检查点表，不进本项目迁移。

## 新库

```bash
INVESTMENT_ASSISTANT_DATABASE_URL=... .venv/bin/python -m investment_assistant.migrate
```

`migrate` 入口按文件名顺序执行未执行过的迁移，并记入 `schema_migrations`，重复运行不做任何事。

## 真实库：备份后单事务执行

真实库从 018 起不走 `migrate` 入口，而是逐个手动执行：

```bash
pg_dump -Fc "$INVESTMENT_ASSISTANT_DATABASE_URL" -f .local/us-workbench/backups/investment_assistant-before-<编号>-<时间戳>.dump
shasum -a 256 .local/us-workbench/backups/investment_assistant-before-<编号>-<时间戳>.dump
psql "$INVESTMENT_ASSISTANT_DATABASE_URL" --single-transaction -v ON_ERROR_STOP=1 -f migrations/<编号>_<名称>.sql
```

执行后统计受影响表的行数并记入 [roadmap 进度](../roadmap/v2-progress.md)，再重载服务（[本机服务](local-service.md)）。

> 注意：真实库的 `schema_migrations` 只记录到 `017`，`018` 之后都是用 `psql` 手动执行的。不要对真实库运行 `migrate` 入口，否则它会把 `018` 之后的迁移重跑一遍。

恢复备份：`pg_restore --clean --if-exists -d "$INVESTMENT_ASSISTANT_DATABASE_URL" <备份文件>`，执行前先停服务。

## 一次性测试库

数据库测试只在设置了 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 时运行，每个测试在独立 schema 中建表、结束后删除。永远不要把它指向真实库。

```bash
initdb -D <临时目录>/pg/data -U test -A trust --no-locale -E UTF8
LC_ALL=C pg_ctl -D <临时目录>/pg/data -o "-p 55433 -k '' -c listen_addresses=127.0.0.1" start
createdb -h 127.0.0.1 -p 55433 -U test workbench_test
INVESTMENT_ASSISTANT_TEST_DATABASE_URL=postgresql://test@127.0.0.1:55433/workbench_test \
  env -u INVESTMENT_ASSISTANT_DATABASE_URL .venv/bin/python -m pytest tests/ -q
```

Unix socket 路径太长时启动会失败，所以用 `-k ''` 关掉 socket、只走 TCP；不加 `LC_ALL=C` 时服务会拒绝启动。
