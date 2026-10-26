-- 024: data_fetch_runs：每次「某族被拉取一次」追加一行，记录成败与原因；只追加、不更新、不删除。
-- 只新增、可重跑；真实库执行需单独授权（`pg_dump` 备份 + `psql --single-transaction`）。

CREATE TABLE IF NOT EXISTS data_fetch_runs (
  id           BIGSERIAL PRIMARY KEY,
  family       TEXT NOT NULL CHECK (family IN ('bars', 'sec_filings', 'news', 'fred', 'universe')),
  job          TEXT NOT NULL,
  trigger      TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual_batch', 'manual_family')),
  run_id       TEXT,
  scope        TEXT NOT NULL CHECK (scope IN ('family', 'ticker')),
  ticker       TEXT CHECK ((scope = 'ticker') = (ticker IS NOT NULL)),
  session      DATE,
  status       TEXT NOT NULL CHECK (status IN ('success', 'partial', 'failed', 'skipped')),
  target_count INTEGER NOT NULL CHECK (target_count >= 0),
  ok_count     INTEGER NOT NULL CHECK (ok_count >= 0 AND ok_count <= target_count),
  failures     JSONB NOT NULL DEFAULT '[]',
  detail       JSONB NOT NULL DEFAULT '{}',
  started_at   TIMESTAMPTZ NOT NULL,
  finished_at  TIMESTAMPTZ NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_data_fetch_runs_family ON data_fetch_runs (family, created_at DESC);
