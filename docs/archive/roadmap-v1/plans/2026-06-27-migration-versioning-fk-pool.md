# T6.1 迁移版本化 + 外键 + 连接池 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让数据库迁移可重复安全执行（版本化账本驱动）、补上 `strategy_scores → ticker_signal_snapshots` 外键、并把每请求新建连接换成进程级连接池——为 Phase 2 起的 5 张新表打好可演进的 schema 地基。

**Architecture:** 复用已存在但未接线的 `db.apply_pending_migrations`（`schema_migrations` 账本）做一个 CLI 迁移入口并切换部署脚本；新增一支幂等的 `ALTER` 迁移加外键（含孤儿清理）；把 `db.connect()` 改为返回进程级 `psycopg_pool` 的连接上下文管理器，所有现有 `with connect(url) as conn:` 调用点零改动透明受益。

**Tech Stack:** Python 3.11、psycopg3 + psycopg-pool、PostgreSQL 16、pytest。

## Global Constraints

- **每个 PR**：新增/改动逻辑有单测；外部调用（psycopg / psycopg_pool）全部 mock，离线可跑；触碰 schema 的迁移必带迁移文件。
- **不引入新的裸 `except Exception` 吞错**；外部失败结构化上报。
- **迁移必须幂等**：可重复安全执行（账本 run-once + `ALTER` 用 `IF NOT EXISTS` / `DO $$ ... $$` 守卫）。
- **已存在的资产（勿重复造）**：`investment_assistant/db.py:21-62` 已有 `_ensure_migration_ledger` / `applied_migrations` / `apply_pending_migrations`，且 `schema_migrations(filename PK, applied_at)` 账本已定义。本计划是**接线 + 补 FK + 连接池**，不是重写账本。
- **当前缺口**：`deploy/install.sh:39-44` 仍调用旧的顺序式 `apply_migration`（无账本、无法 run-once）；`migrations/004_strategy_scores.sql` 的 `source_snapshot_id BIGINT` 无外键；`db.connect()`（`db.py:8-11`）是每次 `psycopg.connect`，无池。
- **迁移文件编号**：本计划占用 `005`（FK）。后续 Phase 2 从 `006` 起（macro_indicators=006、fundamentals=007、filings=008、price_bars=009）。
- **所有 `connect()` 调用点均为 `with connect(url) as conn:` 形态**（已核查 13 处：`db.py`/`dashboard/*`/`hermes/daily.py`），故连接池替换无需改调用点。
- **分支**：从 `main` 切 `feat/migration-versioning`；不主动 push；提交信息结尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **环境准备**：`python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`（本计划 Task 3 会向 requirements 加 `psycopg-pool`）。

---

## File Structure

```
investment_assistant/
  migrate.py            # 新：迁移 CLI 入口（python -m investment_assistant.migrate）
  db.py                 # 改：connect() 改为池化上下文管理器 + 保留迁移函数
migrations/
  005_strategy_scores_fk.sql   # 新：孤儿清理 + 幂等加外键
deploy/install.sh       # 改：迁移步骤切到版本化 runner
requirements.txt        # 改：+ psycopg-pool>=3.2.0
tests/
  test_migration_runner.py     # 新：账本逻辑离线单测 + runner 入口
  test_db_pool.py              # 新：连接池行为单测（mock psycopg_pool）
  test_db_sql.py               # 改：补 005 FK 迁移的断言
```

---

### Task 1：版本化迁移 CLI + 切换部署脚本

> 把已存在的 `apply_pending_migrations` 接成可运行入口，并让 `install.sh` 用它取代旧 `apply_migration`，实现 run-once / 可 `ALTER`。

**Files:**
- Create: `investment_assistant/migrate.py`
- Create: `tests/test_migration_runner.py`
- Modify: `deploy/install.sh:36-46`

**Interfaces:**
- Consumes: `investment_assistant.db.apply_pending_migrations(conn, migrations_dir) -> list[str]`（已存在）、`investment_assistant.db.connect(url)`。
- Produces: `investment_assistant.migrate.run(database_url: str, migrations_dir: str | Path | None = None) -> list[str]`（返回本次应用的文件名）；`investment_assistant.migrate.main()`（读 `INVESTMENT_ASSISTANT_DATABASE_URL`，打印 JSON）。

- [ ] **Step 1: 写账本逻辑离线单测** —— `tests/test_migration_runner.py`（用 Fake conn 验证 run-once / 顺序 / 返回值，不连真库）：

```python
from pathlib import Path
from investment_assistant.db import apply_pending_migrations


class FakeCursor:
    def __init__(self, store):
        self.store = store
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None):
        self.store["executed"].append((sql.strip().split("\n")[0], params))
        if sql.strip().startswith("INSERT INTO schema_migrations"):
            self.store["applied"].add(params[0])
    def fetchall(self):
        return [(name,) for name in sorted(self.store["applied"])]


class FakeConn:
    def __init__(self, store): self.store = store
    def cursor(self): return FakeCursor(self.store)
    def commit(self): self.store["commits"] += 1


def test_apply_pending_runs_each_unapplied_in_order(tmp_path):
    (tmp_path / "001_a.sql").write_text("CREATE TABLE a();")
    (tmp_path / "002_b.sql").write_text("CREATE TABLE b();")
    store = {"executed": [], "applied": set(), "commits": 0}
    applied = apply_pending_migrations(FakeConn(store), tmp_path)
    assert applied == ["001_a.sql", "002_b.sql"]


def test_apply_pending_skips_already_recorded(tmp_path):
    (tmp_path / "001_a.sql").write_text("CREATE TABLE a();")
    (tmp_path / "002_b.sql").write_text("CREATE TABLE b();")
    store = {"executed": [], "applied": {"001_a.sql"}, "commits": 0}
    applied = apply_pending_migrations(FakeConn(store), tmp_path)
    assert applied == ["002_b.sql"]
```

- [ ] **Step 2: 运行确认通过（账本既有逻辑）**

Run: `python -m pytest tests/test_migration_runner.py -q`
Expected: PASS（`apply_pending_migrations` 已存在；此步先钉住其契约）。

- [ ] **Step 3: 写 runner 入口测试** —— 追加到 `tests/test_migration_runner.py`：

```python
from unittest.mock import patch
from investment_assistant import migrate


def test_run_invokes_apply_pending(monkeypatch, tmp_path):
    captured = {}
    class Ctx:
        def __enter__(self): return "CONN"
        def __exit__(self, *a): return False
    with patch.object(migrate, "connect", return_value=Ctx()) as conn, \
         patch.object(migrate, "apply_pending_migrations", return_value=["005_x.sql"]) as app:
        out = migrate.run("postgres://x", migrations_dir=tmp_path)
    conn.assert_called_once_with("postgres://x")
    app.assert_called_once()
    assert out == ["005_x.sql"]
```

- [ ] **Step 4: 运行确认失败**

Run: `python -m pytest tests/test_migration_runner.py::test_run_invokes_apply_pending -q`
Expected: FAIL（无 `investment_assistant.migrate`）。

- [ ] **Step 5: 实现 `investment_assistant/migrate.py`：**

```python
from __future__ import annotations

import json
import os
from pathlib import Path

from investment_assistant.db import apply_pending_migrations, connect

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def run(database_url: str, migrations_dir: str | Path | None = None) -> list[str]:
    target = Path(migrations_dir or DEFAULT_MIGRATIONS_DIR)
    with connect(database_url) as conn:
        return apply_pending_migrations(conn, target)


def main() -> None:
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        raise SystemExit("INVESTMENT_ASSISTANT_DATABASE_URL is required to run migrations")
    applied = run(url)
    print(json.dumps({"applied": applied, "count": len(applied)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_migration_runner.py -q`
Expected: PASS

- [ ] **Step 7: 切换 `deploy/install.sh` 迁移步骤** —— 把 `install.sh:36-46` 的内联块替换为：

```bash
if [[ -n "${INVESTMENT_ASSISTANT_DATABASE_URL:-}" ]]; then
  echo "Applying database migrations (versioned)"
  (cd "$APP" && "$VENV/bin/python" -m investment_assistant.migrate)
fi
```

- [ ] **Step 8: Commit**

```bash
git add investment_assistant/migrate.py tests/test_migration_runner.py deploy/install.sh
git commit -m "feat: versioned migration runner (python -m investment_assistant.migrate) + install.sh switch"
```

### Task 2：`strategy_scores` 外键迁移（005）

> 补 `strategy_scores.source_snapshot_id → ticker_signal_snapshots(id)` 外键；先清理孤儿引用，再幂等加约束（`ON DELETE SET NULL`，因评分历史不应随快照删除而丢失）。

**Files:**
- Create: `migrations/005_strategy_scores_fk.sql`
- Modify: `tests/test_db_sql.py`（追加 005 断言）
- Create: `tests/test_migration_fk_integration.py`（连真库时验证 FK 生效，无库则 skip）

**Interfaces:**
- Produces: 迁移 `005_strategy_scores_fk.sql`，约束名 `fk_strategy_scores_snapshot`。

- [ ] **Step 1: 写迁移文件断言（substring，沿用 test_db_sql 既有风格）** —— 追加到 `tests/test_db_sql.py`：

```python
def test_strategy_scores_fk_migration_adds_constraint():
    sql = Path("migrations/005_strategy_scores_fk.sql").read_text()
    assert "fk_strategy_scores_snapshot" in sql
    assert "REFERENCES ticker_signal_snapshots (id)" in sql
    assert "ON DELETE SET NULL" in sql
    # 必须先清理孤儿引用，避免加约束失败
    assert "UPDATE strategy_scores" in sql
    # 幂等守卫
    assert "pg_constraint" in sql
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_sql.py::test_strategy_scores_fk_migration_adds_constraint -q`
Expected: FAIL（迁移文件不存在）。

- [ ] **Step 3: 写迁移 `migrations/005_strategy_scores_fk.sql`：**

```sql
-- 005: add FK strategy_scores.source_snapshot_id -> ticker_signal_snapshots(id)

-- 1) null out orphaned references so the constraint can be added safely
UPDATE strategy_scores s
SET source_snapshot_id = NULL
WHERE s.source_snapshot_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM ticker_signal_snapshots t WHERE t.id = s.source_snapshot_id
  );

-- 2) add the FK only if it is not already present (idempotent re-run safe)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_strategy_scores_snapshot'
  ) THEN
    ALTER TABLE strategy_scores
      ADD CONSTRAINT fk_strategy_scores_snapshot
      FOREIGN KEY (source_snapshot_id)
      REFERENCES ticker_signal_snapshots (id)
      ON DELETE SET NULL;
  END IF;
END$$;
```

- [ ] **Step 4: 运行确认通过（substring 测试）**

Run: `python -m pytest tests/test_db_sql.py -q`
Expected: PASS

- [ ] **Step 5: 写真库集成测试（无库自动 skip）** —— `tests/test_migration_fk_integration.py`：

```python
import os
import pytest

DB_URL = os.environ.get("INVESTMENT_ASSISTANT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="no test database configured")


def test_fk_rejects_bogus_snapshot_id():
    import psycopg
    from investment_assistant.migrate import run
    run(DB_URL)  # 应用 001..005
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cur.execute(
                    "INSERT INTO strategy_scores (ticker, score_date, strategy, score, source_snapshot_id)"
                    " VALUES ('ZZZ', CURRENT_DATE, 'trend_relative_strength', 50, 999999999)"
                )
        conn.rollback()
```

- [ ] **Step 6: 运行确认 skip / pass**

Run: `python -m pytest tests/test_migration_fk_integration.py -q`
Expected: SKIPPED（本机无 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL`）；CI 配 Postgres 时 PASS。

- [ ] **Step 7: Commit**

```bash
git add migrations/005_strategy_scores_fk.sql tests/test_db_sql.py tests/test_migration_fk_integration.py
git commit -m "feat: add FK strategy_scores.source_snapshot_id -> ticker_signal_snapshots(id)"
```

### Task 3：连接池化 `db.connect()`

> 把每请求 `psycopg.connect` 换成进程级 `psycopg_pool.ConnectionPool`，`connect(url)` 返回 `pool.connection()` 上下文管理器，所有 `with connect(url) as conn:` 调用点透明受益。

**Files:**
- Modify: `investment_assistant/db.py:8-11`
- Modify: `requirements.txt`
- Create: `tests/test_db_pool.py`

**Interfaces:**
- Produces: `db.connect(database_url: str)` → 上下文管理器（`__enter__` 得 `psycopg.Connection`，`__exit__` 归还连接池）；`db._get_pool(url)`（进程级缓存，按 url 复用）；可选 env `INVESTMENT_ASSISTANT_DB_POOL_MAX`（默认 8）。
- 兼容：所有现有 `with connect(url) as conn: ... conn.commit()` 用法不变。

- [ ] **Step 1: 写连接池单测**（mock `psycopg_pool.ConnectionPool`）—— `tests/test_db_pool.py`：

```python
import sys
import types
from unittest.mock import MagicMock
import importlib


def _install_fake_pool(monkeypatch):
    created = []
    fake_module = types.ModuleType("psycopg_pool")
    class FakePool:
        def __init__(self, conninfo, **kw):
            self.conninfo = conninfo
            self.kw = kw
            created.append(self)
        def connection(self):
            return MagicMock(name="conn-ctx")
    fake_module.ConnectionPool = FakePool
    monkeypatch.setitem(sys.modules, "psycopg_pool", fake_module)
    return created


def test_connect_returns_pool_connection_context(monkeypatch):
    created = _install_fake_pool(monkeypatch)
    db = importlib.reload(importlib.import_module("investment_assistant.db"))
    db._reset_pools()  # 清缓存，避免跨用例污染
    ctx = db.connect("postgres://u/db1")
    assert ctx is not None
    assert len(created) == 1


def test_pool_is_cached_per_url(monkeypatch):
    created = _install_fake_pool(monkeypatch)
    db = importlib.reload(importlib.import_module("investment_assistant.db"))
    db._reset_pools()
    db.connect("postgres://u/db1")
    db.connect("postgres://u/db1")       # 同 url 复用
    db.connect("postgres://u/db2")       # 不同 url 新建
    assert len(created) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_db_pool.py -q`
Expected: FAIL（`connect` 仍是 `psycopg.connect`；无 `_get_pool`/`_reset_pools`）。

- [ ] **Step 3: 改 `investment_assistant/db.py`** —— 把顶部 `connect` 替换为池化实现（保留 `apply_migration`/`apply_pending_migrations` 等不动）：

```python
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_POOLS: dict[str, Any] = {}
_POOLS_LOCK = threading.Lock()


def _get_pool(database_url: str):
    with _POOLS_LOCK:
        pool = _POOLS.get(database_url)
        if pool is None:
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(
                database_url,
                min_size=1,
                max_size=int(os.environ.get("INVESTMENT_ASSISTANT_DB_POOL_MAX", "8")),
                open=True,
            )
            _POOLS[database_url] = pool
        return pool


def connect(database_url: str):
    """Return a pooled connection context manager.

    Usage is unchanged from the old per-call psycopg.connect:
        with connect(url) as conn:
            ...
    On exit the connection is returned to the process-wide pool instead of
    being closed.
    """
    return _get_pool(database_url).connection()


def _reset_pools() -> None:
    """Test helper: drop cached pools (closing them best-effort)."""
    with _POOLS_LOCK:
        for pool in _POOLS.values():
            try:
                pool.close()
            except Exception:
                pass
        _POOLS.clear()
```
（`import psycopg` 不再需要顶层导入；其余迁移/仓储函数保持不变。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_db_pool.py -q`
Expected: PASS

- [ ] **Step 5: 加依赖** —— `requirements.txt` 追加一行：

```
psycopg-pool>=3.2.0
```

- [ ] **Step 6: 全套件回归**（确认连接池替换未破坏既有无 DB 兜底）

Run: `python -m pytest -q`
Expected: PASS（无 `INVESTMENT_ASSISTANT_DATABASE_URL` 时 `connect` 不被调用；既有测试不受影响）。

- [ ] **Step 7: Commit**

```bash
git add investment_assistant/db.py requirements.txt tests/test_db_pool.py
git commit -m "feat: pool db connections via psycopg_pool (transparent to call sites)"
```

---

## Self-Review（对照 spec）

**1. Spec 覆盖（审计 §4「迁移」+ 执行计划 T6.1）：**
- 迁移可重复安全执行（版本化账本）：Task 1 接线已存在的 `apply_pending_migrations` 为 CLI + 切 install.sh。✅
- 补 `strategy_scores.source_snapshot_id → ticker_signal_snapshots(id)` 外键：Task 2（含孤儿清理 + 幂等守卫）。✅
- 引入连接池：Task 3（`psycopg_pool`，调用点零改动）。✅

**2. Placeholder 扫描：** 所有代码步骤给完整代码（migrate.py 全文、005 SQL 全文、db.py 池化全文、各测试全文）；无 TBD / “similar to”。

**3. 类型/命名一致性：** `apply_pending_migrations(conn, migrations_dir)`、`migrate.run(database_url, migrations_dir=None)`、`db.connect(url)` / `db._get_pool` / `db._reset_pools`、约束名 `fk_strategy_scores_snapshot` 全程一致。迁移编号 005 与后续 Phase 2 的 006+ 不冲突。

**风险/衔接：** ① 集成测试 `test_migration_fk_integration.py` 需 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL`，本机 skip、CI（T6.3）跑真库；② 连接池 `open=True` 要求构造时 DB 可达，与旧行为一致（install.sh 迁移步骤本就假设 DB 在线）。
