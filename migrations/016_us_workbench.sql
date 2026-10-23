-- US research workbench (design 2026-10-23). Additive only: new tables, two nullable
-- filings columns and one scheduled job. Existing rows are never backfilled or rewritten.

-- Daily bars. OHLC are yfinance auto_adjust=False values (split-adjusted, not
-- dividend-adjusted); adj_close is fully adjusted. A changed re-fetch appends a revision.
CREATE TABLE IF NOT EXISTS price_bars (
  id           BIGSERIAL PRIMARY KEY,
  ticker       TEXT NOT NULL,
  price_date   DATE NOT NULL,
  open         NUMERIC(18,6) NOT NULL,
  high         NUMERIC(18,6) NOT NULL,
  low          NUMERIC(18,6) NOT NULL,
  close        NUMERIC(18,6) NOT NULL,
  volume       BIGINT NOT NULL CHECK (volume >= 0),
  adj_close    NUMERIC(18,6) NOT NULL,
  split_factor NUMERIC(18,6) NOT NULL DEFAULT 1 CHECK (split_factor > 0),
  source       TEXT NOT NULL DEFAULT 'yfinance',
  revision     INTEGER NOT NULL CHECK (revision >= 1),
  fetched_at   TIMESTAMPTZ NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ticker, price_date, revision)
);
CREATE INDEX IF NOT EXISTS idx_price_bars_lookup
  ON price_bars (ticker, price_date DESC, revision DESC);

-- SEC acceptance time decides pre/post-market timing; old rows stay NULL.
ALTER TABLE filings ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS items TEXT[];

-- News metadata and links only; bodies are never fetched.
CREATE TABLE IF NOT EXISTS news_items (
  id           BIGSERIAL PRIMARY KEY,
  source       TEXT NOT NULL CHECK (source IN ('yfinance', 'sec_8k')),
  title        TEXT NOT NULL,
  url          TEXT NOT NULL,
  publisher    TEXT,
  published_at TIMESTAMPTZ,
  fetched_at   TIMESTAMPTZ NOT NULL,
  content_hash TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source, url)
);

CREATE TABLE IF NOT EXISTS news_item_tickers (
  news_item_id BIGINT NOT NULL REFERENCES news_items(id),
  ticker       TEXT NOT NULL,
  PRIMARY KEY (news_item_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_news_item_tickers_ticker ON news_item_tickers (ticker);

CREATE TABLE IF NOT EXISTS signal_candidates (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker       TEXT NOT NULL,
  signal_date  DATE NOT NULL,
  action       TEXT NOT NULL CHECK (action IN ('buy', 'sell', 'watch')),
  rule_id      TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  inputs       JSONB NOT NULL,
  run_id       TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ticker, signal_date, rule_id, rule_version)
);
CREATE INDEX IF NOT EXISTS idx_signal_candidates_date ON signal_candidates (signal_date DESC, ticker);

CREATE TABLE IF NOT EXISTS signal_briefs (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker         TEXT NOT NULL,
  signal_date    DATE NOT NULL,
  model          TEXT,
  prompt_version TEXT NOT NULL,
  cutoff_at      TIMESTAMPTZ NOT NULL,
  input_refs     JSONB NOT NULL,
  output         JSONB NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('ok', 'fallback', 'error')),
  error          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signal_briefs_unit ON signal_briefs (ticker, signal_date, created_at DESC);

CREATE TABLE IF NOT EXISTS signal_decisions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id   UUID NOT NULL UNIQUE,
  request_hash    TEXT NOT NULL,
  ticker          TEXT NOT NULL,
  signal_date     DATE NOT NULL,
  candidate_ids   UUID[] NOT NULL,
  brief_id        UUID REFERENCES signal_briefs(id),
  proposed_action TEXT NOT NULL CHECK (proposed_action IN ('buy', 'sell', 'watch')),
  final_action    TEXT NOT NULL CHECK (final_action IN ('buy', 'sell', 'watch', 'ignore')),
  decision        TEXT NOT NULL CHECK (decision IN ('accept', 'reject', 'downgrade')),
  reason          TEXT NOT NULL CHECK (btrim(reason) <> ''),
  decided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  supersedes_id   UUID REFERENCES signal_decisions(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signal_decisions_unit ON signal_decisions (ticker, signal_date, decided_at DESC);

-- voided_at/void_reason are the only fields ever set after insert.
CREATE TABLE IF NOT EXISTS trades (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id   UUID NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  ticker       TEXT NOT NULL,
  side         TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
  quantity     NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
  price        NUMERIC(18,6) NOT NULL CHECK (price > 0),
  fee          NUMERIC(18,6) NOT NULL DEFAULT 0 CHECK (fee >= 0),
  executed_at  TIMESTAMPTZ NOT NULL,
  decision_id  UUID REFERENCES signal_decisions(id),
  note         TEXT,
  recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  voided_at    TIMESTAMPTZ,
  void_reason  TEXT,
  CHECK ((voided_at IS NULL) = (void_reason IS NULL)),
  CHECK (void_reason IS NULL OR btrim(void_reason) <> '')
);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades (ticker, executed_at);

CREATE TABLE IF NOT EXISTS weekly_reviews (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  week_start    DATE NOT NULL CHECK (EXTRACT(ISODOW FROM week_start) = 1),
  calc_version  TEXT NOT NULL,
  stats         JSONB NOT NULL,
  notes         TEXT NOT NULL DEFAULT '',
  supersedes_id UUID REFERENCES weekly_reviews(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_weekly_reviews_week ON weekly_reviews (week_start DESC, created_at DESC);

-- Tue-Sat 06:30 Beijing follows Mon-Fri US closes; the job skips non-trading days itself.
INSERT INTO scheduled_jobs (name, time_local, weekday_mask, timezone) VALUES
  ('workbench', '06:30', '2-6', 'Asia/Shanghai')
ON CONFLICT (name) DO NOTHING;
