-- 023: 每日筛选（screen_runs / screen_results / pool_tiers.source）与任务时区统一北京时间。
-- 全部只追加、可重跑（IF NOT EXISTS）。

-- 每日筛选的运行记录：同一 session + calc_version 重跑追加新行，读取取最新。
CREATE TABLE IF NOT EXISTS screen_runs (
  id             BIGSERIAL PRIMARY KEY,
  session        DATE NOT NULL,
  calc_version   TEXT NOT NULL,
  universe_name  TEXT NOT NULL,
  universe_as_of DATE NOT NULL,
  cutoff_at      TIMESTAMPTZ NOT NULL,
  status         TEXT NOT NULL,
  summary        JSONB NOT NULL,
  run_id         TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_screen_runs_session ON screen_runs (session, created_at DESC);

-- 范围内每只股票当天的筛选结果；列名 screen_group 避开 SQL 保留字 group，接口字段仍叫 group。
CREATE TABLE IF NOT EXISTS screen_results (
  id               BIGSERIAL PRIMARY KEY,
  screen_run_id    BIGINT NOT NULL REFERENCES screen_runs(id),
  ticker           TEXT NOT NULL,
  screen_group     TEXT NOT NULL CHECK (screen_group IN ('trigger', 'setup', 'none')),
  trigger_rules    TEXT[] NOT NULL DEFAULT '{}',
  filters          JSONB NOT NULL,
  rs               NUMERIC(18,6),
  atr_pct          NUMERIC(18,6),
  dollar_volume_20 NUMERIC(18,2),
  rank             INTEGER,
  selected         BOOLEAN NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_screen_results_ticker ON screen_results (ticker, screen_run_id);

-- 池分层的来源：手动名单还是每日筛选；旧行按 watchlist 补默认值。
ALTER TABLE pool_tiers ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'watchlist'
  CHECK (source IN ('watchlist', 'screen'));
-- filings 改为北京 09:30：只改仍是纽约时区的行，不置空 next_run_at
-- （置空会让调度器在下一个 tick 立即运行一次），直接写入下一个北京 09:30（周一至周五）。
UPDATE scheduled_jobs
   SET timezone = 'Asia/Shanghai', time_local = '09:30',
       next_run_at = (
         SELECT min(ts) FROM (
           SELECT (((now() AT TIME ZONE 'Asia/Shanghai')::date + d) + time '09:30') AT TIME ZONE 'Asia/Shanghai' AS ts
             FROM generate_series(0, 7) AS d) s
          WHERE ts > now() AND extract(isodow FROM ts AT TIME ZONE 'Asia/Shanghai') BETWEEN 1 AND 5)
 WHERE name = 'filings' AND timezone = 'America/New_York';
