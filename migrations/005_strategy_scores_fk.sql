-- 005: add FK strategy_scores.source_snapshot_id -> ticker_signal_snapshots(id)

-- 1) null out orphaned references so the constraint can be added safely
UPDATE strategy_scores s
SET source_snapshot_id = NULL
WHERE s.source_snapshot_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM ticker_signal_snapshots t WHERE t.id = s.source_snapshot_id
  );

-- 2) add the FK only if it is not already present (idempotent re-run safe)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_strategy_scores_snapshot'
  ) THEN
    ALTER TABLE strategy_scores
      ADD CONSTRAINT fk_strategy_scores_snapshot
      FOREIGN KEY (source_snapshot_id)
      REFERENCES ticker_signal_snapshots (id)
      ON DELETE SET NULL;
  END IF;
END$$;
