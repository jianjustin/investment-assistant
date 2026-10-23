-- Trade plans, earnings dates, account snapshots, cash flows and monthly reviews
-- (P1 design 2026-10-23 §3). Additive only: new tables and one nullable column on
-- signal_decisions. Existing rows are never backfilled or rewritten.

-- Trade plans. Rule plans are unique per (ticker, signal_date, plan_version); a
-- re-run with the same levels returns the stored row, a different one is a conflict.
-- Own plans carry request_id/request_hash for idempotent re-submission.
CREATE TABLE IF NOT EXISTS trade_plans (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker             TEXT NOT NULL,
  signal_date        DATE NOT NULL,
  kind               TEXT NOT NULL CHECK (kind IN ('rule', 'own')),
  based_on_id        UUID REFERENCES trade_plans(id),
  plan_version       TEXT NOT NULL,
  ref_price          NUMERIC(18,6) NOT NULL,
  atr                NUMERIC(18,6) NOT NULL,
  entry_low          NUMERIC(18,6) NOT NULL,
  entry_high         NUMERIC(18,6) NOT NULL,
  stop               NUMERIC(18,6) NOT NULL,
  target1            NUMERIC(18,6) NOT NULL,
  trail_atr_multiple NUMERIC(18,6) NOT NULL DEFAULT 3 CHECK (trail_atr_multiple > 0),
  valid_from         DATE NOT NULL,
  valid_until        DATE NOT NULL,
  sizing             JSONB NOT NULL,
  status             TEXT NOT NULL CHECK (status IN ('ok', 'invalid')),
  invalid_reasons    TEXT[] NOT NULL DEFAULT '{}',
  warnings           TEXT[] NOT NULL DEFAULT '{}',
  inputs             JSONB NOT NULL,
  request_id         UUID,
  request_hash       TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (request_id),
  CHECK (stop < entry_low AND entry_low <= entry_high AND entry_high < target1),
  CHECK ((kind = 'own') = (request_id IS NOT NULL)),
  CHECK (request_id IS NULL OR request_hash IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_plans_rule_unique
  ON trade_plans (ticker, signal_date, plan_version) WHERE kind = 'rule';
CREATE INDEX IF NOT EXISTS idx_trade_plans_unit ON trade_plans (ticker, signal_date);

-- Next earnings date per ticker; a failed fetch writes no row, an unchanged
-- answer writes none either. known requires the date, unknown forbids it.
CREATE TABLE IF NOT EXISTS earnings_dates (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker        TEXT NOT NULL,
  earnings_date DATE,
  status        TEXT NOT NULL CHECK (status IN ('known', 'unknown')),
  source        TEXT NOT NULL DEFAULT 'yfinance',
  fetched_at    TIMESTAMPTZ NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((status = 'known') = (earnings_date IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_earnings_dates_ticker ON earnings_dates (ticker, fetched_at DESC);

-- Month-end broker equity. Corrections append a new row pointing at the one it
-- supersedes; reads only use rows nothing else supersedes.
CREATE TABLE IF NOT EXISTS account_snapshots (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id   UUID NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  as_of        DATE NOT NULL,
  equity       NUMERIC(18,6) NOT NULL CHECK (equity > 0),
  note         TEXT,
  recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  supersedes_id UUID REFERENCES account_snapshots(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_account_snapshots_asof ON account_snapshots (as_of DESC, recorded_at DESC);

-- Deposits (positive) and withdrawals (negative). Void-only, constraints as trades.
CREATE TABLE IF NOT EXISTS cash_flows (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id   UUID NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  flow_date    DATE NOT NULL,
  amount       NUMERIC(18,6) NOT NULL CHECK (amount <> 0),
  note         TEXT,
  recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  voided_at    TIMESTAMPTZ,
  void_reason  TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((voided_at IS NULL) = (void_reason IS NULL)),
  CHECK (void_reason IS NULL OR btrim(void_reason) <> '')
);
CREATE INDEX IF NOT EXISTS idx_cash_flows_date ON cash_flows (flow_date);

-- Monthly review snapshots, frozen at generation; corrections supersede.
CREATE TABLE IF NOT EXISTS monthly_reviews (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  month        DATE NOT NULL CHECK (EXTRACT(DAY FROM month) = 1),
  calc_version TEXT NOT NULL,
  stats        JSONB NOT NULL,
  notes        TEXT NOT NULL DEFAULT '',
  supersedes_id UUID REFERENCES monthly_reviews(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_monthly_reviews_month ON monthly_reviews (month DESC, created_at DESC);

-- The decision's confirmed plan, if any. Old rows stay NULL.
ALTER TABLE signal_decisions ADD COLUMN IF NOT EXISTS plan_id UUID REFERENCES trade_plans(id);
