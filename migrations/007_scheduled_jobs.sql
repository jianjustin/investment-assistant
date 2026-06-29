CREATE TABLE IF NOT EXISTS scheduled_jobs (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  time_local   TEXT NOT NULL,
  weekday_mask TEXT NOT NULL DEFAULT '1-5',
  timezone     TEXT NOT NULL DEFAULT 'America/New_York',
  enabled      BOOLEAN NOT NULL DEFAULT TRUE,
  next_run_at  TIMESTAMPTZ,
  last_run_at  TIMESTAMPTZ,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO scheduled_jobs (name, time_local, weekday_mask, timezone) VALUES
  ('metrics', '08:00', '1-5', 'America/New_York'),
  ('filings', '09:00', '1-5', 'America/New_York'),
  ('scores',  '18:00', '1-5', 'America/New_York')
ON CONFLICT (name) DO NOTHING;
