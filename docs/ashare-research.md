# A 股研究已接入本地工作台，历史可用性与产品传导仍需逐项核实

更新日期：2026-10-16。目标：行业和公司改善驱动、持有数周至数月的研究。首个真实样本为澜起科技 `688008.SH`，只采集一只股票和两个基准，没有初始化全市场多年数据。

## 现有代码与复用位置

以下结论来自实际代码、数据库与本地页面，未把 README 列项当作已验证能力。

| 现有能力 | 可复用部分 | A 股缺口 | 本次修改位置 |
| --- | --- | --- | --- |
| `watchlist_items` 与关注列表 API | 原有关注、标签、研究说明 | ticker 缺交易所和资产类别 | `services/watchlist.py`；`ashare/domain.py` 规范证券标识；主数据存 `cn_observations` |
| yfinance 行情与美股趋势计算 | 原有 API、图表组件 | 无 A 股持久化行情、复权和交易日历 | `ashare/sources.py`、`domain.py`、`service.py`；不套 SPY/VIX 规则 |
| PostgreSQL 连接池、编号 SQL 迁移 | 原连接池与迁移方式 | 缺 A 股财务、公告及采集版本 | `013_ashare_research.sql`、`ashare/repository.py` |
| `tasks/runner.py`、`_harness.py`、`scheduled_jobs`、`job_reports` | 异步手动执行、运行记录、失败状态 | A 股休市日、上海时区、分数据集续跑 | `tasks/ashares.py`、scheduler 注册；新任务默认关闭 |
| Svelte 数据页、策略研究页、EChart | 原侧栏、路由、主题、API 工具与组件 | 缺个股研究视图和结构化观察卡 | `AShares.svelte`、`ResearchCard.svelte`，复用 Data/Strategy 入口 |
| 既有事件研究记录 | 保留事件研究页面和表 | 无“改善—证据—价格—失效条件”结构 | 仅新增观察卡及版本表；不改写事件研究结果 |
| SEC 索引、本地原文、`filings/analysis.py` | 引用 NVDA/MU/CRDO 原文及已解析期间/单位 | 跨市场产品传导条件 | `ashare/cards.py`；引用原 filing ID，不重复下载 |
| 通知设置及 SEC monitor | 保留原邮件/Discord 配置及美股调度 | A 股首批不应发送通知 | A 股任务始终 `notify=False`；没有测试发送 |

## CNEquity 选型与核实

所选版本：**0.16.0 / `c118038ea82b5bb78783c0c17a1d9251b36de71d`**。已核对源码、`pyproject.toml`、Apache-2.0 `LICENSE` / `NOTICE`、来源策略登记以及真实接口响应。

| 方式 | 维护与研究口径影响 | 结论 |
| --- | --- | --- |
| 直接依赖完整 CNEquity | 引入独立数据湖、配置、较多依赖与更新生命周期；默认财务回填范围远大于本轮 | 不采用 |
| 包装完整 CNEquity 为适配层 | 可隔离调用，但仍维护两套存储和版本语义，MCP 默认 PIT 口径不能直接信任 | 本轮不采用 |
| 局部模块复用 + 工作台薄适配层 | 仅保留少量可审计代码，沿用 PostgreSQL/API/任务/UI；维护上游字段契约和许可证 | **采用** |

直接复用 `numeric.py`、`holidays_cn.py`；其余主要是参考字段映射和因子解析方式。出处、修改声明及许可见 [UPSTREAM.md](../investment_assistant/ashare/vendor/UPSTREAM.md)。未新增 Python/npm 依赖，也未安装 CNEquity 数据湖或 MCP。

行情收益、最大回撤、复权应用、同期相对收益、季度差分、观察卡与跨市场关联均由工作台实现，不列为 CNEquity 原生功能。

### 数据源与使用限制

| 数据 | 本轮实际来源 | 能力边界 |
| --- | --- | --- |
| 名称、板块、上市日期 | 东方财富 `RPT_F10_ORG_BASICINFO` | 当前快照；`LISTING_STATE=0` 枚举未独立核实，上市状态显示 unknown |
| 原始日线、两个指数 | 东方财富 `push2his`，`fqt=0` | 个股 `1.688008`；沪深300 `1.000300`；半导体指数 **`2.931865`**，不是 `1.931865` |
| 复权因子 | 新浪 `sh688008/hfq.js` | 后复权乘数，当前稀疏因子快照；历史版本仅从首次采集积累 |
| 财务 | 东方财富 LICO + DMSK 资产负债/利润/现金流 | 当前可取得的重述值；记录报告期、首次公告标签、来源更新/再披露日期、首次采集 |
| 股本 | 额外接入 `RPT_F10_FINANCE_MAINFINADATA` | 工作台补充接口；期末 TOTAL_SHARE，非加权平均股数，A/H 不拆分 |
| 估值 | `RPT_VALUEANALYSIS_DET` | PE_TTM / PB_MRQ / PS_TTM；不把动态年化 PE 当 TTM；非正 PE 留空 |
| 公告 | 东方财富公告索引 + 原文 PDF 入口 | 未使用 CNINFO 全市场同步；未实现全文下载管线、分部提取或自动业务解析 |
| 财报预约、解禁 | `RPT_PUBLIC_BS_APPOIN` / `RPT_LIFT_STAGE` | 当前快照；预约会改变；解禁来源万股转股；减持/监管仅标题线索 |

CNEquity 代码许可不等于数据许可。2026-10-16 重新读取的[东方财富服务协议](https://about.eastmoney.com/home/protocol)第六部分对内容使用、行情复制和对外提供设有书面许可限制。上游 `sources/SOURCES.yml` 也将缓存、留存、个人自动化使用等多项权限列为 unknown。新浪端点可取数，但本次未取得明确自动化采集及缓存授权依据。**本地取数成功不证明持续采集、缓存或再分发已获授权**；启用持续采集前应确认数据使用范围或替换为有授权的来源。

本轮请求限单证券、每次最多两次尝试、有间隔，遇 429 记录失败，不绕过访问限制。没有 SLA；来源可能改变字段或停止服务。原始响应按 SHA256 存于 `.local/ashare/raw/`，不进 Git、不上传。

日历采用 2025–2026 官方休市安排核对后的闭市日期，调休周末不当作交易日：[2025 上交所安排](https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml)、[2026 上交所安排](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)。2027 未核实，超界显式报错。

## 数据语义与派生计算

- 身份：股票 `CN:stock:688008.SH`；指数 `CN:index:000300.SH`、`CN:index:931865.CSI`。拒绝只给数字代码及把指数按股票加入关注。北交所日线市场路由未验证，明确报错。
- 默认行情窗口为最近 400 个自然日，最多 550 日；首批最多 10 只股票。日线截止最近已完成的交易日，上海时间 16:00 前不把当日盘中价当收盘。
- 后复权价 = 原价 × 当日累计因子；前复权价 = 原价 × 当日因子 ÷ 窗口末端因子。缺因子不补 1；成交量、成交额不复权。当前因子快照不能冒充历史当时所见版本。
- 收益 = 末价 / 初价 − 1；回撤 = 价格 / 截至当日最高价 − 1，取窗口最小值。缺失日期不填零，显示有效起止和缺口；停牌与来源缺行尚未逐项鉴别。
- 个股与指数只取共同交易日期、归一到 100；相对收益是两者区间收益的百分点差。指数为发布方价格指数，非全收益指数；没有重建历史成分。
- [中证半导体产业指数](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/931865factsheet.pdf)覆盖半导体材料、设备、应用等领域、不超过 40 只证券、半年调样；不能视为纯 DDR5 接口芯片可比组合。另一基准是沪深300。
- 收入、归母净利润、扣非、经营现金流、毛利按年初累计存储；Q1 直接取累计，其他季度用同年本期累计减上期累计。缺上期留空；输入记录 ID 可追溯。应收/存货是期末余额，不差分；基本 EPS 不差分、不机械年化。
- 单季度毛利率由单季毛利 / 单季收入计算。TTM 必须有四个连续季度，非半年乘二。历史重述可能造成两个累计版本不一致，页面提示核对原文。
- 扣非利润不等于纯主营利润。非正 PE、负盈利情景不展示常规估值。情景显式区分分析假设、机械年化、公司指引；公司指引要求原文链接。
- 状态区分已更新、覆盖不全、来源失败、过期、本次窗口无记录、尚未采集、截止时尚不可用。旧值保留日期；没有公告记录绝不等于没有风险。财务辅助接口失败不会丢弃可用的收入/利润，缺字段留空并记录具体失败来源。
- 日线和估值增量更新保留 10 天重叠；更早已知缺口会全窗口补取。公告按 ID、财务按报告期、行情按交易日去重；内容变动追加版本，A→B→A 也保留。每个数据集独立提交，可仅续跑失败/不完整项。

### 历史信息可用性

已重新检查所选 CNEquity 源码：`mcp_server/tools.py::query_fundamentals` 未传 `pit_mode`；`query/reader.py` 第 979–980 行在未传时选择 `best_effort`，并进入 `legacy_cutoff`。MCP 返回文字中的 PIT 声明不能作为严格历史可用的证据。

工作台始终返回 `strict=false`。`as_of` 仅表示**本机观察版本截止时间**：同时过滤版本首次采集时间和保守披露可用时间。日期级公告最早按次日上海零时可用；盘中可用性未经证实。回填的旧报告不能用于首次采集前的决策视图；当前观察卡也不带入早于其保存时间的历史数据视图。

最早真实采集从 **2026-10-16 11:53（Asia/Shanghai）**开始。2025 年的日线和 2024 年的财报是当天回填的当前版本，不能宣称有同期历史快照。来源首次公告日期不保证该数值是首次公告版本。预约、主数据及因子快照更不能伪装为历史状态。

## 澜起科技真实验证

窗口 **2025-09-10—2026-10-15**。本地回读结果见 `.local/ashare/verification.json`；原始响应保留于 `.local/ashare/raw/`。这批数据没有使用演示值。

| 项目 | 结果 |
| --- | --- |
| 身份与关注列表 | 澜起科技 / 上交所科创板 / `688008.SH`；已加入原关注列表 |
| 行情与估值 | 各 262 个交易日；原价、前/后复权可切换；当前窗口缺行 0、复权缺因子 0 |
| 价格 | 2026-10-15 原始收盘 163 CNY；该日来源 PE TTM 64.7221，A/H 市值口径未独立复算 |
| 因子 | 新浪当前快照包含 10 个稀疏因子节点；包含历史起始占位，非 10 个已核实除权事件 |
| 财务 | 8 个报告期：2024-09-30—2026-06-30，早期单季/TTM 因前期不全允许为空 |
| 公告索引 | 163 条，实际公告日期 2025-09-11—2026-10-01，请求窗口到 2026-10-15；不据末条日期推断后续没有风险 |
| 原文验证 | 半年报及股东减持计划两个链接返回 HTTP 206、PDF 文件头；未逐一验证全部链接、未实现全文结构化 |
| 财报预约 | 3 条当前记录；三季报当前预约 2026-10-30，可修订 |
| 解禁 | 来源在本次窗口（另含未来180日）返回空，显示“无记录”，未冒充“没有解禁风险” |
| 基准 | 半导体指数及沪深300各262条；显示基准名称、口径、实际覆盖与共同日期 |
| 观察卡 | 已保存改善假设、支持/反对/待验证证据、机械年化情景、失效条件、3条美股关联；浏览器保存回读版本2 |
| 去重 | 重复手动采集日线、估值、财务等不生成相同版本；公告时间毫秒抖动归一后重复163条新增0 |

金额单位为人民币亿元：

| 指标 | 2026Q1 累计 | 2026H1 累计 | 二季度 = H1 − Q1 |
| --- | ---: | ---: | ---: |
| 收入 | 14.6072 | 33.3550 | 18.7478 |
| 归母净利润 | 8.4738 | 19.9737 | 11.5000 |
| 扣非利润 | 6.0384 | 13.2248 | 7.1864 |
| 经营现金流 | 6.2664 | 13.2803 | 7.0139 |

半年末应收 9.7461 亿元、存货 9.9635 亿元，无论累计或单季度视图均保留期末余额。二季度毛利率为差分后的毛利/收入，约 61.8256%。页面同时提供2025同期，以支持同比核对。

支持证据为公司层面收入增长；反对证据针对“将归母增长全部归因主营”的解释，而非虚构经营恶化。观察卡没有假装产品收入、订单、客户采用已被核实。示例情景使用 H1 利润×2 和可修改的 40 倍 PE，明确其分析性质及股本局限，不是公司指引或投资目标价。

MU 关联 DDR5 服务器内存与 RCD/DB，明确 HBM 不等于 DDR5 接口需求；CRDO 关联高速互连与 PCIe Retimer，但 AEC/SerDes 并非同类产品；NVDA 仅作为平台需求背景，要求具体拓扑、用量、客户导入与量产证据。各自 SEC 财年、币种、GAAP/non-GAAP 保留，不按季度名称强行对齐。

## 修改、迁移与本地运行

新增后端：`investment_assistant/ashare/{domain,sources,repository,service,cards}.py`、`api/routes/ashares.py`、`tasks/ashares.py`。前端：`AShares.svelte`、`ResearchCard.svelte`；现有 Data/Strategy/侧栏/任务中心/设置页接入。既有 watchlist 和 SEC 自动流程增加 A 股隔离。

迁移 **013 已在本机执行**，新增 `cn_observations`、`cn_collection_state`、`research_observation_cards`、`research_observation_card_versions`，以及关闭状态的 `ashares` 调度行。未更改已有 US 数据表。其他环境在已有001–012基础上执行013；不重置数据库：

```bash
cd /Users/chenjianrui/workspaces/investment-assistant
.venv/bin/python - <<'PY'
from dotenv import load_dotenv
import os, pathlib, psycopg
load_dotenv('.env')
with psycopg.connect(os.environ['INVESTMENT_ASSISTANT_DATABASE_URL']) as conn:
    conn.execute(pathlib.Path('migrations/013_ashare_research.sql').read_text())
PY
```

复用当前环境：Python 3.11.15、FastAPI 0.141.1、psycopg 3.3.5、requests 2.34.2、Pydantic 2.13.5、uvicorn 0.52.4、Svelte 5、Vite 6.4.3。实际前端依赖由 `web/package-lock.json` 锁定。没有为 CNEquity 加新依赖。

本地入口：[A股数据](http://127.0.0.1:8787/#data/ashares)、[研究观察卡](http://127.0.0.1:8787/#strategy/observation)、[调度设置](http://127.0.0.1:8787/#settings/jobs)。启动方式：

```bash
cd /Users/chenjianrui/workspaces/investment-assistant
./start.command
```

已运行时不要重复启动。本机已使用现有 `local.investment-assistant` LaunchAgent 重载，仅监听127.0.0.1。前端重建在 `web/` 执行 `npm run build`。

手动采集（不发通知）：

```bash
.venv/bin/python -m investment_assistant.tasks.ashares \
  --symbols 688008.SH --from 2025-09-10 --to 2026-10-15
# 指定数据集或续跑：附加 --datasets financials,announcements / --retry-failed
.venv/bin/python scripts/verify_ashares.py
```

API：`GET /api/ashares/security/{symbol}`、`GET /api/ashares/{symbol}/research`、`POST /api/ashares/sync`、`GET/PUT /api/research/observation-cards/{symbol}`、`GET /api/research/us-references`。保存观察卡需传 `expected_version`，冲突409，不覆盖其他编辑。

**本机 A 股调度已于2026-10-16按用户要求启用**。时间18:30、Asia/Shanghai，交易日历再检查休市日；可在“设置 → 定时任务”查看或关闭 `ashares`。原美股任务保留 America/New_York。开启新任务时无下次时间会由现有调度器执行一次；机器须运行且唤醒。数据使用授权仍是前述未确认边界，2027日历尚未核实，超界会明确报错。A股任务启用后仍不发送外部通知。

### 调度闭环实证（2026-10-16）

13:39:22 通过现有调度 API 将 `ashares.enabled` 改为 true；只改本任务开关，未调整运行时间、其他任务或通知配置。

- 运行编号：`ashares-20261016054014-120a2420`。
- 调度线程自动触发，数据库及页面均记录 `trigger_source=scheduled`，不是手动运行替代验证。
- 13:40:14 开始、13:40:23 完成，耗时约9.2秒，`status=success`、`errors=[]`、`notifications=disabled`。
- 个股8个数据集及2个基准全部完成；解禁为来源返回空，其余成功。各数据集最近采集时间均落在本次运行中。
- 日线、估值、财务等相同内容新增版本0；公告新增2个版本，仅为来源展示时间变化，总数仍163条，不解释为新增经营事件。没有修改观察卡中的投资判断。
- 页面回读保留262个交易日、8期财务、163条公告、观察卡版本2。下一次调度为 **2026-10-16 18:30 +08:00**。
- 原3个美股任务的配置及上次/下次运行时间与启用前一致，调度器心跳正常。

证据：`.local/ashare/schedule-before.json`、`schedule-enabled.json`、`schedule-closed-loop.json`、`scheduler-enabled.jpg`、`scheduled-run-success.jpg`。本地验收脚本现在支持 `--expect-schedule enabled` / `disabled`，只核对状态、不改变开关；未指定时允许任意当前状态。

## 测试与验证边界

| 验证层 | 本次结果 | 不能据此声称 |
| --- | --- | --- |
| Python 模拟/回归 | 375 passed，6 skipped；覆盖证券标识、沪深日历、复权、季度/TTM、缺失与失败、通知关闭等 | 公共来源永远可用；6项跳过中5项须单独数据库测试 |
| PostgreSQL 临时表 | 单独5 passed；去重、A→B→A修订、历史筛选、失败保留/续跑、观察卡版本冲突、历史视图隔离 | 严格PIT回测或正式数据全量审计 |
| 前端组件 | 60 passed；含来源失败提示、单季切换、切换失败保留原价格口径；Node26需下述运行选项 | 全设备视觉验收 |
| 前端构建 | 通过，0错误；保留既有 FetchDateModal warning 和包体积提示 | 所有旧警告已修复 |
| 真实来源 | 单股票/两指数取数、两份PDF入口、重复采集与服务端回读成功 | 全市场/北交所/所有公告全面验证 |
| 真实浏览器 | 手动更新、财务期间切换、观察卡保存回读、公告原文打开、美股财报/关注列表、A股调度关闭且上海时区 | 用户对投资假设的验收 |

```bash
.venv/bin/python -m pytest -q
cd web
NODE_OPTIONS=--no-experimental-webstorage npm test -- --reporter=dot
npm run build
```

数据库测试为 `tests/test_ashare_postgres.py`，仅当设置 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 时运行；全部写入连接级 TEMP 表，不写正式业务表。单元测试隔离了本机生产数据库环境变量，防止 `.env` 污染测试。

原有8只美股关注、29条SEC索引和3个美股调度配置前后相同；本地原文/解析器复用且回归测试通过。本轮未再次运行带通知的 SEC 全流程，也未向 SEC 发起新下载，不能把该项描述为真实新财报抓取验证。未发送邮件或 Discord、未下单、未发布/上传/开隧道、未 commit/push。

## 后续候选顺序

先补齐上市状态、后续年度日历及授权稳定数据源；公告全文和产品分部证据是当前研究口径最直接的补强，需单独实现下载/解析、页码定位及人工核对。

| 顺序 | 候选 | 研究用途 | 数据限制与接入前提 |
| --- | --- | --- | --- |
| 1 | 一致预期、盈利预测修订 | 区分经营改善与市场已反映的预期，跟踪兑现差 | 授权预期源、预测口径/覆盖机构、预测发布及修订版本、真实历史快照 |
| 2 | 供Agent使用的只读MCP | 以统一证据口径读取观察卡与来源 | 稳定只读API、身份/权限、查询限额、来源与缺失状态随响应返回；不授权交易 |
| 3 | 融资融券、资金流、机构持仓 | 观察杠杆拥挤、交易参与及持仓变化背景 | 披露滞后、北向及机构口径变动、流量算法差异；资金流/人气/龙虎榜不转买卖建议 |
| 4 | 行业广度与轮动 | 判断改善由少数公司扩散到产业链的程度 | 历史成分、退市样本、行业分类变更、足够市场覆盖；不能用当前成分回填历史 |
| 5 | 分钟线、分笔、衍生品、完整回测 | 未来细化执行成本、对冲与规则检验 | 授权高频数据、交易规则/费用、复权与合约生命周期、严格PIT及存活偏差控制；本轮未开展 |

## 证据位置

- [CNEquity 固定源码](https://github.com/rootSunc/CNEquity/tree/c118038ea82b5bb78783c0c17a1d9251b36de71d)；本地对照检出在 `/private/tmp/investment-cnequity-reference`（临时目录，不作为运行依赖）。
- [2026 半年报原文](https://pdf.dfcfw.com/pdf/H2_AN202608281828638663_1.pdf)；[股东减持计划原文](https://pdf.dfcfw.com/pdf/H2_AN202609241829866357_1.pdf)。
- `.local/ashare/verification.json`：真实回读证据；`http-verification.json`：最终本地HTTP端点验证；`observation-card.jpg` / `scheduler-disabled.jpg`：页面截图（均在 `.local/ashare/`）；运行结果在现有 `job_reports`。
