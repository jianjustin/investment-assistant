# v2.0.0 发布整理 — 删除 A 股、精简部署、重构文档

> 2026-10-25，基线 `main@6b59879`。roadmap v2（P1–P4）已全部 `engineering_done`，本文定义发布 `v2.0.0` 之前的收口工作。
> 本文是设计，不是实施授权：真实库迁移、推送、打 tag、创建 GitHub Release 都在执行时单独确认。

---

## 1. 目标

1. 项目只做美股：删除 A 股相关的代码、数据、页面和文档。
2. 只保留实际在用的本机部署方式。
3. 重构 `docs/`：roadmap、spec、plan、feature 各管一件事，让人能从文档读懂系统架构和组成部分。
4. 发布 `v2.0.0`。

成功标准：

- 仓库里（`docs/archive/`、`docs/specs/`、`docs/plans/` 里冻结的历史文档除外）不再有 A 股代码路径、页面入口或使用说明；离线测试、一次性库 SQL 测试、前端测试、前端构建全部通过。
- 真实库执行迁移 021 后，工作台手动批处理成功，「今日」「复盘」「设置 → 关注列表」页面正常。
- 新读者只看 `docs/README.md` → `architecture.md` → `features/`，就能说出系统由哪些部分组成、每天的数据流怎么走。

---

## 2. 决策记录（2026-10-25 讨论确认）

| # | 问题 | 决定 |
| --- | --- | --- |
| 1 | 清理范围 | 只删 A 股；v1 遗留功能原样保留，由用户以后决定合并或删除，记入 `roadmap/backlog.md` |
| 2 | 研究观察卡 | 属于 v1 遗留，保留美股部分；只删 A 股分支 |
| 3 | 真实库的 A 股数据 | 新增迁移 `021` 删除；执行前 `pg_dump` 备份 |
| 4 | 文档结构 | 按 §6.1 的结构；feature 按业务能力拆分；spec 和 plan 移到 `docs/specs`、`docs/plans` |
| 5 | 部署方式 | 只保留本机 LaunchAgent；删除 NUC 和 Sealos 的脚本与文档 |
| 6 | 版本号 | `v2.0.0`，与 roadmap v2 对应；以后 roadmap 版本即大版本号 |
| 7 | architecture 详细程度 | 五节：运行形态、代码分层、主线数据流、表分组、定时任务与前端；写到模块级，不写到函数级 |

---

## 3. 范围

**做**：§4 删除 A 股、§5 精简部署、§6 重构文档、§7 发布。

**不做**：

- 不改 v1 遗留功能的行为（Hermes、策略评分、事件研究、美股财季数据、研究观察卡），只删其中的 A 股分支。
- 不改工作台的规则、计划和复盘逻辑。
- 不删 `job_reports` 里 `task = 'ashares'` 的历史行：运行报告只追加，留作历史。
- 不改已执行过的迁移文件（`013` 原样保留：新装的库仍然靠它建研究观察卡表）。
- 不清理本机未入库的 `.local/ashare/` 等运行目录（不在 Git 里，用户自行处理）。

---

## 4. 删除 A 股

### 4.1 现状（2026-10-25 只读核对真实库）

| 对象 | 行数 |
| --- | --- |
| `cn_observations` | 1735 |
| `cn_collection_state` | 11 |
| `research_observation_cards` 里 `CN:` 开头的行 | 1（版本表 2 行） |
| `research_observation_cards` 里的美股行 | 0 |
| `watchlist_items` 里的 CN 行 | 1（`688008.SH`，active） |
| `scheduled_jobs` 里的 `ashares` 行 | 1 |
| `pool_tiers` 里的 CN 行 | 0 |

### 4.2 整体删除

| 位置 | 内容 |
| --- | --- |
| 后端 | `investment_assistant/ashare/`（含 `vendor/` 及其 LICENSE、NOTICE、UPSTREAM.md）、`api/routes/ashares.py`、`tasks/ashares.py` |
| 脚本 | `scripts/verify_ashares.py` |
| 测试 | `tests/test_ashare_*.py`；`tests/test_cross_market_cards.py` 中只测 A 股的用例删除，美股卡片的用例改写后保留 |
| 前端 | `web/src/routes/AShares.svelte`、`AShares.test.ts` |
| 文档 | `docs/ashare-research.md`、`docs/cross-market-research.md`（美股财季部分压缩进 `features/legacy/us-research.md`） |
| 空目录 | `investment_assistant/research_agent/`、`tests/research_agent/`（只剩 `__pycache__`，不在 Git 里） |

### 4.3 改动共享代码

| 耦合点 | 处理 |
| --- | --- |
| `services/watchlist.py`：`validated_symbol`、`market_of`、`_enrich`、`resolve_candidates`、`add_watchlist_item`、`_validate_pool_write` | 只认美股代码：`validated_symbol` 直接用 `us_research.domain.stock_id` 校验，它已经会拒绝 `688008.SH`、`688008`（抛出 `Invalid US stock ticker`），接口返回 400，不需要专门写 A 股判断。去掉 `market` 查询参数和 `CN` 分支；行里的 `market` 字段固定为 `'US'`，保持响应结构不变 |
| `research/cards.py` | `get_card`、`save_card` 从 `ashare/repository.py` 搬到 `research/`（新文件 `research/card_repository.py`，SQL 原样迁移）；`connection` 改用 `db.connect`；删除 `cn_observations` 分支和 CNY 默认值，保留 `currency` 字段 |
| `us_research/service.py` | 改为从 `research/card_repository.py` 导入 `get_card` |
| `workbench/pool.py`、`services/hermes.py`、`services/tickers.py`、`tasks/filings.py` | 删除 `is_cn_symbol`、`us_only` 过滤：观察名单只会有美股，过滤已无必要。`us_only` 只有 `tasks/filings.py` 一个调用方，它过滤的是配置文件里的 `watchlist`；本机和示例配置里都只有美股，直接去掉即可 |
| `tasks/scheduler.py` | `REGISTRY` 删除 `ashares` |
| `api/routes/__init__.py` | 删除 `ashares` 路由注册 |
| 前端 `SideNav`、`Data`、`Strategy`、`Tools`、`Watchlist`、`SecurityPicker`、`research-navigation`、`ResearchCard`、`GuidanceEditor`、`api.ts` | 删除「A 股研究数据」入口、A 股/美股切换、All/CN/US 标签页、`market` 参数和 `CN` 类型、CNY 默认值，以及 A 股相关的提示文案 |
| 其余命中 `CN`/`SH` 的测试 | 逐个核对：A 股专用的用例删除；只是把 CN 当作「被过滤掉的输入」的用例，改成断言「接口返回 400」，或者直接删除 |

完成判据：下面这条命令输出为空。区分大小写，避免把 `.sh` 文件名当成命中。迁移文件不在检查范围内：`013` 原样保留，`021` 本身就要提到这些表。基线 2026-10-25 时，排除 `ashare/` 包和 A 股专属文件后还有 139 处命中。

```bash
grep -rnE '[Aa][Ss]hare|cnequity|is_cn_symbol|cn_observations|A ?股|\.(SH|SZ|BJ)\b' investment_assistant web/src tests scripts README.md
```

例外：

- `investment_assistant/us_research/domain.py` 中拒绝交易所后缀的那一行，它是美股代码校验的一部分，不是 A 股功能。
- `tests/` 中把 `688008.SH`、`TSLA.SH` 这类代码当作「无效美股代码」输入的用例，包括美股研究和观察名单原有的校验测试。但 `tests/` 里不能出现 `[Aa][Ss]hare|cnequity|is_cn_symbol|cn_observations|CN:stock|'CN'`。

### 4.4 迁移 `021_drop_ashare.sql`

```sql
-- A-share removed from the project (v2.0.0). 013 stays so fresh installs still get research cards.
DELETE FROM research_observation_card_versions WHERE security_id LIKE 'CN:%';
DELETE FROM research_observation_cards WHERE security_id LIKE 'CN:%';
DELETE FROM watchlist_items WHERE ticker ~ '^[0-9]{6}\.(SH|SZ|BJ)$';
DELETE FROM scheduled_jobs WHERE name = 'ashares';
DROP TABLE IF EXISTS cn_collection_state;
DROP TABLE IF EXISTS cn_observations;
```

- 这几张表没有外键指向它们，删除顺序无约束。
- 可重复执行：语句都是 `DELETE` 加 `DROP ... IF EXISTS`。
- 在新装的库上，`013` 先建表，`021` 再删除，最终 schema 与真实库一致。
- 测试：在一次性 Postgres 上执行 `001`–`021`，断言 `cn_*` 表不存在、研究卡表还在、CN 观察名单行和 `ashares` 任务行已删、美股行不受影响。另外针对「先插入一批 CN 行和美股行，再执行 021」写一个用例。

**真实库执行**（单独授权）：先 `pg_dump` 备份到 `.local/`，记录 sha256；用 `psql --single-transaction -f migrations/021_drop_ashare.sql` 执行，不走 `migrate` 入口（沿用 P4 的做法）；执行后重新统计 §4.1 的各项行数并核对。

---

## 5. 精简部署

| 删除 | 保留 |
| --- | --- |
| `deploy/`（`push-to-nuc.sh`、`install.sh`、`systemd/`、`docker-compose.postgres.yml`）、`Dockerfile`、`.dockerignore`、`scripts/build-push.sh`、`docs/deployment-sealos.md` | `start.command`、`scripts/start_local.py`、本机 LaunchAgent（`local.investment-assistant`，不在仓库里） |

- `scripts/README.md` 改写：现在列的 `test_discord.py` 等脚本早已不存在，改成实际保留的脚本（`start_local.py`、`review_phase0_archives.py`、`verify_cross_market.py`）。
- 运维文档只写本机方式：LaunchAgent 的启动、重启、日志位置，迁移和备份流程。
- 删除前确认 `runtime_paths.py` 等代码不依赖 `deploy/` 下的文件；`/srv/...`、`/opt/...` 这些默认路径如果只为 NUC 存在，在运维文档里注明本机实际使用的路径，代码不改。

---

## 6. 重构文档

### 6.1 目标结构

```
README.md                    # 项目是什么、怎么跑；链接到 docs
CHANGELOG.md                 # 按版本记录；v2.0.0 是第一条
CLAUDE.md                    # 新增一条约定：spec 放 docs/specs，plan 放 docs/plans
docs/
├── README.md                # 索引 + 四类文档的职责与维护方式
├── architecture.md          # 系统组成（§6.3）
├── getting-started.md       # 安装、配置、启动、测试
├── features/
│   ├── daily-plan.md        # 规则 v1 → 决策单元 → 交易计划 → 06:30 推送；「今日」「标的」页
│   ├── agent-track.md       # Agent 轨道：工具层、提议与反方、引用校验、预算、解读
│   ├── review.md            # 影子跟踪、三方对比、纪律、周/月复盘与推送；资金与月度收益
│   ├── pool-and-context.md  # 观察池分层、行业强弱、广度与区制、FRED、上线前检查
│   ├── sec-filings.md       # SEC 下载器与监控（合并原两篇）
│   └── legacy/
│       ├── README.md        # 遗留功能清单与状态：保留但不再演进，待合并或删除
│       ├── hermes.md        # 宏观分析、决策证据
│       ├── strategy-and-signals.md  # SPY/VIX 信号、趋势、策略评分、技术面
│       ├── event-study.md
│       └── us-research.md   # 美股财季数据、指引、研究观察卡
├── operations/
│   ├── local-service.md     # LaunchAgent、start.command、日志、重启
│   ├── scheduling-and-notifications.md
│   └── migrations-and-backup.md     # 迁移清单 001–021、pg_dump、psql --single-transaction、一次性库测试
├── roadmap/
│   ├── README.md            # 版本表、沿用原则、DoD、状态用语
│   ├── v2-decision-loop.md  # 标注「已完成（v2.0.0）」，正文不改
│   ├── v2-progress.md       # 冻结，作为 v2 的收尾记录；末尾追加发布一行
│   └── backlog.md           # 下一版候选：v1 遗留合并或删除、v2 暂缓项、未完成的使用验收
├── specs/                   # 只增不改
├── plans/                   # 只增不改
└── archive/
    └── roadmap-v1/
        ├── ...（原样）
        ├── specs/           # 06-27 至 10-16 的 v1 时期 spec
        └── plans/           # 同期 plan
```

### 6.2 逐文件处置

| 现有文档 | 去向 |
| --- | --- |
| `docs/architecture.md` | 重写（§6.3） |
| `docs/getting-started.md` | 更新：Python/Node 版本、LaunchAgent、`ZHIPU_API_KEY`/`FRED_API_KEY`、迁移到 021、前端测试需要 `NODE_OPTIONS=--no-experimental-webstorage` |
| `docs/us-workbench.md` | 拆到 `features/daily-plan.md`、`agent-track.md`、`review.md`、`pool-and-context.md`。按「现在系统怎么工作」来写，P1–P4 的上线前提合并成一份迁移清单，放到 `operations/migrations-and-backup.md` |
| `docs/sec-downloader.md` + `docs/sec-monitor-migration.md` | 合并为 `features/sec-filings.md` |
| `docs/scheduling-and-notifications.md` | 移到 `operations/`，任务列表更新为当前的注册表，删掉「已废弃的 systemd」一节 |
| `docs/hermes-usage.md`、`docs/features/trade.md` | 合并为 `features/legacy/hermes.md` |
| `docs/features/data.md`、`strategy.md`、`tools.md`、`settings.md` | 拆分重组：信号、趋势、评分进 `legacy/strategy-and-signals.md`；任务中心、运行记录、关注列表、推送、认证这些主线也在用的底座能力，进 `operations/` 或 `getting-started.md` |
| `docs/research-event-study.md` | 移到 `features/legacy/event-study.md` |
| `docs/cross-market-research.md`、`docs/ashare-research.md` | 删除（美股部分压缩进 `legacy/us-research.md`） |
| `docs/deployment-sealos.md` | 删除 |
| `docs/superpowers/specs`、`plans` 中 2026-10-23 及以后的 | 移到 `docs/specs`、`docs/plans` |
| `docs/superpowers/specs`、`plans` 中 2026-10-16 及以前的 | 移到 `docs/archive/roadmap-v1/specs`、`plans` |
| `docs/archive/roadmap-v1/` 其余内容 | 原样保留 |

移动用 `git mv`，保留文件历史。移动后修正所有相对链接：冻结文档的正文不改，只修链接。完成判据：用脚本检查 `docs/`、`README.md` 中所有相对链接都指向存在的文件。

### 6.3 `architecture.md` 大纲

1. **运行形态**：单进程（FastAPI + 静态前端 + 调度线程），绑定 `127.0.0.1:8787`，由 LaunchAgent 启动；PostgreSQL 是唯一的状态存储；外部依赖有 yfinance、SEC EDGAR、FRED、智谱、Discord，并说明各自缺失时怎么降级。
2. **代码分层**：`api/routes` → `services/`、`workbench/service.py` → `repository`/`db.py`；`tasks/` 是任务入口；纯函数模块清单。逐个模块写一行「做什么 / 依赖什么」，主线和 v1 遗留分开列。
3. **主线数据流**：配 mermaid 图。06:30 `workbench` 批处理的六步（采集、市场环境、规则、计划、Agent、推送），你的操作（采纳/否决、录入成交），08:00 `workbench_review`（影子跟踪、三方对比、纪律、周/月复盘推送）。
4. **数据表分组**：共享底座、工作台（采集 / 信号 / 计划与执行 / Agent / 复盘）、v1 遗留，并注明 LangGraph 检查点表由 `python -m investment_assistant.workbench.agent` 创建，不在迁移里。
5. **定时任务与前端**：任务注册表与默认时间；前端主线入口与「更多」里的遗留入口。

### 6.4 维护规则（写进 `docs/README.md`）

| 类别 | 回答的问题 | 什么时候改 |
| --- | --- | --- |
| roadmap | 往哪走、为什么、到哪一步了 | 方向变化时改；进度文档按周更新 |
| spec | 某阶段为什么这样设计 | 写成后冻结，只增不改 |
| plan | 某阶段怎么实施 | 写成后冻结，只增不改 |
| feature / architecture / operations | 系统现在能做什么、怎么用、怎么验证 | 随代码同一个提交更新 |

---

## 7. 发布 `v2.0.0`

1. `CHANGELOG.md` 写 v2.0.0 条目：P1–P4 能力摘要（各附 spec 链接）；不兼容变更（删除 A 股接口 `/api/ashares/*`、观察名单拒绝 A 股代码、删除 `market` 参数、迁移 021、删除 NUC/Sealos 部署）；已知限制（`user_acceptance_pending` 的各项，Phase 0 Gate HOLD）。
2. `web/package.json` 的 `version` 改为 `2.0.0`（同步 `package-lock.json`）。
3. 根目录 `README.md` 重写：一段话说清项目是什么，加上快速开始、文档入口、当前版本。删掉 Legacy earnings-agent 一节和过时的状态段落。
4. 全部验证（§8）通过、真实库验收完成后，打带注释的 tag `v2.0.0`，推送 `main` 和 tag，用 `gh release create v2.0.0` 创建 GitHub Release，正文用 changelog 条目。推送和创建 Release 之前单独确认。

---

## 8. 验证

| 层 | 方式 |
| --- | --- |
| 后端离线 | `env -u INVESTMENT_ASSISTANT_DATABASE_URL -u INVESTMENT_ASSISTANT_TEST_DATABASE_URL -u TEST_DATABASE_URL .venv/bin/python -m pytest tests/ -q` 全部通过 |
| SQL | 在一次性 Postgres（端口 55433）上跑数据库测试，包括 §4.4 的迁移 021 测试 |
| 前端 | `NODE_OPTIONS=--no-experimental-webstorage npm test` 和 `npm run build` 都通过 |
| 残留 | §4.3 的 grep 没有命中；§6.2 的链接检查没有失效链接 |
| 真实库与服务（单独授权） | `pg_dump` 备份 → 执行 021 → 核对行数 → 构建前端 → `launchctl kickstart -k` 重启服务 → 手动跑一次 `workbench` 批处理（不推送） → 检查「今日」「复盘」「设置 → 关注列表」「策略 → 研究观察卡」页面，以及 `/api/watchlist` 对 `688008.SH` 返回 400 |

---

## 9. 风险

| 风险 | 应对 |
| --- | --- |
| 共享代码里还藏着对 `ashare` 的隐式依赖（延迟导入） | 删除包以后，跑全量测试，再加一次 `python -c "import investment_assistant.api.app"`，以及 §4.3 的 grep |
| 删除 `market` 参数导致前端调用报错 | 前端测试覆盖观察名单、研究卡、策略页；页面验收时实际点一遍 |
| 迁移 021 误删美股数据 | 用正则精确匹配 A 股代码格式，研究卡只按 `CN:` 前缀删除；有 `pg_dump` 备份；执行前后核对行数 |
| 移动文档导致链接失效 | 用脚本检查链接，作为完成判据 |
| 已在运行的服务仍用旧代码调度 `ashares` | 迁移删除任务行，同时重启服务；两步在同一次验收里完成 |
