CREATE TABLE IF NOT EXISTS ticker_signal_snapshots (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  signal_date DATE NOT NULL,
  close NUMERIC(18,6),
  ma20 NUMERIC(18,6),
  ma50 NUMERIC(18,6),
  ma200 NUMERIC(18,6),
  volume BIGINT,
  volume_ratio NUMERIC(18,6),
  relative_strength_spy NUMERIC(18,6),
  relative_strength_qqq NUMERIC(18,6),
  trend_state TEXT NOT NULL CHECK (trend_state IN ('uptrend', 'base', 'downtrend', 'volatile', 'unknown')),
  attention_level TEXT NOT NULL CHECK (attention_level IN ('high', 'medium', 'low')),
  trigger_reason JSONB NOT NULL DEFAULT '[]'::jsonb,
  source TEXT NOT NULL DEFAULT 'yfinance',
  error TEXT,
  run_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ticker, signal_date)
);

CREATE INDEX IF NOT EXISTS idx_ticker_signal_snapshots_date
  ON ticker_signal_snapshots (signal_date DESC, attention_level, ticker);
