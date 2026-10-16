-- Isolated A-share data; existing US watchlist/filing schemas remain intact.
CREATE TABLE IF NOT EXISTS cn_observations (
  id BIGSERIAL PRIMARY KEY,
  security_id TEXT NOT NULL,
  dataset TEXT NOT NULL,
  natural_key TEXT NOT NULL,
  revision TEXT NOT NULL,
  data_date DATE,
  disclosed_at TIMESTAMPTZ,
  source TEXT NOT NULL,
  source_url TEXT NOT NULL,
  payload JSONB NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (security_id, dataset, natural_key, revision)
);
CREATE INDEX IF NOT EXISTS cn_observations_lookup ON cn_observations
  (security_id, dataset, natural_key, first_seen_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS cn_collection_state (
  security_id TEXT NOT NULL,
  dataset TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ready', 'empty', 'failed', 'partial')),
  attempted_at TIMESTAMPTZ NOT NULL,
  succeeded_at TIMESTAMPTZ,
  requested_start DATE,
  requested_end DATE,
  row_count INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (security_id, dataset)
);

CREATE TABLE IF NOT EXISTS research_observation_cards (
  security_id TEXT PRIMARY KEY,
  version INTEGER NOT NULL DEFAULT 1,
  body JSONB NOT NULL,
  evidence_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research_observation_card_versions (
  security_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  body JSONB NOT NULL,
  saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, version)
);

-- Manual verification first; enabling uses the existing Settings/Jobs UI.
INSERT INTO scheduled_jobs (name, time_local, weekday_mask, timezone, enabled)
VALUES ('ashares', '18:30', '1-5', 'Asia/Shanghai', FALSE)
ON CONFLICT (name) DO NOTHING;
