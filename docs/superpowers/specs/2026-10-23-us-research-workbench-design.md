# 美股投研工作台 — 重新设计

日期：2026-10-23。基线 `main@76688de`。本文是已确认的设计，不是实施计划；实施计划另写。

## 1. 目标与非目标

把现有仓库收敛成一条美股主线：**信息采集 → 信号（买入／卖出／观察）→ 按收益复盘**。

已确认的前提：

| 决策 | 结论 |
|---|---|
| 范围 | 在现有仓库上收敛重构，不从零重写 |
| 信号产生 | 规则出候选 → LLM 解读 → 人确认 |
| 复盘口径 | 实际交易为主；未执行的信号自动跟踪作对照组 |
| 资讯来源 | 免费源起步：yfinance 新闻 + SEC 8-K |
| 持仓节奏 | 波段，数天到数周 |
| 股票池 | 少于 10 只 |

非目标：不自动下单、不接券商、不扩大股票池、不购买付费数据、不用回测结果反推规则参数、不回填或改写旧表数据。Phase 0 正式 Gate 继续 HOLD；本主线的复盘只做描述性统计，不宣称任何规则有效。

## 2. 设计原则

1. **只追加，不覆盖。** 信号、解读、决定、成交、复盘一律追加写入；更正通过新记录指向被更正记录（`supersedes_id`）或作废标记完成，不 UPDATE 业务字段。现有 `ticker_signal_snapshots`、`strategy_scores` 的同日覆盖语义不进入新主线。
2. **按时点可还原。** 每条记录区分数据时间（K 线日期、发布时间、受理时间）与系统获得时间（`fetched_at`）。生成信号和解读时，只能使用 `fetched_at` 早于本次运行截止时间、且数据时间不晚于信号日的记录。
3. **规则在代码里，带版本。** 每条候选记录 `rule_id` 与 `rule_version` 及完整输入快照。参数调整即发布新版本，旧信号保持原样可复现。
4. **人在环路。** LLM 只附加理由与反证，不改变动作；动作只由规则产出、由人确认。

## 3. 主流程与运行时点

每个交易日收盘后运行一次批处理。美东 16:00 收盘对应北京时间 04:00（夏令时）或 05:00（冬令时）；为等待数据源定稿，默认北京时间 06:30 运行，由现有调度器触发，按美股交易日历判断是否运行。

1. **采集**：拉取股票池与基准（SPY）的日线，同步 SEC 新文件，抓取资讯。
2. **规则**：对每只股票以 T 日（最近一个完成的交易日）运行全部启用规则，写入 `signal_candidates`。
3. **合成**：同一 ticker 同一 T 日的候选合成一个待决策单元（见 §6）。
4. **解读**：对有候选的股票调用 LLM，写入 `signal_briefs`；LLM 不可用时退回纯规则，状态记为 fallback。
5. **确认**：你在「今日」页面逐个决策单元采纳／否决／降级并写理由，写入 `signal_decisions`。
6. **成交**：你手动录入实际成交到 `trades`，可关联决策。
7. **复盘**：每周生成复盘并冻结统计结果到 `weekly_reviews`。

## 4. 数据模型

迁移候选编号 016（此前撤回的 RWV1 曾使用该编号，实施前再核对冲突）。所有时间戳为 `TIMESTAMPTZ`；所有表含服务端生成的 `created_at`，客户端不能回填。

### 4.1 `price_bars` — 日线

| 字段 | 说明 |
|---|---|
| `id` | BIGSERIAL |
| `ticker`, `price_date` | 标的与交易日 |
| `open`, `high`, `low`, `close`, `volume` | yfinance `auto_adjust=False` 的值：**已按拆股调整、未按分红调整**，用于与成交价对照 |
| `adj_close` | 拆股与分红均调整的收盘价，用于指标计算；复权因子 = `adj_close / close` |
| `split_factor` | 当日拆股比例（无则为 1），来自 yfinance `actions`；持仓期跨拆股时，用它把成交价换算到同一基础 |
| `source` | 默认 `yfinance` |
| `revision` | 同一 ticker+日期的版本号，从 1 开始 |
| `fetched_at` | 获取时间 |

唯一约束 `(ticker, price_date, revision)`。重新采集时值未变则不写；值变化（数据源修订、拆股复权变化）则写入 `revision+1`。读取默认取每个日期最新 revision 中 `fetched_at` 不晚于截止时间者。

### 4.2 `filings` — 扩展现有表

新增 `accepted_at TIMESTAMPTZ`（SEC 受理时间，用于判断盘前／盘中／盘后发布）与 `items TEXT[]`（8-K Item 列表，用于识别 2.02）。旧行保持 NULL，不猜测回填；`accepted_at` 为 NULL 的财报不能触发依赖发布时点的规则（B3／S2），只能触发 W1。

### 4.3 `news_items` 与 `news_item_tickers` — 资讯

`news_items`：`id`、`source`（`yfinance` / `sec_8k`）、`title`、`url`、`publisher`、`published_at`（可空，未知时显式为空）、`fetched_at`、`content_hash`。唯一约束 `(source, url)`。只保存元数据与链接，不抓取全文。

`news_item_tickers`：`(news_item_id, ticker)` 多对多。

### 4.4 `signal_candidates` — 规则候选

| 字段 | 说明 |
|---|---|
| `id` | UUID |
| `ticker`, `signal_date` | T 日 |
| `action` | `buy` / `sell` / `watch` |
| `rule_id`, `rule_version` | 如 `trend_reclaim`, `1` |
| `inputs` | JSONB：引用的 `price_bars.id`、`filings.id`、指标值、阈值 |
| `run_id`, `created_at` | 运行标识与写入时间 |

唯一约束 `(ticker, signal_date, rule_id, rule_version)`。重跑得到相同 `inputs` 时返回已有记录；不同时不覆盖，记录冲突到运行日志并在页面提示。

### 4.5 `signal_briefs` — LLM 解读

`id`、`ticker`、`signal_date`、`model`、`prompt_version`、`cutoff_at`、`input_refs`（引用的财报与资讯 ID，仅限发布时间与获取时间均不晚于 `cutoff_at`）、`output`（JSONB：`summary`、`support[]`、`contra[]`、`conflicts[]`，每条带引用 ID）、`status`（`ok` / `fallback` / `error`）、`created_at`。同一单元可有多次解读，页面默认展示最新一次。

### 4.6 `signal_decisions` — 你的确认

| 字段 | 说明 |
|---|---|
| `id` | UUID |
| `ticker`, `signal_date` | 决策单元 |
| `candidate_ids` | 本单元包含的候选 |
| `brief_id` | 决策时看到的解读，可空 |
| `proposed_action` | 合成后的建议动作（见 §6） |
| `final_action` | `buy` / `sell` / `watch` / `ignore` |
| `decision` | `accept` / `reject` / `downgrade` |
| `reason` | 必填一句话 |
| `decided_at` | 服务端时间 |
| `supersedes_id` | 更正时指向原决定 |

### 4.7 `trades` — 实际成交

`id`、`ticker`、`side`（`buy` / `sell`）、`quantity`、`price`、`fee`、`executed_at`（带时区）、`decision_id`（可空，允许无信号交易）、`note`、`recorded_at`、`voided_at`、`void_reason`。录错时作废并重录，不修改原行。持仓由有效成交按先进先出配对得出，不单独存表。

### 4.8 `weekly_reviews` — 周度复盘

`id`、`week_start`（周一，Asia/Shanghai 日期）、`calc_version`、`stats`（JSONB，生成当时冻结的统计）、`notes`（你的复盘笔记）、`created_at`、`supersedes_id`。

## 5. 首批信号规则（v1）

阈值为事先确定的默认值，不经历史数据调参。指标基于 `adj_close`；跳空比较基于 `open` 与前一日 `close`（同为拆股调整、未分红调整的基础）。相对强度规则暂不纳入 v1：现有 1.2 阈值的单位未确认，Phase 0 中处于挂起状态。

### 买入

| ID | 条件 |
|---|---|
| B1 `trend_reclaim` | 收盘 > MA50 > MA200；且 T 日收盘上穿 MA20，此前至少连续 3 个交易日收在 MA20 下方 |
| B2 `volume_breakout` | 收盘创 20 日收盘新高（不含 T 日）；成交量 ≥ 50 日均量 × 1.5；收盘 > MA50 |
| B3 `earnings_gap_up` | 8-K 含 Item 2.02 后的第一个交易日；开盘较前收盘跳空 ≥ +3%；收盘 ≥ 开盘 |

### 卖出

| ID | 条件 | 适用 |
|---|---|---|
| S1 `trend_break` | 此前至少连续 10 个交易日收在 MA50 上方；T 日收盘跌破 MA50 | 全部股票 |
| S2 `earnings_gap_down` | 8-K 含 Item 2.02 后的第一个交易日；跳空 ≤ −3%；收盘 ≤ 开盘 | 全部股票 |
| S3 `position_drawdown` | 收盘较持仓成本均价跌 ≥ 8%，或较持仓以来最高收盘回撤 ≥ 12% | 仅有持仓的股票 |

### 观察

| ID | 条件 |
|---|---|
| W1 `new_filing` | T 日出现新的 10-Q / 10-K / 8-K；强制触发 LLM 解读 |
| W2 `abnormal_move` | \|日收益\| ≥ 近 20 日日收益标准差 × 2.5，且当日无新财报 |

「财报后第一个交易日」：`accepted_at` 在美东 16:00 之后，取下一个交易日；在 09:30 之前，取当日；盘中发布，取当日但开盘跳空不计，规则不触发。

数据不足（不足 200 根 K 线、当日缺 bar、复权因子异常）时规则不产出候选，并在运行日志记录跳过原因，不写成「无信号」。

## 6. 决策单元合成

1. 同一 ticker、同一 T 日的全部候选合成一个单元。
2. 同时存在买入与卖出候选 → 标记「冲突」，`proposed_action = watch`。
3. 卖出候选出现在无持仓股票上 → 显示为「回避」，`proposed_action = sell`，进入对照组跟踪。
4. 其余情况取候选中的动作；多条同向候选合并展示。
5. 大盘状态（`market_signals` 红／黄／绿）v1 只作背景显示，不过滤、不降级。
6. 单元只有在你提交决定后才算处理完毕；未处理单元在第二天仍显示，并标注已过入场时点。

## 7. 复盘

### 7.1 实际交易

按先进先出配对成交，得到每笔已平仓与未平仓的持仓段。指标：持有天数、已实现／浮动盈亏（含费用）、同期 SPY 收益与超额、持有期最大浮盈／最大浮亏。可追溯到触发它的决定、候选规则和当时的 LLM 解读。

### 7.2 对照组

所有决策单元（含否决、观察、忽略）以 T+1 日 `open` 为假设入场价，收益按 `adj_close` 计算（含分红）：

- 买入：之后 5／10／20 个交易日收益及相对 SPY 超额。
- 卖出：同口径收益取反，表示「避开的跌幅」。
- 观察：只记录后续走势，不计盈亏。

对照组由日线按 `calc_version` 实时计算，不单独存表；周度复盘时冻结。窗口未到期的显示为「未成熟」，不以部分窗口代替。

### 7.3 周度复盘视角

1. **按规则**：每条规则的触发次数、对照组收益分布。
2. **按你的决定**：采纳 vs 否决的后续表现。
3. **执行偏差**：实际成交价与 T+1 开盘价的差距、决定到成交的延迟。
4. **无信号交易**：未关联决定的成交单列。

样本量小（少于 10 只股票，同日重叠），只展示计数、均值、中位数与分布，不计算显著性，不给出「规则有效」结论。

## 8. LLM 解读

复用现有 `investment_assistant/hermes` 的 DeepSeek 客户端与规则版回退方式。输入：候选及其输入快照、自上一个决策单元以来的财报（只给元数据与已解析段落）和资讯标题／链接。输出必须逐条引用输入 ID；引用不存在的 ID 视为无效并降级为 `error`。提示词带版本号，写入 `prompt_version`。资讯链接只作引用，不代表原文已核验。

## 9. 界面收敛

| 入口 | 内容 |
|---|---|
| 今日 | 待决策单元：候选、规则输入、LLM 理由与反证、最新财报与资讯；确认操作 |
| 标的 | 单股时间线：价格、财报、资讯、候选、决定、成交 |
| 复盘 | 持仓与成交录入、对照组、周度复盘 |
| 更多 | A 股、事件研究、研究观察卡、设置、运行记录等现有功能 |

现有六个顶层入口收进「更多」，保留只读可用，不删除。

## 10. 与现有能力的关系

| 现有能力 | 处理 |
|---|---|
| `data/price.py`（yfinance） | 复用取数，改为写入 `price_bars`（`auto_adjust=False`，另存 `adj_close` 与拆股比例） |
| `filings` 监控与下载 | 复用；扩展 `accepted_at`、`items` |
| `tickers/trend.py`、`strategies/trend_relative_strength.py` | 均线计算可复用；新规则独立实现，不改旧打分 |
| `ticker_signal_snapshots`、`strategy_scores`、`event_studies` | 保留只读，在「更多」中可用；新主线不写入、不回填 |
| `hermes` DeepSeek 客户端 | 复用 |
| 调度器 | 新增一个收盘后批处理任务 |
| 配置 `watchlist` | 作为股票池来源，上限 10 只 |

## 11. 错误与边界

- 数据源失败：本次运行对受影响股票不出候选，记录失败原因；不以前值或空值代替。
- 数据库或 schema 未就绪：接口返回 503，页面不显示为空列表，不自动执行迁移。
- 重复提交决定或成交：客户端带请求 ID，相同内容幂等返回，不同内容返回 409。
- 节假日与半日市：使用交易日历；半日市照常运行。

## 12. 测试与验收

- 每条规则：构造日线夹具，覆盖触发、边界不触发、数据不足三类。
- 时点：截止时间之后获取的数据不被使用；`accepted_at` 盘前／盘中／盘后三种情况。
- 只追加：重跑幂等、冲突不覆盖、决定更正与成交作废链。
- 复盘：先进先出配对、费用、未成熟窗口、卖出取反口径。
- LLM：回退、引用无效 ID 降级。
- 端到端：一只股票从采集到周度复盘的离线全流程，网络与真实数据库均不参与。

软件交付、真实运行、四周使用观察、规则有效性是四类不同证据，分别验收。
