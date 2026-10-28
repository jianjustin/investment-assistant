-- 027: 我的成长闭环（v2.7 spec docs/specs/2026-10-28-v2.7-growth-loop-design.md §11）。
-- 新建十一张只追加的表；放宽 agent_runs.mode（retro / discuss）、agent_tool_calls.phase
-- （retro / discuss）、stage_runs.stage（retro）。不改任何旧行、不加种子行；全部可重跑。
-- 真实库执行需单独授权（pg_dump 备份 + psql --single-transaction），且必须先于重启服务执行。

-- ---------------------------------------------------------------- 放宽旧约束
-- 约束名查不到时按定义找出只涉及该列的 CHECK 删掉（同 026 的做法），再加具名约束。
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
  CHECK (mode IN ('propose', 'interpret', 'review', 'revise', 'retro', 'discuss'));
-- agent_runs_mode_plan_check、agent_runs_interpret_no_pass_check 不变：retro / discuss
-- 不在 ('propose','revise') 里，所以 ok 时没有计划、也不能 pass。

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
  CHECK (phase IN ('propose', 'counter', 'review', 'retro', 'discuss'));

-- \mstage\M 不会匹配 stages_version。
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
  CHECK (stage IN ('collect', 'screen', 'regime', 'signals', 'plan', 'agent', 'review', 'retro', 'push'));

-- ---------------------------------------------------------------- 复盘卡（§4）
CREATE TABLE IF NOT EXISTS review_cards (
  id             BIGSERIAL PRIMARY KEY,
  event_key      TEXT NOT NULL UNIQUE,
  subject        TEXT NOT NULL CHECK (subject IN ('unit', 'trade')),
  ticker         TEXT NOT NULL,
  signal_date    DATE,
  buy_trade_id   UUID REFERENCES trades(id),
  end_kind       TEXT NOT NULL CHECK (end_kind IN ('position_closed', 'stop', 'target', 'expired', 'invalidated')),
  end_session    DATE NOT NULL,
  retro_version  TEXT NOT NULL,
  facts          JSONB NOT NULL,
  detected_run_id TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK ((subject = 'unit') = (signal_date IS NOT NULL)),
  CHECK ((subject = 'trade') = (buy_trade_id IS NOT NULL)),
  CHECK (subject = 'unit' OR end_kind = 'position_closed')
);
CREATE INDEX IF NOT EXISTS idx_review_cards_end ON review_cards (end_session DESC);
CREATE INDEX IF NOT EXISTS idx_review_cards_unit ON review_cards (ticker, signal_date);

CREATE TABLE IF NOT EXISTS review_card_drafts (
  id            BIGSERIAL PRIMARY KEY,
  card_id       BIGINT NOT NULL REFERENCES review_cards(id),
  attempt       INT NOT NULL CHECK (attempt >= 1),
  trigger       TEXT NOT NULL CHECK (trigger IN ('batch', 'manual')),
  agent_run_id  UUID REFERENCES agent_runs(id),
  status        TEXT NOT NULL CHECK (status IN ('ok', 'rejected', 'error', 'skipped')),
  reason        TEXT,
  output        JSONB,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (status = 'ok' OR reason IS NOT NULL),
  CHECK ((status = 'ok') = (output IS NOT NULL)),
  CHECK (status = 'skipped' OR agent_run_id IS NOT NULL),
  UNIQUE (card_id, attempt)
);
-- 每张卡至多一份成功的草稿
CREATE UNIQUE INDEX IF NOT EXISTS idx_review_card_drafts_one_ok
  ON review_card_drafts (card_id) WHERE status = 'ok';

-- ---------------------------------------------------------------- 讨论（§8）
CREATE TABLE IF NOT EXISTS discussions (
  id            BIGSERIAL PRIMARY KEY,
  request_id    UUID NOT NULL UNIQUE,
  request_hash  TEXT NOT NULL,
  context_kind  TEXT NOT NULL CHECK (context_kind IN ('plan', 'card')),
  ticker        TEXT NOT NULL,
  signal_date   DATE NOT NULL,
  plan_id       UUID REFERENCES trade_plans(id),
  card_id       BIGINT REFERENCES review_cards(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK ((context_kind = 'plan') = (plan_id IS NOT NULL)),
  CHECK ((context_kind = 'card') = (card_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_discussions_plan ON discussions (plan_id);
CREATE INDEX IF NOT EXISTS idx_discussions_card ON discussions (card_id);

-- ---------------------------------------------------------------- 我的知识（§5）
CREATE TABLE IF NOT EXISTS knowledge_items (
  id              BIGSERIAL PRIMARY KEY,
  origin          TEXT NOT NULL CHECK (origin IN ('manual', 'review_card', 'discussion')),
  source_card_id  BIGINT REFERENCES review_cards(id),
  source_discussion_id BIGINT REFERENCES discussions(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK ((origin = 'review_card') = (source_card_id IS NOT NULL)),
  CHECK ((origin = 'discussion') = (source_discussion_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS discussion_turns (
  id              BIGSERIAL PRIMARY KEY,
  discussion_id   BIGINT NOT NULL REFERENCES discussions(id),
  seq             INT NOT NULL CHECK (seq >= 1),
  role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  request_id      UUID UNIQUE,
  request_hash    TEXT,
  body            TEXT NOT NULL,
  attachment      JSONB,
  run_id          TEXT,
  reply_to        BIGINT UNIQUE REFERENCES discussion_turns(id),
  status          TEXT CHECK (status IN ('ok', 'rejected', 'error', 'skipped')),
  reason          TEXT,
  refs            JSONB NOT NULL DEFAULT '[]',
  detail          JSONB NOT NULL DEFAULT '{}',
  agent_run_id    UUID REFERENCES agent_runs(id),
  cutoff_at       TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (discussion_id, seq),
  CHECK ((role = 'user') = (request_id IS NOT NULL)),
  CHECK ((role = 'user') = (reply_to IS NULL)),
  CHECK ((role = 'assistant') = (status IS NOT NULL)),
  CHECK ((role = 'assistant') = (cutoff_at IS NOT NULL)),
  CHECK (role = 'assistant' OR char_length(btrim(body)) BETWEEN 1 AND 4000),
  CHECK (status IS NULL OR status = 'ok' OR reason IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS knowledge_drafts (
  id                  BIGSERIAL PRIMARY KEY,
  origin              TEXT NOT NULL CHECK (origin IN ('review_card', 'discussion')),
  card_draft_id       BIGINT REFERENCES review_card_drafts(id),
  lesson_index        INT CHECK (lesson_index BETWEEN 0 AND 2),
  discussion_turn_id  BIGINT REFERENCES discussion_turns(id),
  target_knowledge_id BIGINT REFERENCES knowledge_items(id),
  target_version      INT,
  title               TEXT NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 60),
  body                TEXT NOT NULL CHECK (char_length(btrim(body)) BETWEEN 1 AND 4000),
  scope               TEXT NOT NULL CHECK (char_length(btrim(scope)) BETWEEN 1 AND 500),
  counter_examples    TEXT NOT NULL CHECK (char_length(btrim(counter_examples)) BETWEEN 1 AND 1000),
  concepts            TEXT[] NOT NULL DEFAULT '{}',
  tickers             TEXT[] NOT NULL DEFAULT '{}',
  refs                JSONB NOT NULL DEFAULT '[]',
  created_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK ((origin = 'review_card') = (card_draft_id IS NOT NULL AND lesson_index IS NOT NULL)),
  CHECK ((origin = 'discussion') = (discussion_turn_id IS NOT NULL)),
  CHECK (origin = 'discussion' OR target_knowledge_id IS NULL),
  CHECK ((target_knowledge_id IS NULL) = (target_version IS NULL)),
  CHECK (cardinality(concepts) + cardinality(tickers) BETWEEN 1 AND 10),
  UNIQUE (card_draft_id, lesson_index),
  UNIQUE (discussion_turn_id)
);

CREATE TABLE IF NOT EXISTS knowledge_versions (
  id               BIGSERIAL PRIMARY KEY,
  knowledge_id     BIGINT NOT NULL REFERENCES knowledge_items(id),
  version          INT NOT NULL CHECK (version >= 1),
  supersedes_id    BIGINT UNIQUE REFERENCES knowledge_versions(id),
  request_id       UUID NOT NULL UNIQUE,
  request_hash     TEXT NOT NULL,
  draft_id         BIGINT UNIQUE REFERENCES knowledge_drafts(id),
  title            TEXT NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 60),
  body             TEXT NOT NULL CHECK (char_length(btrim(body)) BETWEEN 1 AND 4000),
  scope            TEXT NOT NULL CHECK (char_length(btrim(scope)) BETWEEN 1 AND 500),
  counter_examples TEXT NOT NULL DEFAULT '' CHECK (char_length(counter_examples) <= 1000),
  concepts         TEXT[] NOT NULL DEFAULT '{}',
  tickers          TEXT[] NOT NULL DEFAULT '{}',
  schema_version   TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (knowledge_id, version),
  CHECK ((version = 1) = (supersedes_id IS NULL)),
  CHECK (cardinality(concepts) + cardinality(tickers) BETWEEN 1 AND 10)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_versions_created ON knowledge_versions (created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_versions_tickers ON knowledge_versions USING GIN (tickers);
CREATE INDEX IF NOT EXISTS idx_knowledge_versions_concepts ON knowledge_versions USING GIN (concepts);

CREATE TABLE IF NOT EXISTS knowledge_status (
  id            BIGSERIAL PRIMARY KEY,
  knowledge_id  BIGINT NOT NULL REFERENCES knowledge_items(id),
  status        TEXT NOT NULL CHECK (status IN ('archived', 'active')),
  reason        TEXT NOT NULL DEFAULT '' CHECK (char_length(reason) <= 300),
  request_id    UUID NOT NULL UNIQUE,
  request_hash  TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_status_item ON knowledge_status (knowledge_id, created_at);

CREATE TABLE IF NOT EXISTS knowledge_draft_verdicts (
  id                   BIGSERIAL PRIMARY KEY,
  draft_id             BIGINT NOT NULL UNIQUE REFERENCES knowledge_drafts(id),
  action               TEXT NOT NULL CHECK (action IN ('approve', 'dismiss')),
  knowledge_version_id BIGINT UNIQUE REFERENCES knowledge_versions(id),
  request_id           UUID NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK ((action = 'approve') = (knowledge_version_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS review_card_verdicts (
  id            BIGSERIAL PRIMARY KEY,
  card_id       BIGINT NOT NULL UNIQUE REFERENCES review_cards(id),
  request_id    UUID NOT NULL UNIQUE,
  request_hash  TEXT NOT NULL,
  draft_id      BIGINT REFERENCES review_card_drafts(id),
  note          TEXT NOT NULL DEFAULT '' CHECK (char_length(note) <= 2000),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- ---------------------------------------------------------------- 引用记录（§6.2）
CREATE TABLE IF NOT EXISTS knowledge_citations (
  id            BIGSERIAL PRIMARY KEY,
  agent_run_id  UUID NOT NULL REFERENCES agent_runs(id),
  plan_id       UUID REFERENCES trade_plans(id),
  review_id     BIGINT REFERENCES plan_reviews(id),
  knowledge_id  BIGINT NOT NULL,
  version       INT NOT NULL,
  field         TEXT NOT NULL CHECK (field IN ('thesis', 'invalidation', 'changes', 'counter', 'risks', 'review')),
  call_seq      INT NOT NULL CHECK (call_seq >= 1),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY (knowledge_id, version) REFERENCES knowledge_versions(knowledge_id, version),
  CHECK (plan_id IS NULL OR review_id IS NULL),
  UNIQUE (agent_run_id, knowledge_id, version, field)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_citations_item ON knowledge_citations (knowledge_id, version);
CREATE INDEX IF NOT EXISTS idx_knowledge_citations_plan ON knowledge_citations (plan_id);
