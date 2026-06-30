CREATE TABLE IF NOT EXISTS notify_settings (
  id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  discord_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  webhooks        JSONB NOT NULL DEFAULT '{}'::jsonb,
  task_channels   JSONB NOT NULL DEFAULT '{}'::jsonb,
  task_enabled    JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO notify_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
