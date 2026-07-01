CREATE TABLE IF NOT EXISTS event_studies (
  id           BIGSERIAL PRIMARY KEY,
  kind         TEXT NOT NULL,
  params_hash  TEXT NOT NULL,
  result       JSONB NOT NULL DEFAULT '{}'::jsonb,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, params_hash)
);

CREATE INDEX IF NOT EXISTS idx_event_studies_kind
  ON event_studies (kind, generated_at DESC);
