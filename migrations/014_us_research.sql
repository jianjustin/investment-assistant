-- Additive US facts and guidance storage; does not change existing research or filings.
CREATE TABLE IF NOT EXISTS us_research_observations (
    id BIGSERIAL PRIMARY KEY,
    security_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    revision TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload JSONB NOT NULL,
    source_url TEXT,
    source_hash TEXT,
    disclosed_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (security_id, dataset, natural_key, revision)
);
CREATE INDEX IF NOT EXISTS us_research_observations_lookup
    ON us_research_observations(security_id, dataset, natural_key, first_seen_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS us_research_collection_state (
    security_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    status TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL,
    succeeded_at TIMESTAMPTZ,
    row_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_success_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(security_id, dataset)
);
