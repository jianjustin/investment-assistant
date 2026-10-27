-- 025: stage_runs：每次 workbench 任务、每个阶段追加一行证据（计数、原因、产出引用、耗时）；
-- 只追加、不更新、不删除。表结构逐列对应 docs/specs/2026-10-27-v2.4-derivation-and-workflow-design.md §5.1。
-- 只新增、可重跑；真实库执行需单独授权（`pg_dump` 备份 + `psql --single-transaction`）。

CREATE TABLE IF NOT EXISTS stage_runs (
  id             BIGSERIAL PRIMARY KEY,
  run_id         TEXT NOT NULL,
  job            TEXT NOT NULL CHECK (job = 'workbench'),
  trigger        TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual_batch')),
  session        DATE,
  stage          TEXT NOT NULL CHECK (stage IN ('collect', 'screen', 'regime', 'signals', 'plan', 'agent', 'push')),
  stages_version TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('success', 'partial', 'degraded', 'failed', 'skipped')),
  reason         TEXT CHECK (status NOT IN ('skipped', 'failed') OR reason IS NOT NULL),
  input_count    INTEGER NOT NULL CHECK (input_count >= 0),
  output_count   INTEGER NOT NULL CHECK (output_count >= 0),
  skips          JSONB NOT NULL DEFAULT '[]',
  failures       JSONB NOT NULL DEFAULT '[]',
  degradations   JSONB NOT NULL DEFAULT '[]',
  outputs        JSONB NOT NULL DEFAULT '{}',
  detail         JSONB NOT NULL DEFAULT '{}',
  started_at     TIMESTAMPTZ NOT NULL,
  finished_at    TIMESTAMPTZ NOT NULL CHECK (finished_at >= started_at),
  duration_ms    INTEGER NOT NULL CHECK (duration_ms >= 0),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- 每次运行每阶段一行，同时充当按 run_id 查询的索引
  UNIQUE (run_id, stage)
);
CREATE INDEX IF NOT EXISTS idx_stage_runs_session ON stage_runs (session, stage);
