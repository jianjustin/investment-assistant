-- Review expansion: agent run modes, brief-to-run links and review push
-- records (P4 design 2026-10-25 §3). Additive except replacing agent_runs'
-- ok/plan CHECK with a mode-aware one: an interpret run is 'ok' without a
-- plan. Existing rows keep their semantics (mode defaults to 'propose').
-- No updates, deletes or backfills to existing rows. Runs on the real
-- database separately, with a pg_dump backup, like 019.

-- Runs either propose a plan or interpret a unit; existing rows read as
-- 'propose'. A new partial-aware index serves per-mode lookups.
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'propose'
  CHECK (mode IN ('propose','interpret'));

-- Replace the old anonymous ok/plan CHECK (definition matched by text, so
-- the unnamed constraint is dropped no matter how PG printed it).
DO $$
DECLARE
  cname text;
BEGIN
  FOR cname IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'agent_runs'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%plan_id IS NOT NULL%'
      AND pg_get_constraintdef(oid) NOT LIKE '%mode%'
  LOOP
    EXECUTE format('ALTER TABLE agent_runs DROP CONSTRAINT %I', cname);
  END LOOP;
END $$;
ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_mode_plan_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_mode_plan_check
  CHECK ((mode = 'propose' AND status = 'ok') = (plan_id IS NOT NULL));
ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_interpret_no_pass_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_interpret_no_pass_check
  CHECK (mode = 'propose' OR status <> 'pass');
CREATE INDEX IF NOT EXISTS idx_agent_runs_unit_mode
  ON agent_runs (ticker, signal_date, mode, created_at DESC);

-- Briefs written from P4 on point at the agent run that produced them;
-- older Codex briefs keep a null link.
ALTER TABLE signal_briefs ADD COLUMN IF NOT EXISTS agent_run_id UUID REFERENCES agent_runs(id);

-- One row per review push attempt, successful or not; a period can be
-- re-pushed manually any number of times. reason is redacted before insert.
CREATE TABLE IF NOT EXISTS review_pushes (
  id             BIGSERIAL PRIMARY KEY,
  kind           TEXT NOT NULL CHECK (kind IN ('weekly','monthly','monthly_reminder')),
  period         DATE NOT NULL,
  review_id      UUID,
  trigger_source TEXT NOT NULL CHECK (trigger_source IN ('scheduled','manual')),
  sent           BOOLEAN NOT NULL,
  messages       INT NOT NULL DEFAULT 0,
  reason         TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (sent OR reason IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_review_pushes_kind_period
  ON review_pushes (kind, period, created_at DESC);

-- The review task itself ships disabled; acceptance turns it on.
INSERT INTO scheduled_jobs (name, time_local, weekday_mask, timezone, enabled)
VALUES ('workbench_review', '08:00', '1-7', 'Asia/Shanghai', FALSE)
ON CONFLICT (name) DO NOTHING;
