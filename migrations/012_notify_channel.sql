-- 通知渠道全局单选（discord | email）+ 邮件配置（地址等非敏感项；SMTP 密码只走环境变量）
ALTER TABLE notify_settings
  ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'discord',
  ADD COLUMN IF NOT EXISTS email   JSONB NOT NULL DEFAULT '{}'::jsonb;
