-- Pool tiers, FRED macro observations, daily market regime snapshots and rule
-- backcheck records (P2 design 2026-10-23 §3). Additive only: four new tables,
-- no updates, deletes, alters or backfills to existing tables.

-- Append-only tier history. A batch appends a row only when (tier, sector_etf)
-- differs from the ticker's latest row; reads reconstruct the tier as of a day
-- and cutoff time.
CREATE TABLE IF NOT EXISTS pool_tiers (
  id                BIGSERIAL PRIMARY KEY,
  ticker            TEXT NOT NULL,
  tier              TEXT NOT NULL CHECK (tier IN ('core', 'extended', 'removed')),
  sector_etf        TEXT,
  effective_session DATE NOT NULL,
  recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pool_tiers_ticker ON pool_tiers (ticker, effective_session DESC, recorded_at DESC);

-- FRED observations. A revision (same series and date, different value) appends
-- a new row; reads take the newest fetched_at at or before the cutoff.
CREATE TABLE IF NOT EXISTS macro_observations (
  id         BIGSERIAL PRIMARY KEY,
  series_id  TEXT NOT NULL,
  obs_date   DATE NOT NULL,
  value      NUMERIC(18,6) NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_macro_observations_series
  ON macro_observations (series_id, obs_date DESC, fetched_at DESC);

-- One market context snapshot per session and calc_version. A re-run with the
-- same content returns the stored row; a different one is a conflict, never an
-- overwrite.
CREATE TABLE IF NOT EXISTS market_regimes (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session      DATE NOT NULL,
  calc_version TEXT NOT NULL,
  label        TEXT NOT NULL CHECK (label IN ('risk_on', 'neutral', 'risk_off', 'insufficient')),
  breadth      JSONB NOT NULL,
  sectors      JSONB NOT NULL,
  macro        JSONB NOT NULL,
  inputs       JSONB NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session, calc_version)
);

-- Frozen results of the manual pre-launch rule backcheck.
CREATE TABLE IF NOT EXISTS rule_backchecks (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  calc_version TEXT NOT NULL,
  params       JSONB NOT NULL,
  stats        JSONB NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
