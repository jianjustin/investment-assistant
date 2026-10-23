---
title: 美股投研工作台实施计划
tags: [美股, 信号, 复盘, 实施计划]
created: 2026-10-23
---

# 美股投研工作台实施计划

设计：[2026-10-23-us-research-workbench-design.md](../specs/2026-10-23-us-research-workbench-design.md)（`3c69575`）。本文只规定实施顺序、文件与验证方式；设计决定以设计文档为准，不在这里重新讨论。

## 0. 执行边界

- 在 `main` 上串行实施，每个任务结束提交一次，只 `git add` 本任务列出的路径。工作树中已有的 `docs/roadmap/README.md`、`docs/design/`、`docs/roadmap/08-living-collaboration.md` 与本计划无关，不得提交或修改。
- 每个任务先写失败测试，再实现，再跑本任务测试与相关回归。
- 数据库测试只在显式的 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 下用 `pg_temp` 临时表运行（沿用 `tests/test_us_research_postgres.py` 的方式）；未提供时跳过，并在任务报告里如实记为「SQL 未验证」。不对真实库执行迁移。
- 测试不访问网络：yfinance、SEC、DeepSeek 一律通过注入的 fetcher／client 替身。
- 不启动、重启或停止本地服务与调度器；前端不运行默认 `npm run build`（会覆盖运行中的 `web/dist`），构建检查输出到 `.local/us-workbench/build-review/`。
- 不推送、不部署。真实迁移、服务重载、真实数据采集与使用验收另行授权。

后端测试命令统一为：

```bash
env -u INVESTMENT_ASSISTANT_DATABASE_URL SCHEDULER_ENABLED=0 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest <测试文件> -q
```

前端测试命令（在 `web/` 目录）：

```bash
npx vitest run <测试文件>
```

## 1. 新代码位置

```
investment_assistant/workbench/
  __init__.py
  bars.py          # 日线采集、规范化、按截止时间读取
  news.py          # 资讯采集与去重
  rules.py         # 8 条 v1 规则（纯函数）
  synthesis.py     # 决策单元合成
  briefs.py        # LLM 解读：提示词 v1、引用校验、回退
  ledger.py        # 决定与成交：幂等、更正、作废
  positions.py     # 先进先出持仓与拆股换算（纯函数）
  review.py        # 对照组、交易复盘、周度复盘
  repository.py    # 全部 SQL；本层不 commit
  service.py       # 事务边界与对外接口
investment_assistant/tasks/workbench.py
investment_assistant/api/routes/workbench.py
migrations/016_us_workbench.sql
web/src/routes/Today.svelte, Instrument.svelte, Review.svelte, More.svelte
web/src/lib/workbench.ts
tests/test_workbench_*.py
```

## 2. 任务

### Task 1：迁移与 schema

**文件：** `migrations/016_us_workbench.sql`、`tests/test_workbench_schema.py`、`tests/test_workbench_postgres.py`（后续任务追加用例）

1. 先确认 `migrations/` 中没有其他 016；有冲突则顺延编号并同步修改本计划。
2. 失败测试（离线）：读取 SQL 文本，断言八张表、`filings` 两个新列、各唯一约束存在；断言 SQL 不含 `UPDATE`、`DELETE`、对旧表的回填。
3. 写 SQL：
   - `price_bars`：设计 §4.1 字段，加 `split_factor NUMERIC NOT NULL DEFAULT 1`，唯一 `(ticker, price_date, revision)`。
   - `filings`：`ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ`、`items TEXT[]`。
   - `news_items`、`news_item_tickers`：设计 §4.3。
   - `signal_candidates`、`signal_briefs`：设计 §4.4、§4.5，主键 UUID。
   - `signal_decisions`、`trades`：设计 §4.6、§4.7，另加 `request_id UUID NOT NULL UNIQUE` 与 `request_hash TEXT NOT NULL`，用于设计 §11 的幂等提交。
   - `weekly_reviews`：设计 §4.8。
   - `scheduled_jobs` 插入 `('workbench', '06:30', '2-6', 'Asia/Shanghai')`，`ON CONFLICT DO NOTHING`。北京时间周二至周六对应美股周一至周五收盘；节假日由任务内部按交易日历跳过。
4. 有测试库时：`pg_temp` 中执行建表，验证唯一约束与 CHECK 约束（`action`、`decision`、`side` 等枚举）。
5. 提交：`feat: add US workbench schema`。

### Task 2：日线采集与读取

**文件：** `investment_assistant/workbench/bars.py`、`repository.py`（日线部分）、`tests/test_workbench_bars.py`

1. 失败测试：
   - 规范化：给定 `auto_adjust=False` 形态的 DataFrame（含 `Adj Close`、`Stock Splits`），输出 `open/high/low/close/volume/adj_close/split_factor`；`Stock Splits` 为 0 时记为 1。
   - 修订：同值重采不写；值变化写 `revision+1`；旧 revision 保留。
   - 截止时间：`fetched_at` 晚于截止时间的 revision 不被读取。
   - 缺 bar：T 日无数据时返回明确的缺失状态，不用前值替代。
2. 实现：`fetch_bars(ticker, start, end, *, fetcher)` 默认用 `yf.Ticker(t).history(auto_adjust=False, actions=True)`；`store_bars(conn, rows, *, now)`；`read_bars(conn, ticker, end_date, *, cutoff_at, limit)`。复用 `data/calendar.py` 判断交易日。
3. 提交：`feat: collect revisioned daily bars for US workbench`。

### Task 3：SEC 受理时间与 Item

**文件：** `investment_assistant/filings/monitor_source.py`、`investment_assistant/db.py`（`INSERT INTO filings` 处）、`tests/test_sec_monitor.py`、`tests/test_filings_repository.py`

1. 失败测试：submissions JSON 的 `acceptanceDateTime`、`items` 被解析为带时区的 `accepted_at` 和 `items` 列表；缺字段时为 `None`，不猜测。
2. 实现：在现有结果字典中增加两个字段并写入 `filings` 新列；旧行不回填。
3. 回归：`tests/test_sec_monitor.py tests/test_filings_repository.py tests/test_filings_task.py tests/test_services_filings.py`。
4. 提交：`feat: record SEC acceptance time and 8-K items`。

### Task 4：资讯采集

**文件：** `investment_assistant/workbench/news.py`、`repository.py`（资讯部分）、`tests/test_workbench_news.py`

1. 失败测试：yfinance 新闻条目（含新旧两种字段形态）规范化为标题、链接、媒体、`published_at`；无发布时间时为 `None`；8-K 转为 `source='sec_8k'` 的资讯；`(source, url)` 去重；同一链接关联多个 ticker。
2. 实现：只存元数据与链接，不抓正文；单条解析失败跳过并计数，不中断整批。
3. 提交：`feat: collect news metadata for US workbench`。

### Task 5：持仓（纯函数）

**文件：** `investment_assistant/workbench/positions.py`、`tests/test_workbench_positions.py`

S3 规则和交易复盘都依赖持仓，因此先于规则实现。

1. 失败测试：先进先出配对、部分平仓、费用摊入成本、作废成交不参与、持仓期内拆股后按 `split_factor` 换算成本与数量、卖出超过持仓时报错。
2. 实现：输入成交列表与拆股序列，输出持仓段（开仓日、平仓日、数量、成本、已实现盈亏）与当前持仓（成本均价、持仓以来最高收盘需由调用方传入日线）。
3. 提交：`feat: derive FIFO positions for US workbench`。

### Task 6：信号规则

**文件：** `investment_assistant/workbench/rules.py`、`tests/test_workbench_rules.py`、`tests/fixtures/workbench/`（合成日线）

1. 失败测试：8 条规则各覆盖「触发／边界不触发／数据不足跳过」三类；另测：
   - 财报日映射：`accepted_at` 盘后→下一交易日、盘前→当日、盘中→不触发、`None`→不触发 B3/S2 但可触发 W1。
   - S3 只在有持仓时评估。
   - 每个候选的 `inputs` 包含引用的 bar id、指标值与阈值；`rule_version` 为 `1`。
   - 不足 200 根 bar、T 日缺 bar、复权因子异常 → 返回跳过原因，不返回空候选列表冒充「无信号」。
2. 实现：每条规则是 `(bars, filings, position) -> Candidate | Skip | None` 的纯函数，阈值作为模块常量；`RULES` 注册表按设计 §5 顺序。
3. 提交：`feat: add v1 signal rules for US workbench`。

### Task 7：决策单元合成与候选持久化

**文件：** `investment_assistant/workbench/synthesis.py`、`repository.py`（候选部分）、`tests/test_workbench_synthesis.py`

1. 失败测试：设计 §6 的五种情况（冲突、无持仓卖出显示回避、同向合并、大盘状态只做背景、未处理单元次日仍可见并标注过期）；候选重跑相同 `inputs` 幂等返回，不同 `inputs` 不覆盖并返回冲突。
2. 提交：`feat: synthesize decision units from signal candidates`。

### Task 8：LLM 解读

**文件：** `investment_assistant/workbench/briefs.py`、`repository.py`（解读部分）、`tests/test_workbench_briefs.py`

1. 失败测试：
   - 输入只含 `published_at` 与 `fetched_at` 都不晚于 `cutoff_at` 的财报与资讯；`published_at` 为空的资讯以「发布时间未知」标注后可用。
   - 输出每条支持／反证／冲突都引用输入 ID；引用不存在的 ID → `status='error'`，不展示该输出。
   - 未配置密钥或调用失败 → `status='fallback'`，摘要由规则输入生成。
   - LLM 输出中出现动作字段时被忽略，候选动作不变。
2. 实现：复用 `hermes/deepseek_client.request_json_completion_verbose`；提示词常量带 `PROMPT_VERSION = "workbench-brief-1"`。
3. 提交：`feat: add cited LLM briefs for decision units`。

### Task 9：决定与成交

**文件：** `investment_assistant/workbench/ledger.py`、`repository.py`（决定与成交部分）、`tests/test_workbench_ledger.py`

1. 失败测试：理由必填；`supersedes_id` 链只能指向同一单元的决定；成交作废需理由且不可二次作废；相同 `request_id` 与相同内容返回原记录，不同内容返回冲突；无信号成交允许 `decision_id` 为空；`decided_at`、`recorded_at` 由服务端生成。
2. 提交：`feat: record decisions and trades append-only`。

### Task 10：复盘

**文件：** `investment_assistant/workbench/review.py`、`tests/test_workbench_review.py`

1. 失败测试：
   - 对照组：T+1 `open` 入场，5/10/20 日按 `adj_close` 计收益与相对 SPY 超额；卖出取反；观察不计盈亏；窗口未满标记「未成熟」。
   - 交易复盘：持仓段盈亏（含费用）、同期 SPY、最大浮盈／浮亏。
   - 周度复盘四个视角（按规则、按决定、执行偏差、无信号交易）；只输出计数、均值、中位数与分布；冻结写入时带 `calc_version`，更正以 `supersedes_id` 新增。
2. 提交：`feat: compute shadow outcomes and weekly reviews`。

### Task 11：批处理任务、服务与 API

**文件：** `investment_assistant/workbench/service.py`、`investment_assistant/tasks/workbench.py`、`investment_assistant/tasks/scheduler.py`（注册）、`investment_assistant/api/routes/workbench.py`、`investment_assistant/api/routes/__init__.py`、`tests/test_workbench_service.py`、`tests/test_workbench_api.py`

1. 失败测试：
   - 批处理：非交易日直接返回 skipped；顺序为采集→规则→合成→解读；单只股票失败不阻断其他股票，失败原因写入运行报告；股票池取配置 `watchlist`，超过 10 只时报错而不是截断。
   - API（沿用现有 BasicAuth）：
     - `GET /api/workbench/today`：待决策单元及其候选、解读、近期财报与资讯。
     - `GET /api/workbench/instruments/{ticker}`：时间线。
     - `POST /api/workbench/decisions`、`POST /api/workbench/trades`、`POST /api/workbench/trades/{id}/void`。
     - `GET /api/workbench/review/shadow`、`GET /api/workbench/review/trades`。
     - `GET/POST /api/workbench/weekly-reviews`。
     - `POST /api/workbench/run`：手动触发批处理（经 `tasks/runner.submit`）。
   - 错误：校验 400、未知 404、幂等冲突 409、数据库或 schema 未就绪 503（不返回空列表，不自动迁移）。
2. 实现：任务经 `tasks/_harness.run_task` 写运行报告，`notify=False`；在 `scheduler.REGISTRY` 注册 `workbench`。
3. 回归：`tests/test_scheduler.py tests/test_api_app.py tests/test_api_auth.py tests/test_api_contract.py`。
4. 提交：`feat: add US workbench batch job and API`。

### Task 12：前端

**文件：** `web/src/lib/router.ts`、`web/src/app.svelte`、`web/src/lib/components/SideNav.svelte`、`web/src/lib/workbench.ts`、`web/src/routes/Today.svelte`、`Instrument.svelte`、`Review.svelte`、`More.svelte` 及对应 `*.test.ts`、`web/src/app-navigation.test.ts`

1. 失败测试：
   - 导航：顶层为「今日／标的／复盘／更多」；原六个入口在「更多」下可达，旧 hash（如 `#strategy/...`）仍能打开原页面。
   - 今日：显示候选、规则输入、解读（fallback 与 error 有明确标识）、冲突与回避标签；提交决定时理由必填，携带 `request_id`，409 时保留草稿。
   - 标的：时间线按时间排序，资讯显示「发布时间未知」。
   - 复盘：成交录入与作废、对照组未成熟标识、周度复盘生成与笔记；503 显示为「数据库未就绪」而非空列表。
   - 切换页面或标的时复用 `navigation-guard` 保护未提交草稿。
2. 类型检查与构建（不覆盖 `web/dist`）：

```bash
./node_modules/.bin/svelte-check --tsconfig ./tsconfig.json
./node_modules/.bin/vite build --outDir ../.local/us-workbench/build-review
```

3. 提交：`feat: converge UI into today, instrument and review`。

### Task 13：端到端场景、文档与回归

**文件：** `tests/test_workbench_scenarios.py`、`web/src/workbench-scenarios.test.ts`、`docs/us-workbench.md`、`docs/README.md`（只加一行链接）

1. 离线端到端：一只合成股票走完 采集→B1 触发→解读→采纳→录入买入成交→S1 触发→采纳→录入卖出成交→周度复盘；另一单元否决后仍出现在对照组；修改后来的决定不改变已冻结的周度复盘。夹具中所有数字标明为合成数据。
2. 安全场景：网络被禁止、LLM 不可用、schema 缺失、重复提交、财报无受理时间、截止时间后才获取的数据。
3. 全量回归：后端 `.venv/bin/python -m pytest -q`，前端 `npx vitest run`；报告中如实列出通过／跳过／失败数，以及 SQL 测试是否实际运行。
4. 使用文档：入口、每日操作、规则说明与阈值、对照组口径、已知限制（免费资讯覆盖有限、小样本只做描述统计、不是严格 PIT）。
5. 提交：`test: verify US workbench end to end`。

## 3. 依赖关系

1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13，串行执行。其中 2、3、4（采集）互不依赖，5 只依赖 1；但为保持 main 单写入，仍按顺序执行。

## 4. 完成标准

- 13 个任务全部提交，各自测试通过。
- 全量回归无新增失败；既有失败与跳过逐项列出原因。
- SQL 测试在测试库实际运行；若没有测试库，明确记为「SQL 未验证」，整体状态为「工程完成、运行待验收」。
- 真实迁移、服务重载、真实数据采集、浏览器验收与四周使用观察不属于本计划，另行授权。
