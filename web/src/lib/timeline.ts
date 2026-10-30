/** v2.5 plan timeline: chain / version / review types and their Chinese labels (spec §4, §5, §7, §11). */
import { AGENT_REASON_TEXT, CHAIN_EXITING_TEXT, ENTRY_TYPE_TEXT } from './workbench'
import type {
  AgentRunFailed, AgentRunOk, EntryType, ExecutionStatus, HoldingStatus, Plan, PlanNote, PlanShadowOutcome, RowRetrigger,
} from './workbench'
import type { KnowledgeRefItem } from './growth'

// timeline-2 (v2.9 §4.1) adds `exiting` and `superseded`
export type ChainState = 'legacy' | 'invalidated' | 'closed_by_decision' | 'exiting' | 'holding' | 'position_closed'
  | 'superseded' | 'expired' | 'entry'
export type ChainMode = 'entry' | 'holding'
export type Outcome = 'maintain' | 'revise' | 'invalidate' | 'skipped' | 'error'
export type DecidedBy = 'agent' | 'host'
export type Origin = 'signal' | 'review' | 'recheck'
export type ConditionResultValue = 'met' | 'not_met' | 'unknown'
export type UserInputKind = 'research' | 'news' | 'judgment' | 'other' | 'retract'

/** One invalidation / review condition of an agent-2 plan (`condition-1`). */
export interface Condition { kind: string; params?: Record<string, unknown>; text?: string; refs?: string[] }
/** One condition judgment written on a review row. */
export interface ConditionResult {
  list: 'invalidation' | 'review_when'; index: number; kind: string; params?: Record<string, unknown>
  result: ConditionResultValue; detail?: string | null
}
export interface Signal { kind: string; fired: boolean; detail?: string | null; evidence?: unknown }
export interface DiffItem { field: string; before: unknown; after: unknown; host_only?: boolean }
export interface Change { field: string; text: string; refs: string[] }

/** `latest_review` of the today / chain views; `conditions` only where the backend sends the full row. */
export interface LatestReview {
  id?: number; session?: string; trigger?: 'batch' | 'recheck'; outcome: Outcome; decided_by: DecidedBy | null
  reason: string | null; new_plan_id?: string | null; revision_status?: string | null; created_at: string
  conditions?: ConditionResult[]
}

/** `agent.chain` of a today unit; `cutoff_at` / `diff` are filled where known (plan page). */
export interface ChainHead {
  version_no: number; head_plan_id: string; state: ChainState; mode: ChainMode | null; basis: string
  latest_review: LatestReview | null
  cutoff_at?: string | null; diff?: DiffItem[] | null
}

/** A unit's agent block: a run view plus its chain head (null for agent-1 or without migration 026). */
export type AgentView = (AgentRunOk | AgentRunFailed) & {
  chain?: ChainHead | null; legacy?: boolean
  /** v2.7 §6.2: the knowledge this version cited; absent on an older backend or before migration 027 */
  knowledge_refs?: KnowledgeRefItem[]
}

export interface PlanReview {
  id: number; ticker: string; signal_date: string; head_plan_id: string; session: string
  trigger: 'batch' | 'recheck'; run_id: string | null; mode: ChainMode; timeline_version: string
  signals: Signal[] | null; conditions: ConditionResult[] | null; user_input_ids: number[] | null
  outcome: Outcome; decided_by: DecidedBy | null; reason: string | null; refs: string[] | null
  review_agent_run_id: string | null; revision_agent_run_id: string | null; new_plan_id: string | null
  detail: Record<string, unknown> | null; attempt: number; cutoff_at: string
  input_tokens: number; output_tokens: number; created_at: string
  head_version_no?: number; new_version_no?: number | null
}

export interface VersionRun {
  id: string; mode: string; agent_version: string; model: string; status: AgentRunOk['status'] | AgentRunFailed['status']
  reason: string | null; cutoff_at: string; output: AgentRunOk['output']; counter: AgentRunOk['counter']
  input_tokens: number; output_tokens: number; created_at: string
}

export interface Version {
  version_no: number; plan_id: string; origin: Origin; supersedes_plan_id: string | null; agent_run_id: string
  cutoff_at: string; as_of_session: string; created_at: string; is_head: boolean
  diff: DiffItem[] | null; changes: Change[]; plan: Plan; run: VersionRun; shadow: PlanShadowOutcome | null
  knowledge_refs?: KnowledgeRefItem[]
  // v2.9 §10.2: execution state of this version (execution-1); absent on an older backend
  execution?: { status: ExecutionStatus; date?: string | null; quantity?: number | string | null } | null
}

export interface UserInput {
  id: number; request_id: string; ticker: string; signal_date: string | null; kind: UserInputKind; body: string
  source_url: string | null; supersedes_id: number | null; created_at: string
  superseded_by?: number | null; ref?: string; status?: 'active' | 'corrected' | 'retracted'
}
export interface UserInputBody {
  request_id: string; ticker: string; signal_date?: string; kind: UserInputKind; body: string
  source_url?: string; supersedes_id?: number
}

/** GET /api/workbench/chains/{ticker}/{signal_date}. */
export interface Chain {
  ticker: string; signal_date: string; session: string
  state: { state: ChainState; mode: ChainMode | null; basis: string; active?: boolean; timeline_version?: string }
  head_plan_id: string; version_no: number; latest_review: LatestReview | null; shadow_version: string
  versions: Version[]; reviews: PlanReview[]; inputs: UserInput[]
  // v2.9 §9.1: merged units, the chain's holding_status rows and plan notes
  retriggers?: RowRetrigger[]; holding_status?: HoldingStatus[]; notes?: PlanNote[]
}

/** today()['chains'] rows (§10.2). */
export interface ChainRow {
  ticker: string; signal_date: string; state: ChainState; mode: ChainMode | null; basis: string
  version_no: number; head_plan_id: string; valid_until: string; pool: string
  latest_review: { outcome: Outcome; decided_by: DecidedBy | null; created_at: string; reason: string | null } | null
  signals_today: string[]
}

/** GET /api/workbench/chains?ticker= rows. */
export interface TickerChain {
  signal_date: string; state: ChainState; mode: ChainMode | null; version_no: number; head_plan_id: string
  latest_review: { outcome: Outcome; decided_by: DecidedBy | null; created_at: string; reason: string | null } | null
}

export const OUTCOME_TEXT: Record<Outcome, string> = {
  maintain: '维持', revise: '修订', invalidate: '作废', skipped: '跳过', error: '出错',
}
export const DECIDED_BY_TEXT: Record<DecidedBy, string> = { agent: 'Agent', host: '系统规则' }
export const SIGNAL_TEXT: Record<string, string> = {
  new_8k: '新 8-K', abnormal_move: '异常波动', stop_touched: '触及止损', t1_touched: '触及 T1',
  expiry_near: '临近到期', regime_change: '区制变化', user_input: '新的用户输入', retrigger: '再次触发',
}
export const MODE_TEXT: Record<ChainMode, string> = { entry: '入场期', holding: '持仓期' }
export const ORIGIN_TEXT: Record<Origin, string> = { signal: '信号日', review: '每日复查', recheck: '重新复查' }
export const CONDITION_RESULT_TEXT: Record<ConditionResultValue, string> = { met: '成立', not_met: '未成立', unknown: '无法判定' }
export const TRIGGER_TEXT: Record<string, string> = { batch: '批处理', recheck: '重新复查' }
export const CHAIN_STATE_TEXT: Record<ChainState, string> = {
  entry: '入场期', holding: '持仓期', invalidated: '已作废', closed_by_decision: '已决定不买',
  position_closed: '已平仓', expired: '已到期', legacy: '旧版', exiting: '退出期', superseded: '被取代',
}
export const CHANGE_FIELD_TEXT: Record<string, string> = {
  action: '动作', entry: '入场区间', stop: '止损', target1: 'T1', thesis: '论点', invalidation: '失效条件',
  review_when: '复查条件',
  // agent-3 (v2.9 §5.5): model fields and the two host-only fields
  entry_type: '入场类型', max_hold_sessions: '最长持有', valid_until: '有效期至', entry_cap: '入场期上限',
}
export const USER_INPUT_KIND_TEXT: Record<UserInputKind, string> = {
  research: '研报要点', news: '新闻', judgment: '我的判断', other: '其他', retract: '撤回',
}
// R10: reviews and rechecks only cover entry / holding; uniqueness and retriggers also count `exiting`.
export const REVIEWABLE_STATES: ChainState[] = ['entry', 'holding']
export const ACTIVE_STATES: ChainState[] = ['entry', 'holding', 'exiting']

// --- condition text: the same templates and param rendering as backend conditions.describe ---

const CONDITION_TEMPLATES: Record<string, { params: string[]; text: string }> = {
  close_below: { params: ['price'], text: '收盘跌破 {price}' },
  close_above: { params: ['price'], text: '收盘突破 {price}' },
  no_entry_by: { params: ['date'], text: '{date} 收盘前未进入入场区' },
  no_entry_before_earnings: { params: [], text: '财报前未进入入场区' },
  earnings_within: { params: ['sessions'], text: '距财报不足 {sessions} 个交易日' },
  regime_is: { params: ['label'], text: '区制变为 {label}' },
  sector_weak: { params: [], text: '所属行业转弱' },
  rs_below: { params: ['window', 'value'], text: '相对 SPY {window} 日强弱低于 {value}' },
  new_filing: { params: ['form'], text: '出现新的 {form}' },
  date_reached: { params: ['date'], text: '到 {date} 再看' },
  next_session: { params: [], text: '下一交易日' },
}

const pyStr = (value: unknown): string => (value === null || value === undefined ? 'None' : String(value))

/** Decimal(str(value)).quantize(0.01, ROUND_HALF_UP) for a positive price; null when not a valid price. */
function cents(value: unknown): string | null {
  if (typeof value !== 'number' && typeof value !== 'string') return null
  const s = String(value).trim()
  const n = Number(s)
  if (!/^\+?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(s) || !Number.isFinite(n) || n <= 0) return null
  if (/e/i.test(s)) return n.toFixed(2)
  const [whole, frac = ''] = s.replace(/^\+/, '').split('.')
  const scaled = BigInt((whole || '0') + (frac + '000').slice(0, 2)) + (Number((frac + '000')[2]) >= 5 ? 1n : 0n)
  const digits = scaled.toString().padStart(3, '0')
  return `${digits.slice(0, -2)}.${digits.slice(-2)}`
}

/** Python f'{number:g}': 6 significant digits, trailing zeros stripped. */
function pyG(n: number): string {
  if (n === 0) return Object.is(n, -0) ? '-0' : '0'
  const [mantissa, exp] = n.toExponential(5).split('e')
  const x = Number(exp)
  const strip = (m: string) => (m.includes('.') ? m.replace(/0+$/, '').replace(/\.$/, '') : m)
  if (x < -4 || x >= 6) return `${strip(mantissa)}e${x < 0 ? '-' : '+'}${String(Math.abs(x)).padStart(2, '0')}`
  return strip(n.toFixed(Math.max(0, 5 - x)))
}

function showParam(name: string, value: unknown): string {
  if (name === 'price') return cents(value) ?? pyStr(value)
  if (name === 'date') {
    const ok = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value))
    return ok ? (value as string) : pyStr(value)
  }
  if (name === 'value') {
    const n = typeof value === 'number' ? value : NaN
    return Number.isFinite(n) ? pyG(n) : pyStr(value)
  }
  return pyStr(value)
}

/** Page text of a condition: the registry template filled with its params (backend `conditions.describe`). */
export function conditionText(kind: string, params: Record<string, unknown> | null | undefined): string {
  const def = CONDITION_TEMPLATES[kind]
  if (!def) return String(kind)
  return def.params.reduce((text, name) => text.replace(`{${name}}`, showParam(name, (params ?? {})[name])), def.text)
}

// --- messages ---

/** Reason text of a failed revision (`detail.revision_status` = '<status>: <reason>'). */
export function revisionReasonText(status: string): string {
  const [head, ...rest] = status.split(': ')
  const tail = rest.join(': ')
  if (head === 'plan_invalid') return `${AGENT_REASON_TEXT.plan_invalid}${tail ? `：${tail}` : ''}`
  const reason = tail || head
  return AGENT_REASON_TEXT[reason] ?? reason
}

/** 「Agent 建议修订，但修订未通过校验（原因），当前仍为第 n 版」 for a revise without a new version; else null. */
export function revisionFailureText(
  review: { outcome: string; new_plan_id?: string | null; revision_status?: string | null } | null | undefined,
  versionNo: number,
): string | null {
  if (!review || review.outcome !== 'revise' || review.new_plan_id || !review.revision_status) return null
  return `Agent 建议修订，但修订未通过校验（${revisionReasonText(review.revision_status)}），当前仍为第 ${versionNo} 版`
}

/** A recheck runs a review and possibly a revision: poll as long as the other long jobs (15 min). */
export const RECHECK_POLL_MS = 900_000
export const RECHECK_PENDING_TEXT = '复查仍在后台进行，稍后刷新查看'
export const isRunTimeout = (error: unknown) => error instanceof Error && error.message === 'run timeout'

/** Page text of a finished recheck run (`/api/runs/<id>`): the outcome, plus the reason when skipped / error. */
export function recheckDoneText(run: { status: string; result?: unknown; error?: string }): string {
  if (run.status !== 'done') return `复查失败：${recheckConflictText(run.error ?? '未知原因')}`
  const row = (run.result ?? {}) as { outcome?: Outcome; reason?: string | null }
  const outcome = row.outcome ? OUTCOME_TEXT[row.outcome] ?? row.outcome : '已完成'
  const why = (row.outcome === 'skipped' || row.outcome === 'error') && row.reason
    ? `（${AGENT_REASON_TEXT[row.reason] ?? row.reason}）` : ''
  return `复查完成：${outcome}${why}`
}

/** 409 reasons of POST …/recheck in Chinese. */
export function recheckConflictText(reason: string): string {
  if (reason === 'chain_not_active') return '这条链不在入场期或持仓期'
  if (reason.startsWith('chain_exiting')) return CHAIN_EXITING_TEXT
  if (reason.startsWith('agent_unavailable')) {
    const why = reason.split(':').slice(1).join(':').trim()
    return `Agent 不可用${why ? `：${AGENT_REASON_TEXT[why] ?? why}` : ''}`
  }
  return AGENT_REASON_TEXT[reason] ?? reason
}

/** Text of a host diff side: entry pairs, condition lists and thesis lists rendered for reading. */
export function diffValueText(field: string, value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (field === 'entry_type' && typeof value === 'string') return ENTRY_TYPE_TEXT[value as EntryType] ?? value
  if (Array.isArray(value)) {
    if (field === 'invalidation' || field === 'review_when')
      return value.map(c => conditionText((c as Condition)?.kind, (c as Condition)?.params)).join('；') || '无'
    return value.map(v => String(v)).join(field === 'entry' ? '–' : '；') || '无'
  }
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

export const isCallRef = (ref: string) => ref.startsWith('call:')

/** §6.1 / 10.2: a review whose host verdict ended a holding chain reads as an exit instruction, not 「作废」. */
export const isExitReview = (r: Pick<PlanReview, 'mode' | 'outcome' | 'timeline_version'>) =>
  r.mode === 'holding' && r.outcome === 'invalidate' && r.timeline_version === 'timeline-2'

/** Plan page review head: 「再次触发（<规则>，<信号日>）→ 直接修订」 for `via = retrigger` (spec §10.2). */
export function retriggerText(r: PlanReview, retriggers: RowRetrigger[] | undefined, ruleLabel: (id: string) => string): string {
  const hit = (retriggers ?? []).find(x => x.unit_signal_date === r.session)
  const rules = hit?.rule_ids?.length ? hit.rule_ids.map(ruleLabel).join('、') : ''
  const inner = hit ? `（${rules ? `${rules}，` : ''}${hit.unit_signal_date}）` : ''
  return `再次触发${inner}→ 直接修订`
}

/** The Agent block of one version of a chain (plan page and 「今日」 row expansion). */
export function versionAgentView(chain: Chain, v: Version): AgentView {
  const r = [...(chain.reviews ?? [])].reverse()
    .find(x => x.head_plan_id === v.plan_id && ['maintain', 'revise', 'invalidate'].includes(x.outcome)) ?? null
  return {
    id: v.run.id, status: v.run.status === 'pass' ? 'pass' : 'ok', model: v.run.model,
    agent_version: v.run.agent_version, output: v.run.output, counter: v.run.counter, plan: v.plan,
    input_tokens: v.run.input_tokens, output_tokens: v.run.output_tokens, created_at: v.created_at,
    chain: {
      version_no: v.version_no, head_plan_id: chain.head_plan_id,
      // 只有最新版带链状态（作废只作用于最新版）；旧版按入场期展示。
      state: v.is_head ? chain.state.state : 'entry', mode: chain.state.mode, basis: chain.state.basis,
      latest_review: r ? { ...r, revision_status: (r.detail?.revision_status as string | undefined) ?? null,
                           conditions: r.conditions ?? [] } : null,
      cutoff_at: v.cutoff_at, diff: v.diff,
    },
    knowledge_refs: v.knowledge_refs ?? [],
  } as AgentView
}
