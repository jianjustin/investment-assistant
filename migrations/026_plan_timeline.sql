-- 026: 计划时间线（v2.5 spec docs/specs/2026-10-28-v2.5-plan-timeline-design.md §6）。
-- 新建三张只追加的表 agent_plan_versions、plan_reviews、user_inputs，并放宽四处旧约束：
-- agent_runs.mode 增加 review / revise、agent_tool_calls.phase 增加 review、stage_runs.stage
-- 增加 review、trade_plans 的 Agent 唯一索引只管 agent-1；signal_decisions 增加两列可空列。
-- 不改任何旧行、不加种子行；全部可重跑。真实库执行需单独授权（pg_dump 备份 +
-- psql --single-transaction），且必须先于重启服务执行（spec D19）。

-- ---------------------------------------------------------------- agent_runs（§6.4）
-- 020 内联的 mode CHECK 名字由 PG 生成：按定义找出只涉及 mode 的 CHECK 删掉，再加具名约束。
DO $$
DECLARE
  cname text;
BEGIN
  FOR cname IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'agent_runs'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) ~ '\mmode\M'
      AND pg_get_constraintdef(oid) !~ '\mplan_id\M'
      AND pg_get_constraintdef(oid) !~ '\mstatus\M'
  LOOP
    EXECUTE format('ALTER TABLE agent_runs DROP CONSTRAINT %I', cname);
  END LOOP;
END $$;
ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_mode_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_mode_check
  CHECK (mode IN ('propose', 'interpret', 'review', 'revise'));
-- 修订运行与首版一样，ok 时必有计划；复查调用与解读一样，ok 时没有计划、也不会 pass。
ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_mode_plan_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_mode_plan_check
  CHECK ((mode IN ('propose', 'revise') AND status = 'ok') = (plan_id IS NOT NULL));
ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_interpret_no_pass_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_interpret_no_pass_check
  CHECK (mode IN ('propose', 'revise') OR status <> 'pass');

-- ---------------------------------------------------------------- agent_tool_calls（§6.4）
DO $$
DECLARE
  cname text;
BEGIN
  FOR cname IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'agent_tool_calls'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) ~ '\mphase\M'
  LOOP
    EXECUTE format('ALTER TABLE agent_tool_calls DROP CONSTRAINT %I', cname);
  END LOOP;
END $$;
ALTER TABLE agent_tool_calls DROP CONSTRAINT IF EXISTS agent_tool_calls_phase_check;
ALTER TABLE agent_tool_calls ADD CONSTRAINT agent_tool_calls_phase_check
  CHECK (phase IN ('propose', 'counter', 'review'));

-- ---------------------------------------------------------------- stage_runs（§6.4）
-- \mstage\M 不会匹配 stages_version（后面紧跟单词字符）。
DO $$
DECLARE
  cname text;
BEGIN
  FOR cname IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'stage_runs'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) ~ '\mstage\M'
  LOOP
    EXECUTE format('ALTER TABLE stage_runs DROP CONSTRAINT %I', cname);
  END LOOP;
END $$;
ALTER TABLE stage_runs DROP CONSTRAINT IF EXISTS stage_runs_stage_check;
ALTER TABLE stage_runs ADD CONSTRAINT stage_runs_stage_check
  CHECK (stage IN ('collect', 'screen', 'regime', 'signals', 'plan', 'agent', 'review', 'push'));

-- ---------------------------------------------------------------- trade_plans（§6.4）
-- agent-2 的一个单元有多版计划，唯一性改由 agent_plan_versions 保证；agent-1 照旧每单元一行。
DROP INDEX IF EXISTS idx_trade_plans_agent_unique;
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_plans_agent_unique
  ON trade_plans (ticker, signal_date, plan_version) WHERE kind = 'agent' AND plan_version = 'agent-1';

-- ---------------------------------------------------------------- signal_decisions（§6.4）
-- 旧行为空；review_view = {layout, baseline_expanded, agent_version_no}。
ALTER TABLE signal_decisions ADD COLUMN IF NOT EXISTS agent_plan_id UUID REFERENCES trade_plans(id);
ALTER TABLE signal_decisions ADD COLUMN IF NOT EXISTS review_view JSONB;

-- ---------------------------------------------------------------- agent_plan_versions（§6.1）
-- 一个单元（ticker, signal_date）的 agent-2 版本链，version_no 从 0 连续编号；只追加。
CREATE TABLE IF NOT EXISTS agent_plan_versions (
  plan_id            UUID PRIMARY KEY REFERENCES trade_plans(id),
  ticker             TEXT NOT NULL,
  signal_date        DATE NOT NULL,
  version_no         INT NOT NULL CHECK (version_no >= 0),
  supersedes_plan_id UUID REFERENCES agent_plan_versions(plan_id),
  origin             TEXT NOT NULL CHECK (origin IN ('signal', 'review', 'recheck')),
  agent_run_id       UUID NOT NULL REFERENCES agent_runs(id),
  cutoff_at          TIMESTAMPTZ NOT NULL,
  as_of_session      DATE NOT NULL,
  diff               JSONB,
  schema_version     TEXT NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK ((version_no = 0) = (supersedes_plan_id IS NULL)),
  CHECK ((version_no = 0) = (origin = 'signal')),
  CHECK ((version_no = 0) = (diff IS NULL)),
  UNIQUE (ticker, signal_date, version_no),
  UNIQUE (supersedes_plan_id),
  UNIQUE (agent_run_id)
);

-- ---------------------------------------------------------------- plan_reviews（§6.2）
-- 每次复查一行（含 skipped / error）；只追加。
CREATE TABLE IF NOT EXISTS plan_reviews (
  id                    BIGSERIAL PRIMARY KEY,
  ticker                TEXT NOT NULL,
  signal_date           DATE NOT NULL,
  head_plan_id          UUID NOT NULL REFERENCES agent_plan_versions(plan_id),
  session               DATE NOT NULL,
  trigger               TEXT NOT NULL CHECK (trigger IN ('batch', 'recheck')),
  run_id                TEXT,
  mode                  TEXT NOT NULL CHECK (mode IN ('entry', 'holding')),
  timeline_version      TEXT NOT NULL,
  signals               JSONB NOT NULL DEFAULT '[]',
  conditions            JSONB NOT NULL DEFAULT '[]',
  user_input_ids        BIGINT[] NOT NULL DEFAULT '{}',
  outcome               TEXT NOT NULL CHECK (outcome IN ('maintain', 'revise', 'invalidate', 'skipped', 'error')),
  decided_by            TEXT NOT NULL CHECK (decided_by IN ('agent', 'host')),
  reason                TEXT NOT NULL CHECK (btrim(reason) <> ''),
  refs                  JSONB NOT NULL DEFAULT '[]',
  review_agent_run_id   UUID REFERENCES agent_runs(id),
  revision_agent_run_id UUID REFERENCES agent_runs(id),
  new_plan_id           UUID REFERENCES agent_plan_versions(plan_id),
  detail                JSONB NOT NULL DEFAULT '{}',
  attempt               INT NOT NULL CHECK (attempt >= 1),
  cutoff_at             TIMESTAMPTZ NOT NULL,
  input_tokens          INT NOT NULL DEFAULT 0,
  output_tokens         INT NOT NULL DEFAULT 0,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (new_plan_id IS NULL OR outcome = 'revise'),
  CHECK (decided_by = 'host' OR review_agent_run_id IS NOT NULL)
);
-- 每条链每个交易日至多一条有效批处理复查；skipped / error 与重新复查不受限。
CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_reviews_one_batch
  ON plan_reviews (ticker, signal_date, session)
  WHERE trigger = 'batch' AND outcome IN ('maintain', 'revise', 'invalidate');
CREATE INDEX IF NOT EXISTS idx_plan_reviews_session ON plan_reviews (session);
CREATE INDEX IF NOT EXISTS idx_plan_reviews_chain ON plan_reviews (ticker, signal_date, created_at);

-- ---------------------------------------------------------------- user_inputs（§6.3）
-- 用户补充的研报要点、新闻、判断；更正与撤回都是新行（supersedes_id），只追加。
-- signal_date 为空 = 属于该标的的所有链。
CREATE TABLE IF NOT EXISTS user_inputs (
  id            BIGSERIAL PRIMARY KEY,
  request_id    UUID NOT NULL UNIQUE,
  request_hash  TEXT NOT NULL,
  ticker        TEXT NOT NULL,
  signal_date   DATE,
  kind          TEXT NOT NULL CHECK (kind IN ('research', 'news', 'judgment', 'other', 'retract')),
  body          TEXT NOT NULL CHECK (char_length(btrim(body)) BETWEEN 1 AND 4000),
  source_url    TEXT,
  supersedes_id BIGINT REFERENCES user_inputs(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (kind <> 'retract' OR supersedes_id IS NOT NULL)
);
