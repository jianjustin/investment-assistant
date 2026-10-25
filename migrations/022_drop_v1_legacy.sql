-- v2.1.0: v1 legacy removed (Hermes, SPY/VIX signals, ticker trends, strategy scores,
-- event study, research cards). job_reports history stays. No CASCADE: an unexpected
-- dependency must fail the transaction instead of being dropped silently.
DELETE FROM scheduled_jobs WHERE name IN ('metrics', 'scores', 'event_study');
DROP TABLE IF EXISTS strategy_scores;            -- references ticker_signal_snapshots (005)
DROP TABLE IF EXISTS ticker_signal_snapshots;
DROP TABLE IF EXISTS market_signals;
DROP TABLE IF EXISTS event_studies;
DROP TABLE IF EXISTS research_observation_card_versions;
DROP TABLE IF EXISTS research_observation_cards;
