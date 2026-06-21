CREATE TABLE IF NOT EXISTS strategy_scores (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  score_date DATE NOT NULL,
  strategy TEXT NOT NULL,
  score INTEGER NOT NULL CHECK (score >= 0 AND score <= 100),
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  limits JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_snapshot_id BIGINT,
  run_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ticker, score_date, strategy)
);
