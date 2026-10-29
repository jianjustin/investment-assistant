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
| 024 | v2.3：`data_fetch_runs`：每次某族被拉取一次追加一行记录成败与原因；只建表与索引，不动旧表（2026-10-27 已在真实库执行，见下文） | 主线 |
| 025 | v2.4：`stage_runs`：每次 `workbench` 任务、每个阶段追加一行证据（计数、原因、产出引用、耗时）；只建表与索引，不动旧表（2026-10-27 已在真实库手动执行，见下文） | 主线 |
| 026 | v2.5：计划时间线。新建只追加的 `agent_plan_versions`（版本链）、`plan_reviews`（每日复查记录，每条链每个交易日至多一条有效批处理复查）、`user_inputs`（用户输入）；`signal_decisions` 加可空列 `agent_plan_id`、`review_view`；放宽 `agent_runs.mode`（加 `review`、`revise`）及两条相关 CHECK、`agent_tool_calls.phase`（加 `review`）、`stage_runs.stage`（加 `review`）；`idx_trade_plans_agent_unique` 只管 `agent-1`。不改旧行、可重跑；三张新表不进 `WORKBENCH_TABLES`，就绪与否由 `repository.timeline_ready` 判定。对旧代码无害（只新增表 / 列、放宽约束）。必须先于重启执行（spec D19）；2026-10-28 已在真实库手动执行，见下文 | 主线 |
| 027 | v2.7：我的成长闭环。新建十一张只追加的表：`review_cards`、`review_card_drafts`、`review_card_verdicts`（复盘卡及其起草与审定）、`discussions`、`discussion_turns`（就此计划讨论）、`knowledge_items`、`knowledge_versions`、`knowledge_status`（我的知识）、`knowledge_drafts`、`knowledge_draft_verdicts`（教训草稿及其决定）、`knowledge_citations`（计划与复查引用了哪一版知识）；放宽 `agent_runs.mode`（加 `retro`、`discuss`）、`agent_tool_calls.phase`（加 `retro`、`discuss`）、`stage_runs.stage`（加 `retro`）。约束名查不到时按定义找出后删除（同 026 的 `DO` 块），不改旧行、不加种子行、可重跑；十一张新表不进 `WORKBENCH_TABLES`，就绪与否由 `repository.growth_ready` 判定。对 v2.6 代码无害（只新增表、放宽约束）。必须先于重启执行（spec D29）；真实库执行需单独授权，见下文 | 主线 |

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

执行后统计受影响表的行数并记入 [roadmap](../roadmap/roadmap.md)，再重载服务（[本机服务](local-service.md)）。

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

### 023 的真实库执行（逐步手动，每步先征得用户同意）

023 只新增表和带默认值的列，旧代码照常运行，所以先迁移、后重启（反过来新代码会读不存在的列）。

#### 执行记录（2026-10-26，手动 psql 执行）

| 步骤 | 结果 |
| --- | --- |
| 1. 只读预检 | `schema_migrations` 最新仍为 `017_trade_plans.sql`；`screen_runs`、`screen_results` 不存在，`pool_tiers` 无 `source` 列、共 8 行；`public` 表数 32；`filings` 为 `America/New_York 20:30`（周一至周五，下次 2026-10-27 08:30 +0800） |
| 2. 全库备份 | `.local/us-workbench/backups/investment_assistant-before-023-20261026-101340.dump`（4,235,781 字节，sha256 `dae881b7e2e0e263363a0934985cb079347e602012e73d4f2f6a2197d5515480`）；`pg_restore --list` 可读，32 张表与线上一致 |
| 3. 执行 | 用户在终端手动执行（10:13 备份之后、10:25 核对之前），`psql --single-transaction -v ON_ERROR_STOP=1 -f migrations/023_screen_and_beijing_jobs.sql`；`schema_migrations` 仍只到 `017` |
| 4. 验证 | `screen_runs`、`screen_results` 已建（各 0 行），索引 `idx_screen_runs_session`、`idx_screen_results_ticker` 在；`pool_tiers.source` 为 `text NOT NULL DEFAULT 'watchlist'`，CHECK `pool_tiers_source_check` 在，8 行旧数据全部为 `watchlist`；`filings` 为 `Asia/Shanghai 09:30`（周一至周五），`next_run_at` = 2026-10-27 09:30 +0800（周二，当天 09:30 已过）；`workbench`（06:30 周二至周六）与 `workbench_review`（08:00 每天）未变；`public` 表数 32 → 34 |
| 5. 重启服务 | 重启前进程 pid 1196 启动于 2026-10-25 18:04（旧代码，`GET /api/workbench/screen` 为 404），无运行中任务；10:28:30 +0800 `launchctl kickstart -k`，新进程 pid 42156 启动于 10:29:00；`/api/health`：数据库、调度线程（轮询运行中）、SEC、Yahoo、Discord、FRED 均 up，3 项 `systemctl` 检查在 macOS 上为 down（重启前即如此，与本次无关）；`/api/workbench/screen`（`report: null`，尚无筛选记录）、`/api/workbench/today`、`/api/jobs/scheduled`、`/api/status` 均 200；`/api/jobs/scheduled` 三个任务都是 `Asia/Shanghai` 并带 `description` |

服务重启与手动验收（spec §11.2）见 [v2.2 验收记录](../roadmap/v2.2-acceptance.md)。

### 024 的真实库执行（逐步手动，每步先征得用户同意）

024 只新增一张表，旧代码照常运行；新代码在没表时也只降级。先迁移、后重启。

#### 执行记录（2026-10-27，手动 psql 执行）

| 步骤 | 结果 |
| --- | --- |
| 1. 只读预检 | `data_fetch_runs` 不存在；`public` 表数 34；`schema_migrations` 最新仍为 `017_trade_plans.sql`；`job_reports` 无 `running` 行；服务进程 pid 83648 启动于 2026-10-26 15:36（v2.3 代码提交之前，`GET /api/data/families` 为 404） |
| 2. 全库备份 | `.local/us-workbench/backups/investment_assistant-before-024-20261027-100426.dump`（5,367,773 字节，sha256 `8c8e09dec0d5139fbfd6fa24180952381a0933d66c53093a334a64dd7533c244`）；`pg_restore --list` 可读，34 张表与线上一致 |
| 3. 执行 | 10:04:57 +0800，`psql --single-transaction -v ON_ERROR_STOP=1 -f migrations/024_data_fetch_runs.sql`（`CREATE TABLE`、`CREATE INDEX`）；`schema_migrations` 仍只到 `017` |
| 4. 验证 | `data_fetch_runs` 0 行，索引 `data_fetch_runs_pkey`、`idx_data_fetch_runs_family` 在，CHECK 约束 7 条；`public` 表数 34 → 35；`trade_plans` 8、`signal_candidates` 12、`pool_tiers` 30、`job_reports` 65、`scheduled_jobs` 3，与预检相同 |
| 5. 重启服务 | 10:05:19 +0800 `launchctl kickstart -k`，新进程 pid 96706 启动于 10:05:49；`/api/health`：数据库、调度线程（轮询运行中）、Yahoo、Discord、FRED up，SEC 首次探测为代理 SSL 中断、数秒后复查 up，3 项 `systemctl` 检查在 macOS 上为 down（与本次无关）；`/api/data/families`、`/api/data/families/bars`、`/api/data/browse/bars?ticker=MU`、`/api/workbench/today`、`/api/jobs/scheduled`、`/api/status` 均 200 |

手动验收（spec §11.2）见 [v2.3 验收记录](../roadmap/v2.3-acceptance.md)。

### 025 的真实库执行（逐步手动，每步先征得用户同意）

025 只新增一张表，旧代码照常运行；新代码在没表时也只降级（`stage_status.error`）。先迁移、后重启。

#### 执行记录（2026-10-27，手动 psql 执行）

| 步骤 | 结果 |
| --- | --- |
| 1. 只读预检 | `stage_runs` 不存在；`public` 表数 35；`schema_migrations` 最新仍为 `017_trade_plans.sql`；`job_reports` 无 `running` 行；服务进程 pid 6694 启动于 2026-10-27 10:47（v2.4 代码提交之前） |
| 2. 全库备份 | `.local/us-workbench/backups/investment_assistant-before-025-20261027-175527.dump`（5,372,345 字节，sha256 `1c46d0030a78bb0455add9f7277f38649224e2f0adef93e1c52b982533465f97`）；`pg_restore --list` 可读，35 张表与线上一致 |
| 3. 执行 | 17:55:36 +0800，`psql --single-transaction -v ON_ERROR_STOP=1 -f migrations/025_stage_runs.sql`（`CREATE TABLE`、`CREATE INDEX`）；`schema_migrations` 仍只到 `017` |
| 4. 验证 | `stage_runs` 0 行，索引 `stage_runs_pkey`、`stage_runs_run_id_stage_key`、`idx_stage_runs_session` 在，CHECK 约束 9 条；`public` 表数 35 → 36；`trade_plans` 8、`signal_candidates` 12、`job_reports` 65、`data_fetch_runs` 7、`scheduled_jobs` 3，与预检相同 |
| 5. 重启服务 | 17:55:42 +0800 `launchctl kickstart -k`，新进程 pid 97239 启动于 17:56:12；`/api/health`：数据库、调度线程（轮询运行中）、SEC、Discord、FRED up，Yahoo 首次探测为代理 SSL 中断、复查 up，3 项 `systemctl` 检查在 macOS 上为 down（与本次无关）；`/api/workbench/today`、`/api/workbench/stage-runs?session=2026-10-26`（`stage_runs_ready: true`）、`/api/data/families`、`/api/jobs/scheduled`、`/api/status` 均 200 |

### 026 的真实库执行（逐步手动，用户 2026-10-28 授权执行 v2.5 plan Task 14）

026 只新增表、列与放宽约束，对旧代码无害；新代码在缺表时降级为 `stages-1`。与 025 不同，**必须先迁移、后重启**（spec D19）。

#### 执行记录（2026-10-28，手动 psql 执行）

| 步骤 | 结果 |
| --- | --- |
| 1. 只读预检 | 16:30 +0800：`agent_plan_versions`、`plan_reviews`、`user_inputs` 都不存在，`signal_decisions` 无 `agent_plan_id` / `review_view`；`public` 表数 36；`job_reports` 无 `running` 行；服务进程 pid 97239 启动于 2026-10-27 17:56（v2.4 代码）；行数 `trade_plans` 9、`signal_candidates` 15、`agent_runs` 8、`agent_tool_calls` 72、`signal_decisions` 4、`stage_runs` 14、`job_reports` 69 |
| 2. 全库备份 | `.local/us-workbench/backups/investment_assistant-before-026-20261028-163044.dump`（5,582,037 字节，sha256 `e555371b5306ceec709b0fbb50920683186be8d1382ddf212ef7356118f3babf`）；`pg_restore --list` 可读，36 张表与线上一致 |
| 3. 执行 | 16:30:49 +0800，`psql --single-transaction -v ON_ERROR_STOP=1 -f migrations/026_plan_timeline.sql`（3 个 `CREATE TABLE`、4 个 `CREATE INDEX`、12 个 `ALTER TABLE`、3 个 `DO` 块、1 个 `DROP INDEX`）；三条 `NOTICE` 是首次执行时 `DROP CONSTRAINT IF EXISTS` 找不到具名约束，属预期；`schema_migrations` 仍只到 `017` |
| 4. 验证 | 三张新表各 0 行；`signal_decisions.agent_plan_id`（`uuid`）、`review_view`（`jsonb`）在；`agent_runs_mode_check` 允许 `propose`、`interpret`、`review`、`revise`，`agent_runs_mode_plan_check`、`agent_runs_interpret_no_pass_check` 与 spec §6.4 逐字一致；`agent_tool_calls_phase_check` 允许 `review`；`stage_runs_stage_check` 为 8 个阶段；`idx_trade_plans_agent_unique` 只管 `plan_version = 'agent-1'`；`public` 表数 36 → 39；旧表行数与预检相同 |
| 5. 重启服务 | 16:31:08 +0800 `launchctl kickstart -k`，新进程 pid 8923 启动于 16:31:38；`/api/health`：数据库、调度线程（轮询运行中）、Filings 存储、Discord、FRED up，SEC 与 Yahoo 经代理时有 SSL 中断（复查时交替 up / down，与 v2.4 验收日相同），3 项 `systemctl` 检查在 macOS 上为 down（与本次无关）；`/api/workbench/today`（`timeline_ready: true`）、`/api/jobs/scheduled`、`/api/status`、`/api/workbench/plan-reviews`、`/api/workbench/chains?ticker=QCOM`、`/api/workbench/user-inputs?ticker=QCOM` 均 200 |

回滚：`pg_restore --clean -d "$INVESTMENT_ASSISTANT_DATABASE_URL" <上面的 dump>`，再重启到 v2.4 代码。

### 027 的真实库执行（逐步手动，每一步单独授权）

027 只新增表并放宽三处约束，对 v2.6 代码无害；v2.7 代码在缺表时降级：批处理按 `stages-2` 记 8 行（没有 `retro` 行，`summary.errors` 有 `growth: migration_027_missing`）、`get_knowledge` 返回错误信封、新接口 503「迁移 027 未执行」、`today` / 链视图的 `knowledge_refs` 为空列表。与 026 一样**必须先迁移、后重启**（spec D29）：

1. **只读预检**：十一张表都不存在（`to_regclass` 为 null）；`job_reports` 没有 `running` 行；记下 `public` 表数与 `agent_runs`、`stage_runs` 的行数。
2. **全库备份**：`pg_dump -Fc "$INVESTMENT_ASSISTANT_DATABASE_URL" -f .local/us-workbench/backups/investment_assistant-before-027-<时间戳>.dump`，`shasum -a 256` 记下，`pg_restore --list` 确认可读。
3. **执行**：`psql "$INVESTMENT_ASSISTANT_DATABASE_URL" --single-transaction -v ON_ERROR_STOP=1 -f migrations/027_growth_loop.sql`；首次执行时 `DROP CONSTRAINT IF EXISTS` 找不到具名约束的 `NOTICE` 属预期；`schema_migrations` 仍只到 `017`。
4. **验证**：十一张新表各 0 行；`agent_runs_mode_check` 含 `retro`、`discuss`，`agent_runs_mode_plan_check`、`agent_runs_interpret_no_pass_check` 不变；`agent_tool_calls_phase_check` 含 `retro`、`discuss`；`stage_runs_stage_check` 为 9 个阶段；`public` 表数 +11；旧表行数与预检相同。
5. **重启服务**（[本机服务](local-service.md)）：新进程起来后手动跑一次批处理，`stage_runs` 该 `run_id` 有 9 行；`python -m investment_assistant.workbench.retro_cards check --since <首次批处理交易日 S 之前的第 4 个交易日>`（即 S−4，`retro.window_start(S)`：首次批处理只检测 S−4 到 S，起点再早会把窗口外的旧结束事件当成「缺卡」；要核对更早的事件，先 `retro_cards detect --since <日期>` 补卡再核对） 与 `python -m investment_assistant.workbench.my_knowledge check-cutoff --since <上线日>` 通过。

回滚：`pg_restore --clean -d "$INVESTMENT_ASSISTANT_DATABASE_URL" <上面的 dump>`，再重启到 v2.6 代码。执行记录写进 `docs/roadmap/v2.7-acceptance.md` 的「迁移 027 执行记录」一节。

2026-10-29 已在真实库执行（13:39 备份、执行，13:40 重启），记录见 [v2.7 验收记录](../roadmap/v2.7-acceptance.md)。

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
