-- 028: 每日工作流（v2.8 spec docs/specs/2026-10-29-v2.8-daily-workflow-design.md §10）。
-- stage_runs：job 增加 'daily'、stage 增加 'sec_monitor'、新增 attempt 列、唯一键改为 (run_id, stage, attempt)；
-- 新建 agent_connections、agent_connection_events、agent_attempt_resets；scheduled_jobs 三行合成 daily。
-- 真实库执行需单独授权（pg_dump 备份 + psql --single-transaction），且必须先于重启服务执行。

ALTER TABLE stage_runs ADD COLUMN IF NOT EXISTS attempt SMALLINT NOT NULL DEFAULT 1;
ALTER TABLE stage_runs DROP CONSTRAINT IF EXISTS stage_runs_attempt_check;
ALTER TABLE stage_runs ADD CONSTRAINT stage_runs_attempt_check CHECK (attempt >= 1);

DO $$
DECLARE
  cname text;
BEGIN
  FOR cname IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'stage_runs'::regclass AND contype = 'c'
      AND (pg_get_constraintdef(oid) ~ '\mjob\M' OR pg_get_constraintdef(oid) ~ '\mstage\M')
      AND pg_get_constraintdef(oid) !~ '\mattempt\M'
  LOOP
    EXECUTE format('ALTER TABLE stage_runs DROP CONSTRAINT %I', cname);
  END LOOP;
  FOR cname IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'stage_runs'::regclass AND contype = 'u'
      AND pg_get_constraintdef(oid) = 'UNIQUE (run_id, stage)'
  LOOP
    EXECUTE format('ALTER TABLE stage_runs DROP CONSTRAINT %I', cname);
  END LOOP;
END $$;
ALTER TABLE stage_runs DROP CONSTRAINT IF EXISTS stage_runs_job_check;
ALTER TABLE stage_runs ADD CONSTRAINT stage_runs_job_check CHECK (job IN ('workbench', 'daily'));
ALTER TABLE stage_runs DROP CONSTRAINT IF EXISTS stage_runs_stage_check;
ALTER TABLE stage_runs ADD CONSTRAINT stage_runs_stage_check
  CHECK (stage IN ('sec_monitor', 'collect', 'screen', 'regime', 'signals', 'plan', 'agent', 'review', 'push', 'retro'));
ALTER TABLE stage_runs DROP CONSTRAINT IF EXISTS stage_runs_run_stage_attempt_key;
ALTER TABLE stage_runs ADD CONSTRAINT stage_runs_run_stage_attempt_key UNIQUE (run_id, stage, attempt);

-- ---------------------------------------------------------------- agent_connections / agent_connection_events（§10.2）

CREATE TABLE IF NOT EXISTS agent_connections (
  id                  SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),     -- 单行：本机只有一个连接
  provider            TEXT NOT NULL DEFAULT 'chatgpt' CHECK (provider = 'chatgpt'),
  host_id             TEXT NOT NULL CHECK (host_id ~ '^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  client_id           TEXT CHECK (client_id IS NULL OR client_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  status              TEXT NOT NULL DEFAULT 'disconnected'
                        CHECK (status IN ('disconnected', 'pending', 'connected', 'needs_login')),
  subject             TEXT,
  email               TEXT,
  scopes              TEXT[] NOT NULL DEFAULT '{}',
  access_token        TEXT,
  access_expires_at   TIMESTAMPTZ,
  refresh_token       TEXT,
  refresh_expires_at  TIMESTAMPTZ,
  earliest_refresh_at TIMESTAMPTZ,
  model               TEXT CHECK (model IS NULL OR length(model) BETWEEN 1 AND 200),
  model_display_name  TEXT,
  connected_at        TIMESTAMPTZ,
  last_refresh_at     TIMESTAMPTZ,
  last_error          TEXT CHECK (last_error IS NULL OR length(last_error) <= 300),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (status <> 'connected' OR (client_id IS NOT NULL AND subject IS NOT NULL
                                   AND access_token IS NOT NULL AND refresh_token IS NOT NULL
                                   AND access_expires_at IS NOT NULL)),
  CHECK (status = 'connected' OR (access_token IS NULL AND refresh_token IS NULL))
);

CREATE TABLE IF NOT EXISTS agent_connection_events (
  id          BIGSERIAL PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('login_started', 'connected', 'login_failed', 'refreshed',
                                            'refresh_failed', 'disconnected', 'model_selected')),
  code        TEXT CHECK (code IS NULL OR code ~ '^[A-Za-z0-9_.:-]{1,100}$'),   -- 安全错误码，不含原文
  detail      JSONB NOT NULL DEFAULT '{}',        -- 只放 protocol 版本、到期时间、模型 slug；绝不放令牌
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_connection_events_created ON agent_connection_events (created_at DESC);

-- ---------------------------------------------------------------- agent_attempt_resets（§10.3）

CREATE TABLE IF NOT EXISTS agent_attempt_resets (
  id          BIGSERIAL PRIMARY KEY,
  ticker      TEXT NOT NULL,
  signal_date DATE NOT NULL,
  mode        TEXT NOT NULL CHECK (mode IN ('propose', 'interpret')),
  request_id  UUID NOT NULL UNIQUE,
  origin      TEXT NOT NULL CHECK (origin IN ('run_detail', 'plan_page', 'api')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_attempt_resets_unit ON agent_attempt_resets (ticker, signal_date, mode, created_at DESC);

-- ---------------------------------------------------------------- scheduled_jobs 与 job_reports（§10.4）

INSERT INTO scheduled_jobs (name, time_local, weekday_mask, timezone, enabled, next_run_at)
SELECT 'daily', '11:30', '2-6', 'Asia/Shanghai',
       COALESCE((SELECT enabled FROM scheduled_jobs WHERE name = 'workbench'), TRUE),
       (SELECT min(ts) FROM (
          SELECT (((now() AT TIME ZONE 'Asia/Shanghai')::date + d) + time '11:30') AT TIME ZONE 'Asia/Shanghai' AS ts
            FROM generate_series(0, 7) AS d) s
         WHERE ts > now() AND extract(isodow FROM ts AT TIME ZONE 'Asia/Shanghai') BETWEEN 2 AND 6)
ON CONFLICT (name) DO NOTHING;
DELETE FROM scheduled_jobs WHERE name IN ('workbench', 'workbench_review', 'filings');

CREATE INDEX IF NOT EXISTS idx_job_reports_run_id ON job_reports (run_id);
