-- Metadata stays nullable: existing observations must remain unverifiable.
-- This migration adds no data, inferred dates, or calculation-version defaults.
ALTER TABLE ticker_signal_snapshots ADD COLUMN IF NOT EXISTS price_date DATE;
ALTER TABLE ticker_signal_snapshots ADD COLUMN IF NOT EXISTS calculation_version TEXT;
ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS calculation_version TEXT;
