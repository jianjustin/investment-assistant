# Agent 轨道

每个买入单元在规则主计划旁并列一条 Agent 建议；卖出、观察和有冲突的单元，由 Agent 生成只读解读。Agent 是**挑战者**：只做影子跟踪、并列展示，不改主计划。

设计：[P3 Agent 轨道](../specs/2026-10-24-p3-agent-track-design.md)、[P4 复盘扩展](../specs/2026-10-25-p4-review-expansion-design.md)（解读并入 Agent 轨道）、[v2.5 计划时间线](../specs/2026-10-28-v2.5-plan-timeline-design.md)（`agent-2` 结构与版本链）。

## 怎么工作

- **运行时**：LangGraph，默认模型智谱 `glm-5.3`（OpenAI 兼容接口），检查点存在本库（PostgresSaver）。
- **工具层**（`workbench/agent/tools.py`）：十个普通 Python 函数（批处理的提议、反方、复查、解读和复盘卡起草都用这十个）。前八个（`get_trigger`、`get_price_bars`、`get_indicators`、`get_filings`、`get_news`、`get_earnings`、`get_market_context`、`get_position`）只能读运行截止时间之前的数据，只允许查单元自身的标的和 SPY/SMH/XLK/QQQ，不接受日期参数。截止时间由批处理传入，模型无法修改。每次调用的参数、返回值和 SHA-256 都写入 `agent_tool_calls`。
- **`get_concept`**（v2.6，第九个工具）：`get_concept(concept_id=None)` 读取系统概念卡（[知识层](knowledge.md)）：不给 id 返回全部 id、标题与分组，给 id（如 `plan.stop`）返回整张卡（`concept_ref`、版本、`summary`、给 Agent 的纯文本 `body`、`content_sha256`）。它是**截止时间的唯一例外**：不读数据库、不用截止时间，概念卡随代码版本走，任何时刻读到的都是当前代码版本的卡；结果里写明 `point_in_time: false` 和说明，连同 `concept_ref`、`content_sha256` 原样存进 `agent_tool_calls`，推理阅读视图对这类调用标「概念卡随代码版本走，不受截止时间约束」。未知 id 记成错误信封「未知概念 <id>，不给 id 可取全部列表」；卡目录校验失败记成「概念卡不可用：<第一条问题>」，只影响这个工具。它不是价格类工具（价位仍须引用 `get_price_bars` / `get_indicators`），它的 `call:N` 与其它工具一样可以被论点引用；提示词、`agent_version`、工具轮数上限与预算都不变。
- **`get_knowledge`**（v2.7，第十个工具，排在 `get_concept` 之后）：`get_knowledge(ticker=None, concept=None)` 读你审定过的经验（[我的知识](knowledge.md)，只读条目、版本与状态三张表，**没有任何工具读复盘卡草稿或教训草稿**）。给 `ticker`（过同样的标的范围检查）或 `concept`（`plan.stop` 或 `concept:plan.stop@1`，版本忽略）取挂在上面的条目，两个都给 → 错误信封「ticker 与 concept 只能给一个」，未知概念 → 「未知概念 <id>」；都不给返回索引（`ref`、标题、挂靠、`written_at`，不含正文，至多 50 条）。条目按 `written_at` 倒序至多 10 条，超出记 `omitted`；每条带 `ref`（`know:<id>@<版本>`）、`id`、`version`、标题、正文、适用范围、反例、挂靠。**按截止时间读**：只含 `created_at ≤ cutoff` 的版本，截止时间时已归档的不返回，之后写的新版本、之后的归档都看不到；结果写明 `point_in_time: true`、`cutoff_at` 和说明「这是用户审定过的经验，是判断不是事实；价位不能只引用它」，推理阅读视图对这类调用标「我的知识按截止时间读取：只含截止时间之前写入的版本」。迁移 027 未执行 → 错误信封「我的知识不可用：迁移 027 未执行」，只影响这个工具。它不是价格类工具。
- **`know:` 引用与 `knowledge_citations`**（v2.7，`agent-2` / `agent-review-1` 不升版本）：论点、失效条件、变化说明、反证、风险和复查结论的引用里可以写 `know:<id>@<版本>`，**只能引用本次运行里 `get_knowledge` 返回过的版本**（`Recorder.knowledge_refs`，其余校验器不改，只是调用方传入的允许集合变大）；价位仍须引用价格类工具，所以经验不能单独支撑价位。提议、反方、复查三份提示词各加一段说明（`graph.KNOWLEDGE_NOTE`）。计划通过校验后，`growth_check.knowledge_citations` 从**保留下来的**字段抽出引用（`thesis`、`invalidation`、`changes`、`counter`、`risks`、`review`，价位的引用不记；被反方丢弃的条目不记），首版在 `_run_agent_unit` 写计划行的事务里、修订在写新版的事务里（带新版 `plan_id`）、复查在写 `plan_reviews` 行的事务里（带 `review_id`、`plan_id` 为空，维持 / 作废 / 修订结论都记）写进 `knowledge_citations`，每行带返回它的 `call_seq`；`pass`、作废、出错的运行不写。计划写入失败回滚时引用行一起回滚。
- **讨论专用工具**（v2.7，`workbench/agent/discuss_tools.py`，`DISCUSS_TOOLS`）：`get_plan_context`、`get_derivation(plan_id)`、`get_agent_run(run_id)` 三个只读工具，只给「就此计划讨论」的运行（`run_discuss`，十个批处理工具加这三个共十三个），批处理的各阶段绑定的工具集合恒为那十个（`graph._wrapped_tools(..., tools=)`）。它们只接受 `DiscussContext` 里记下的本单元计划与运行，越界返回错误信封「只能查本次讨论的计划与运行」；卡上下文只含冻结事实、是否已审定、审定记录和已采纳的知识，不含任何草稿，`get_agent_run` 也不读复盘卡的起草运行与讨论运行；`get_agent_run` 的工具结果每条截断到 2000 字。全部在调用方给的只读事务里执行，不写任何表。
- **复盘卡起草与讨论回答**（v2.7，`graph.run_retro` / `graph.run_discuss`，单阶段，版本 `agent-retro-1` / `agent-discuss-1`，运行 `mode` 为 `retro` / `discuss`）：输出由 `growth_check.check_draft` / `check_answer` 校验，引用允许 `fact:<键>`（复盘）或 `fact:context`（讨论）、本次 `call:N`、本次返回过的 `concept:` / `know:`、上下文里的 `user:<id>`；新的作废原因 `retro_malformed`、`lesson_invalid`、`answer_malformed`（另有 `migration_027_missing`、`discussion_busy`、`draft_exists` 三个前置检查的原因），文案见[作废与跳过原因](../knowledge/concepts/agent.reject_reasons.md)；讨论回答里不合格的经验草稿只丢弃草稿、回答照常（`draft_dropped`）。
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

## 就此计划讨论

从计划卡、「标的」页的计划行、复盘卡进入，问「这个止损怎么来的」「为什么这版放宽了入场区间」：Agent 只读这份计划（或这张卡）的推导链、运行记录、概念卡和你的经验，给带引用的解释，**不改任何东西**；需要时可以起草一条经验（落为草稿，等你审定）。设计：[v2.7 §8](../specs/2026-10-28-v2.7-growth-loop-design.md#8-就此计划讨论)，版本 `agent-discuss-1`，模块 `workbench/discussion.py`（用例）、`agent/discuss_tools.py` 与 `agent/growth_check.py`（工具与校验）。

- **新建与提问**：`POST /api/workbench/discussions`（body `{request_id, context: {kind: 'plan', plan_id} | {kind: 'card', card_id}}`）新建一次讨论（同一上下文可以有多次），再 `POST /api/workbench/discussions/{id}/turns`（body `{request_id, body, attachment?: {kind: 'draft' | 'knowledge', id, version?}}`，`body` 1–4000 字）提问。提问的前置检查同步执行并按顺序：参数 400，迁移 027 未执行 503，讨论不存在 404，同一 `request_id` 同内容返回原行（`status: replayed`）、不同内容 409 `request_id_conflict`，Agent 不可用 409 `agent_unavailable: <原因>`，当日 token 达上限 409 `token_budget`，上一个问题还在回答 409 `discussion_busy`；通过后写下你的这一轮，在后台调用模型，返回 **202** `{turn_id, run_id, status: pending}`。
- **读取与等待**：`GET /api/workbench/discussions/{id}` 返回上下文与按顺序排列的全部轮次，回答紧跟在它的提问后面；没有回答的提问带 `state`：`pending`（后台还在跑）或 `interrupted`（服务重启过或后台出错，页面写「没有收到回答（服务可能重启过），可以再问一次」，不算忙）。页面每 2 秒读一次，最长 600 秒。`GET /api/workbench/discussions?plan_id=|card_id=` 列出某个上下文的讨论。
- **截止时间 = 提问时刻**：回答的 `cutoff_at` 就是你那一轮的 `created_at`，工具读到的是截至这一刻的数据；提示词同时给出「计划当时的截止时间」，要求区分「当时看到的」与「之后发生的」（这靠提示词，机制上保证不了模型的措辞）。
- **工具**：十个批处理工具加三个讨论专用工具（见上），模型**没有任何写工具**；工具全部在 `service.read_only_tx()` 的真实只读事务里执行（宿主传入 `DiscussContext.read`，不是 `service._read_only`）。讨论只写四类行：你的一轮与回答（`discussion_turns`）、这次回答的运行与工具调用（`agent_runs`，`mode = discuss`；`agent_tool_calls`，`phase = discuss`）、可选的一条经验草稿（`knowledge_drafts`），测试比对一轮前后全库各表行数；每次 Agent 运行还会让 LangGraph 的检查点表（PostgresSaver）多几行，这不算在四类里，比对时把检查点表排除在外。讨论的 token 计入每日上限。
- **提示词与校验**：输入是上下文摘要（`[fact:context]`，含你输入过的 `user:<id>`）、最近 10 轮合计不超过 12000 字的问与答、你这一轮；附件原文另起一块，标「用户提供，非证据，不可引用」。回答校验（`check_answer`）：形状与长度 `answer_malformed`；`refs` 非空且每项是本次 `call:N`、本次返回过的 `concept:` / `know:`、上下文里的 `user:<id>` 或 `fact:context`，否则 `invalid_citation`，这一轮记 `rejected`，页面写「这次回答没有通过引用校验：<原因>」，原文折叠在「仍要看原文（未通过校验）」后面。经验草稿另校验（适用范围、反例必填，`target` 必须是附件里那条知识或本次返回过的），不合格只丢弃草稿、回答照常，轮次 `detail.draft_dropped` 记原因。
- **「存为补充信息」与「就这条改写」**：前者把你这一轮的原文按 `POST /api/workbench/user-inputs` 存为用户输入，`request_id = uuid5(NAMESPACE_URL, 'discussion-turn:' + <这一轮的 request_id>)`（前后端同一算法，`discussion.user_input_request_id`），重复点击幂等，讨论视图按它查出这一轮对应的 `user:<id>`，之后的问题里它可被引用；讨论本身不触发复查，要进计划得点「重新复查」。后者把一条草稿或知识的原文作为你这一轮的附件交给模型，改写结果仍是草稿，要在「我的知识 → 草稿」审定。
- **出错**：后台任何异常都会写一条 `status = error` 的回答（原因脱敏），不留无回答的悬空轮；额度用尽记 `error / quota_exhausted`。
- **怎么验证一次**：从计划卡问「这个止损怎么来的」，回答带引用，「看这次回答读了什么」打开推理视图可读；抽查全库，除上面四类行（和 LangGraph 检查点表的运行记录）外没有变化；让它起草一条经验，草稿出现在「我的知识 → 草稿」，采纳后成为新条目。
- **已知限制**：不做流式输出，一次回答可能要一两分钟；服务重启会中断正在进行的回答；`get_trigger`、`get_position` 不按截止时间过滤（沿用现状）；`get_agent_run` 不读复盘卡的起草运行与讨论运行。

## 推理阅读视图

`GET /api/workbench/agent-runs/{run_id}/reasoning`（v2.6，`workbench/reasoning.py`，只读事务、不调用外部数据源）把**一次 Agent 运行**按阅读顺序摊开：`run_id` 不是 UUID → 400，不存在 → 404，数据库不可用 → 503。覆盖 `propose`（首版）、`revise`（修订）、`review`（单阶段复查）、`interpret`（解读）、`retro`（复盘卡起草）、`discuss`（讨论回答）六种 `mode`，计划卡、版本链每版与复查记录各自链到生成它的运行。返回 `{run, legacy, version, review, steps, notes}`：

- **步骤**（每步 `{kind, title, concept}`，`concept` 是这一步的概念卡）：首版 `read`（提议者读了什么）→ `proposal`（动作、摘要、价位、论点 `T1…`、失效与复查条件、修订另含 `changes` 与宿主 `diff`）→ `check`（校验结果，**在反方之前**，与图里的执行顺序一致）→ `read`（反方读了什么）→ `counter` → `response` → `outcome`（生成的计划行状态与推导一致性，只对生成了计划的运行）；修订在最前面多一步 `evidence`（触发这次修订的复查：复查交易日、七项信号、条件判定、给模型的用户输入 id，并链到该复查自己的单阶段运行）；单阶段复查是 `evidence → read → verdict → check`；解读是 `read → interpretation → check`；复盘卡起草是 `evidence`（冻结事实的十个键与结束类型）`→ read → draft`（`summary` 标题、`items` 叙述各句与决定回顾、`lessons` 教训草稿）`→ check`；讨论回答是 `question`（你的问题、标「用户提供，非证据，不可引用」的附件、讨论对象）`→ read → answer`（回答、引用、经验草稿；被丢弃的草稿写在 `note`）`→ check`。
- **`read`**：每个调用 `{seq, ref: 'call:N', tool, tool_text, args, result, error, result_sha256_8, called_at, concept, fields, cutoff_exempt, cutoff_note}`。`fields` 把结果里的名字对应到概念卡：顶层键（`atr14`）、宏观序列（`macro.BAMLH0A0HYM2`）、`get_trigger` 返回的规则 id 取值（`trend_reclaim` → `rule.trend_reclaim`）、`get_concept` 返回的 `id`。`get_concept` 调用 `cutoff_exempt: true`；`get_knowledge` 调用的 `cutoff_note` 写「我的知识按截止时间读取：只含截止时间之前写入的版本」（`cutoff_exempt` 仍为 false），返回的 `entries[].ref` / `title` 在页面上链到条目页。
- **`check`**：列出这类运行适用的检查项，结果 `pass` / `implicated` / `not_recorded` / `not_run`。`ok` / `pass` → 全部通过；`rejected` → 作废原因出现在该项原因集合里的**全部**项标 `implicated`（校验器遇到第一处失败就停，只记原因，不推断哪些项通过了，`note` 写明这一点），其余 `not_recorded`；`error` / `skipped` → 全部 `not_run`，附原因文案。
- **`response`（回应）**：`agent-2` 流程没有单独的「回应」步骤，也不新增；这里的「回应」= 本版之后以本版为被复查对象的复查记录（结论、判定方、理由、触发的信号，修订时附新版的版本号与「相对上版变化」）。没有复查就写「回应：本版之后还没有复查」。`agent-1` 运行与没有生成计划的运行没有这一步。
- **反方读了什么**：第二个 `read` 步骤固定出现；反方跑了但没调工具写「反方没有调用工具」，反方没有运行（提议已作废或运行出错 / 跳过）写「反方没有运行」；提议者那一步没有记录到调用写「没有记录到工具调用」。
- **推导一致性读不出**：`outcome` 步骤的 `consistency` 为 `null`，`consistency_error` 给一行原因，`notes` 同时加一条「推导一致性没能读出（consistency_error）：…」，其余步骤不受影响。
- **作废的运行**（`rejected` / `error` / `skipped`）：已记录的工具调用照样给出；输出或反方存了就照常显示（例如入场期修订版因计划行作废而 `rejected / plan_invalid`，提议和反方都在），没存的那一步写「这次运行作废：<原因文案>，只保留工具调用」，`check` 照给。
- **`agent-1` 旧运行**：`legacy: true`，`notes` 写「agent-1（旧版）：没有失效条件、下次复查条件与逐条对应的反证，也不参与复查；以下按原样显示」；步骤是 `read → proposal`（论点作为「理由」）`→ check → read → counter`（只有 `risks`）`→ outcome`，没有 `response`。
- **迁移 026 未执行**：没有 `version`、`evidence`、`response`，`notes` 写「迁移 026 未执行，没有版本与复查记录」。

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
- API：`GET /api/workbench/agent-runs?since=`（运行列表与覆盖率 `coverage`）、`GET /api/workbench/agent-runs/{id}`（详情和全部工具调用）、`GET /api/workbench/agent-runs/{id}/reasoning`（推理阅读视图，见上）、`POST /api/workbench/agent-runs`（body `{ticker, signal_date}`；已有 `ok`/`pass` 返回 409，不是买入单元返回 400）。
- 命令行：`python -m investment_assistant.workbench.agent run --ticker X --date YYYY-MM-DD`。
- 运行报告：`summary.agent`（`{runs, tokens, quota_exhausted}`）、`summary.sources.agent`、`summary.timings.agent`；`error` 状态的运行带脱敏后的 `detail`。
- 验证一次：跑完批处理后 `GET /api/workbench/agent-runs`，`coverage.missing` 应为空；任选一个买入单元，Agent 卡片上每个价位旁都有引用编号，点开能看到工具调用和哈希。

## 已知限制

- 额度错误码（`1113`、`1308`、`1310`）和端点是按文档初值写的，需要拿真实响应核对（看 `error` 运行的 `detail`）。
- 模型输出格式不保证稳定：带围栏的 JSON 和数字字符串已做兼容；JSON 里夹带说明文字的，作废为 `malformed`。
- Agent 价位来自模型输出，不构成投资建议；证据状态仍是「未验证」。目前不设晋升机制，只观察，不安排用 Agent 替换主计划。
