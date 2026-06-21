CREATE TABLE IF NOT EXISTS market_signals (
  id BIGSERIAL PRIMARY KEY,
  signal_date DATE NOT NULL UNIQUE,
  market_status TEXT NOT NULL CHECK (market_status IN ('green', 'yellow', 'red')),
  spy_ticker TEXT NOT NULL DEFAULT 'SPY',
  spy_close NUMERIC(18,6) NOT NULL,
  spy_ma200 NUMERIC(18,6) NOT NULL,
  spy_above_200ma BOOLEAN NOT NULL,
  vix_ticker TEXT NOT NULL DEFAULT '^VIX',
  vix_close NUMERIC(18,6) NOT NULL,
  source TEXT NOT NULL DEFAULT 'yfinance',
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  run_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_market_signals_signal_date
  ON market_signals (signal_date DESC);
