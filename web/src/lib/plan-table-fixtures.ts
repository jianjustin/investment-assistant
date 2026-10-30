/** Test fixtures for the v2.9 plan table (shapes follow src/lib/workbench.ts, spec §9.1). Not imported by the app. */
import type { PlanTableGroups, PlanTableRow } from './workbench'

export const holdingStatus = (over: Record<string, unknown> = {}) => ({
  ticker: 'AMD', session: '2026-10-30', quantity: 20, avg_cost: '150.00', last_close: '158.00', stop: '147.00',
  stop_mode: 'initial', target1: '170.00', t1_reached: false, to_stop_pct: -6.96, to_t1_pct: 7.59,
  held_sessions: 4, max_hold_sessions: 10, remaining_sessions: 6, r_now: 0.6, reached_1r: false,
  instruction: 'hold', exit_reason: null, reason: '无新信号，复查条件未满足', ...over,
})

export const row = (over: Partial<PlanTableRow> = {}): PlanTableRow => ({
  row_id: 'chain:MU:2026-10-29', group: 'entry', ticker: 'MU', pool: 'core',
  chain: { signal_date: '2026-10-29', version_no: 1, head_plan_id: 'p1', state: 'entry', label: 'MU·10-29 第 1 版',
           retriggers: [{ unit_signal_date: '2026-10-30', rule_ids: ['trend_reclaim'] }] },
  plan: { plan_id: 'p1', kind: 'agent', plan_version: 'agent-3', action: 'buy', entry_type: 'zone_limit',
          entry_type_text: '区间限价', entry_low: '95.10', entry_high: '97.30', stop: '91.40', target1: '104.70',
          shares: 120, shares_note: null, valid_from: '2026-10-31', valid_until: '2026-11-04', max_hold_sessions: 10,
          status: 'ok', defaults_applied: false },
  baseline: { plan_id: 'b1', plan_version: 'plan-2', entry_low: '95.00', entry_high: '97.00', stop: '91.00',
              target1: '104.00', shares: 110, status: 'ok', active_chain: true },
  open_scenarios: [
    { case: 'in_zone', action: 'buy_open', text: '开在 95.10–97.30：开盘买入 120 股' },
    { case: 'gap_up', action: 'limit_upper', text: '高开过 97.30：不追，挂 97.30 限价等回落' },
    { case: 'gap_down', action: 'stop_buy_lower', text: '低开：≤ 91.40 作废；否则回升到 95.10 时买入' }],
  void_when: [
    { source: 'validity', text: '有效期至 11-04 收盘仍未成交' }, { source: 'gap', text: '开盘 ≤ 91.40' },
    { source: 'invalidation', text: '收盘跌破 92.00', last_result: 'not_met' },
    { source: 'max_hold', text: '持仓后：持有 10 个交易日仍未到 1R → 次日开盘卖出' }],
  status: { label: '入场期 · 今日修订（再次触发）', execution: 'pending', latest_review: null, today_signals: ['retrigger'] },
  holding: null, notes: [{ id: 3, body: '等回踩再看', created_at: '2026-10-30T10:00:00Z' }],
  links: { plan: '#plan/p1', instrument: '#instrument/MU' }, ...over,
})

export const holdRow = (over: Partial<PlanTableRow> = {}) => row({
  row_id: 'chain:AMD:2026-10-20', group: 'holding', ticker: 'AMD',
  chain: { signal_date: '2026-10-20', version_no: 2, head_plan_id: 'h1', state: 'holding', label: 'AMD·10-20 第 2 版', retriggers: [] },
  open_scenarios: [], holding: holdingStatus() as any, notes: [],
  status: { label: '持仓期', execution: 'adopted', execution_detail: { date: '10-22', quantity: 20 } }, ...over,
})
export const endedRow = (over: Partial<PlanTableRow> = {}) => row({
  row_id: 'chain:NVDA:2026-10-24', group: 'ended', ticker: 'NVDA',
  chain: { signal_date: '2026-10-24', version_no: 0, head_plan_id: 'e1', state: 'expired', label: 'NVDA·10-24 第 0 版', retriggers: [] },
  open_scenarios: [], void_when: [], notes: [], ended_at: '2026-10-28',
  status: { label: '已过期（未执行）', execution: 'not_executed' }, ...over,
})

export const groups = (over: Partial<PlanTableGroups> = {}): PlanTableGroups =>
  ({ entry: [row()], holding: [holdRow()], ended: [endedRow()], ...over })

