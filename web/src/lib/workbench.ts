/** US workbench API client and pure helpers (design 2026-10-23). */
import type { AgentView, ChainRow, Change, Condition } from './timeline'
import type { Annotations, FocusItem, InstrumentContext, InstrumentHolding, InstrumentPlan, KeyData } from './knowledge'

export type Action = 'buy' | 'sell' | 'watch'
export type FinalAction = Action | 'ignore'
export type Choice = 'accept' | 'reject' | 'downgrade'

export interface Candidate {
  id: string; ticker?: string; signal_date: string; action: Action; rule_id: string; rule_version?: string
  inputs?: { values?: Record<string, unknown>; thresholds?: Record<string, unknown> }; created_at?: string
}
export interface BriefItem { text: string; refs: string[] }
export interface Brief {
  id: string; status: 'ok' | 'fallback' | 'error'; error?: string | null; created_at?: string
  prompt_version?: string; model?: string | null
  output?: { summary: string; support: BriefItem[]; contra: BriefItem[]; conflicts: BriefItem[] }
}
export interface Filing {
  id: number; form: string; filing_date: string; accepted_at: string | null; items: string[] | null
  accession_number?: string
}
export interface NewsItem {
  id: number; source: 'yfinance' | 'sec_8k'; title: string; url: string; publisher: string | null
  published_at: string | null; fetched_at: string
}
export interface Position { quantity: number; avg_cost: number; opened_at: string }
export interface Plan {
  id: string; ticker: string; signal_date: string; kind: 'rule' | 'own' | 'agent'; plan_version: string
  status: 'ok' | 'invalid'; entry_low: number; entry_high: number; stop: number; target1: number
  ref_price: number; atr: number; valid_from: string; valid_until: string
  sizing: { status: 'sized' | 'capped' | 'no_equity' | 'no_room'; shares: number | null
            risk_amount?: number | null; snapshot_as_of?: string | null } | null
  invalid_reasons: string[]; warnings: string[]; based_on_id?: string | null
  inputs?: { context?: PlanContext }
}
export interface Holding {
  ticker: string; quantity: number; avg_cost: number; plan_id: string | null
  stop: number | null; mode: string | null; t1_reached: boolean; target1: number | null
  last_close: number | null; to_stop_pct: number | null; to_target_pct: number | null
  next_earnings: string | null
  has_chain?: boolean            // v2.5 D7: the holding's unit has an agent-2 chain (in any state)
  chain_state?: string | null    // that chain's state at S: holding, or ended under the holding (e.g. invalidated)
}
export interface Snapshot {
  id: string; request_id: string; as_of: string; equity: number; note: string | null
  recorded_at: string; supersedes_id: string | null
}
export interface CashFlow {
  id: string; request_id: string; flow_date: string; amount: number; note: string | null
  recorded_at: string; voided_at: string | null; void_reason: string | null
}
export interface AccountParams {
  risk_pct: number; single_cap: number; total_cap: number; public_url: string; return_tiers: number[]
}
export interface AccountView { snapshots: Snapshot[]; flows: CashFlow[]; params: AccountParams }
export interface PlanShadowOutcome {
  status: 'pending' | 'expired' | 'open' | 'closed'; fill_date: string | null; fill_price: number | null
  legs: { fraction: number; exit_date: string; exit_price: number; reason: string }[]
  r: number | null; return: number | null; spy_return: number | null
}
export interface PlanShadow {
  id: string; ticker: string; signal_date: string; kind: 'rule' | 'own' | 'agent'; plan_version: string
  status: string; outcome: PlanShadowOutcome
}
export interface PlanShadowView { session: string; since: string; calc_version: string; plans: PlanShadow[] }
export interface AgentItem { text: string; refs: string[]; id?: string }
export interface AgentOutput {
  action: 'buy' | 'pass'; summary: string
  levels: Record<'entry_low' | 'entry_high' | 'stop' | 'target1', { value: string; refs: string[] }> | null
  thesis: AgentItem[]
  // agent-2 (v2.5 §4.1)
  invalidation?: Condition[]; review_when?: Condition[]; changes?: Change[]
}
export interface AgentCounter {
  status: string; risks: AgentItem[]; dropped: number
  counter?: { thesis: number; text: string; refs: string[] }[]; uncountered?: number[]   // agent-2
}
export interface AgentRunOk {
  id: string; status: 'ok' | 'pass'; model: string; agent_version: string
  output: AgentOutput | null
  counter: AgentCounter | null
  plan: Plan | null; input_tokens: number; output_tokens: number; created_at: string
}
export interface AgentRunFailed {
  id: string; status: 'rejected' | 'error' | 'skipped'; reason: string | null; created_at: string
}
export type AgentRun = AgentRunOk | AgentRunFailed
export interface AgentToolCall {
  seq: number; phase: 'propose' | 'counter'; tool: string
  args: Record<string, unknown>; result: Record<string, unknown>
  result_sha256: string; called_at: string
}
export type AgentRunDetail = (AgentRunOk | AgentRunFailed) & { tool_calls: AgentToolCall[] }
export interface DisciplineTrade {
  trade_id: string; ticker: string; track: 'rule' | 'own' | 'agent' | null
  flags: string[]; immature: string[]; r: number | null
}
export interface DisciplineView {
  session: string; since: string; trades: DisciplineTrade[]
  counts: { chase: number; early_take: number; held_loser: number; unplanned: number }
  immature: Record<string, number>; planned_buys: number; compliance_rate: number | null
}
export interface MonthlyReview {
  id: string; month: string; calc_version: string; stats: {
    month: string; return: { status: string; return: number | null; net_flow?: number | null }
    tier: string | null; spy: { return: number; excess: number } | null; review_flag: string
    sensitivity: { approximate: boolean; count?: number; rows: { risk_pct: number; return: number; max_drawdown: number }[] }
    discipline: DisciplineView; plans: Record<string, { count: number; expired: number; r_mean: number | null; r_median: number | null }>
    review?: { flag: string; compound: number | null; spy_compound: number | null;
               months?: { month: string; return: number | null; spy_return: number | null }[] }
    tracks?: { units: TrackRow[]; summary: TrackSummary } | null
    generated_at: string
  }; notes: string; supersedes_id: string | null; created_at: string
}
export interface PlanContext {
  context_version: string; pool_tier: 'core' | 'extended' | 'unknown'
  regime: { id: string; label: string } | null
  sector: { etf: string; rs20: number | null; rs60: number | null
            state: 'strong' | 'weak' | 'mixed' | null } | null
  next_earnings: string | null
}
export interface MarketContext {
  id: string; session: string; calc_version: string
  label: 'risk_on' | 'neutral' | 'risk_off' | 'insufficient'
  breadth: { tickers?: number; eligible_50?: number; above_50?: number; pct_50?: number | null
             eligible_200?: number; above_200?: number; pct_200?: number | null
             eligible_52w?: number; new_highs?: number; new_lows?: number }
  sectors: Record<string, { rs20: number; rs60: number; state: 'strong' | 'weak' | 'mixed' } | null>
  macro: Record<string, { value: number | string; obs_date: string; change: number | string | null
                          change_from: string | null } | null>
  inputs: { macro_status?: Record<string, 'ok' | 'not_configured' | 'error'>; [key: string]: unknown }
  created_at: string
}
export interface ExtendedUnit {
  ticker: string; signal_date: string; proposed_action: Action; rule_ids: string[]; plan: Plan | null
  agent_status: string | null
}
export interface ExcessStat {
  n: number; mean: number | null; median: number | null; positive_share: number | null
  immature: number; missing: number
}
export interface BackcheckRow {
  triggers: number; ticker_sessions: number; per_100: number; max_per_ticker: number; cluster_days: number
  filled: number; expired: number; stopped_within_5: number; stopped_within_5_share: number | null
  t1_share: number | null
  r: { count: number; mean: number | null; median: number | null; p25: number | null; p75: number | null }
  excess?: Record<'5' | '10' | '20', ExcessStat>
  flags: string[]
}
export interface Backcheck {
  id: string; calc_version: string; created_at: string; params: Record<string, unknown>
  stats: { note: string; all: BackcheckRow; rules: Record<string, BackcheckRow>
           tickers: { ticker: string; warmup_end: string | null; eval_start: string | null
                      eval_end: string | null; eval_sessions: number }[] }
}
export interface Unit {
  ticker: string; signal_date: string; proposed_action: Action; labels: string[]; candidate_ids: string[]
  rule_ids: string[]; entry_passed: boolean; holding: boolean; source?: 'watchlist' | 'screen' | null
  candidates: Candidate[]; brief: Brief | null; filings: Filing[]; news: NewsItem[]; position: Position | null
  plan: Plan | null
  agent: AgentView | null
}
export interface ScreenTrigger {
  ticker: string; rule_ids: string[]; rs: number | null
  review: 'plan' | 'invalid' | 'conflict' | 'watch'
  plan: { entry_low: string; entry_high: string; stop: string; target1: string; shares: number | null;
          sizing_status: string | null } | null
  invalid_reasons: string[]
}
export interface ScreenReport {
  session: string; calc_version: string; status: string; error: string | null
  universe: { name: string; as_of: string; stale: boolean }
  counts: Record<string, number>; selected: string[]; members: number; cap: number
  evicted: string[]; removed: string[]; flags: string[]
  triggers: ScreenTrigger[]; setups: { ticker: string; rs: number | null; atr_pct: number | null; rank: number | null }[]
  setups_more?: number; results?: unknown[]
}
export interface TodayView {
  session: string; units: Unit[]; extended_units: ExtendedUnit[]; holdings: Holding[]
  market: MarketContext | null; screen: ScreenReport | null
  chains?: ChainRow[]; timeline_ready?: boolean     // v2.5 §10.2; false = migration 026 missing
}
export interface Decision {
  id: string; ticker: string; signal_date: string; proposed_action: Action; final_action: FinalAction
  decision: Choice; reason: string; decided_at: string; supersedes_id: string | null
}
export interface Trade {
  id: string; ticker: string; side: 'buy' | 'sell'; quantity: number; price: number; fee: number
  executed_at: string; decision_id: string | null; note: string | null; recorded_at: string
  voided_at: string | null; void_reason: string | null
}
export interface ChartBar {
  price_date: string; open: number; high: number; low: number; close: number; volume: number
  ma20: number | null; ma50: number | null; ma200: number | null
}
export interface InstrumentView {
  ticker: string; session: string; bars: any[]; filings: Filing[]; news: NewsItem[]; candidates: Candidate[]
  decisions: Decision[]; trades: Trade[]; position: Position | null; closed: any[]
  chart: { bars: ChartBar[]; adjustment: string; annotations?: Annotations }
  // v2.6 (§9.4): additive keys; an older backend simply lacks them
  holding?: InstrumentHolding | null
  focus?: FocusItem[]; key_data?: KeyData; context?: InstrumentContext; plans?: InstrumentPlan[]
  // a new block that failed to read is null and its reason is here, keyed by block name (focus, key_data, ...)
  errors?: Record<string, string>
}
export interface Window { status: 'mature' | 'immature'; exit_date?: string; return?: number; spy_return?: number; excess?: number; move?: number }
export interface ShadowUnit extends Decision {
  rule_ids: string[]
  outcome: { status: 'entered' | 'pending_entry'; entry_date?: string; entry_price?: number; windows: Record<string, Window> }
}
export interface ShadowView { session: string; since: string; calc_version: string; units: ShadowUnit[] }
export interface TradeReview { session: string; calc_version: string; closed: any[]; open: any[] }
export interface WeeklyReview { id: string; week_start: string; calc_version: string; stats: any; notes: string; supersedes_id: string | null; created_at: string }

export class WorkbenchError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    cache: 'no-store', ...init,
    headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
  })
  const data = await r.json().catch(() => null)
  if (!r.ok) throw new WorkbenchError(data?.error ?? `HTTP ${r.status}`, r.status)
  return data as T
}
const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const getToday = () => request<TodayView>('/api/workbench/today')
export const getScreen = (session?: string, full = false) =>
  request<{ report: ScreenReport | null }>(`/api/workbench/screen${session ? `?session=${encodeURIComponent(session)}` : '?'}${full ? `${session ? '&' : ''}full=1` : ''}`)
export const getInstrument = (ticker: string) => request<InstrumentView>(`/api/workbench/instruments/${encodeURIComponent(ticker)}`)
export const postDecision = (body: object) => post<{ status: string; record: Decision }>('/api/workbench/decisions', body)
export const getTrades = () => request<{ trades: Trade[] }>('/api/workbench/trades')
export const postTrade = (body: object) => post<{ status: string; record: Trade }>('/api/workbench/trades', body)
export const voidTrade = (id: string, reason: string) => post<Trade>(`/api/workbench/trades/${id}/void`, { reason })
export const getShadow = () => request<ShadowView>('/api/workbench/review/shadow')
export const getTradeReview = () => request<TradeReview>('/api/workbench/review/trades')
export const getWeekly = () => request<{ reviews: WeeklyReview[] }>('/api/workbench/weekly-reviews')
export const postWeekly = (body: object) => post<WeeklyReview>('/api/workbench/weekly-reviews', body)
export const runWorkbench = () => post<{ run_id: string; status: string }>('/api/workbench/run', {})
export const getAccount = () => request<AccountView>('/api/workbench/account/snapshots')
export const postSnapshot = (body: object) => post<{ status: string; record: Snapshot }>('/api/workbench/account/snapshots', body)
export const postFlow = (body: object) => post<{ status: string; record: CashFlow }>('/api/workbench/account/flows', body)
export const voidFlow = (id: string, reason: string) => post<CashFlow>(`/api/workbench/account/flows/${id}/void`, { reason })
export const getPlanShadow = (since?: string) =>
  request<PlanShadowView>(`/api/workbench/plans/shadow${since ? `?since=${since}` : ''}`)
export const getAgentRun = (id: string) => request<AgentRunDetail>(`/api/workbench/agent-runs/${id}`)
export const rerunAgent = (ticker: string, signalDate: string) =>
  post<AgentRunOk | AgentRunFailed>('/api/workbench/agent-runs', { ticker, signal_date: signalDate })
export const getDiscipline = () => request<DisciplineView>('/api/workbench/discipline')
export const getMonthly = () => request<{ reviews: MonthlyReview[] }>('/api/workbench/monthly-reviews')
export const postMonthly = (body: object) => post<MonthlyReview>('/api/workbench/monthly-reviews', body)
export const pushToday = () => post<{ session: string; sent: boolean; messages?: number; reason?: string }>('/api/workbench/push', {})
export const getBackchecks = () => request<{ backchecks: Backcheck[] }>('/api/workbench/backchecks')
export const runBackcheck = (tickers?: string[]) => post<Backcheck>('/api/workbench/backchecks', { tickers: tickers ?? null })

export function describeError(error: unknown): string {
  if (error instanceof WorkbenchError) {
    if (error.status === 503) return `数据库未就绪：${error.message}`
    // v2.5 §9.3: 'agent_plan_stale: <sentence>' — the sentence after the code is shown as is.
    if (error.status === 409 && error.message.startsWith('agent_plan_stale:'))
      return error.message.slice('agent_plan_stale:'.length).trim()
    if (error.status === 409) return `已有更新的记录，请刷新后基于最新记录操作（${error.message}）`
    if (error.status === 400) return `输入有误：${error.message}`
  }
  return `请求失败：${error instanceof Error ? error.message : String(error)}`
}

export const newRequestId = () => crypto.randomUUID()

export function finalAction(proposed: Action, choice: Choice): FinalAction {
  return choice === 'accept' ? proposed : choice === 'reject' ? 'ignore' : 'watch'
}

export interface OwnPlanInput { entry_low: string; entry_high: string; stop: string; target1: string }
export type Basis = 'rule' | 'own' | 'agent'
/** What the page showed when deciding (v2.5 §9.3); acceptance stats only. */
export interface ReviewView { layout: 'agent_first' | 'legacy'; baseline_expanded: boolean; agent_version_no: number | null }

export function levelsError(input: OwnPlanInput): string | null {
  const [low, high, stop, target1] = [input.entry_low, input.entry_high, input.stop, input.target1].map(Number)
  if (![low, high, stop, target1].every(n => Number.isFinite(n) && n > 0)) return '四个价位都必须是正数'
  if (!(stop < low && low <= high && high < target1)) return '价位需满足：止损 < 入场下限 ≤ 入场上限 < T1'
  return null
}

export function decisionPayload(unit: Unit, choice: Choice, reason: string, requestId: string,
                                ownPlan: ({ request_id: string } & OwnPlanInput) | null = null,
                                basis: Basis = 'rule', agentPlanId: string | null = null,
                                reviewView: ReviewView | null = null) {
  const agent = unit.agent
  const agentPlan = agent && 'plan' in agent ? agent.plan : null
  const planId = choice === 'accept' && !ownPlan
    ? (basis === 'agent'
         ? (agentPlan && agentPlan.status === 'ok' ? agentPlan.id : null)
         : (basis === 'rule' && unit.plan && unit.plan.status === 'ok' ? unit.plan.id : null))
    : null
  return {
    request_id: requestId, ticker: unit.ticker, signal_date: unit.signal_date, candidate_ids: unit.candidate_ids,
    brief_id: unit.brief && unit.brief.status !== 'error' ? unit.brief.id : null,
    proposed_action: unit.proposed_action, final_action: finalAction(unit.proposed_action, choice),
    decision: choice, reason: reason.trim(),
    plan_id: planId,
    own_plan: ownPlan,
    // v2.5: the Agent version the page showed (409 agent_plan_stale when no longer the head); sent only when known.
    ...(agentPlanId ? { agent_plan_id: agentPlanId } : {}),
    ...(reviewView ? { review_view: reviewView } : {}),
  }
}

export const RULE_LABELS: Record<string, string> = {
  trend_reclaim: '趋势回踩修复', volume_breakout: '放量突破', earnings_gap_up: '财报跳空向上',
  trend_break: '跌破 MA50', earnings_gap_down: '财报跳空向下', position_drawdown: '持仓回撤',
  new_filing: '新财报', abnormal_move: '异常波动',
  plan_stop: '计划止损', plan_target: '计划目标',   // v2.6 D27: sell rules of held positions with a plan
}
export const ACTION_LABELS: Record<string, string> = { buy: '买入', sell: '卖出', watch: '观察', ignore: '忽略' }
export const UNIT_LABELS: Record<string, string> = { conflict: '冲突', avoid: '回避' }
export const REGIME_LABELS: Record<string, string> = { risk_on: '进攻', neutral: '中性', risk_off: '防守', insufficient: '样本不足' }
export const SECTOR_STATE_LABELS: Record<string, string> = { strong: '强', weak: '弱', mixed: '分化' }
export const TIER_LABELS: Record<string, string> = { excellent_plus: '非常优秀', excellent: '优秀', viable: '可行', attention: '需关注' }
export const FLAG_LABELS: Record<string, string> = { chase: '追高', early_take: '过早止盈', held_loser: '死扛亏损', unplanned: '计划外' }
export const CHOICE_LABELS: Record<Choice, string> = { accept: '采纳', reject: '否决', downgrade: '降级为观察' }
export const KIND_TEXT: Record<string, string> = { rule: '规则', own: '自定', agent: 'Agent', agent_latest: 'Agent（最新版）' }
// v2.5 D17: from weekly review-6 / monthly review monthly-3 on, plans.agent counts each chain's first version
// (plans.agent_latest its head); older snapshots keep the plain「Agent」.
const FIRST_VERSION_CALCS = new Set(['review-6', 'monthly-3'])
export function planKindText(kind: string, calcVersion: string | null | undefined): string {
  if (kind === 'agent' && calcVersion && FIRST_VERSION_CALCS.has(calcVersion)) return 'Agent（首版）'
  return KIND_TEXT[kind] ?? kind
}
export const AGENT_REASON_TEXT: Record<string, string> = {
  disabled: '已关闭', not_configured: '未配置', quota_exhausted: '额度用尽', token_budget: '超出 token 上限',
  stage_budget: '超出时限', max_attempts: '已达重试上限', malformed: '输出格式无效',
  invalid_citation: '引用无效已作废', level_check: '价位校验未通过', tool_rounds_exceeded: '工具调用超限',
  model_error: '模型调用失败', checkpoint_unavailable: '状态库未就绪',
  // agent-2 / daily review (v2.5 §4.4, D23): same as backend agent.REASON_TEXT
  thesis_count: '论点数量不符', invalid_condition: '失效或复查条件无效', changes_mismatch: '变化说明与实际差异不符',
  no_change: '修订与上版没有差异', review_malformed: '复查输出格式无效', migration_026_missing: '迁移 026 未执行',
  review_in_progress: '正在复查', plan_invalid: '修订版按规则作废',
}

export const ruleLabel = (id: string) => RULE_LABELS[id] ?? id

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

export function dateTime(value: string | null | undefined): string {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
}

export function publishedText(value: string | null): string {
  return value ? dateTime(value) : '发布时间未知'
}

export interface TimelineItem { kind: 'filing' | 'news' | 'candidate' | 'decision' | 'trade'; at: string; text: string; url?: string }

export function timeline(view: InstrumentView): TimelineItem[] {
  const items: TimelineItem[] = [
    ...view.filings.map(f => ({ kind: 'filing' as const, at: f.accepted_at ?? f.filing_date,
      text: `${f.form}${f.items?.length ? `（Items ${f.items.join(', ')}）` : ''}${f.accepted_at ? '' : ' · 受理时间未知'}` })),
    ...view.news.map(n => ({ kind: 'news' as const, at: n.published_at ?? n.fetched_at, url: n.url,
      text: `${n.title} · ${n.publisher ?? n.source} · ${publishedText(n.published_at)}` })),
    ...view.candidates.map(c => ({ kind: 'candidate' as const, at: c.created_at ?? c.signal_date,
      text: `${c.signal_date} ${ruleLabel(c.rule_id)} → ${ACTION_LABELS[c.action]}` })),
    ...view.decisions.map(d => ({ kind: 'decision' as const, at: d.decided_at,
      text: `${d.signal_date} ${CHOICE_LABELS[d.decision]} → ${ACTION_LABELS[d.final_action]}：${d.reason}` })),
    ...view.trades.map(t => ({ kind: 'trade' as const, at: t.executed_at,
      text: `${t.side === 'buy' ? '买入' : '卖出'} ${t.quantity} @ ${t.price}${t.voided_at ? `（已作废：${t.void_reason}）` : ''}` })),
  ]
  return items.sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
}


// --- three-track comparison and review pushes (P4 design §4, §6) ---

export type TrackStatus = 'missing' | 'not_executable' | 'pending' | 'expired' | 'open' | 'closed' | 'pass'
  | 'not_executed' | 'no_plan'
export interface TrackResult { status: TrackStatus; r: number | null }
export interface RuleTrack extends TrackResult { plan_id: string | null }
export interface AgentTrack extends TrackResult { run_id: string | null; run_status: string | null; run_reason: string | null; plan_id: string | null }
export interface ActualTrack extends TrackResult {
  decision_id: string | null; final_action: string | null; plan_id: string | null; plan_kind: 'rule' | 'agent' | 'own' | null
  buy_trade_ids: string[]; open: boolean
}
export interface TrackRow {
  ticker: string; signal_date: string; pool: 'core' | 'extended'
  rule: RuleTrack; agent: AgentTrack; actual: ActualTrack
}
export interface TrackStats {
  units: number; determined: number; pending: number; missing: number
  mean: number | null; median: number | null; sum: number | null; wins: number
  by_status: Record<string, number>; by_plan_kind?: Record<string, number>
}
export interface TrackSummary { all: Record<'rule' | 'agent' | 'actual', TrackStats>; core: Record<'rule' | 'agent' | 'actual', TrackStats>; extended: Record<'rule' | 'agent' | 'actual', TrackStats> }
export interface TracksView { session: string; since: string; until: string; calc_version: string; units: TrackRow[]; summary: TrackSummary }
export interface ReviewPush {
  id: string; kind: 'weekly' | 'monthly' | 'monthly_reminder'; period: string; review_id: string | null
  trigger_source: 'scheduled' | 'manual'; sent: boolean; messages: number; reason: string | null; created_at: string
}

export const TRACK_STATUS_TEXT: Record<TrackStatus, string> = {
  missing: '缺失', not_executable: '计划作废', pending: '待定', expired: '到期未成交',
  open: '未平仓', closed: '已平仓', pass: '不建议', not_executed: '未执行', no_plan: '无计划成交',
}

export const getTracks = (since?: string, until?: string) => request<TracksView>(
  `/api/workbench/review/tracks${since || until ? `?${since ? `since=${since}` : ''}${since && until ? '&' : ''}${until ? `until=${until}` : ''}` : ''}`)
export const getReviewPushes = () => request<{ pushes: ReviewPush[] }>('/api/workbench/review-pushes')
export const postReviewPush = (kind: 'weekly' | 'monthly', period: string) =>
  post<{ kind: string; period: string; sent: boolean; messages?: number; reason?: string }>(
    '/api/workbench/review-pushes', { kind, period })

export function rText(r: number | null): string {
  if (r === null || !Number.isFinite(r)) return '—'
  return `${r >= 0 ? '+' : ''}${r.toFixed(2)}R`
}
