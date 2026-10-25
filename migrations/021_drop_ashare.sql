-- A-share removed from the project (v2.0.0). 013 stays so fresh installs still get research cards.
DELETE FROM research_observation_card_versions WHERE security_id LIKE 'CN:%';
DELETE FROM research_observation_cards WHERE security_id LIKE 'CN:%';
DELETE FROM watchlist_items WHERE ticker ~ '^[0-9]{6}\.(SH|SZ|BJ)$';
DELETE FROM scheduled_jobs WHERE name = 'ashares';
DROP TABLE IF EXISTS cn_collection_state;
DROP TABLE IF EXISTS cn_observations;
