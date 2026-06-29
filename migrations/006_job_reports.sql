CREATE TABLE IF NOT EXISTS job_reports (
  id          BIGSERIAL PRIMARY KEY,
  task        TEXT NOT NULL,
  run_id      TEXT NOT NULL,
  status      TEXT NOT NULL,
  started_at  TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_reports_task_created
  ON job_reports (task, created_at DESC);
