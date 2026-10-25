# 美股投研工作台

主线：**信息采集 → 信号（买入／卖出／观察）→ 按收益复盘**。设计见 [2026-10-23 设计文档](superpowers/specs/2026-10-23-us-research-workbench-design.md)，实施顺序见 [实施计划](superpowers/plans/2026-10-23-us-research-workbench.md)。

工作台只给出研究候选，不自动下单、不接券商。复盘只做描述性统计，不证明任何规则有效；Phase 0 正式 Gate 仍为 HOLD。

## 上线前提

1. 对目标数据库执行迁移 `016_us_workbench.sql`（新增 8 张表、`filings` 两个可空列、一个调度任务）。未迁移时，所有工作台接口返回 503，页面显示「数据库未就绪」，不会显示成空列表，也不会自动迁移。
2. 工作台标的来自数据库观察名单（`watchlist_items` 中 `active` 的美股即观察池，上限 100 只、核心池上限 15 只；配置 `watchlist` 不再被工作台读取，其他任务照旧）。超过上限时写入与批处理都会报错，不会静默截断。
2a. P1 起需再执行迁移 `017_trade_plans.sql`（新增 5 张表与 `signal_decisions.plan_id`，只追加不回填）；未迁移时计划相关接口与推送同样返回 503。执行前先 `pg_dump` 备份。
2b. 配置新增 `workbench` 段：`risk_pct`（单笔风险，默认 0.01）、`single_cap`（单票上限 0.25）、`total_cap`（总持仓上限 1.0）、`public_url`（推送链接前缀，默认 `http://localhost:8787`）、`return_tiers`（月度收益分档，默认 `[0.20, 0.10, 0.0]`）。示例见 `config/investment-assistant.example.json`；改参数不需要新 `plan_version`，参数会冻结进每份计划。
3. LLM 解读由 `WORKBENCH_LLM_PROVIDER` 选择：默认 `codex`，通过本机 Codex CLI 使用已登录的 ChatGPT 套餐（只读沙箱、不保存会话、单次约 20 秒）；`deepseek` 需要 `DEEPSEEK_API_KEY`；`off` 关闭。调用失败时退回规则版解读。可用 `WORKBENCH_CODEX_MODEL` 指定模型。
4. `SEC_USER_AGENT`（含联系邮箱）用于 SEC 列表；列表失败只记入运行报告。
2c. P2 起需再执行迁移 `018_pool_and_market_context.sql`（新增 `pool_tiers`、`macro_observations`、`market_regimes`、`rule_backchecks` 四张表，只追加）；执行前先 `pg_dump` 备份。配置环境变量 `FRED_API_KEY`（FRED 官方 API 密钥；未配置时运行报告记「未配置」，不写库、不发请求）。在「设置 → 观察名单」为打算重点跟踪的美股勾选「核心」、按需选行业 ETF（SMH/XLK/QQQ）。
2d. P3 起需再执行迁移 `019_agent_track.sql`（新增 `agent_runs`、`agent_tool_calls`，并把 `trade_plans.kind` 放宽为含 `agent`；对旧表只放宽约束与加部分唯一索引，不 UPDATE、不 DELETE、不回填）；执行前先 `pg_dump` 备份。另需对目标库执行一次 `python -m investment_assistant.workbench.agent setup`（由 LangGraph 自带的 `PostgresSaver.setup()` 建 `checkpoints` 等三张表，不进本项目迁移）。配置环境变量 `ZHIPU_API_KEY`（智谱密钥），并核对 `WORKBENCH_AGENT_BASE_URL`（默认 `https://open.bigmodel.cn/api/coding/paas/v4`，即 GLM Coding Plan 端点）。

## 每日流程

| 时间（北京） | 发生什么 | 你要做的 |
|---|---|---|
| 周二至周六 06:30 | 调度任务 `workbench` 运行：拉取日线（含 SPY）、yfinance 搜索资讯（只保留 relatedTickers 含本股的条目）、SEC 列表；对最近收盘交易日运行规则；为有候选的股票生成解读。纽约当天不是交易日时跳过 | 无 |
| 早上 | 打开「今日」：每个股票一天一个决策单元，显示候选规则、输入值、解读（支持／反证／冲突，每条带引用）、近期财报与资讯 | 选择采纳／否决／降级为观察，写一句理由，提交 |
| 成交后 | 「复盘 → 交易与持仓」录入成交（本机时区时间），可关联当时的决定 | 录错时「作废」并写理由，再重新录入 |
| 每周 | 「复盘 → 周度复盘」选择周一，生成快照并写笔记 | 需要更正时对同一周再次生成，新快照指向旧快照 |

也可以在「今日」点「立即运行批处理」手动触发；手动运行总是针对最近一个已收盘的交易日（纽约 17:00 之后才算当天收盘）。

## 规则 v1

阈值事先固定，不用历史数据调参；改阈值即发布新版本，旧信号保留原版本与输入。

| 规则 | 动作 | 条件 |
|---|---|---|
| 趋势回踩修复 `trend_reclaim` | 买入 | 收盘 > MA50 > MA200，且收盘重新站上 MA20，此前至少连续 3 天在 MA20 下方 |
| 放量突破 `volume_breakout` | 买入 | 收盘创前 20 日收盘新高，成交量 ≥ 前 50 日均量 × 1.5，收盘 > MA50 |
| 财报跳空向上 `earnings_gap_up` | 买入 | 8-K Item 2.02 后第一个交易日，开盘较前收盘跳空 ≥ +3%，收盘 ≥ 开盘 |
| 跌破 MA50 `trend_break` | 卖出 | 此前至少连续 10 天收在 MA50 上方，当日跌破 |
| 财报跳空向下 `earnings_gap_down` | 卖出 | 财报后第一个交易日跳空 ≤ −3%，收盘 ≤ 开盘 |
| 持仓回撤 `position_drawdown` | 卖出 | 仅有持仓时：收盘较成本跌 ≥ 8%，或较持仓以来最高收盘回撤 ≥ 12% |
| 新财报 `new_filing` | 观察 | 当日出现新的 10-Q／10-K／8-K |
| 异常波动 `abnormal_move` | 观察 | 日收益绝对值 ≥ 近 20 日波动率 × 2.5，且当日无新财报 |

- 财报时点按 SEC 受理时间判断：盘后发布算下一个交易日，盘前算当天，盘中发布不触发跳空规则。EDGAR 的受理时间是 UTC（`Z` 后缀），已用真实 8-K 核对过（filingDate 10-21 的盘后 Item 2.02 8-K 标为 `2026-10-22T00:41:42Z`，即纽约 20:41）。批处理会用 SEC 列表补全财报库中缺失的受理时间和 Item，只补空值不覆盖；仍缺受理时间的财报只能触发「新财报」。
- 不足 200 根日线、当日缺日线或复权因子异常时，价格规则不产出候选，并在运行报告记录跳过原因，不写成「无信号」。
- 同一天同时出现买入和卖出候选标记「冲突」并默认观察；没有持仓的卖出候选标记「回避」。大盘状态只作背景显示，不过滤信号。

## 复盘口径

- **实际交易**：先进先出配对，买入费用计入成本，卖出费用按数量分摊；跨拆股时按拆股比例换算。显示持有交易日数、盈亏、同期 SPY、最大浮盈与浮亏。
- **对照组**：所有已决定的单元（包括否决和观察）都假设在下一交易日开盘入场，统计 5／10／20 个交易日相对 SPY 的超额收益；卖出单元取反（避开的跌幅），观察单元只记录走势。窗口没走完显示「未成熟」，不用部分窗口代替。
- **周度复盘**：按规则、按决定（采纳／否决／降级）、执行偏差（成交价较下一交易日开盘、决定到成交的小时数）、无信号交易四个视角，只给计数、均值、中位数和原始数值。快照生成后冻结，之后更正决定不会改变已生成的快照。

## 交易计划

- **功能**：批处理为「建议买入且无冲突、未决定」的单元生成 `plan-1` 规则计划：参考价取 T 日收盘，ATR14（Wilder，拆股调整口径），入场区间 ±0.5 ATR、止损 −2 ATR、T1 +4 ATR（2R），有效期 T+1 至 T+3 个交易日；价位四舍五入到 0.01。仓位按「资金 × 1% ÷ 每股风险」与单票、总持仓两个市值上限取最小，缺资金快照时只给每股风险并标注 `no_equity`；无空间时计划作废（`no_room`）。有效期内有财报 → 计划作废；之后 10 个交易日内有财报 → 提示；未知或已过 → 提示。重跑结果相同返回原计划，不同则记入运行报告的冲突列表，不覆盖。采纳时可改价：提交自定价位会另存一份 `own` 计划并与决定同事务写入，作废原因降级为提示，建议股数按新价位重算。
- **手动入口**：页面「今日」（单元卡片直接显示价位、股数、提示与作废原因；采纳表单可选「规则计划 / 自定价位」）；API `GET /api/workbench/today`（单元含 `plan`）、`POST /api/workbench/decisions`（`plan_id` 或 `own_plan` 二选一）；CLI 无单独入口，跟随批处理。
- **验证入口**：运行报告 `summary.plans`（每只股票 `inserted`/`existing`/`conflict`/`skip: 原因`）与 `summary.earnings`（财报采集，失败记 `error:` 不写库）；页面「今日」的单元卡片。
- **验证示例**：手动运行批处理后查看运行报告，`plans.SYNTH == "inserted"`；打开「今日」看到「入场区间 x–y · 止损 z · T1 w · 建议 N 股」与「证据：未验证」。

## 持仓止损

- **功能**：持仓的计划取「当前未平仓批次中最近一笔、且其决定关联了计划的买入」；有计划的持仓改用 `plan_stop`（T 日最低价 ≤ 当前止损）与 `plan_target`（开仓以来首次触及 T1，卖出一半，只触发一次），不再跑 `position_drawdown`；无计划的持仓照旧。触及 T1 后当前止损 = max(开仓以来最高收盘 − 3 ATR, 持仓成本)，收盘后更新、次日生效；价位遇拆股按比例换算。
- **手动入口**：页面「今日」底部「持仓止损」区块（每只持仓的当前止损、模式、是否触及 T1、距止损/T1 百分比、下次财报）；API `GET /api/workbench/today` 的 `holdings`；规则候选照旧出现在单元卡片。
- **验证入口**：运行报告 `tickers.<T>.candidates` 中出现 `plan_stop`/`plan_target`；页面「今日」持仓区块。
- **验证示例**：持仓某股触及 T1 次日，运行报告出现 `plan_target` 候选；「今日」持仓行显示「止损 …（移动）· 已触 T1」。

## 观察池与分层

- **功能**：观察池 = 观察名单中 `active` 的美股（≤ 100 只），带 `core` 标签的为核心池（≤ 15 只），其余为扩展池；`sector:<ETF>` 标签把个股映射到行业 ETF（SMH/XLK/QQQ）。批处理 = 观察池 ∪ 当前持仓：持仓股不论分层都按核心池对待（推送、解读），但不在观察池中的持仓不计入市场广度。每次批处理把分层变更追加进 `pool_tiers`（`effective_session` 为本次交易日）；某股某日的分层按「`effective_session <= 该日` 且 `recorded_at <= 截止时间` 的最新一行」还原。扩展池单元照常生成规则计划与影子跟踪（仓位照算），但不调用 LLM 解读、不进「今日」待决定列表、不推送；「今日」在底部折叠区只读显示。周度复盘（`review-3`）分池统计：按信号日的分层归池，不看现在的分层。
- **手动入口**：页面「设置 → 观察名单」美股行的「核心」勾选与「行业 ETF」下拉（写成标签；表头显示「美股池 n/100 · 核心 m/15」）；写入时超限或标签不规范返回 400 且不改观察名单。
- **验证入口**：运行报告 `summary.pool`（`core/extended/holdings/changes`）；表 `pool_tiers`；页面「今日」扩展池折叠区与「复盘 → 周度复盘」分池表。
- **验证示例**：在「设置 → 观察名单」给某美股勾选「核心」，次日运行报告 `pool.changes` 出现一条 `tier: core`；周中改分层的股票在当周周度复盘中仍按信号日分层归池。

## 市场环境

- **功能**：每次批处理在采集之后、规则之前生成市场环境快照（`regime-1`，表 `market_regimes`）：池内广度（当日有 K 线的观察池股票，`adj_close` 口径：站上 MA50/MA200 占比、52 周新高/新低）、区制标签（MA200 合格样本 < 20 为「样本不足」；占比 ≥ 60% 且 MA50 占比 ≥ 50% 为「进攻」；< 40% 且 < 30% 为「防守」；其余「中性」）、行业 ETF 相对 SPY 的 20/60 日强弱（rs20/rs60，弱/强/分化/数据不足）、FRED 利差背景（`BAMLH0A0HYM2` HY OAS 与 `T10Y2Y`，各 120 天，含 20 个观测前变化；值为 `.` 跳过；修订追加）。区制只作提示：每份计划把 `context`（分层、区制、行业、下次财报日）冻结进 `inputs.context`，防守区制、快照失败、行业弱势分别追加提示 `regime_risk_off` / `regime_unavailable` / `sector_weak`，不改价位、仓位与有效性（`plan_version` 仍为 `plan-1`）。FRED 密钥只取环境变量，任何日志与错误文本中出现即替换为 `***`。
- **手动入口**：页面「今日」顶部「市场环境」卡片（区制、广度、行业强弱、利差；无数据时分别写「FRED 未配置」「FRED 采集失败」「FRED 无数据」）；计划卡片上的「区制 · 下次财报 · 行业」一行；推送概览的「市场环境」字段与「扩展池新计划 N 份（不推送）」。
- **验证入口**：运行报告 `summary.regime`（`inserted/existing/conflict` 与标签）、`summary.etfs`、`summary.macro`、`summary.sources`（按数据源列失败：日线/资讯/财报日期/SEC/ETF 日线/FRED/区制）、`summary.timings`（collect/regime/rules/total 秒数；总耗时 > 1800 秒记 `batch_over_budget`）；表 `market_regimes`、`macro_observations`；页面「今日」。
- **验证示例**：批处理运行报告中 `regime: {status: inserted, label: risk_on}`、`macro.BAMLH0A0HYM2.inserted > 0`；「今日」市场环境卡片显示「市场环境 进攻 · 站上 MA50 …%」，新计划卡片显示「区制 进攻 · 下次财报 … · 行业 SMH 强」。

## Agent 轨道

- **功能**：每个买入单元在规则主计划旁多一条 Agent 建议（LangGraph + 智谱 `glm-5.3`）。Agent 通过八个工具读取截止时间之前的数据（只允许单元标的与 SPY/SMH/XLK/QQQ，不接受日期参数），独立给出动作、入场区间、止损、T1 和带引用的理由；「反方」步骤找反证并核对引用。每个价位和理由都引用一次写库的工具调用（`call:N`），引用不存在或价位没有价格类工具支撑时整条作废（`rejected / invalid_citation`），只显示原因、不显示内容。`ok` 的建议生成 `agent` 计划（`agent-1`，有效期与移动止损同 `plan-1`，仓位按入场区间中点）并进入影子跟踪；采纳时可把执行依据选为「Agent 建议」，纪律轨道记为 `agent`。扩展池单元也跑，排在主列表之后，其建议不推送。批处理在规则计划全部写入之后才开始；Agent 失败只记在 Agent 轨道，不影响规则计划与推送。每单元最多 3 次尝试、超过后只记一行 `skipped / max_attempts`；批处理开始 1500 秒后不再启动新单元；智谱 5 小时窗口额度用尽时其余单元记 `skipped / quota_exhausted`，规则轨道照常。
- **环境变量**：`WORKBENCH_AGENT_PROVIDER`（`zhipu` 默认 / `off` 关闭）；`ZHIPU_API_KEY`；`WORKBENCH_AGENT_MODEL`（默认 `glm-5.3`）；`WORKBENCH_AGENT_BASE_URL`（默认智谱 OpenAI 兼容端点）；`WORKBENCH_AGENT_DAILY_TOKENS`（可选正整数，当日已用 token 达到上限后其余单元 `skipped / token_budget`）。密钥只从环境变量读取，出现在错误文本中一律替换为 `***`。
- **手动入口**：页面「今日」的 Agent 建议卡片（失败时「重新运行 Agent」按钮，引用编号可展开查看工具调用的参数、返回值与哈希前 8 位）；API `GET /api/workbench/agent-runs?since=`（运行列表与覆盖率）、`GET /api/workbench/agent-runs/{id}`（运行详情与全部工具调用）、`POST /api/workbench/agent-runs`（body `{ticker, signal_date}`，已有 `ok`/`pass` 返回 409，不是买入单元返回 400）；命令行 `python -m investment_assistant.workbench.agent run --ticker X --date YYYY-MM-DD`（同手动接口）、`python -m investment_assistant.workbench.agent setup`（建检查点表）。
- **验证入口**：运行报告的 `summary.agent`（`{runs, tokens, quota_exhausted}`）、`summary.sources.agent`（状态为 `error` 的标的）、`summary.timings.agent`；`GET /api/workbench/agent-runs` 的 `coverage.missing`（区间内没有 Agent 建议或明确原因的买入单元）；运行详情的工具调用与 `result_sha256`；`error` 运行的 `detail`（脱敏后的异常文本，密钥替换为 `***`，运行列表与详情都返回）；页面「今日」与推送的 Agent 行（`ok` 写价位与第一条反方风险，`pass` 写不建议，其余写「Agent 未给出建议（原因）」）。
- **验证示例**：跑一次批处理后 `GET /api/workbench/agent-runs`，`coverage` 显示 `covered / units` 全覆盖、`missing` 为空；打开「今日」任一买入单元，Agent 建议卡片的每个价位旁有引用编号，点开可见工具调用与哈希。

## 上线前检查

- **功能**：`backcheck-1`，新规则上线前手动运行，回答「触发是否过频、止损是否总被扫掉」。只读库里已存 K 线（当前修订）与 SEC 文件，不联网、不补采：每只股票前 200 根 K 线只做指标预热，评估区每个交易日以当时为止的 K 线运行现有规则（无持仓），买入候选按 `plan-1` 算价位、`plan-shadow-1` 模拟；`valid_until` 后不足 20 个交易日的信号计入触发数不计入结果。统计每条规则与合计：触发数、每 100 个股票日触发数、同日 ≥ 3 只齐触的日数、成交/过期数、5 个交易日内止损占比、到达 T1 占比、R 均值/中位数/四分位；标记 `too_frequent`（> 5/100 股票日）、`stops_swept`（成交 ≥ 10 且 5 日内止损 ≥ 50%）、`insufficient`（成交 < 10）。结果冻结进 `rule_backchecks`，页面注明「描述性检查，不调参，不代表规则有效」。
- **手动入口**：页面「复盘 → 上线前检查」（列表与「运行历史检查」按钮）；API `GET/POST /api/workbench/backchecks`（body 可含 `tickers`）；命令行 `python -m investment_assistant.workbench.backcheck [--tickers A,B]`（默认当前观察池）。
- **验证入口**：页面「复盘 → 上线前检查」的运行记录（时间、标的、触发/成交数、标记）；表 `rule_backchecks`。
- **验证示例**：`python -m investment_assistant.workbench.backcheck` 打印记录 id 与 `stats.all` 的 JSON；页面「上线前检查」出现一条运行，标记为 `insufficient`（当前观察池历史成交不足 10 笔属正常）。

## 推送

- **功能**：定时运行在批处理之后自动推送当日简报到 Discord（默认 `signals` 频道，可在设置中改或关）：概览、新计划、持仓、待处理与异常四条消息；无新计划也推送；同一交易日已成功推送则不再重复；纽约休市推一行「纽约休市，未运行」。字段值截断到 1024 字符、单条 ≤ 6000 字符，超出写「其余 N 条见系统」。推送失败只写入运行报告，不让批处理失败；下次推送附「上次推送失败」。手动运行批处理不推送。
- **手动入口**：页面「今日」右上「重新推送今日计划」（强制重推）；API `POST /api/workbench/push`；渠道与开关在「设置」中按任务键 `workbench` 调整。
- **验证入口**：运行报告 `summary.push`（`{session, sent, reason?, messages}`）；Discord `signals` 频道。
- **验证示例**：在「今日」点「重新推送今日计划」，页面提示「已推送 N 条」，运行报告 `push.sent == true`。

## 资金与月度复盘

- **功能**：月末按券商录总资金快照（`as_of` + 权益），更正必须指向当前有效快照；出入金按笔录入（入金为正），只能作废。月度收益 =（本月末快照 − 上月末快照 − 区间净出入金）÷ 上月末快照，任一端缺快照显示「缺资金快照，无法计算」；附分档（>20% 非常优秀 / 10–20% 优秀 / 0–10% 可行 / <0 需关注）、同期 SPY 与超额、流程复查（连续 3 个月复合收益 < 0 且跑输 SPY 才标记）、敏感性表（当月已平仓交易的实际 R 按 0.5%/1%/1.5%/2% 近似）、当月纪律与计划影子。周度复盘升为 `review-2`，新增计划影子与纪律两个视角；已生成的旧快照不变。计划影子（`plan-shadow-1`）按价位独立模拟规则与自定计划：三种入场、止损与 T1 同日按止损先、移动止损保本下限、跳空穿止损按开盘价。
- **手动入口**：页面「复盘 → 资金」（快照与出入金录入、作废；风险参数只读显示）与「复盘 → 月度复盘」（选月份生成、查看）；API `GET/POST /api/workbench/account/snapshots`、`GET/POST /api/workbench/account/flows`、`POST /api/workbench/account/flows/{id}/void`、`GET/POST /api/workbench/monthly-reviews`、`GET /api/workbench/plans/shadow`、`GET /api/workbench/discipline`；CLI 无。
- **验证入口**：页面两个页签；月度快照生成后冻结（`stats` JSONB），更正需 supersede。
- **验证示例**：录 8-31 与 9-30 两笔快照后，「复盘 → 月度复盘」选 2026-09-01 生成，页面显示「月度收益 +5.00% · 可行 · SPY …」。

## 数据与时点

- 日线保存 yfinance `auto_adjust=False` 的开高低收（已按拆股调整、未按分红调整）和全复权收盘价；数据源改值时追加修订版本，不覆盖。
- 规则与解读只使用运行截止时间之前已获取的数据；资讯发布时间未知时显示「发布时间未知」，不用获取时间冒充。
- 资讯只保存标题与链接，不抓取正文；有链接不代表原文已核验。LLM 解读引用了不存在的输入时整条作废并隐藏，只显示失败原因。
- 这不是严格的历史时点回测：yfinance 历史数据会被修订，本系统只能保证「自本系统开始采集后」的记录可按时点还原。

## 已知限制

- 免费资讯源覆盖与稳定性有限：yfinance 的 `Ticker.get_news` 已被 Yahoo 改为 404（yfinance 会静默返回空列表），现改用搜索接口；运行报告的 `news.fetched` 为 0 时说明资讯源再次失效。SEC 列表依赖 `SEC_USER_AGENT`。
- 样本量小（观察池 100 只以内、重叠信号多），统计结果没有推断意义；上线前检查只是描述性统计。
- 原有六个入口收在侧栏「更多」下，保持只读可用；新主线不写入、不回填旧的快照与评分表。
- Agent 轨道的额度错误码（`1113`、`1308`、`1310`）与智谱 OpenAI 兼容端点是按文档初值写的，需按真实响应核对（看 `error` 运行的 `detail`）；模型输出格式不保证稳定，围栏 JSON 与数字字符串已兼容，夹带说明文字会作废为 `malformed`。Agent 计划价位来自模型输出，不构成投资建议，Phase 0 证据状态仍为「未验证」。

## 验证记录（2026-10-23）

工程完成、运行待验收。离线测试使用替身数据源和一次性 PostgreSQL 测试库（独立 schema，测试后删除）；没有对真实数据库执行迁移，没有启动或重启服务，没有真实采集，也没有浏览器验收。
