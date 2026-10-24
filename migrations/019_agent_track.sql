-- Agent track: agent runs and their recorded tool calls per decision unit
-- (P3 design 2026-10-24 §3). Additive except widening trade_plans.kind: the
-- kind CHECK gains 'agent' and a partial unique index pins one agent plan per
-- unit. No updates, deletes or backfills to existing rows.

-- The only change to an existing table: widen trade_plans.kind and pin agent
-- plan uniqueness. Runs once on the real database, separately authorized.
ALTER TABLE trade_plans DROP CONSTRAINT IF EXISTS trade_plans_kind_check;
ALTER TABLE trade_plans ADD CONSTRAINT trade_plans_kind_check CHECK (kind IN ('rule','own','agent'));
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_plans_agent_unique
  ON trade_plans (ticker, signal_date, plan_version) WHERE kind = 'agent';

-- One row per agent run of a unit (attempt from 1); append-only. plan_id is
-- set exactly when status is 'ok'; every other status carries a reason.
CREATE TABLE IF NOT EXISTS agent_runs (
  id            UUID PRIMARY KEY,
  ticker        TEXT NOT NULL,
  signal_date   DATE NOT NULL,
  pool          TEXT NOT NULL CHECK (pool IN ('main','extended')),
  attempt       INT NOT NULL CHECK (attempt >= 1),
  agent_version TEXT NOT NULL,
  provider      TEXT NOT NULL,
  model         TEXT NOT NULL,
  cutoff_at     TIMESTAMPTZ NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('ok','pass','rejected','error','skipped')),
  reason        TEXT,
  output        JSONB,
  counter       JSONB,
  plan_id       UUID REFERENCES trade_plans(id),
  input_tokens  INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  started_at    TIMESTAMPTZ NOT NULL,
  finished_at   TIMESTAMPTZ NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK ((status = 'ok') = (plan_id IS NOT NULL)),
  CHECK (status IN ('ok','pass') OR reason IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_unit ON agent_runs (ticker, signal_date, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_started ON agent_runs (started_at);

-- Recorded tool calls: arguments, result envelope and its canonical hash —
-- the proof behind every ref the model cites. seq is the citation number
-- within the run, shared by both phases; append-only.
CREATE TABLE IF NOT EXISTS agent_tool_calls (
  id             BIGSERIAL PRIMARY KEY,
  run_id         UUID NOT NULL REFERENCES agent_runs(id),
  seq            INT NOT NULL CHECK (seq >= 1),
  phase          TEXT NOT NULL CHECK (phase IN ('propose','counter')),
  tool           TEXT NOT NULL,
  args           JSONB NOT NULL,
  result         JSONB NOT NULL,
  result_sha256  TEXT NOT NULL CHECK (length(result_sha256) = 64),
  called_at      TIMESTAMPTZ NOT NULL,
  UNIQUE (run_id, seq)
);
