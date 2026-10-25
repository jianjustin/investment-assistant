# 迁移与备份

## 迁移清单

迁移文件只增不改：已执行的文件不再编辑，改 schema 一律新增编号。业务表只追加，迁移不回填、不改写旧行（`021` 删除 A 股数据是唯一例外）。

| 编号 | 内容 | 组 |
| --- | --- | --- |
| 001 | `market_signals`：SPY/VIX 市场信号 | v1 遗留（022 已删） |
| 002 | `watchlist_items`：观察名单 | 共享 |
| 003 | `ticker_signal_snapshots`：个股趋势快照 | v1 遗留（022 已删） |
| 004–005 | `strategy_scores` 及指向快照的外键 | v1 遗留（022 已删） |
| 006 | `job_reports`：运行报告（写入即剪枝，保留 30 天） | 共享 |
| 007 | `scheduled_jobs`：调度表，种子 `metrics`/`filings`/`scores` | 共享 |
| 008 | `notify_settings`：通知设置 | 共享 |
| 009 | `event_studies`：事件研究 | v1 遗留（022 已删） |
| 010 | `job_reports` 加指定日期与触发来源 | 共享 |
| 011 | `filings`：SEC 文件索引 | 共享 |
| 012 | 通知渠道单选（Discord / 邮件）与邮件配置 | 共享 |
| 013 | 研究观察卡表（及已删除的 A 股表，见 021） | v1 遗留（022 已删） |
| 014 | `us_research_*`：美股财季数据与指引 | 主线 · 基本面 |
| 015 | `ticker_signal_snapshots`、`strategy_scores` 加来源元数据（可空） | v1 遗留（022 已删） |
| 016 | 工作台 P0：日线、资讯、候选、解读、决定、成交、周度复盘；`workbench` 任务（北京 06:30，周二至周六） | 主线 |
| 017 | P1：交易计划、财报日、资金快照、出入金、月度复盘；`signal_decisions.plan_id` | 主线 |
| 018 | P2：`pool_tiers`、`macro_observations`、`market_regimes`、`rule_backchecks` | 主线 |
| 019 | P3：`agent_runs`、`agent_tool_calls`；`trade_plans.kind` 放宽为含 `agent` | 主线 |
| 020 | P4：`agent_runs.mode`、`signal_briefs.agent_run_id`、`review_pushes`；`workbench_review` 任务（北京 08:00，插入为关闭） | 主线 |
| 021 | 删除 A 股：`cn_*` 两张表、CN 观察名单行、`CN:` 研究卡、`ashares` 任务行；`job_reports` 历史保留 | 共享 |
| 022 | 删除 v1 遗留：`strategy_scores`、`ticker_signal_snapshots`、`market_signals`、`event_studies`、`research_observation_card_versions`、`research_observation_cards` 六张表与 `metrics`、`scores`、`event_study` 调度行；`job_reports` 历史与已冻结的 `backcheck-1` 记录保留 | 共享 |
| 023 | v2.2：`screen_runs`、`screen_results`、`pool_tiers.source`（默认 `watchlist`）；`filings` 任务改为北京 09:30（只改仍是纽约时区的行） | 主线 + 共享 |

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

### 022 的真实库执行（逐步手动，每步先征得用户同意）

代码先上（提交合入并重启 LaunchAgent）之后才执行 022；期间 `scheduled_jobs` 里的 `metrics`、`scores` 行只会被记为 `unregistered job` 并照常重排。

1. 只读预检：确认 `schema_migrations` 最大编号为 `017`；统计 6 张表行数；查 `pg_constraint`、`pg_depend` 确认 6 张表之外没有对象依赖它们。
2. 全库备份：

   ```bash
   pg_dump -Fc "$INVESTMENT_ASSISTANT_DATABASE_URL" -f .local/us-workbench/backups/investment_assistant-before-022-<时间戳>.dump
   ```

3. 6 张表单独导出（便于单表恢复）：

   ```bash
   pg_dump -Fc "$INVESTMENT_ASSISTANT_DATABASE_URL" \
     -t market_signals -t ticker_signal_snapshots -t strategy_scores -t event_studies \
     -t research_observation_cards -t research_observation_card_versions \
     -f .local/us-workbench/backups/investment_assistant-v1-legacy-tables-<时间戳>.dump
   ```

4. 执行（手动 psql，不走 `migrate` 入口）：

   ```bash
   psql "$INVESTMENT_ASSISTANT_DATABASE_URL" --single-transaction -v ON_ERROR_STOP=1 -f migrations/022_drop_v1_legacy.sql
   ```

5. 验证：6 张表的 `to_regclass` 都为 null；`scheduled_jobs` 无 `metrics`、`scores`、`event_study`，`workbench`、`workbench_review`、`filings` 行还在；手动跑一次工作台批处理成功。

#### 执行记录（2026-10-25，手动 psql 执行）

| 步骤 | 结果 |
| --- | --- |
| 上线前置 | `notify_settings` 只读查询：`filings` → `earnings`、`workbench` → `signals`、`workbench_review` 未存（默认 `signals`），无主线任务路由到 `daily`；代码 `691641c` 已上线、LaunchAgent 已重启 |
| 1. 只读预检 | `schema_migrations` 17 条、最新 `017_trade_plans.sql`；行数 `strategy_scores` 568、`ticker_signal_snapshots` 568、`market_signals` 71，`event_studies`、`research_observation_cards`、`research_observation_card_versions` 为 0（共 792 kB）；唯一外键 `fk_strategy_scores_snapshot` 两端都在 6 张表内；`pg_depend` 中 6 张表之外无依赖对象 |
| 2. 全库备份 | `.local/us-workbench/backups/investment_assistant-before-022-20261025-204403.dump`（4,268,871 字节，sha256 `e77c76ad0db7fd68022d017cb08b5bb18e693bea51b9a7e19d2212fddd480e2b`）；`pg_restore --list` 可读，38 张表与线上一致 |
| 3. 遗留表导出 | `.local/us-workbench/backups/investment_assistant-v1-legacy-tables-20261025-204504.dump`（38,244 字节，sha256 `0bffe4d87b28a10dd361832cc31b65f60ed5bafda0d980ff50bdaa4e61ea8e81`）；6 张表、4 个序列、3 个索引、外键都在，行数与预检一致 |
| 4. 执行 | 20:48:30 +0800，`psql --single-transaction -v ON_ERROR_STOP=1`：`DELETE 2`（`metrics`、`scores`；库里本无 `event_study` 行）与 6 次 `DROP TABLE`，退出码 0；`schema_migrations` 仍只到 `017` |
| 5. 验证 | 6 张表 `to_regclass` 均为 null，`public` 表数 38 → 32；`scheduled_jobs` 只剩 `filings`、`workbench`、`workbench_review`；`job_reports` 的 `metrics`、`scores` 历史各 9 行保留；`us_research_observations`（29,648 行）、`us_research_collection_state`、`price_bars`（3,802 行）未动；服务接口全部 200，健康检查数据库与调度线程 up；手动批处理 `workbench-20261025125234-aff00057` `success`（交易日 2026-10-23，`errors` 为空，手动运行不推送） |

单表恢复：`pg_restore -d "$INVESTMENT_ASSISTANT_DATABASE_URL" .local/us-workbench/backups/investment_assistant-v1-legacy-tables-20261025-204504.dump`，再按需插回两行调度。

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
