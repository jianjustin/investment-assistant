# Changelog

版本号与 roadmap 版本对应，见 [roadmap](docs/roadmap/roadmap.md)。

## v2.5.0 — 2026-10-28

计划时间线（[spec](docs/specs/2026-10-28-v2.5-plan-timeline-design.md)、[实施 plan](docs/plans/2026-10-28-v2.5-plan-timeline.md)）：Agent 计划结构化为可复查的论点并成为默认复查对象，同一单元的 Agent 计划组成版本链，批处理每日复查，系统信号与你贴入的信息触发修订，每版各自影子跟踪。状态：`engineering_done`、`user_acceptance_pending`（迁移 026 已于 2026-10-28 在真实库执行、服务已重启跑 v2.5 代码；没有真实浏览器验收与定时运行证据）。保留偏差与已知限制见下文与 [roadmap](docs/roadmap/roadmap.md)。

### 新增

- **三张新表（迁移 026）**：`agent_plan_versions`（版本链：`version_no`、`origin` = `signal` / `review` / `recheck`、`supersedes_plan_id`、`cutoff_at`、宿主差异 `diff`、模型变化说明 `changes`）、`plan_reviews`（每条复查结论：`maintain` / `revise` / `invalidate` / `skipped` / `error`、`decided_by`、信号、条件判定、引用的用户输入）、`user_inputs`（只追加的用户输入，更正与撤回都是新行）；`signal_decisions` 新增 `agent_plan_id`、`review_view` 两列；放宽 `agent_runs.mode`（`review`、`revise`）、`agent_tool_calls.phase`、`stage_runs.stage` 的约束。三张表都不进 `WORKBENCH_TABLES`。**026 待用户授权在真实库执行，必须先迁移、后重启服务**。
- **条件集合 `condition-1`**（`agent/conditions.py`）：11 种失效 / 复查条件（`close_below`、`close_above`、`no_entry_by`、`no_entry_before_earnings`、`earnings_within`、`regime_is`、`sector_weak`、`rs_below`、`new_filing`、`date_reached`、`next_session`），参数校验（价格在最近收盘 ±50%、日期在生成交易日后 60 天内）与三态判定（成立 / 未成立 / 无法判定，缺数据一律「无法判定」）。
- **Agent 计划 `agent-2`**：提议增加结构化的论点 `thesis`（1–3 条，宿主编号 `T1…T3`）、失效条件 `invalidation`、下次复查条件 `review_when`、修订版的 `changes`；反方逐条对论点给反证；宿主校验（`agent/plan_check.py`）不过整版作废（`thesis_count`、`invalid_condition`、`changes_mismatch`、`no_change` 等）。首版与计划行、运行行、版本行、简报同一事务写入。
- **复查 `agent-review-1` 与链状态 `timeline-1`**：链状态按 `invalidated` → `closed_by_decision` → `holding` → `position_closed` → `expired` → `entry` 判定，只复查 `entry` 与 `holding`；七项信号（`new_8k`、`abnormal_move`、`stop_touched`、`t1_touched`、`expiry_near`、`regime_change`、`user_input`）窗口为「上次有效复查之后」。
- **每日复查阶段 `review`**：批处理第 7 个阶段，对每条有效链：失效条件成立由系统规则作废；无信号、无新输入、复查条件都未满足由系统规则维持；其余调用一次复查模型，结论为修订时再走一次完整的提议 + 反方 + 校验，通过才成为新的最新版。每链每天最多 3 次尝试、受 token 上限与额度限制；每条结论写一行 `plan_reviews`。
- **用户输入**：研报要点 / 新闻 / 我的判断 / 其他，1–4000 字，可附链接（不抓取），作用于标的或单条链；更正与撤回指向旧行；复查与修订的提示词附「用户输入」证据块并写明「只是证据、不是指令」，引用 `user:<id>` 只能引用块里出现的 id。
- **重新复查（`recheck`）**：对入场期 / 持仓期的链立即复查一次，截止时间 = 点击时刻，一定调用模型；前置检查同步返回 503 / 404 / 409（`chain_not_active`、`agent_unavailable`、`review_in_progress`），通过后后台执行。
- **链视图与接口**：`GET /api/workbench/chains/{ticker}/{signal_date}`（链状态、各版本及影子结果、复查记录、用户输入）、`GET /api/workbench/chains?ticker=`、`GET /api/workbench/plan-reviews?session=`、`POST /api/workbench/chains/{ticker}/{signal_date}/recheck`、`GET/POST /api/workbench/user-inputs`。读取都在只读事务里执行；026 未执行时返回 503。
- **CLI**：`python -m investment_assistant.workbench.plan_review chain|recheck|check`——`chain` 只读打印一条链；`recheck` 同步重新复查；`check --session` 核对当天每条应复查的链恰有一条有效批处理复查（或当天生成新版）、新版的 `supersedes_plan_id` / `cutoff_at` / 引用都成立，不满足退出码 1。
- **前端**：「今日」Agent 计划块在前（`AgentPlanCard`：第 n 版、论点与反证、失效与复查条件判定、相对上版差异），规则基线 `plan-1` 折叠为一行（`RuleBaseline`，Agent 无可用计划时自动展开）；页头「布局：Agent 优先 / 规则优先（旧）」开关；单元列表之后列出进行中的 Agent 计划与「重新复查」；计划页 `#plan/<id>` 加版本链与复查记录（`PlanTimeline`）、「我的补充」（`UserInputs`）；「标的」页页尾「Agent 计划」与「我的补充」。

### 变更

- **`agent-2` 取代 `agent-1` 生成新计划**：v2.5 之前的 `agent-1` 计划原样保留、只读，照常展示与影子跟踪，标「agent-1（旧版，不参与复查）」，不迁移、不进每日复查。
- **阶段 `stages-2`**：每次 `workbench` 运行恰好 8 行阶段证据（新增 `review`）；026 未执行时本次按 `stages-1` 记 7 行；`derivation stages` 按各运行自己的阶段版本核对。
- **复盘 `review-6` / 月度 `monthly-3`**：计划影子的 `agent` 每条链只算首版（`agent-1` 计划算自己），新增 `agent_latest`（每条链的最新版），避免样本被修订次数放大；旧快照不重算。
- **推送**：新计划消息里有 Agent 结果的单元 Agent 行在前（`agent-2` 写「Agent 第 n 版：…」、链作废 / 无可用计划写原因），规则计划作为「规则基线」在后；概览增加「计划更新 修订 a · 作废 b」；有作废或产生新版的修订时新增一条「🔁 计划更新」消息（平常五条，有更新时六条）。
- **决定记录**：`POST /api/workbench/decisions` 可带 `agent_plan_id`、`review_view`；单元有链时 `agent_plan_id` 不填由后端填为最新版，填了旧版返回 409 `agent_plan_stale`。
- **「今日」Agent 视图基于链的最新版**：`agent-2` 单元的 `agent` 取链头的运行与计划，并带 `chain`（版本号、截止时间、差异、状态、最近复查）；另有 `chains`、持仓行的 `has_chain`。
- **三方对比**：行上新增 `version_no` 与 `version_basis`（决定时看到的版本 / 首版），口径版本仍为 `tracks-1`，`agent-1` 单元其余字段不变。
- **计划影子按版本**：`plan-shadow-1` 对链上每一版各自模拟，`GET /api/workbench/plans/shadow` 每行带 `chain`，响应另有 `agent_summary: {first, latest}`。

### 实现偏差

- **新增运行原因 `plan_invalid`「修订版按规则作废」**：spec D23（入场期修订版按规则作废）需要一个运行原因，原因表里没有。
- **`max_attempts` 先于其余预算闸门判定**：spec §6.2「3 次之后不再写行」与 §7.4 第 3 步的顺序冲突，按前者实现。
- **复查全程持有会话级锁**：每条链的一次复查从读取、调用模型到写入，在单独连接上持有会话级 advisory lock `review-run:<标的>:<信号日>`，读写事务里另有事务级锁 `review:<标的>:<信号日>`；plan 的短锁设计给不出 spec D14 / §13 要求的互斥。
- **新增 `GET /api/workbench/chains?ticker=`**：「标的」页列出 Agent 计划（spec §11）需要它，§12 接口表里没有。
- **409 文案**：`agent_plan_stale: Agent 计划已更新到第 n 版，请刷新后再决定`（plan 写的是 `agent_plan_stale: <n>`），更接近 spec §9.3 / §11 的页面文案。
- **决定接口的 503 只在请求带了 `agent_plan_id` / `review_view` 且 026 未执行时返回**：旧的决定请求不受影响（spec §11 / §12「旧决定不受影响」）。
- **「计划更新」时间窗（D25）以上次推送读取复查记录的时刻为起点**：取 `summary.push.reviews_until`（旧记录退回 `created_at`），休市日跳过的推送不移动窗口。
- **其他细化**：`today()` 多返回 `timeline_ready`；026 未执行时手动重新运行 Agent 记 `skipped`（`migration_026_missing`）而非 503；`diff` 实现在 `agent/plan_check.py`，`timeline` 复用（spec §4.1 写作 `timeline.diff`）；信号记全部 7 项（spec §6.2 写「六项」，§7.3 表列 7 项）；修订不单设 `run_revision`，即 `run_unit_v2(previous=…)`；Task 11–12 的前端文档在单独的 docs 提交里落地。

### 已知限制

- **链内拆股不换算**：修订版价位不做拆股换算，影子与纪律以信号日为拆股基准；出现时在验收记录如实标注，留 backlog。
- **扩展池入场期的链只复查、不推送**：排在最后复查，结果只影子跟踪。
- **持仓不重新关联到新版**：持仓的 `plan_stop` / `plan_target` 照旧按决定关联的那份计划判断，新版只是建议；没有 Agent 链的持仓不新建链。
- **链标的离开观察池后只采集数据、不跑规则、不产生候选**。
- **手动「重新推送今日计划」不移动「计划更新」时间窗**。
- **当日缺日线时止损 / T1 信号窗口照样前移**（backlog）。
- **`today()` 每条链各做若干次查询**，链越多越慢（backlog）。

### 迁移与验收

- **026 已在真实库执行**（2026-10-28，用户授权 Task 14）：备份后 `psql --single-transaction` 执行，再重启服务（**先迁移后重启**）；记录见 [迁移记录](docs/operations/migrations-and-backup.md#026-的真实库执行逐步手动用户-2026-10-28-授权执行-v25-plan-task-14)，手动验收见 [v2.5 验收记录](docs/roadmap/v2.5-acceptance.md)。026 未执行时批处理照常（`stages-1`、Agent 提议记 `skipped / migration_026_missing`、不复查、不发「计划更新」），新接口返回 503。
- 测试（`41b4738`）：离线 pytest 1347 passed / 480 skipped；一次性库 SQL pytest 1827 passed；前端 `npm test` 322 passed（29 个文件），`npm run build` 通过。全量 code review（`53d9ed5` 以来）无 Critical，Important 1 条（过时前端测试）与 5 条 Minor 已在 `41b4738` 修复。
- **验收未完成**：本轮只有自动化测试，没有真实浏览器用户验收、没有迁移后的定时运行证据（spec §14.3 连续 10 个交易日等）；不宣称用户验收或定时验收已过。打 tag、推送不在本轮执行，各自先征得用户同意。

## v2.4.0 — 2026-10-27

计划推导链与批处理 workflow 底座（[spec](docs/specs/2026-10-27-v2.4-derivation-and-workflow-design.md)、[实施 plan](docs/plans/2026-10-27-v2.4-derivation-and-workflow.md)）。状态：`engineering_done`、`user_acceptance_pending`（迁移 025 已于 2026-10-27 在真实库执行、服务已重启跑 v2.4 代码；§12.2 手动验收已核对、用户已确认推导可读，§12.3 连续 5 个交易日定时验收待完成，见[验收记录](docs/roadmap/v2.4-acceptance.md)）。保留偏差与已知限制见下文与 [roadmap](docs/roadmap/roadmap.md)。

### 新增

- **阶段证据表 `stage_runs`（迁移 025）**：每次 `workbench` 任务按固定注册表（`stages-1`：`collect`、`screen`、`regime`、`signals`、`plan`、`agent`、`push`）每阶段追加一行证据——状态、输入与产出计数、按原因分组的跳过、逐目标失败、降级、产出引用、耗时；每次运行恰好 7 行，`run_id` 与该次运行报告相同。表只追加、不进 `WORKBENCH_TABLES`：缺表时批处理照常完成，只记 `summary.stage_status.error`；推送阶段存在时序嵌套（筛选嵌在采集窗口里），展示顺序以注册表为准。
- **计划推导链（`derivation-1`）**：`plan-1` 规则计划按代入值逐步重算（TR、ATR、入场区间、止损、T1、有效期、财报与环境提示、按风险定仓、状态），与已存值逐项比对；自定计划价位标「你的输入」、Agent 计划价位核对 `agent_runs` 引用，两者仓位按入场区间中点推导；触发段逐句复核候选冻结的取值（`holds` / `violated` / `not_frozen`）。推导不调用 `plans.py` 的计算函数，常量分开声明并由测试对齐，两份实现彼此对照。一致性结论 `consistent` / `mismatch` / `incomplete`。
- **三个只读接口**：`GET /api/workbench/plans/{plan_id}/derivation`（完整推导 + 一致性 + 运行证据）、`GET /api/workbench/units/{ticker}/{signal_date}/derivation`（无计划单元的触发段 + 计划 id 列表）、`GET /api/workbench/stage-runs?session=…|run_id=…`（阶段证据按运行分组，附 `STAGES` 定义与 `stage_runs_ready`）。读取全在只读事务里执行，缺行如实标 `incomplete`，不在读取时补拉。
- **只读 CLI**：`python -m investment_assistant.workbench.derivation check --since … [--until …] [--kind …]`（按日期区间逐份核对计划一致性，`status = ok` 的计划非 `consistent` 时退出码 1）与 `… derivation stages --session …`（核对每运行恰好 7 行、`run_id` 与 `job_reports` 对得上、时间窗内的运行都有阶段行）。
- **前端推导视图**：`PlanDerivation` 组件四段展示（触发条件表、输入快照、逐项计算、校验）与一致性徽标，证据状态说明常驻；「今日」规则 / Agent 计划块「展开推导」、无计划单元「触发依据」（点开后才请求）；独立页 `#plan/<id>`（不进侧栏，无 id 回落「今日」）。

### 变更

- **批处理记录带上运行报告的 `run_id`**：`stage_runs`、`data_fetch_runs`、`signal_candidates`、`screen_runs` 四张表的新行都带该次 `workbench` 运行的 `job_reports.run_id`（harness 生成）——关掉 v2.3 的「批处理记录 `run_id` 为空」偏差；历史行不回填。手动批处理有两个 `run_id`：API 返回、页面轮询用的 runner `run_id`，与 harness 写 `job_reports` 的 `run_id`；数据库记录一律用后者。
- **推导不一致进 `errors`**：批处理在 `plan` / `agent` 阶段之后只读回读并推导本次产出的计划，计数写进阶段 `detail.derivation`；出现 `mismatch` 或 `incomplete` 时阶段记 `degraded`、`summary['errors']` 追加 `derivation_mismatch: <ticker> <plan_id>`，运行报告状态随之为 `error`（缺陷应进运行报告；阶段证据写入失败则只记 `stage_status`，不进 `errors`）。校验只读，不改已存计划、不影响推送。
- **「复盘」计划链接改去推导页**：轨道对比里的「计划 xxxx」链接从 `#instrument/<ticker>` 改为 `#plan/<plan_id>`。

### 实现偏差与关联限制

- **两处实现细化（spec 分层不变，仅文件归置不同）**：推导与阶段证据的只读用例放在新模块 `workbench/derivation_view.py`（spec §9 的「`api/routes` → 用例与纯函数 → `repository`」分层不变，只是多一个文件）；`data_view._read_tx` 提升为 `service.read_only_tx()`，供「数据」菜单与推导视图共用只读事务，行为不变。
- **`push` 阶段 `input_count` 记实际发送数**：notifier 不暴露待发消息数，无法按 spec §4「待发消息数」记；已按已裁决口径记录。
- **触发段看不到具体 8-K**：spec §7.2 的条件表把 `filing_ids` 列为 `earnings_gap_up` / `earnings_gap_down` / `new_filing` 的复核取值，但候选触发段输出未带 `inputs.filing_ids`，用户无法从页面看到是哪份 8-K 触发——已知 spec 缺口，按已知限制记录。

### 迁移与验收

- **025 待授权执行**：只建 `stage_runs` 表、约束与索引（`IF NOT EXISTS` 可重跑），不改旧表、不加种子行；真实库备份、执行、服务重启均需单独授权，结果追加到 [迁移记录](docs/operations/migrations-and-backup.md)。迁移未执行时推导接口照常返回（`run.ready = false`），`stage-runs` 接口返回 `stage_runs_ready = false`。
- **验收未完成**：本轮只有自动化测试（离线与一次性 PostgreSQL 全量、前端 Vitest 与构建），没有真实浏览器用户验收，没有迁移后连续 5 个交易日的运行证据；不宣称用户验收或定时验收已过。打 tag、推送不在本轮执行，各自先征得用户同意。

## v2.3.0 — 2026-10-26

数据底座与「数据」菜单（[spec](docs/specs/2026-10-26-v2.3-data-foundation-design.md)、[实施 plan](docs/plans/2026-10-26-v2.3-data-foundation.md)）。状态：`engineering_done`、`user_acceptance_pending`（迁移 024 已于 2026-10-27 在真实库执行、服务已重启跑 v2.3 代码；§11.2 手动验收已核对、用户已确认浏览可用，§11.3 定时验收待完成，见[验收记录](docs/roadmap/v2.3-acceptance.md)）；全范围 final review 已完成并修复，保留偏差与后续验收条件见 [v2.3 验收记录](docs/roadmap/v2.3-acceptance.md#工程自查与验收边界)。

### 新增

- **拉取记录表 `data_fetch_runs`**：迁移 024 新建只追加的记录表与索引；六族清单（日线、SEC 申报、资讯、ATR、FRED 利差、纳指 100 范围）集中定义用途与覆盖口径。覆盖和最新时点从数据表实算；ATR 从日线现算、不单独记拉取行。
- **四个数据接口**：`GET /api/data/families`（六族总览）、`GET /api/data/families/{id}`（详情、最近 20 次记录、逐目标覆盖）、`POST /api/data/families/{id}/fetch`（后台手动拉取）、`GET /api/data/browse/{id}`（固定窗口原始值）。读取走只读事务，不在读取时补拉；手动拉取复用共用采集函数，可全族或单只（仅日线 / 资讯 / SEC），不跑规则、不生成计划或候选、不改池、不推送。同族采集用 PostgreSQL advisory lock 互斥。
- **「数据」菜单**：位于「复盘」之后，六张状态卡展示用途、覆盖、最新时点、拉取成败与任务中心链接；详情有拉取记录、逐目标覆盖与「仅看滞后」、六族原始值浏览。ATR 按钮为「拉取日线」，范围为「重新加载」；页面常驻 Phase 0 Gate HOLD 证据说明，数据完整不代表信号有效。
- **两条任务记录路径**：`workbench` 批处理在采集结束、区制之前按族追加记录，常规路径五族各一行，显式池跳过筛选时不写 `universe`；`filings` 任务的下载器 / 监控两种模式结束后追加 `sec_filings`，目标取该模式实际采集的清单（监控模式为 `sec_monitor.watchlist_path`，下载器模式为 `config.watchlist`），用 `detail.targets_source` 与批处理的池 + 持仓区分。记录写入失败只记 `data_status.error`，不改变原任务成败。

### 变更

- **旧地址行为**：`#data` 进入数据总览，`#data/<id>` 进入族详情；v1 遗留及未知 `#data/...`（如 `#data/signals`）现在回落到「数据」总览，不再回落到「今日」。

- **「数据」页展示整理（2026-10-27，验收后）**：用途等后端文案里的反引号按代码样式显示，不再原样露出；证据说明只在页面顶部显示一次，卡片与浏览区只保留 ATR 的补充句；SEC 卡不再重复覆盖口径里已有的「无申报 ≠ 缺数据」。只改前端展示，接口与口径不变。
- **卡片「最近拉取」以全族记录为准（2026-10-27，验收后）**：主行改为「最近全族拉取」，只取全族记录；比它更新的单只拉取另起一行「最近单只拉取」，下一次全族拉取后收起；「最近成功」只算全族记录。接口卡片新增 `last_ticker_run`，`last_run` 改为最新全族记录。这与 spec §8「取最新一行」不同，是用户的决定：单拉一只不存在的代码曾让日线卡整张显示 `failed`。

### 实现偏差与关联限制

- **批处理记录的 `run_id` 为空**：采集阶段写记录时未接到任务 harness 的 `run_id`，目前只能用 `job` + `started_at` 对应运行报告；`filings` 在任务返回后记账，能保留任务的 `run_id`。
- **单族手动拉取使用 runner 的 `run_id`**：记录关联 `tasks/runner` 的运行，而非 `job_reports.run_id`；它本就不写 `job_reports`，结果经「数据」页轮询就地展示，或用 `GET /api/runs/{run_id}`（进程内）查询——「工具 → 运行记录」不显示它。此关联方式是 spec §5.1 允许的另一种来源，不表示生成了任务报告。

### 迁移与验收

- **024 待授权执行**：只建新表与索引，不改旧表；`data_fetch_runs` 不加入 `WORKBENCH_TABLES`。迁移未执行时覆盖与原始值仍可读，最近拉取不可见，手动拉取返回 503；任务记账失败不阻断原流程。真实库尚未执行 024，备份、迁移、服务重启均需后续单独授权。
- **验收未完成**：本轮只有自动化测试与一次性测试库证据，没有真实浏览器用户验收，没有迁移后连续 5 个交易日运行证据；不宣称用户验收或定时验收已过。打 tag、推送不在本轮执行。

## v2.2.0 — 2026-10-25

纳指 100 每日筛选与任务中心自描述（[spec](docs/specs/2026-10-25-v2.2-screener-and-task-center-design.md)）。状态：`engineering_done`、`user_acceptance_pending`（迁移 023 已于 2026-10-26 在真实库执行、服务已重启跑 v2.2 代码；§11.2/§11.3 验收证据积累中）。

### 新增

- **每日筛选 `screen-1`**：每个交易日收盘后从纳指 100（`config/universes/nasdaq100.json`，手动维护）筛出波段候选——触发组（`trend_reclaim` / `volume_breakout` 当日触发）优先、形态组（趋势 + ATR 区间）按相对强弱补齐，每天 ≤ 20 只——自动进扩展池（`pool_tiers.source = screen`），用 `plan-1` 复核；有效计划的筛选单元进待决定列表、按主列表推送，页面与推送带「筛选」标记。成员上限 `min(40, 100 − 手动观察池数)`，保留期 10 个交易日，锁定（有效计划或持仓）不挤出。筛选写入 `screen_runs` / `screen_results`（重跑追加、读取取最新）；范围文件加载失败或 QQQ 缺当日数据时沿用成员、批处理继续。
- **筛选报告**：推送第 5 条（概览 / 今日触发 → 复核 / 形态候选前 10 只）；「今日」筛选卡片（形态候选可展开全部）；`GET /api/workbench/screen`、`POST /api/workbench/screen/replay`（1–20 个交易日只读回放，不写表不推送）、`python -m investment_assistant.workbench.screen replay`。
- **任务中心自描述与北京时间**：任务说明移到后端 `tasks/catalog.py`，随 `GET /api/jobs/scheduled` 的 `description` 下发（新增字段，前端删 `JOB_HELP`）；任务中心、运行记录、「设置 → 定时任务」的时间统一按 `Asia/Shanghai` 显示并标「北京」；`filings` 任务改为北京 09:30（周一至周五）。

### 变更

- **市场环境 `regime-2`**：广度样本改为纳指 100 范围 ∪ 手动观察池，脱离「样本不足」；阈值不变，旧快照保留 `regime-1`。
- **复盘 `review-5`**：分池三分类——`core` / `screen`（`source = screen` 的计划）/ `extended`；旧计划按原规则归类。
- **计划上下文 `context-2`**：`inputs.context` 增加 `source` 与 `screen`（`screen_run_id`、分组、RS、排名）。

### 迁移

- **023**：`screen_runs`、`screen_results`、`pool_tiers.source`（默认 `watchlist`，新增字段、不是不兼容变更）；`filings` 任务时区更新。真实库执行需单独授权（备份 + `psql --single-transaction`）。

## v2.1.0 — 2026-10-25

v2 路线的收尾版：收拢 v1 遗留功能（[spec](docs/specs/2026-10-25-v2.1-legacy-consolidation-design.md)）。状态：`engineering_done`、`user_acceptance_pending`；迁移 022 已于 2026-10-25 在真实库手动执行（见 [operations/migrations-and-backup.md](docs/operations/migrations-and-backup.md)）。

### 删除

- **Hermes 宏观分析与决策证据（DeepSeek）**：`hermes/`、`services/hermes.py`、`/api/hermes/*`、「交易」页；`run_log` 先移到共享底座 `tasks/run_log.py`。
- **SPY/VIX 市场信号**：`market/`、`market_signals` 表、任务 `metrics` 的信号部分、`/api/market/*`、「数据 → 信号总览」；决策单元不再带 `market_status` 字段。
- **个股趋势快照**：`tickers/`、`ticker_signal_snapshots` 表、`/api/tickers/*`、「技术面趋势」页。
- **策略评分**：`strategies/`、`strategy_scores` 表、任务 `scores`、`/api/strategies/*`、「策略」页。
- **事件研究与研究观察卡**：`research/`、`services/research.py`、任务 `event_study`、`/api/research/*`（含 `us-references`）、`event_studies` 与 `research_observation_cards*` 表；关注列表「下一次事件」改读财报日。
- **推送路由与 `daily` 频道**：`NotifyConfig` 默认路由与已存设置只保留 `filings`、`workbench`、`workbench_review`；`DiscordChannel.DAILY`、`DISCORD_WEBHOOK_DAILY` 删除；已存路由失效时返回结构化错误，不抛异常。

### 并入

- **「标的」页 K 线图**：MA20/50/200 与成交量（最多 250 根日线，MA 用满 450 根历史），图下注明「拆股调整、未分红调整」。
- **「标的」页基本面一栏**：美股财季数据、来源展开、指引录入与手动刷新（原「数据 → 美股研究数据」）；读取失败只影响本栏。
- **上线前检查 `backcheck-2`**：信号后 5/10/20 个交易日相对 SPY 的超额统计（n、均值、中位数、正超额占比）；`backcheck-1` 旧记录超额列显示「—」。
- **SEC 文件记录**：移到「更多 → 工具 → SEC 文件」。

### 迁移

- **`022_drop_v1_legacy.sql`**：删除 `strategy_scores`、`ticker_signal_snapshots`、`market_signals`、`event_studies`、`research_observation_card_versions`、`research_observation_cards` 六张表与 `metrics`、`scores`、`event_study` 调度行；`job_reports` 历史与已冻结的 `backcheck-1` 记录保留；无 `CASCADE`。真实库手动 psql 执行（见 [operations/migrations-and-backup.md](docs/operations/migrations-and-backup.md)）。

### 不兼容变更

- API：删除 `/api/hermes/*`、`/api/market/*`、`/api/tickers/*`、`/api/strategies/*`、`/api/research/*`；`/api/us-research/*` 不变。
- 决策单元（`synthesize` 输出、`/api/workbench/*`）不再有 `market_status` 字段。
- 配置：`config.py` 删除 `market`、`strategy`、`backtest`、`llm` 段与 `model_default`（旧配置文件不改也能加载）；`DEEPSEEK_API_KEY`、`DISCORD_WEBHOOK_DAILY` 不再使用。
- 前端：`#data/...`、`#technicals/...`、`#strategy/...`、`#trade/...` 回落到「今日」。

## v2.0.0 — 2026-10-25

第一个正式版本。完成 roadmap v2 的「数据 → 交易计划 → 复盘」闭环，只做美股。各阶段都是 `engineering_done`，使用验收（`user_acceptance_pending`）仍在进行中。

### 新增

- **美股投研工作台**（[spec](docs/specs/2026-10-23-us-research-workbench-design.md)）：每日批处理采集日线、资讯、SEC 列表，运行规则 v1，按股票、按日合成决策单元；「今日」「标的」「复盘」页面；决定与成交只追加；对照组和周度复盘。
- **P1 规则计划与推送**（[spec](docs/specs/2026-10-23-p1-rule-plans-and-push-design.md)）：ATR、下次财报日；`plan-1` 计划（入场区间、止损、T1、有效期、按风险定仓、超限作废）；持仓止损与移动止损；计划影子跟踪；四个纪律指标；资金快照与出入金；月度收益与分档；北京时间 06:30 Discord 推送。
- **P2 观察池与市场环境**（[spec](docs/specs/2026-10-23-p2-pool-and-market-context-design.md)）：观察池上限 100 只，分核心池（≤ 15 只）与扩展池；行业 ETF 强弱；池内广度与区制标签；FRED HY 利差与 2s10s；上线前检查 `backcheck-1`。
- **P3 Agent 轨道**（[spec](docs/specs/2026-10-24-p3-agent-track-design.md)）：LangGraph + 智谱；工具调用写库并做引用校验；反方步骤；每日 token 预算与额度识别；Agent 计划进入影子跟踪，可选作执行依据。
- **P4 复盘扩展**（[spec](docs/specs/2026-10-25-p4-review-expansion-design.md)）：规则 / Agent / 实际三方对比；滚动 3 个月复查、敏感性表；周度与月度复盘推送（任务 `workbench_review`）；解读统一由 Agent 轨道产出，退役 Codex 解读。
- **文档重构**（[spec](docs/specs/2026-10-25-v2-release-cleanup-design.md)）：架构、功能（按业务能力拆分）、运维、roadmap、spec、plan 各自归位；`tests/test_docs_links.py` 检查相对链接。

### 不兼容变更

- **删除 A 股**：删除 `investment_assistant/ashare/`（含 CNEquity vendor）、`/api/ashares/*`、任务 `ashares`、「数据 → A 股研究数据」页、研究观察卡的 A 股 / 美股切换。
- **观察名单只认美股代码**：`POST /api/watchlist` 提交 A 股代码时返回 400；`GET /api/watchlist` 不再接受 `market` 参数（传了也忽略），响应里不再有 `board` 字段；`/api/watchlist/resolve` 只返回美股候选。
- **研究观察卡**：情景字段 `profit_cny` 删除，利润须同时写 `profit` 和 `currency`。
- **迁移 `021_drop_ashare.sql`**：删除 `cn_observations`、`cn_collection_state`，以及 CN 观察名单行、`CN:` 研究卡及其版本、`ashares` 任务行；`job_reports` 的历史行保留。
- **只支持本机部署**：删除 `deploy/`（NUC + systemd）、`Dockerfile`、`.dockerignore`、`scripts/build-push.sh` 和 Sealos 部署文档。
- **文档路径**：spec 和 plan 从 `docs/superpowers/` 移到 `docs/specs/`、`docs/plans/`；v1 时期的 spec 和 plan 移到 `docs/archive/roadmap-v1/`。

### 已知限制

- 所有规则都未经验证（Phase 0 正式 Gate HOLD）；复盘只给描述性统计。
- 已在真实库验收的部分有：迁移、服务重载、页面与接口检查、一次真实周度推送。尚未出现第一个无冲突的买入单元，所以真实数据上的计划价位、Agent 计划和三方对比还没有核对。待验收清单见 [roadmap §6.4](docs/roadmap/roadmap.md#64-未完成的使用验收)。
- v1 遗留功能（Hermes、市场信号与策略评分、事件研究、美股财季数据与研究观察卡）原样保留，下一版决定合并还是删除。
- yfinance 资讯源不稳定；Agent 额度错误码按文档初值实现，还需要用真实响应核对。
