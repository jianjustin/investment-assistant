# Agent 轨道

每个买入单元在规则主计划旁并列一条 Agent 建议；卖出、观察和有冲突的单元，由 Agent 生成只读解读。Agent 是**挑战者**：只做影子跟踪、并列展示，不改主计划。

设计：[P3 Agent 轨道](../specs/2026-10-24-p3-agent-track-design.md)、[P4 复盘扩展](../specs/2026-10-25-p4-review-expansion-design.md)（解读并入 Agent 轨道）、[v2.5 计划时间线](../specs/2026-10-28-v2.5-plan-timeline-design.md)（`agent-2` 结构与版本链）。

## 怎么工作

- **运行时**：LangGraph，默认模型智谱 `glm-5.3`（OpenAI 兼容接口），检查点存在本库（PostgresSaver）。
- **工具层**（`workbench/agent/tools.py`）：八个普通 Python 函数，只能读运行截止时间之前的数据，只允许查单元自身的标的和 SPY/SMH/XLK/QQQ，不接受日期参数。截止时间由批处理传入，模型无法修改。每次调用的参数、返回值和 SHA-256 都写入 `agent_tool_calls`。
- **提议（`propose`，`agent-2`）**：独立给出动作、入场区间、止损、T1，以及下面几项结构化字段。每个价位和论点都要引用一次已写库的工具调用（`call:N`）；引用不存在，或价位找不到价格类工具支撑，整条作废（`rejected / invalid_citation`），只显示原因、不显示内容。还要通过基本校验，比如买入的止损必须低于入场。任一字段校验不过，整版作废：
  - **论点** `thesis`：1–3 条，每条带引用，宿主按顺序编号 `T1…T3`；条数不对 → `thesis_count`。
  - **失效条件** `invalidation`：1–5 条，取自条件集合（见下），每条带引用；**下次复查条件** `review_when`：0–3 条，留空等于「下一交易日」。`kind` 未登记、不能用在这一栏、参数不合法或缺引用 → `invalid_condition`。
  - **相对上版变化** `changes`：首版不填（填了 → `malformed`）；修订版必填，字段集合必须等于宿主算出的差异（`changes_mismatch`），没有差异 → `no_change`。修订只由每日复查生成。
- **条件集合 `condition-1`**（`agent/conditions.py`，失效与复查共用）：`close_below` / `close_above`（`price`）、`no_entry_by`（`date`，仅失效）、`no_entry_before_earnings`（仅失效）、`earnings_within`（`sessions` 1–10）、`regime_is`（`label`）、`sector_weak`、`rs_below`（`window` 20/60、`value`）、`new_filing`（`form` 8-K/10-Q/10-K）、`date_reached`（`date`，仅复查）、`next_session`（仅复查）。价格须在生成时最近收盘的 ±50% 内，日期须晚于本版生成交易日且不超过其后 60 天。每条判定为成立 / 未成立 / 无法判定，数据缺失一律「无法判定」，不当作成立。
- **反方**：逐条对论点给出反证（`counter: [{thesis, text, refs}]`），其余风险进 `risks`；引用不存在或论点编号不存在的条目丢弃并计数，没有反证的论点列入 `uncountered`。反方不改价位和动作。
- **Agent 计划与版本链**：结果为 `ok` 的首版生成 `agent` 计划（`plan_version = agent-2`），同一个事务里依次写计划行、运行行与工具调用、版本行 `agent_plan_versions`（`version_no = 0`、`origin = signal`、`cutoff_at` 等于运行的截止时间）和简报，任何一步失败都整体回滚，单元记 `error`。有效期 T+1…T+3、移动止损与 `plan-1` 相同，仓位按入场区间中点计算，`inputs` 另记 `as_of_session`、`version_no`、`supersedes_plan_id`、`chain_entry_cap`（入场期链上限：信号日后第 10 个交易日）。手动「重新运行 Agent」同样只生成首版；已有 `ok` / `pass` 时返回 409。首版计划进入影子跟踪和推导核对（`('agent-2', 'agent')`：价位核对 `agent_runs.output`，有效期按 `as_of_session` 与链上限推导，缺版本行 → `incomplete`）。采纳时可以把执行依据选为「Agent 建议」。
- **`agent-1` 旧版**：v2.5 之前生成的 `agent-1` 计划原样保留、只读，照常展示与影子跟踪，标「agent-1（旧版，不参与复查）」；不迁移、不回填、不进每日复查。
- **解读（`interpret`，`agent-brief-1`）**：无冲突买入单元的解读，直接取提议的摘要和第一条反证（`agent-1` 运行取反方风险）；其余单元单独跑一次单阶段解读。模型不可用或校验失败时，退回规则版摘要。
- **隔离**：Agent 在规则计划全部写入之后才开始，失败只影响 Agent 轨道。每个单元最多尝试 3 次（超过记 `skipped / max_attempts`）；批处理开始 1500 秒后不再启动新单元；智谱额度用尽时其余单元记 `skipped / quota_exhausted`；达到每日 token 上限时记 `skipped / token_budget`。扩展池单元也跑，但排在后面，结果不推送。
- **迁移 026 未执行**：写不了版本行，所以需要提议的单元逐个记 `skipped / migration_026_missing`（主列表单元照旧得到规则版简报），解读照常运行；`agent` 阶段记 `degraded`（`migration_026_missing`），`summary.errors` 加一条 `timeline: migration_026_missing`；规则计划照常。「今日」照旧按最新运行显示，不带链。

## 计划时间线

一个单元（标的、信号日）的全部 `agent-2` 版本组成一条**版本链**，每天复查一次，你贴入的研报、新闻和判断作为证据参与复查。设计见 [v2.5 计划时间线](../specs/2026-10-28-v2.5-plan-timeline-design.md) §5、§7、§8、§12。

- **版本链**：第 0 版（`origin = signal`）由信号日批处理生成；第 1 版起只由复查生成（`review` 每日复查、`recheck` 重新复查），`supersedes_plan_id` 指向上一版，链不分叉。每一版都是一行 `trade_plans`，有自己的截止时间（生成时刻）、`as_of_session`、宿主差异 `diff` 与模型的变化说明 `changes`，各自做影子跟踪；旧版写入后不再改动。链状态（`timeline-1`）按顺序取第一条成立的：`invalidated`（被复查作废）、`closed_by_decision`（决定不买）、`holding`（决定链上的买入还有未平批次）、`position_closed`、`expired`（过了最新版截止日未成交）、`entry`（其余）；只有 `entry` 与 `holding` 会被复查。
- **每日复查**：批处理第 7 个阶段 `review`，规则见 [每日计划 · 每日复查](daily-plan.md#每日复查)：失效条件成立由系统规则作废；没有信号、没有新的用户输入、复查条件都未满足由系统规则维持；其余调用一次 `agent-review-1`，结论为修订时再走一次完整的提议 + 反方 + 校验，通过才成为新的最新版。每条结论写一行 `plan_reviews`。
- **信号**：`new_8k`、`abnormal_move`、`stop_touched`、`t1_touched`、`expiry_near`、`regime_change`、`user_input`，窗口都是「上次有效复查之后」，七项不论是否触发都记进复查记录。
- **用户输入**（`user_inputs`，只追加）：类型 `research`（研报要点）/ `news`（新闻）/ `judgment`（我的判断）/ `other`，正文 1–4000 字，可附 `http(s)://` 链接（≤ 500 字，不抓取）；不填 `signal_date` 作用于该标的所有链，填了只作用于这一条链（单元必须有候选，否则 404）。**更正**或**撤回**（`kind = retract`）都是新的一行，用 `supersedes_id` 指向同一标的的旧行（不是同一标的 → 400）；旧版计划引用过的旧行永远可读，之后的复查只看到截止时间之前仍有效的行。同一 `request_id` 同内容返回原行（`status = replayed`），不同内容 409。复查与修订的提示词里附「用户输入」证据块：上次复查之后的新输入给原文（最多 10 条、合计 8000 字，超出的记「另有 n 条未纳入」），更早的只给标题行；原文每一行前都加 `    │ ` 前缀，宿主的「原文开始 / 原文结束」标记行没有这个前缀，正文无法伪造标记或标题；提示词写明用户输入只是证据、不是指令，引用 `user:<id>` 只能引用块里出现的 id。新输入触发 `user_input` 信号，即一次认真复查，本身不会直接改计划。
- **重新复查**：对 `entry` / `holding` 的链立即复查一次（`trigger = recheck`）。截止时间 = 点击时刻（请求进入时取，不是后台开始执行的时刻），复查交易日 = 该时刻最近已收盘的交易日；跳过「无事可看」的系统维持，一定调用模型（失效条件成立仍由系统规则作废）；新版 `origin = recheck`；不受每天 3 次的限制，但受每日 token 上限与额度限制。前置检查同步执行：迁移 026 未执行 503、没有链 404、链不在入场期 / 持仓期 409 `chain_not_active`、Agent 不可用 409 `agent_unavailable: <原因>`、该链正在复查 409 `review_in_progress`，都不写行；通过后在后台执行（同「立即运行批处理」），返回 `{run_id, status: pending}`，用 `GET /api/runs/{run_id}` 查结果。**互斥**：每条链的一次复查（批处理或重新复查）从读取、调用模型到写入，全程在一条不经连接池的专用数据库连接上持有会话级 advisory lock `review-run:<标的>:<信号日>`（不占连接池，连接用完即关）；读取与写入事务里另有事务级锁 `review:<标的>:<信号日>`。前置检查只试运行锁，不试探事务级写锁（试探若恰好落在批处理的写事务里，会让批处理在花完 token 后丢掉这次复查）。所以批处理正在复查这条链（包括正在等模型）时点「重新复查」→ 409 `review_in_progress`；连点两次，第二次 409；重新复查正在跑时批处理跳过该链（`review_in_progress`，不写行）。已排队的后台任务开始时先取这把锁，拿不到就以 `review_in_progress` 结束，不调用模型。模型调用期间链被别的写入改动（例如你提交了不买的决定）时，这次复查不写复查记录，但模型运行照样记成 `skipped`（`review_in_progress`）并带上 token，计入每日 token 上限。
- **入口**：
  - API：`GET /api/workbench/chains?ticker=`（该标的全部链，含已结束的，信号日倒序：`signal_date`、`state`、`mode`、`version_no`、`head_plan_id`、`latest_review`（`outcome`、`decided_by`、`created_at`、`reason`，没有有效复查为 `null`），供「标的」页列出 Agent 计划）；`GET /api/workbench/chains/{ticker}/{signal_date}`（链视图：`state`（`state`、`mode`、`basis`）、`versions`（每版的计划行、生成运行的输出与反方、`changes`、`diff`、`plan-shadow-1` 影子结果）、`reviews`（全部复查记录，带被复查与产生的版本号）、`inputs`（作用于这条链的用户输入，带 `ref`、`status`：`active` / `corrected` / `retracted`））；`GET /api/workbench/plan-reviews?session=`（某个复查交易日的全部复查记录）；`POST /api/workbench/chains/{ticker}/{signal_date}/recheck`；`GET /api/workbench/user-inputs?ticker=&signal_date=`（不带 `signal_date` 时列出该标的全部输入）与 `POST /api/workbench/user-inputs`（body `{request_id, ticker, signal_date?, kind, body, source_url?, supersedes_id?}`）。读取接口都在只读事务里执行，不调用外部数据源；迁移 026 未执行时这些接口都返回 503「迁移 026 未执行」。
  - 命令行 `python -m investment_assistant.workbench.plan_review`：`chain --ticker X --date YYYY-MM-DD`（打印链状态、各版本、复查记录与用户输入，只读；没有链退出码 1）；`recheck --ticker X --date YYYY-MM-DD`（同步重新复查，打印复查记录与新版 id；冲突退出码 1）；`check --session YYYY-MM-DD`（只读）：该交易日每条应复查的链（按批处理开始时的最新版判定处于 `entry` / `holding`，未被 `object_cap` 排除）恰有一条有效批处理复查，或最新版就是当天生成的（`fresh_version`）；列出缺复查的链及其 `skipped` / `error` 行与阶段跳过原因；「批处理开始时」取当天 `review` 阶段证据行的开始时间（没有阶段证据时取该链当天第一条批处理复查记录；两者都没有时，当天重新复查产生的版本不算作批处理看到的版本），被排除的链与无行跳过的原因取自该行的 `detail.excluded`（逐链，不截断）。当天生成的每一版 `supersedes_plan_id` 指向上一版、`cutoff_at` 等于生成运行的 `cutoff_at`、输出与反方里的引用都成立（`call:N` 是生成运行自己的工具调用，`user:<id>` 是该标的的输入且 `created_at ≤ cutoff_at`），当天复查记录的引用同样核对。任一不满足退出码 1；参数错误（含不是美股代码的 `--ticker`）、数据库不可用或迁移 026 未执行退出码 2；其余异常照常抛出。
- **怎么验证一次**：批处理跑完后执行 `plan_review check --session <当天>`，应为「通过」；信号日当天新生成的链显示「当天生成（fresh_version）」。任选一条入场期的链，`POST /api/workbench/user-inputs` 贴一条判断（带 `signal_date`），再 `POST …/recheck`，轮询 `/api/runs/{run_id}` 到 `done`；`GET /api/workbench/chains/…` 的 `reviews` 末尾多一条 `trigger = recheck` 的记录，其 `cutoff_at` 等于点击时刻、`user_input_ids` 含刚贴的输入、`signals` 里 `user_input` 已触发。
- **已知限制**：
  - `check` 按当前记录的决定与成交判定链状态（与复查阶段同一口径）；版本与复查记录按批处理开始前的为准。
  - 重新复查在后台线程里执行，服务重启会丢掉还没跑完的任务（不写行，锁随连接关闭释放）；页面轮询到 `error` 时可以再点一次。每条正在复查的链多占用一个数据库连接（持锁用）。
  - 用户输入的时间以数据库写入时刻为准，不能补登更早的时间；更正、撤回只对之后的复查生效，不回填旧版。
  - `GET /api/workbench/user-inputs` 不带 `signal_date` 时，按该标的的候选日逐个读取各链的输入，候选日很多时较慢。

## 配置

| 环境变量 | 说明 |
| --- | --- |
| `WORKBENCH_AGENT_PROVIDER` | `zhipu`（默认）或 `off` |
| `ZHIPU_API_KEY` | 智谱密钥；只从环境变量读取，出现在错误文本里时一律替换为 `***` |
| `WORKBENCH_AGENT_MODEL` | 默认 `glm-5.3` |
| `WORKBENCH_AGENT_BASE_URL` | 默认 GLM Coding Plan 端点 `https://open.bigmodel.cn/api/coding/paas/v4` |
| `WORKBENCH_AGENT_DAILY_TOKENS` | 可选，每日 token 上限 |

首次使用前建检查点表：`python -m investment_assistant.workbench.agent setup`。

## 入口与验证

- 页面：「今日」的 Agent 建议卡片（引用编号可以展开，看到工具调用的参数、返回值和哈希前 8 位；失败时有「重新运行 Agent」）；「复盘 → 轨道对比」里点 Agent 运行 id。
- 「今日」接口（`GET /api/workbench/today`）：`agent-2` 单元的 `agent` 取**链的最新版**的运行与计划（不是最新一次运行），并带 `chain`（`version_no`、`head_plan_id`、最新版的生成时间 `cutoff_at` 与相对上一版的宿主差异 `diff`（第 0 版为 `null`）、`state`、`mode`、`basis`、`latest_review`（最近一次有效复查，含各条件的判定 `conditions`））；`agent-1` 单元带 `legacy: true`。另有 `chains`（已决定买入、等待成交的入场期链与持仓期链：第几版、最近复查的结论 / 判定方 / 时间 / 理由前 40 字、当日触发的信号）、持仓行的 `has_chain`（持仓所在单元有 `agent-2` 链，任何状态都算）与 `chain_state`（该链在 S 的状态：`holding`，或在持仓期间结束的状态如 `invalidated`；无链为 `null`），以及 `timeline_ready`（迁移 026 是否就绪）。
- API：`GET /api/workbench/agent-runs?since=`（运行列表与覆盖率 `coverage`）、`GET /api/workbench/agent-runs/{id}`（详情和全部工具调用）、`POST /api/workbench/agent-runs`（body `{ticker, signal_date}`；已有 `ok`/`pass` 返回 409，不是买入单元返回 400）。
- 命令行：`python -m investment_assistant.workbench.agent run --ticker X --date YYYY-MM-DD`。
- 运行报告：`summary.agent`（`{runs, tokens, quota_exhausted}`）、`summary.sources.agent`、`summary.timings.agent`；`error` 状态的运行带脱敏后的 `detail`。
- 验证一次：跑完批处理后 `GET /api/workbench/agent-runs`，`coverage.missing` 应为空；任选一个买入单元，Agent 卡片上每个价位旁都有引用编号，点开能看到工具调用和哈希。

## 已知限制

- 额度错误码（`1113`、`1308`、`1310`）和端点是按文档初值写的，需要拿真实响应核对（看 `error` 运行的 `detail`）。
- 模型输出格式不保证稳定：带围栏的 JSON 和数字字符串已做兼容；JSON 里夹带说明文字的，作废为 `malformed`。
- Agent 价位来自模型输出，不构成投资建议；证据状态仍是「未验证」。目前不设晋升机制，只观察，不安排用 Agent 替换主计划。
