# v2.0.0 发布整理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 A 股、只保留本机部署、按 roadmap / spec / plan / feature 重构文档，发布 `v2.0.0`。

**Architecture:** 先解耦再删除：研究观察卡的 SQL 搬出 `ashare/`，观察名单改为只认美股、无效代码一律当作身份无效，然后整包删除 `ashare/`；迁移 021 清理真实库。文档用 `git mv` 迁移，由一个离线测试守住相对链接。

**Tech Stack:** Python 3.11+ / FastAPI / psycopg / pytest；Svelte 5 + Vitest；PostgreSQL 17（一次性库）。

**Spec:** [docs/specs/2026-10-25-v2-release-cleanup-design.md](../specs/2026-10-25-v2-release-cleanup-design.md)

## Global Constraints

- 直接在 `main` 上开发和提交，不开分支或 worktree（`CLAUDE.md`）。
- 提交信息以 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 结尾。
- 后端离线回归：`env -u INVESTMENT_ASSISTANT_DATABASE_URL -u INVESTMENT_ASSISTANT_TEST_DATABASE_URL -u TEST_DATABASE_URL .venv/bin/python -m pytest tests/ -q`。
- SQL 测试只连一次性库：`INVESTMENT_ASSISTANT_TEST_DATABASE_URL=postgresql://test@127.0.0.1:55433/workbench_test`（搭建方法：`initdb -D <scratch>/pg/data -U test -A trust --no-locale -E UTF8`；`LC_ALL=C pg_ctl -D <scratch>/pg/data -o "-p 55433 -k '' -c listen_addresses=127.0.0.1" start`；`createdb -h 127.0.0.1 -p 55433 -U test workbench_test`）。永远不要把它指向真实库。
- 前端测试：`cd web && NODE_OPTIONS=--no-experimental-webstorage npm test`；构建：`npm run build`。
- 已执行过的迁移文件（`001`–`020`）不改；`job_reports` 历史行不删；`pool_tiers` 只追加，不删。
- 真实库迁移、服务重启、推送、打 tag、创建 GitHub Release 只在 Task 10、11 中、经用户在对话里明确同意后执行。
- 冻结文档（`docs/specs/`、`docs/plans/`、`docs/archive/`、`roadmap/v2-*.md`）的正文不改，只修相对链接。
- 残留检查（Task 3、4 完成判据，见 spec §4.3）：`grep -rnE '[Aa][Ss]hare|cnequity|is_cn_symbol|cn_observations|A ?股|\.(SH|SZ|BJ)\b' investment_assistant web/src scripts README.md` 只允许命中 `investment_assistant/us_research/domain.py` 中拒绝交易所后缀的那一行；`tests/` 中只允许把 `688008.SH`/`TSLA.SH` 等当作「无效美股代码」输入的用例命中，不允许命中 `[Aa][Ss]hare|cnequity|is_cn_symbol|cn_observations|CN:stock|'CN'`。

## Review Focus

1. **真实库迁移前，观察名单仍有 `688008.SH`**：Task 3 部署的新代码先于迁移 021 运行时，工作台批处理不能因为这一行报错——`pool.from_watchlist` 跳过身份无效的代码，列表接口给该行标 `identity_error`。测试：Task 3 `test_from_watchlist_skips_invalid_identity`。
2. **旧链接 `#strategy/observation?market=CN&symbol=688008.SH`**：打开后应落到美股研究卡并选中第一只美股，不报错、不白屏。测试：Task 4 `readResearchSelection rejects CN selections`。
3. **调用方仍带 `?market=CN` 或 `?market=US`**：`/api/watchlist` 忽略该参数，返回全部行，不报 422。测试：Task 3 `test_list_ignores_market_param`。
4. **调度器遇到库里残留的 `ashares` 任务行**（迁移前服务已重载）：调度器不能因为注册表里没有这个任务而崩溃。现有行为是记成 `unregistered job` 并跳过，已有测试 `tests/test_scheduler.py::test_run_due_jobs_unknown_name_records_error` 覆盖；Task 3 必须保持它通过。另外，真实库里这一行是 `enabled = FALSE`，所以不会被调度到。
5. **新装库从 `001` 跑到 `021`**：研究卡表仍然存在、`cn_*` 表不存在。测试：Task 1 `test_021_on_fresh_install`。

---

## File Structure

| 动作 | 路径 | 职责 |
| --- | --- | --- |
| Create | `migrations/021_drop_ashare.sql` | 删除 A 股表和数据（spec §4.4） |
| Create | `tests/test_migration_021.py` | 021 的静态检查与一次性库测试 |
| Create | `investment_assistant/research/card_repository.py` | 研究观察卡的 SQL：`get_card`、`save_card` |
| Rename | `tests/test_cross_market_cards.py` → `tests/test_research_cards.py` | 只保留美股卡片用例 |
| Modify | `investment_assistant/services/watchlist.py`、`workbench/pool.py`、`services/hermes.py`、`services/tickers.py`、`tasks/filings.py`、`tasks/scheduler.py`、`api/routes/__init__.py`、`api/routes/watchlist.py`、`research/cards.py`、`us_research/service.py` | 去掉 A 股分支 |
| Delete | `investment_assistant/ashare/`、`api/routes/ashares.py`、`tasks/ashares.py`、`scripts/verify_ashares.py`、`tests/test_ashare_*.py` | A 股整包 |
| Modify / Delete | `web/src/...`（Task 4 列出） | 前端去掉 A 股 |
| Delete | `deploy/`、`Dockerfile`、`.dockerignore`、`scripts/build-push.sh` | 非本机部署 |
| Create | `tests/test_docs_links.py` | 文档相对链接守卫 |
| Create / Move | `docs/**`（Task 6–9 列出） | 文档重构 |
| Create | `CHANGELOG.md` | 版本记录 |

---

### Task 1: 迁移 021

**Files:**
- Create: `migrations/021_drop_ashare.sql`
- Create: `tests/test_migration_021.py`

**Interfaces:**
- Produces: 迁移文件 `021_drop_ashare.sql`，内容即 spec §4.4 的 SQL（原样照抄，含首行注释）。

- [ ] **Step 1: 写失败的测试** `tests/test_migration_021.py`

```python
def test_only_one_021_migration():
    assert [p.name for p in Path('migrations').glob('021_*.sql')] == ['021_drop_ashare.sql']

def test_021_only_touches_ashare_objects():
    code = re.sub(r'--[^\n]*', '', Path('migrations/021_drop_ashare.sql').read_text(encoding='utf-8'))
    assert set(re.findall(r'DROP TABLE IF EXISTS (\w+)', code)) == {'cn_observations', 'cn_collection_state'}
    assert set(re.findall(r'DELETE FROM (\w+)', code)) == {
        'research_observation_card_versions', 'research_observation_cards', 'watchlist_items', 'scheduled_jobs'}
    assert 'job_reports' not in code and 'pool_tiers' not in code

def test_021_removes_cn_rows_and_keeps_us(ashare_db):  # 一次性库
    # 先插入：CN/US 研究卡各一（含版本行）、观察名单 688008.SH / 600519.SH / MU / BRK.B、
    # scheduled_jobs 的 ashares 与 workbench、一行 job_reports(task='ashares')、cn_observations 一行
    # 执行 021 两次（可重复执行）后断言：
    #   cn_observations / cn_collection_state 不存在（to_regclass 为 NULL）
    #   research_observation_cards 只剩 US 行，versions 只剩 US 行
    #   watchlist_items == {'MU', 'BRK.B'}；scheduled_jobs 有 workbench、无 ashares
    #   job_reports 中 task='ashares' 的行仍在

def test_021_on_fresh_install(ashare_db):
    # ashare_db 夹具已按序执行 001–020；再执行 021 后
    #   to_regclass('research_observation_cards') 非空，to_regclass('cn_observations') 为空
```

夹具 `ashare_db`：照 `tests/conftest.py::workbench_db` 的写法，在一次性 schema 中按文件名顺序执行 `migrations/0[01]*.sql` 与 `020_*.sql`（即 001–020），没有 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 时 skip。定义在本测试文件内。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python -m pytest tests/test_migration_021.py -v`（不设测试库 URL）
Expected: 两个静态测试 FAIL（文件不存在），两个库测试 SKIP。

- [ ] **Step 3: 写 `migrations/021_drop_ashare.sql`**（spec §4.4 原文）

- [ ] **Step 4: 运行，确认通过**

Run: 先不带 URL 跑一次（静态测试 PASS），再带一次性库 URL 跑一次：`INVESTMENT_ASSISTANT_TEST_DATABASE_URL=postgresql://test@127.0.0.1:55433/workbench_test .venv/bin/python -m pytest tests/test_migration_021.py tests/test_migration_runner.py tests/test_migration_fk_integration.py -v`
Expected: 全部 PASS，0 skipped。

- [ ] **Step 5: 提交** `feat: add migration 021 to drop A-share data`

---

### Task 2: 研究观察卡脱离 `ashare`

**Files:**
- Create: `investment_assistant/research/card_repository.py`
- Modify: `investment_assistant/research/cards.py`、`investment_assistant/us_research/service.py:309`、`investment_assistant/services/watchlist.py:65`
- Rename + Modify: `tests/test_cross_market_cards.py` → `tests/test_research_cards.py`
- Modify: `tests/test_us_research_postgres.py:24`（仍从 `013` 文件读建表语句，保留；只确认无 `ashare` 导入）

**Interfaces:**
- Produces: `research.card_repository.get_card(conn, sid: str) -> dict | None`、`save_card(conn, sid: str, body: dict, expected_version: int | None) -> dict`——签名与 SQL 和 `ashare/repository.py:97-140` 现有实现一致，原样搬过来。
- Produces: `research.cards.stock_id(symbol) -> str` 只返回 `US:stock:<T>`；A 股代码抛 `ValueError`（由 `us_research.domain.stock_id` 抛出）。
- Produces: `research.cards` 的数据库连接改用 `investment_assistant.db.connect(os.environ['INVESTMENT_ASSISTANT_DATABASE_URL'])`；原 `ashare.service.connection` 的未配置报错语义保持（缺 URL 时抛同样的 `ValueError`）。

- [ ] **Step 1: 改测试**：`git mv tests/test_cross_market_cards.py tests/test_research_cards.py`；删除 `688008.SH`/`CN:stock` 相关用例与 `013` 之外对 `cn_*` 表的依赖；保留并让美股卡片的读写、版本冲突、引用校验用例改为从 `research.card_repository` 取函数。新增：

```python
def test_card_rejects_ashare_symbol():
    with pytest.raises(ValueError):
        cards.stock_id('688008.SH')

def test_cards_module_has_no_ashare_import():
    assert 'ashare' not in Path('investment_assistant/research/cards.py').read_text(encoding='utf-8')
```

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python -m pytest tests/test_research_cards.py -v`
Expected: FAIL（`card_repository` 不存在、`stock_id('688008.SH')` 仍返回 CN id）。

- [ ] **Step 3: 实现**：新建 `card_repository.py`（搬 SQL）；`cards.py` 删除 `cn_stock_id`、`_observation` 的 `cn_observations` 分支（只查 `us_research_observations`）、两处 `'CNY'` 默认值及 `profit_cny` 兼容读取（`currency` 字段保留，无默认时为 `None`）；`us_research/service.py` 与 `services/watchlist.py` 改为从 `research.card_repository` 导入 `get_card`。

- [ ] **Step 4: 运行**

Run: `INVESTMENT_ASSISTANT_TEST_DATABASE_URL=… .venv/bin/python -m pytest tests/test_research_cards.py tests/test_us_research_postgres.py tests/test_us_research_service.py tests/test_services_research.py -v`
Expected: PASS，0 skipped。

- [ ] **Step 5: 提交** `refactor: move research card storage out of the A-share package`

---

### Task 3: 观察名单只认美股，删除 `ashare` 后端

**Files:**
- Modify: `investment_assistant/services/watchlist.py`、`investment_assistant/api/routes/watchlist.py`、`investment_assistant/workbench/pool.py`、`investment_assistant/services/hermes.py:23-38`、`investment_assistant/services/tickers.py:130-132`、`investment_assistant/tasks/filings.py:19-21`、`investment_assistant/tasks/scheduler.py:15,22`、`investment_assistant/api/routes/__init__.py`
- Delete: `investment_assistant/ashare/`、`investment_assistant/api/routes/ashares.py`、`investment_assistant/tasks/ashares.py`、`scripts/verify_ashares.py`、`tests/test_ashare_domain.py`、`tests/test_ashare_postgres.py`、`tests/test_ashare_sources.py`
- Modify tests: `tests/test_watchlist_markets.py`、`tests/test_watchlist_api.py`、`tests/test_workbench_pool.py`、`tests/test_workbench_api.py:102`、`tests/test_verify_cross_market.py:221`、`tests/test_scheduler.py`
- 本地清理（不在 Git 中）：`rm -rf investment_assistant/research_agent tests/research_agent`

**Interfaces:**
- Consumes: Task 2 的 `research.card_repository.get_card`。
- Produces（`services/watchlist.py`）：
  - `validated_symbol(value: str) -> str`：`us_research.domain.stock_id(value.strip().upper())` 的 ticker 部分；非字符串仍抛 `ValueError('证券代码必须为字符串')`。
  - `watchlist_rows(*, enriched: bool = False) -> list[dict]`：删除 `market` 参数；每行 `market` 为 `'US'`，身份无效的行 `market` 为 `None` 并带 `identity_error`（现有文案不变）；`_enrich` 删除 `board` 字段与 CN 分支。
  - `resolve_candidates(symbol: str) -> list[dict]`：返回 `[{'symbol': validated_symbol(symbol), 'market': 'US', 'asset_type': 'stock'}]`。
  - `current_watchlist()`：active 且身份有效的行。
- Produces（`api/routes/watchlist.py`）：`GET /api/watchlist?enriched=` 不再声明 `market` 参数（多余的查询参数被忽略）。
- Produces（`workbench/pool.py`）：`from_watchlist` 跳过身份无效的代码（用 `us_research.domain.stock_id` 校验，抛 `ValueError` 即跳过）；空池报错文案保持 `'股票池为空：观察名单中没有 active 的美股'`。
- Produces（`tasks/scheduler.py`）：`REGISTRY` 无 `ashares` 键。

- [ ] **Step 1: 改写/新增测试**

```python
# tests/test_workbench_pool.py：原 test_from_watchlist_skips_paused_archived_and_cn 改名
def test_from_watchlist_skips_invalid_identity():
    rows = _rows(['AAPL'], tags=['core']) + _rows(['688008.SH'], tags=['core']) + _rows(['NVDA'])
    p = pool.from_watchlist(rows)  # 688008.SH: 无效美股代码，迁移 021 前可能仍在库里
    assert p.core == ('AAPL',) and p.extended == ('NVDA',)

# tests/test_watchlist_api.py
def test_add_rejects_ashare_code(client, monkeypatch):  # 688008.SH 作无效输入
    monkeypatch.setenv('INVESTMENT_ASSISTANT_DATABASE_URL', 'postgresql://unused')
    assert client.post('/api/watchlist', json={'ticker': '688008.SH'}).status_code == 400

def test_list_ignores_market_param(client, monkeypatch):
    monkeypatch.setattr(wl, 'watchlist_rows', lambda **kw: [{'ticker': 'MU', 'market': 'US'}])
    assert client.get('/api/watchlist?market=CN').status_code == 200

def test_resolve_returns_us_candidate(client):
    assert client.get('/api/watchlist/resolve?symbol=mu').json() == {
        'candidates': [{'symbol': 'MU', 'market': 'US', 'asset_type': 'stock'}]}

# tests/test_scheduler.py
def test_registry_has_no_ashares():
    assert 'ashares' not in scheduler.REGISTRY
# 现有 test_run_due_jobs_unknown_name_records_error 保持不变
```

`tests/test_watchlist_markets.py`：删除所有 CN 用例（`ashare` 导入、`600519`、`CN:stock`、resolve 6 位数字）；`AAPL.US`/`TSLA.SH`/`ABC.DEF` 作为无效代码的 `identity_error` 用例保留。`test_workbench_api.py:102`、`test_verify_cross_market.py:221` 中的 `688008.SH` 改成美股代码或直接删掉（它们原本测的是「CN 被过滤」）。

- [ ] **Step 2: 运行，确认失败**

Run: `.venv/bin/python -m pytest tests/test_workbench_pool.py tests/test_watchlist_api.py tests/test_watchlist_markets.py tests/test_scheduler.py -v`
Expected: 新用例 FAIL（例如 `ashares` 仍在 `REGISTRY`、resolve 仍走 A 股）。

- [ ] **Step 3: 实现**：按 Interfaces 改共享代码；`hermes.py`、`tickers.py` 删除 A 股检查（两处 `ValueError('…A股…')`）；`tasks/filings.py` 去掉 `us_only`，直接传 `config.watchlist`；删除 `ashare/` 包等 Delete 列表中的文件。

- [ ] **Step 4: 运行全量与残留检查**

Run: 离线全量回归（Global Constraints）；再带一次性库 URL 跑一次全量；`.venv/bin/python -c "import investment_assistant.api.app"`；残留 grep（Global Constraints，限 `investment_assistant scripts tests`）。
Expected: 全部 PASS；import 无报错；grep 只命中约定的例外。

- [ ] **Step 5: 提交** `feat!: remove the A-share package and make the watchlist US-only`

---

### Task 4: 前端去掉 A 股

**Files:**
- Delete: `web/src/routes/AShares.svelte`、`web/src/routes/AShares.test.ts`
- Modify: `web/src/lib/components/SideNav.svelte:32`（删「A 股研究数据」）、`web/src/routes/Data.svelte`（删 `ashares` 子页与导入）、`web/src/routes/Strategy.svelte`（删 A 股/美股切换，观察卡固定渲染 `<USResearch mode="card" />`）、`web/src/routes/Tools.svelte`（删 `ashares` 任务描述与选项）、`web/src/lib/components/Watchlist.svelte`（删 All/CN/US 标签页和 `board` 小字；美股专属按钮的条件改为 `!row.identity_error`）、`web/src/lib/components/SecurityPicker.svelte`（删 `market` 属性）、`web/src/lib/api.ts`（`getWatchlist(enriched = false)`）、`web/src/lib/research-navigation.ts`（`Market = 'US'`，删 CN 分支）、`web/src/lib/components/ResearchCard.svelte`（默认币种固定 `USD`，删 `profit_cny` 兼容与 `CNY` 选项）、`web/src/lib/components/GuidanceEditor.svelte:81`（删「不能视作 A 股扣非利润」半句）、`web/src/routes/USResearch.svelte`（调用 `SecurityPicker` 不再传 `market`）
- Modify tests: `web/src/app-navigation.test.ts`、`web/src/lib/router.test.ts`、`web/src/lib/research-navigation.test.ts`、`web/src/lib/components/Watchlist.test.ts`、`web/src/lib/components/ResearchCard.test.ts`、`web/src/routes/USResearch.test.ts`、`web/src/lib/api.test.ts`

**Interfaces:**
- Consumes: Task 3 的 `/api/watchlist` 行结构（`market: 'US' | null`、`identity_error`）。
- Produces: `researchHash(zone, sub, market: 'US', symbol)` 生成的链接格式不变（`?market=US&symbol=…`），旧书签可用；`readResearchSelection` 对 `market=CN` 返回 `null`。

- [ ] **Step 1: 改测试**：删除 A 股相关断言；新增

```ts
it('readResearchSelection rejects CN selections', () => {
  expect(readResearchSelection('#strategy/observation?market=CN&symbol=688008.SH')).toBeNull()
  expect(readResearchSelection('#strategy/observation?market=US&symbol=MU')).toEqual({ market: 'US', symbol: 'MU' })
})
it('side nav has no A-share entry', ...)        // app-navigation.test.ts：不出现「A 股研究数据」
it('watchlist shows no market tabs', ...)       // Watchlist.test.ts：不存在 aria-label「关注市场」
it('getWatchlist(true) requests ?enriched=true only', ...)  // api.test.ts
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd web && NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/lib/research-navigation.test.ts src/app-navigation.test.ts src/lib/components/Watchlist.test.ts src/lib/api.test.ts`
Expected: 新用例 FAIL。

- [ ] **Step 3: 实现**：按 Files 列表修改。

- [ ] **Step 4: 运行**

Run: `cd web && NODE_OPTIONS=--no-experimental-webstorage npm test && npm run build`；残留 grep（限 `web/src`）。
Expected: 测试与构建全部通过；grep 无命中。

- [ ] **Step 5: 提交** `feat!: remove A-share pages and market switches from the web app`

---

### Task 5: 删除非本机部署

**Files:**
- Delete: `deploy/`、`Dockerfile`、`.dockerignore`、`scripts/build-push.sh`
- Modify: `scripts/README.md`（改写为现存脚本表：`start_local.py` 由 `start.command` 调用、本机服务入口；`review_phase0_archives.py` Phase 0 归档只读评审；`verify_cross_market.py` 美股研究数据只读验收）

- [ ] **Step 1: 确认没有引用**

Run: `grep -rnE 'deploy/|Dockerfile|build-push|push-to-nuc|install\.sh|docker-compose' --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git --exclude-dir=.local --exclude-dir=docs .`
Expected: 只命中待删文件自身（`runtime_paths.py` 的 `/opt`、`/srv` 默认路径不改，由 Task 7 的运维文档说明本机实际路径）。

- [ ] **Step 2: 删除、改写 `scripts/README.md`，跑离线全量回归**

Expected: PASS。

- [ ] **Step 3: 提交** `chore!: drop NUC and Sealos deployment files`

---

### Task 6: 文档骨架迁移与链接守卫

**Files:**
- Create: `tests/test_docs_links.py`
- Move（`git mv`）：
  - `docs/superpowers/specs/2026-10-2[345]-*.md` → `docs/specs/`
  - `docs/superpowers/plans/2026-10-2[345]-*.md` → `docs/plans/`
  - `docs/superpowers/specs/2026-0[67]-*.md`、`2026-10-16-*.md` → `docs/archive/roadmap-v1/specs/`
  - `docs/superpowers/plans/2026-0[67]-*.md`、`2026-10-16-*.md` → `docs/archive/roadmap-v1/plans/`
- Modify: `CLAUDE.md`（追加一条：「设计 spec 放 `docs/specs/YYYY-MM-DD-<topic>-design.md`，实施 plan 放 `docs/plans/YYYY-MM-DD-<topic>.md`，写成后只增不改。」）
- Modify: 所有因移动而失效的相对链接（含冻结文档，只改链接）

**Interfaces:**
- Produces: `tests/test_docs_links.py::test_relative_links_resolve`——扫描 `README.md`、`CHANGELOG.md`（存在时）、`docs/**/*.md` 中的 `[text](target)`，跳过 `http(s):`、`mailto:`、纯锚点 `#…`；去掉 `#锚点` 后按文件所在目录解析，断言目标存在。后续 Task 7–9 依赖它作完成判据。

- [ ] **Step 1: 写测试并运行**，Expected：当前已有失效链接时 FAIL（记下失效列表），没有时 PASS。
- [ ] **Step 2: 执行移动、修链接、改 `CLAUDE.md`**；删除空的 `docs/superpowers/`。
- [ ] **Step 3: 运行** `.venv/bin/python -m pytest tests/test_docs_links.py -v`，Expected：PASS。
- [ ] **Step 4: 提交** `docs: move specs and plans out of docs/superpowers and guard relative links`

---

### Task 7: 架构、上手与运维文档

**Files:**
- Rewrite: `docs/architecture.md`（spec §6.3 五节；主线数据流用 mermaid `flowchart`；模块表分「主线」「共享底座」「v1 遗留」三组，每个模块一行：做什么 / 依赖什么）
- Rewrite: `docs/getting-started.md`（spec §6.2 所列更新点）
- Create: `docs/operations/local-service.md`（LaunchAgent `local.investment-assistant`、`start.command`、日志路径、`launchctl kickstart -k gui/$(id -u)/local.investment-assistant`、`runtime_paths.py` 默认路径在本机的实际含义）
- Move + Update: `docs/scheduling-and-notifications.md` → `docs/operations/`（任务表改为当前 `REGISTRY`：`workbench`、`workbench_review`、`filings`、`metrics`、`scores`、`event_study`；删「systemd 服务（已废弃）」一节）
- Create: `docs/operations/migrations-and-backup.md`（迁移清单 001–021 一行一条；`pg_dump` 备份 + `psql --single-transaction -f` 执行；一次性库测试搭建，取自 Global Constraints；合并 `us-workbench.md` 中 P1–P4「上线前提」里的迁移与配置项）
- Delete: `docs/deployment-sealos.md`

- [ ] **Step 1: 写文档**。事实以代码为准：任务时间读 `migrations/*.sql` 的 `scheduled_jobs` 种子与真实库无关的默认值；环境变量以 `investment_assistant/config.py`、`workbench/agent/model.py`、`workbench/macro.py` 实际读取的为准。
- [ ] **Step 2: 运行** `tests/test_docs_links.py`，Expected：PASS。
- [ ] **Step 3: 提交** `docs: rewrite architecture, getting started and operations for v2`

---

### Task 8: 功能文档

**Files:**
- Create: `docs/features/daily-plan.md`、`agent-track.md`、`review.md`、`pool-and-context.md`（内容来自 `docs/us-workbench.md` 对应各节，改写为「现在怎么工作」：做什么、前端入口、API/CLI 入口、如何验证一次、已知限制；每篇末尾链接对应的 P1–P4 spec）
- Create: `docs/features/sec-filings.md`（合并 `sec-downloader.md` 与 `sec-monitor-migration.md`）
- Create: `docs/features/legacy/README.md`（遗留清单：Hermes、策略评分与信号、事件研究、美股财季数据与研究观察卡；状态「保留，不再演进，待合并或删除」，链接 `roadmap/backlog.md`）
- Create: `docs/features/legacy/hermes.md`（合并 `hermes-usage.md`、`features/trade.md`）、`strategy-and-signals.md`（来自 `features/data.md`、`features/strategy.md` 的信号/趋势/评分/技术面部分）、`event-study.md`（`git mv docs/research-event-study.md`）、`us-research.md`（`cross-market-research.md` 的美股部分压缩）
- 底座能力（任务中心、运行记录、SSE、关注列表、推送配置、定时任务、环境变量、认证；来自 `features/tools.md`、`features/settings.md`）并入 `docs/operations/scheduling-and-notifications.md` 与 `docs/getting-started.md`
- Delete: `docs/us-workbench.md`、`sec-downloader.md`、`sec-monitor-migration.md`、`hermes-usage.md`、`cross-market-research.md`、`ashare-research.md`、`features/data.md`、`strategy.md`、`tools.md`、`settings.md`、`trade.md`

- [ ] **Step 1: 写文档、删旧文档**；冻结文档里指向被删文档的链接改为指向新位置。
- [ ] **Step 2: 运行** `tests/test_docs_links.py`；再 `grep -rnE 'A ?股|ashare' docs --include=*.md | grep -vE '^docs/(archive|specs|plans)/|^docs/roadmap/v2-'`，Expected：链接 PASS，grep 无命中。
- [ ] **Step 3: 提交** `docs: reorganize feature docs by capability and fold legacy features`

---

### Task 9: roadmap 与文档索引

**Files:**
- Modify: `docs/roadmap/README.md`（版本表：v2 状态改为「已完成，发布 `v2.0.0`（2026-10-25）」；新增「下一版」一行指向 `backlog.md`；文档表加 `backlog.md`；删除指向 `us-workbench.md` 的行）
- Modify: `docs/roadmap/v2-decision-loop.md`（只在标题下加一行 `> 状态：已完成，发布于 v2.0.0。`）
- Modify: `docs/roadmap/v2-progress.md`（顶部加冻结说明一行；阶段证据表末尾追加 2026-10-25 发布整理一行，内容在 Task 10 验收后补齐）
- Create: `docs/roadmap/backlog.md`（三节：v1 遗留功能合并或删除——逐项列出 Hermes/DeepSeek、策略评分与信号、事件研究、美股财季数据与研究观察卡，以及 `metrics`/`scores`/`event_study` 任务；v2 暂缓项——照搬 `v2-decision-loop.md` §6 中「暂缓」各行；未完成的使用验收——`v2-progress.md`「当前阶段」表中各阶段的 `user_acceptance_pending` 下一步）
- Rewrite: `docs/README.md`（索引按 spec §6.1；加 spec §6.4 维护规则表）

- [ ] **Step 1: 写文档**
- [ ] **Step 2: 运行** `tests/test_docs_links.py`，Expected：PASS。
- [ ] **Step 3: 提交** `docs: close roadmap v2 and add the backlog and docs index`

---

### Task 10: README、CHANGELOG、版本号与全量验证

**Files:**
- Rewrite: `README.md`（spec §7 第 3 条：一段话定位、快速开始、文档入口、当前版本 `v2.0.0`）
- Create: `CHANGELOG.md`（spec §7 第 1 条；格式：`## v2.0.0 — 2026-10-25`，下分「新增」「不兼容变更」「已知限制」）
- Modify: `web/package.json`、`web/package-lock.json`（`cd web && npm version 2.0.0 --no-git-tag-version`）

- [ ] **Step 1: 写文件、改版本号**
- [ ] **Step 2: 全量验证**（spec §8 前四行）：离线全量回归；一次性库全量回归（0 skipped 中应含 Task 1 的库测试）；前端 `npm test` 与 `npm run build`；残留 grep；`tests/test_docs_links.py`。
Expected: 全部通过；记录通过数。
- [ ] **Step 3: 提交** `docs: add the v2.0.0 changelog and readme`

---

### Task 11: 真实库与服务验收（需用户明确同意后执行）

- [ ] **Step 1: 征得同意**：在对话里说明将执行的动作（备份、迁移 021、构建前端、重启服务、手动批处理不推送），等用户明确同意。
- [ ] **Step 2: 备份**：`pg_dump -Fc "$INVESTMENT_ASSISTANT_DATABASE_URL" -f .local/us-workbench/backups/investment_assistant-before-021-<时间戳>.dump`，记录 sha256。
- [ ] **Step 3: 迁移**：`psql "$INVESTMENT_ASSISTANT_DATABASE_URL" --single-transaction -v ON_ERROR_STOP=1 -f migrations/021_drop_ashare.sql`；重新统计 spec §4.1 各项，Expected：`cn_*` 表不存在，CN 研究卡与版本 0 行，观察名单 8 只美股，无 `ashares` 任务行，`job_reports` 中 `ashares` 历史行数不变。
- [ ] **Step 4: 构建与重启**：先备份 `web/dist` 到 `.local/us-workbench/dist-backup-<时间戳>`，`cd web && npm run build`，`launchctl kickstart -k gui/$(id -u)/local.investment-assistant`。
- [ ] **Step 5: 检查**：`curl -u … /api/status`；`POST /api/watchlist` 提交 `688008.SH` 返回 400；在任务中心手动运行一次 `workbench`（手动运行不推送）且无报错；页面「今日」「复盘」「设置 → 关注列表」「策略 → 研究观察卡」正常。
- [ ] **Step 6: 记录证据**：补齐 `v2-progress.md` 末尾的发布整理一行（备份文件名与 sha256、迁移结果、批处理 run_id）；提交 `docs: record migration 021 and the v2.0.0 acceptance`。

---

### Task 12: 发布（需用户明确同意后执行）

- [ ] **Step 1: 征得同意**：说明将推送 `main`、推送 tag `v2.0.0`、创建 GitHub Release（私有仓库 `jianjustin/investment-assistant`），等用户明确同意。
- [ ] **Step 2: 打 tag**：`git tag -a v2.0.0 -m "v2.0.0"`。
- [ ] **Step 3: 推送**：`git push origin main && git push origin v2.0.0`。
- [ ] **Step 4: 创建 Release**：从 `CHANGELOG.md` 截取 v2.0.0 一节写到 scratchpad 文件，`gh release create v2.0.0 --title "v2.0.0" --notes-file <该文件>`；正文末尾加 `🤖 Generated with [Claude Code](https://claude.com/claude-code)`。
- [ ] **Step 5: 核对**：`gh release view v2.0.0`，Expected：tag 指向本地 `main` 的 HEAD。
