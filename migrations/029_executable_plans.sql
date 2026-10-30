-- 029: 可执行的计划（v2.9 spec docs/specs/2026-10-30-v2.9-executable-plans-design.md §8、§21）。
-- trades 加 plan_id；trade_plans 加两个执行字段并换掉 017 的价位 CHECK（R3，持仓期止损可以高于入场价）；
-- 新建三张只追加的表 chain_retriggers、holding_status、plan_notes；放宽 plan_reviews 的 decided_by 约束
-- （§4.3 直接修订）。不改任何旧行、不加种子行；全部可重跑。真实库执行需单独授权（pg_dump 备份 +
-- psql --single-transaction），且必须先于重启服务执行（spec D36）。

-- ---------------------------------------------------------------- trades（§8.1）
-- 新成交关联的计划版本；旧行为空。新旧两种关联（plan_id / decision_id）不并存。
ALTER TABLE trades ADD COLUMN IF NOT EXISTS plan_id UUID REFERENCES trade_plans(id);
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_link_one_check;
ALTER TABLE trades ADD CONSTRAINT trades_link_one_check
  CHECK (plan_id IS NULL OR decision_id IS NULL);
CREATE INDEX IF NOT EXISTS idx_trades_plan ON trades (plan_id) WHERE plan_id IS NOT NULL;

-- ---------------------------------------------------------------- trade_plans（§8.2）
-- 旧行两列为空；两个执行字段同有同无。
ALTER TABLE trade_plans ADD COLUMN IF NOT EXISTS entry_type TEXT;
ALTER TABLE trade_plans ADD COLUMN IF NOT EXISTS max_hold_sessions INT;
ALTER TABLE trade_plans DROP CONSTRAINT IF EXISTS trade_plans_entry_type_check;
ALTER TABLE trade_plans ADD CONSTRAINT trade_plans_entry_type_check
  CHECK (entry_type IS NULL OR entry_type IN ('zone_limit', 'breakout_stop', 'next_open'));
ALTER TABLE trade_plans DROP CONSTRAINT IF EXISTS trade_plans_max_hold_check;
ALTER TABLE trade_plans ADD CONSTRAINT trade_plans_max_hold_check
  CHECK (max_hold_sessions IS NULL OR max_hold_sessions BETWEEN 3 AND 30);
ALTER TABLE trade_plans DROP CONSTRAINT IF EXISTS trade_plans_exec_fields_check;
ALTER TABLE trade_plans ADD CONSTRAINT trade_plans_exec_fields_check
  CHECK ((entry_type IS NULL) = (max_hold_sessions IS NULL));

-- 017 内联的价位 CHECK 由 PG 生成名字：按定义找出（含 stop < entry_low、不含 chain_mode）删掉，再加具名约束
-- （spec §21.1 R3）。持仓期 Agent 计划把止损上移到入场价之上时，计划行 inputs.chain_mode = 'holding'。
-- inputs 没有 chain_mode 键时 ->> 得 NULL，CHECK 会把 NULL 当作通过，所以用 COALESCE 兜成不等于 'holding'。
DO $$
DECLARE
  cname text;
BEGIN
  FOR cname IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'trade_plans'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%stop < entry_low%'
      AND pg_get_constraintdef(oid) NOT LIKE '%chain_mode%'
  LOOP
    EXECUTE format('ALTER TABLE trade_plans DROP CONSTRAINT %I', cname);
  END LOOP;
END $$;
ALTER TABLE trade_plans DROP CONSTRAINT IF EXISTS trade_plans_levels_check;
ALTER TABLE trade_plans ADD CONSTRAINT trade_plans_levels_check
  CHECK (entry_low <= entry_high AND entry_high < target1 AND stop < target1
         AND (stop < entry_low OR (kind = 'agent' AND COALESCE(inputs->>'chain_mode', '') = 'holding')));

-- ---------------------------------------------------------------- plan_reviews（§8.6）
-- 持仓期 / 再次触发的直接修订没有单独的复查运行，host 之外的行也可以只带修订运行。
DO $$
DECLARE
  cname text;
BEGIN
  FOR cname IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'plan_reviews'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%review_agent_run_id%'
      AND pg_get_constraintdef(oid) NOT LIKE '%revision_agent_run_id%'
  LOOP
    EXECUTE format('ALTER TABLE plan_reviews DROP CONSTRAINT %I', cname);
  END LOOP;
END $$;
ALTER TABLE plan_reviews DROP CONSTRAINT IF EXISTS plan_reviews_agent_run_check;
ALTER TABLE plan_reviews ADD CONSTRAINT plan_reviews_agent_run_check
  CHECK (decided_by = 'host' OR review_agent_run_id IS NOT NULL OR revision_agent_run_id IS NOT NULL);

-- ---------------------------------------------------------------- chain_retriggers（§8.3）
-- 只追加：新单元并入一条活跃链时记一行（链的「再次触发」信号）。
CREATE TABLE IF NOT EXISTS chain_retriggers (
  id                BIGSERIAL PRIMARY KEY,
  ticker            TEXT NOT NULL,
  unit_signal_date  DATE NOT NULL,
  chain_signal_date DATE NOT NULL,
  chain_state       TEXT NOT NULL CHECK (chain_state IN ('entry', 'holding', 'exiting')),
  rule_ids          TEXT[] NOT NULL,
  baseline_plan_id  UUID REFERENCES trade_plans(id),
  entry_cap         DATE,
  run_id            TEXT NOT NULL,
  timeline_version  TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (ticker, unit_signal_date),
  CHECK (unit_signal_date > chain_signal_date),
  CHECK ((chain_state = 'entry') = (entry_cap IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_chain_retriggers_chain ON chain_retriggers (ticker, chain_signal_date);

-- ---------------------------------------------------------------- holding_status（§8.4、R15）
-- 只追加：每个持仓标的每个复查交易日一行（同一 session 重跑 ON CONFLICT DO NOTHING）。
CREATE TABLE IF NOT EXISTS holding_status (
  id                 BIGSERIAL PRIMARY KEY,
  ticker             TEXT NOT NULL,
  session            DATE NOT NULL,
  chain_signal_date  DATE,
  plan_id            UUID REFERENCES trade_plans(id),
  review_id          BIGINT REFERENCES plan_reviews(id),
  run_id             TEXT NOT NULL,
  quantity           NUMERIC(18,6) NOT NULL,
  avg_cost           NUMERIC(18,6) NOT NULL,
  last_close         NUMERIC(18,6),
  stop               NUMERIC(18,6),
  target1            NUMERIC(18,6),
  stop_mode          TEXT CHECK (stop_mode IS NULL OR stop_mode IN ('initial', 'trailing')),
  t1_reached         BOOLEAN,
  reached_1r         BOOLEAN,
  to_stop_pct        NUMERIC(10,2),
  to_t1_pct          NUMERIC(10,2),
  r_now              NUMERIC(10,2),
  held_sessions      INT NOT NULL CHECK (held_sessions >= 1),
  max_hold_sessions  INT,
  remaining_sessions INT,
  instruction        TEXT NOT NULL CHECK (instruction IN ('hold', 'sell_half', 'exit', 'no_plan')),
  exit_reason        TEXT CHECK (exit_reason IS NULL OR exit_reason IN
                       ('stop_touched', 'time_stop', 'invalidation', 'agent_invalidate')),
  reason             TEXT NOT NULL CHECK (btrim(reason) <> ''),
  detail             JSONB NOT NULL DEFAULT '{}',
  timeline_version   TEXT NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (ticker, session),
  CHECK ((instruction = 'exit') = (exit_reason IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_holding_status_session ON holding_status (session);

-- ---------------------------------------------------------------- plan_notes（§8.5）
-- 只追加：用户写给自己的备注，作用于一条链或一份非链计划；更正与撤回都是新行（supersedes_id）。
CREATE TABLE IF NOT EXISTS plan_notes (
  id                BIGSERIAL PRIMARY KEY,
  request_id        UUID NOT NULL UNIQUE,
  request_hash      TEXT NOT NULL,
  ticker            TEXT NOT NULL,
  chain_signal_date DATE,
  plan_id           UUID REFERENCES trade_plans(id),
  kind              TEXT NOT NULL CHECK (kind IN ('note', 'retract')),
  body              TEXT NOT NULL CHECK (char_length(btrim(body)) BETWEEN 1 AND 1000),
  supersedes_id     BIGINT REFERENCES plan_notes(id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK ((chain_signal_date IS NULL) <> (plan_id IS NULL)),
  CHECK (kind <> 'retract' OR supersedes_id IS NOT NULL)
);
