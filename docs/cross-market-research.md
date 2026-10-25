---
title: 跨市场研究已在本地完成数据与界面验证，来源缺口和用户验收仍明确保留
tags: [cross-market-research, local-verification]
created: 2026-10-16
---

# 跨市场研究已在本地完成数据与界面验证，来源缺口和用户验收仍明确保留

截至 2026-10-16，A 股多股票关注、美股研究数据、跨市场观察卡和版本化公司指引已部署到本机 [127.0.0.1:8787](http://127.0.0.1:8787)。应用代码为本地提交 `291aaff`；Agent 的自动测试、真实来源回读和关键浏览器检查已完成，**用户手动验收待完成**。保留一项 Minor 级旧值提示误报，具体影响见下文。

## 从实际研究进入

| 目的 | 页面入口 | 本地直接链接 |
| --- | --- | --- |
| 管理同一份关注名单 | 设置 → 关注列表；全部 / A 股 / 美股 | [关注列表](http://127.0.0.1:8787/#settings/watchlist) |
| 切换 A 股并查看已存数据 | 数据 → A 股研究数据 | [688008.SH](http://127.0.0.1:8787/#data/ashares?market=CN&symbol=688008.SH) |
| 检查未来 2–4 季经营兑现 | 数据 → 美股研究数据 | [MU](http://127.0.0.1:8787/#data/us-research?market=US&symbol=MU) |
| 整理假设、证据、下一事件和失效条件 | 策略 → 研究观察卡 | [MU 观察卡](http://127.0.0.1:8787/#strategy/observation?market=US&symbol=MU) |
| 查看更新结果及覆盖限制 | 工具 → 运行记录 | 使用页面中的美股研究筛选 |

例如先选择 MU，核对实际财季、收入和现金流，再展开指标来源查看申报文件与定位信息；行业模板提供 HBM、DRAM/NAND、客户采用等待核查问题。切换单季、TTM、稀释数据及来源时，未知字段仍显示缺失原因。手动刷新会创建独立运行记录；普通页面读取只使用本地已存数据。

关注列表的新增、编辑、暂停、恢复、移除以及卡片/指引写入由用户操作触发。六位 A 股代码先解析候选身份，再由用户选定完整代码。暂停项不进入自动采集；移除关注保留已采集数据和研究卡。大于 10 只的 A 股名单分批处理，单只失败不阻断其他对象。卡片与指引草稿在切股、刷新和离开页面前有保护，保存冲突保留编辑内容；实际浏览器确认框的证据限制见后文。

## 真实覆盖及缺失字段

本轮读取 17,131 条财务事实，核验 65 个引用的原始快照和 2,747 项独立算术检查。快照位于主运行目录 `.local/us-research/raw/`，每个引用的文件均核对 SHA256；派生指标使用真实数据库 ID，SEC 定位符回到对应原始值，不用临时内容摘要充当持久化 ID。

| 股票 | 返回财季行 | 最新实际财季 | 股票日线数量 | 已解析原索引文档 |
| --- | --- | --- | --- | --- |
| CRDO | 12 | 2026-05-03—2026-08-01 | 501 | 2 |
| GOOG | 12 | 2026-04-01—2026-06-30 | 501 | 3 |
| MSFT | 12 | 2026-04-01—2026-06-30 | 501 | 3 |
| MU | 12 | 2026-05-29—2026-09-03 | 501 | 3 |
| NVDA | 12 | 2026-04-27—2026-07-26 | 501 | 4 |
| RKLB | 12 | 2026-04-01—2026-06-30 | 501 | 6 |
| SNDK | 12 | 2026-04-04—2026-07-03 | 420 | 4 |
| TSLA | 12，含缺口 | 2026-04-01—2026-06-30 | 501 | 4 |

12 是展示目标和实际行数，不代表所有指标齐备。其余 7 家的返回期间边界连续；TSLA 沿用既有“不收 10-K”的规则，有 4 处第四季缺口，最早一行始于 2022-07-01，不能把这 12 行称为连续 12 季或跨缺口求 TTM。SNDK 日线始于 2025-02-13；其他股票始于 2024-10-16，均截止 2026-10-15，不能虚构 SNDK 上市前行情或忽略其拆分前后主体差异。

首次整批运行中，8 家财务和原文处理均为 `ready`；行情均为 `partial`，没有 `failed` 或 `empty` 数据集。行情部分覆盖来自已公开显示的当前复权历史及市值/股权类别可比性限制。外层任务执行器为 `done`、内部任务为 `error`，因为内部汇总把 `partial` 纳入错误列表；这不表示 8 家全部采集失败，也不应改写成全部完整成功。页面手动刷新 MU 后又做了最终快照核验。

### NVDA 的可复算例子

以下均为 **百万美元**，实际财季为 2026-04-27—2026-07-26，保留申报版本和输入 ID：

| 指标 | 原始值与独立计算 | 处理结果 |
| --- | --- | --- |
| 收入 | 直接单季 96,221（ID 19708）；累计 177,837 − 前期累计 81,615 = 96,222 | 单季保留直接披露值；两种版本不一致，收入 TTM 为 null，并保留冲突原因与全部来源 |
| 经营现金流 | 74,421 − 50,344 = 24,077（ID 19690、19672） | 可比累计差分，标为计算值 |
| 广义资产投入 | 4,434 − 1,757 = 2,677（ID 19688、19670） | `PaymentsToAcquireProductiveAssets` 单列，不冒充现金 PPE |
| 现金 PPE / 标准 FCF | 最新可用标准 PPE 输入缺失 | PPE 和 FCF 为 null；不以广义资产投入替代 |
| 归属普通股股东利润 | 最新标准输入缺失 | 保持 null；不以归母或合并利润替代 |

来源包括 [NVDA 2026-08-26 的申报索引](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/0001045810-26-000075-index.html)和 [2026-05-20 的申报索引](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000052/0001045810-26-000052-index.html)。Company Facts 原始快照的 SHA256、准确 JSON 定位符、源值和数据库输入见本机 `nvda-hand-evidence.json` 与 `nvda-hand-arithmetic.json`。

MU、CRDO、NVDA 的最新普通股归属利润也不能靠早年标签向前填充。Yahoo 市值的日期、币种和全部普通股股权类别尚未核实，当前 PE / PS / FCF 收益率均保持 null，不用股价乘任意股数制造可比市值。

## 来源与计算的适用范围

SEC Company Facts 提供标准分类标签、适用于整个申报实体的事实，不是完整分部、产品或经营指标数据库。实际财季必须使用起止日对齐，不能直接把申报 `fy/fp` 或日历季度当作公司财季；参见 [SEC 官方 API 说明](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)。

HBM、AEC、云订单、RPO、客户集中度、non-GAAP 对账等公司专属数据需要原始披露或人工附证。当前 8 家模板提供问题和待核查项目，没有将缺失经营数据变成自动取得的事实。non-GAAP 也不等于 A 股扣非利润；公司指引不等于市场一致预期。真实回读中，美股结构化指引和研究卡各为 **0 条**，本轮没有替用户保存模拟记录。已有原文解析保留事实、原文摘录和覆盖说明，不代表已自动生成可比指引。

金额先取直接单季，或仅在同财年、同币种、同口径且无未解决修订时由累计值差分；期末余额、EPS、加权股数不这样相减。TTM 需要连续四季；利润率按汇总金额相除，标准 FCF 用 CFO 减现金 PPE。冲突候选保存在同一真实父记录中，各有完整定位符；不能挑一个候选值消除歧义。

原始价和调整后价格分开存储；收益和相对 SPY/QQQ 表现使用相同调整口径与实际共同日期。当前供应商复权回填不等于当时的拆股/分红版本，也不宣称严格总回报。历史 `as_of` 同时检查披露时间和本机首次观察时间，`strict=false`；回填旧财报不等于拥有启用前的严格历史快照。

## 本机保留检查与运行方式

受保护的部署只同步隔离基线 `00a8b2e` 之后的已审查文件，逐一检查原文件摘要并留恢复备份；仅在事务中执行迁移 014。已有 SEC 原始文件映射保持只读，运行快照写到主目录，不留在隔离工作树。原有 `local.investment-assistant` LaunchAgent 的监听进程及工作目录核实后重载，记录 PID 为 32692；该 PID 仅代表本次验证时刻。

部署前后 6 项保留检查全部通过：9 条关注的身份/状态/论点/标签，原 29 份 SEC 索引，688008.SH 的版本 2 卡片正文及历史，4 项调度身份/时间/时区/启用状态，通知配置及环境文件均保持。没有新启用调度、没有外部通知、交易或云端发布。上述摘要只覆盖这 6 类检查对象，不是全部 A 股数据逐行未变的证明。688008 当前读取 8 期财务、163 条公告、3 条披露预约及卡片 v2。两次只读 GET 已确认日线 261/262 的差异来自查询窗口：当前默认 2025-09-11—2026-10-16 显示 261 根；原验证脚本的固定窗口 2025-09-10—2026-10-15 返回 262 根，仅前者排除了 2025-09-10，数据库状态的 `stored_rows` 仍为 262。最新日线为 2026-10-15，`stale` 表示尚未覆盖新近已收盘的 2026-10-16；本次核对未触发采集或写入。证据为 `ashare-window-readback.json`。这解释了显示数量差异，仍不构成全部 A 股原数据逐行摘要保留证明。

主目录为 `/Users/chenjianrui/workspaces/investment-assistant`。现有服务运行时直接访问上面的本地地址，不再启动第二个调度器。只有确认该服务未运行时，才使用原入口：

```bash
cd /Users/chenjianrui/workspaces/investment-assistant
./start.command
```

只读复核命令如下；脚本内部读取既有 dotenv，HTTP 只允许回环地址和 GET，数据库强制只读。唯一可选写入是 `--output` 指定的核验报告，不执行采集或迁移：

```bash
cd /Users/chenjianrui/workspaces/investment-assistant
.venv/bin/python scripts/verify_cross_market.py \
  --api-url http://127.0.0.1:8787 \
  --raw-root /Users/chenjianrui/workspaces/investment-assistant/.local/us-research/raw \
  --output /Users/chenjianrui/workspaces/investment-assistant/.local/cross-market/verification.json
```

成果已按用户要求整理为 `main` 上的提交 `a0ab8ae`，包含本次功能所依赖的此前未提交 A 股基础模块，共 87 个变更文件。提交的完整源码树与已审查版本 `ec29eed` 一致，主目录是后续开发和运行入口。

本次 `codex/cross-market-research` 分支已删除，附加工作树已通过应用归档并移除，支持恢复；其他工作树未改动。完整分支历史另存于 `.local/cross-market/main-integration/cross-market-research.bundle`，已通过 Git 校验。清理前后 200 份既有本地证据文件的摘要一致，原始来源、测试日志、截图及审查材料保留。没有推送远端或云端发布，用户功能验收仍待完成。

提交前在 `main` 主目录重新运行后端与前端完整测试及构建：后端 526 通过、52 条按条件跳过，前端 129 通过，构建 0 错误。此次未重复连接数据库执行 TEMP 测试或采集来源，原 92 项 TEMP 测试及真实来源验证记录保留。最新日志和清理核对记录位于 `.local/cross-market/main-integration/`。

## 测试、浏览器与待验收范围

下表证据路径均相对于主运行目录；测试及构建日志已保存在 `.local/cross-market/test-logs/`，不依赖临时目录长期留存。

| 验证类别 | 最终结果 | 证据 |
| --- | --- | --- |
| 完整后端，无数据库 URL | 526 通过、52 跳过、1 个既存警告 | `.local/cross-market/test-logs/final-fix-backend-full.txt` |
| 单独审查的 7 个 TEMP 数据库测试文件 | 92 通过、1 个既存警告 | `.local/cross-market/test-logs/cross-market-final-temp-tests.txt` |
| 完整前端组件/路由测试 | 22 文件、129 项通过 | `.local/cross-market/test-logs/final-fix-ui-full.txt` |
| 隔离工作树构建 | svelte-check 0 错误，Vite 成功 | `.local/cross-market/test-logs/final-fix-build.txt` |
| 主运行目录构建 | 0 错误，Vite 成功 | `.local/cross-market/test-logs/cross-market-primary-build.txt` |
| 真实来源与持久化回读 | 65 快照、17,131 财务事实、2,747 独立算术核验通过 | `.local/cross-market/verification.json` |

后端警告为既有 Starlette/anyio 弃用提示；前端保留既有 FetchDateModal 初始值提示和大包体提示。普通完整测试必须移除所有数据库环境变量：

```bash
env -u INVESTMENT_ASSISTANT_DATABASE_URL \
  -u INVESTMENT_ASSISTANT_TEST_DATABASE_URL -u TEST_DATABASE_URL \
  .venv/bin/python -m pytest -q
NODE_OPTIONS=--no-experimental-webstorage npm --prefix web test
NODE_OPTIONS=--no-experimental-webstorage npm --prefix web run build
```

TEMP 集成测试是单独、逐文件审查后的显式运行，使用连接本地临时表和 `search_path=pg_temp`，凭据只在进程内读取。**不得把真实生产连接放入 `TEST_DATABASE_URL` 后运行整个套件**：旧 `test_migration_fk_integration.py` 会执行迁移并写真实业务表；本轮该测试仍跳过，除非另建可丢弃数据库。回归中的另一只 A 股、增删关注、卡片冲突及指引写入均在隔离数据/组件夹具中验证，不能宣称用户真实记录已完成这些写操作。

本次单独审查的 TEMP 测试明确限定为以下 7 个文件，不能替换成整个 `tests/`；测试进程内部从本机 dotenv 读取连接，仅传入 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL`，不打印连接内容：

```text
tests/test_ashare_postgres.py
tests/test_watchlist_postgres.py
tests/test_us_research_postgres.py
tests/test_us_research_service.py
tests/test_us_research_api.py
tests/test_cross_market_cards.py
tests/test_us_guidance.py
```

浏览器使用 1440×1000 桌面和 390×844 窄屏，检查了 A 股筛选、600519.SH 身份候选后取消、另一 A 股直接链接、688008 切回；8 只美股选择、单季/TTM/稀释切换、来源展开、MU 手动刷新及 partial 提示、跨市场卡入口、指引表单、运行记录和原信号/评分页面。

600519 只解析并缓存了一份真实公开公司资料，未加入关注，也未写入其行情、财务或卡片。浏览器原生确认框的工具交互超时，两处草稿仍保留，随后手动清空而未保存；准确的确认/取消/卸载保护仅由渲染组件测试验证，不能写成浏览器原生弹框已通过。390px 检查使用收起的侧栏；财务表和关注表需要内部横向滚动，关注表仍偏密。截图在主目录 `.local/cross-market/`，由 `browser-validation.json` 列明。

## 已知审查问题与实现取舍

最终整变更审查的 2 项 Important 与 3 项 Minor 中，前 4 项已关闭：统一股票身份验证、指引草稿保护、公司身份元数据保留、显式配置传递。第 5 项“旧值提示”仅部分关闭：次日报价或滚动窗口外旧 bar 仍可能让最新成功数据显示保留旧值的保守警告。所选最新数值、日期和来源未因此改变；用户可能需要额外查看日期。按本轮单次最终修复波次的裁定暂存此 Minor，不能声称全部发现已关闭。

| 已采用的裁定 | 作用与判断错误时的代价 |
| --- | --- |
| 以当前 A 股源码为隔离基线，逐摘要同步已审查差异 | 保留上一轮改动；判断错误会覆盖并发修改或混入无关代码，因此保留恢复备份 |
| 文件系统只对指定工作树操作申请狭窄权限 | 不改全局权限；路径判断错误会导致写入被拒或越出任务范围 |
| 初次交付阶段连续执行，保留本地分支和工作树，不合并/推送 | 这是当时的实施裁定；随后用户明确要求提交 main 并清理，已按新授权完成。误解授权会扩大操作范围，因此操作始终限定本机 |
| 提交显式路径，排除依赖链接、配置、运行数据和原文 | 避免泄露或把机器状态当源码；漏选会导致交付文件不全，故有最终差异核对 |
| 真实采集在主运行目录完成，原始库只读 | 页面与快照指向同一运行实例；根目录错置会使可追溯来源在部署后失效 |
| 研究适配器复用重试策略，并局部清洗来源错误 | 防止原通用日志输出代理凭据；代价是详细网络诊断需安全地单独核查 |
| 财务经济内容与整份响应摘要分别管理，保持旧定位符/摘要成对 | 无关来源新增不制造全库修订；错误去重可能漏掉变值，A→B→A 有独立回归 |
| 同自然键冲突保留完整候选，统一父数据库 ID | 不挑值、不伪造子 ID；代价是冲突指标暂时不可算，来源修正后再追加版本 |
| 暂存残余 Minor 旧值提示误报 | 保留准确值和来源并公开提示限制；错误时的代价是用户多一次日期核查 |

实现、来源和浏览器验证已有各自证据，仍需用户自行检查页面是否适合日常研究并决定是否验收。后续新增数据源、真实卡片或指引录入、调整采集规则和云端发布均不由本报告代替授权。

## 来源与本机证据

- [SEC 官方 EDGAR API 说明](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)：标准实体事实及实际财季对齐限制。
- A 股前一阶段验证（已于 v2.0.0 删除）；[本轮设计](archive/roadmap-v1/specs/2026-10-16-cross-market-medium-term-research-design.md)；[本轮计划](archive/roadmap-v1/plans/2026-10-16-cross-market-medium-term-research.md)。当前交付状态以本报告为准，前一阶段的“只采集一只”等描述保留其历史语境。
- 主目录 `/Users/chenjianrui/workspaces/investment-assistant/.local/cross-market/` 下的 `verification.json`、`live-coverage.json`、`nvda-hand-evidence.json`、`nvda-hand-arithmetic.json`、`live-run-result.json`、`preservation-before.json`、`preservation-after.json`、`browser-validation.json`、`ashare-window-readback.json`；均为本机忽略产物，不进 Git 或云端。
- 交付时归档的过程与审查证据：`/Users/chenjianrui/workspaces/investment-assistant/.local/cross-market/sdd-audit/2026-10-16-cross-market-medium-term-research/`，其中 `task-6-report.md` 保留阶段测试和最终来源记录，`progress.md` 保留当时的裁定。此次提交与清理的后续记录保存在 `.local/cross-market/main-integration/`，未改写原始审查记录；分支历史及工作树归档保留恢复能力。
