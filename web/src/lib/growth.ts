import { AGENT_REASON_TEXT, newRequestId, rText, WorkbenchError } from './workbench'

/** v2.7 growth loop on the front end (spec docs/specs/2026-10-28-v2.7-growth-loop-design.md §4–§8, §13):
 *  shapes of review cards, my knowledge and plan discussions, plus the texts that must match the backend verbatim. */

// ---- review cards (spec §4) ----

export type EndKind = 'position_closed' | 'stop' | 'target' | 'expired' | 'invalidated'
export type ExitBasis = 'stop' | 'target' | 'other'
export type CardStatus = 'reviewed' | 'to_review' | 'draft_failed' | 'drafting'
export type DisciplineFlag = 'chase' | 'early_take' | 'held_loser' | 'unplanned'

/** One row of GET /review-cards (spec §4.7). `flags` are the settled flags, `immature` the ones still pending. */
export interface ReviewCardRow {
  id: number; ticker: string; subject: 'unit' | 'trade'; signal_date: string | null
  end_kind: EndKind; exit_basis: ExitBasis | null; end_session: string
  decision_text: string; actual_r: number | null; filled?: boolean; rule_r: number | null; agent_r: number | null
  // retro-2 (v2.9 D29): the sentence is the execution state; retro-1 rows only carry `decision_text`
  execution_text?: string | null
  flags: string[]; immature: string[]; status: CardStatus; headline: string | null
}
export interface ReviewCardsView { cards: ReviewCardRow[]; counts: Partial<Record<CardStatus, number>> }

export interface FactPlan {
  key: string; kind: 'rule' | 'own' | 'agent'; version_no: number | null; origin: string | null
  levels: { entry_low: string; entry_high: string; stop: string; target1: string }
  valid_from: string; valid_until: string; cutoff_at: string | null; status: string; invalid_reasons: string[]
  roles: ('reference' | 'executed' | 'seen_at_decision' | 'first' | 'head')[]
}
export interface FactLeg { fraction: number; exit_date: string; exit_price: string | number; reason: string }
export interface FactShadow {
  status: string; fill_date: string | null; fill_price: string | number | null; legs: FactLeg[]; r: number | null
}
export interface FactTrack {
  status: string; status_text: string; r: number | null; plan_id: string | null
  version_no?: number | null; version_basis?: string | null; plan_kind?: string | null
}
export interface FactDiscipline {
  trades: { trade_id: string; flags: string[]; immature: string[] }[]
  totals: { chase: number; early_take: number; held_loser: number; unplanned: number; pending: number }
  as_of: string
}
/** retro-2 `facts.execution` (spec §6.3): the execution state, the plan followed, the notes at card time and any old decision. */
export interface FactExecution {
  status: string; text: string; plan_kind?: string | null; plan_id?: string | null; version_no?: number | null
  notes?: { id: number; body: string; created_at: string }[]
  legacy_decision?: {
    text: string; decision?: string | null; final_action?: string | null; reason?: string | null; decided_at?: string | null
    plan_id?: string | null; agent_plan_id?: string | null
  } | null
  first_fill?: { executed_at: string; quantity: string | number; price: string | number } | null
  follow?: string | null; trade_ids?: string[]
}
/** retro-2 `facts.holding` (retro.holding_fact): days held, the first exit instruction and the day the shares were sold. */
export interface FactHolding {
  held_sessions: number | null; exit?: { session: string; reason: string | null } | null
  sell_date?: string | null; sold_before_exit?: boolean
}
export interface Facts {
  subject: {
    kind: 'unit' | 'trade'; ticker: string; signal_date: string | null; pool: string; end_kind: EndKind
    end_text: string; end_session: string; exit_basis: ExitBasis | null; buy_trade_id?: string
  }
  plans: FactPlan[]
  bars_after: {
    first_day: string | null; last_day: string | null; sessions: number; high: string | number | null
    high_date: string | null; low: string | number | null; low_date: string | null; close_end: string | number | null
    per_plan: { key: string; entry_touched: string | null; stop_touched_on: string | null; t1_touched_on: string | null }[]
  }
  shadow: Record<string, FactShadow>
  tracks: { rule?: FactTrack; agent?: FactTrack; actual: FactTrack }
  // retro-1 cards freeze `decision`; retro-2 cards (v2.9 D29) freeze `execution` and `holding` instead
  decision?: {
    decision: string | null; final_action: string | null; plan_kind: string | null; plan_id: string | null
    agent_plan_id: string | null; agent_version_no: number | null; reason: string | null
    decided_at: string | null; text: string
  }
  execution?: FactExecution
  holding?: FactHolding | null
  trades: {
    trades: { id: string; side: 'buy' | 'sell'; quantity: string | number; price: string | number; fee: string | number; executed_at: string }[]
    segments: { buy_trade_id: string; sell_trade_id: string; quantity: string | number; r?: number | null }[]
    actual_r: number | null
  }
  discipline: FactDiscipline
  reviews: {
    count: number; outcomes: Record<string, number>
    invalidated: { session: string; reason: string | null; decided_by: string | null } | null
  } | null
  knowledge: { ref: string; title_at_version: string; fields: string[] }[]
}

export interface Ref { text: string; refs: string[] }
export interface LessonDraft {
  title: string; body: string; scope: string; counter_examples: string
  concepts: string[]; tickers: string[]; refs: string[]
}
/** The `output` of an ok review_card_drafts row (spec §4.4). */
export interface CardDraft {
  // agent-retro-2 writes 「你的执行」; older drafts keep `decision_review`
  headline: string; expected_vs_actual: Ref[]; decision_review?: Ref; execution_review?: Ref; lessons: LessonDraft[]
}
export interface CardDraftRow {
  id: number; attempt: number; trigger: 'batch' | 'manual'; agent_run_id: string | null
  status: 'ok' | 'rejected' | 'error' | 'skipped'; reason: string | null; output: CardDraft | null; created_at: string
}
/** A knowledge_drafts row from a card draft, as GET /review-cards/{id} lists it (`id` = draft_id). */
export interface LessonDraftRow extends LessonDraft { id: number; lesson_index: number }

export type VerdictAction = 'approve' | 'dismiss'
export interface CardVerdictLessonInput {
  draft_id?: number; action: VerdictAction
  title: string; body: string; scope: string; counter_examples: string; concepts: string[]; tickers: string[]
}
export interface CardVerdictInput { request_id: string; note: string; lessons: CardVerdictLessonInput[] }
export interface CardVerdict {
  note: string; created_at: string
  lessons: { draft_id: number | null; action: VerdictAction; title: string; ref: string | null }[]
}
export interface DiscussionListItem { id: number; created_at: string; turn_count: number; first_question: string | null }
export interface ReviewCardView {
  card: {
    id: number; event_key: string; subject: 'unit' | 'trade'; ticker: string; signal_date: string | null
    end_kind: EndKind; end_session: string; created_at: string
    /** any live buy on the subject (older payloads omit it) */
    filled?: boolean
  }
  facts: Facts; status: CardStatus; drafts: CardDraftRow[]; lesson_drafts: LessonDraftRow[]
  verdict: CardVerdict | null; discipline_now: FactDiscipline; discussions: DiscussionListItem[]
}

// ---- my knowledge (spec §5, §7) ----

export interface KnowledgeValues {
  title: string; body: string; scope: string; counter_examples: string; concepts: string[]; tickers: string[]
}
/** One knowledge version; `concepts` read back as `concept:<id>@<version>`, written as plain ids. */
export interface KnowledgeVersion extends KnowledgeValues {
  id: number; knowledge_id: number; version: number; supersedes_id: number | null
  draft_id: number | null; created_at: string
}
export interface KnowledgeEntry {
  id: number; origin: 'manual' | 'review_card' | 'discussion'; title: string; scope: string
  concepts: string[]; tickers: string[]; current_version: number; status: 'active' | 'archived'
  written_at: string; updated_at: string; citation_count: number; sample_count: number
}
export interface KnowledgeCitation {
  ticker: string; signal_date: string; plan_id: string | null; head_plan_id: string | null
  version_no: number | null; review_id: number | null; cited_version: number; field: string
}
export interface KnowledgeStatusRow { status: 'active' | 'archived'; reason: string; created_at: string }
export interface KnowledgeItemView {
  item: {
    id: number; origin: 'manual' | 'review_card' | 'discussion'; source_card_id: number | null
    source_discussion_id: number | null; created_at: string; status?: 'active' | 'archived'
  }
  versions: KnowledgeVersion[]; status_history: KnowledgeStatusRow[]; citations: KnowledgeCitation[]
  current: KnowledgeVersion
}
export interface KnowledgeDraft extends KnowledgeValues {
  id: number; origin: 'review_card' | 'discussion'; card_id: number | null; discussion_id: number | null
  discussion_turn_id: number | null; target_knowledge_id: number | null; target_version: number | null
  /** newest version of the target item now; the draft is stale when it differs from `target_version` */
  target_current_version: number | null
  refs: string[]; created_at: string
  verdict: { action: VerdictAction; ref: string | null } | null
}
/** A discussion draft that rewrites a version which is no longer the newest cannot be adopted (the same sentence the
 *  backend answers with, 409 `knowledge_stale`): only dismiss it, or rewrite it again in the discussion. */
export function staleDraftText(d: Pick<KnowledgeDraft, 'target_knowledge_id' | 'target_version' | 'target_current_version'>): string | null {
  if (d.target_knowledge_id == null || d.target_version == null || d.target_current_version == null) return null
  if (d.target_current_version === d.target_version) return null
  return `草稿基于第 ${d.target_version} 版，现在是第 ${d.target_current_version} 版：只能不采纳，或在讨论里基于第 ${d.target_current_version} 版重新改写`
}
export interface KnowledgeDraftInput extends Partial<KnowledgeValues> {
  request_id: string; action: VerdictAction; base_version?: number
}
export interface KnowledgePerfBlock {
  count: number; determined: number; expired: number; r_mean: number | null; r_median: number | null
}
export interface KnowledgePerf {
  calc_version: string; sample: KnowledgePerfBlock; min_sample: number; note: string
  rows: {
    unit: { ticker: string; signal_date: string }; plan_id: string; kind: string; version_no: number | null
    cited_version: number; fields: string[]; status: string; status_text: string; r: number | null
    fill_date: string | null; outcome_date: string | null
  }[]
  by_version: { version: number; plans: number; units: number }[]
  reviews_cited: number
}
/** `knowledge_refs` of a plan version (spec §6.2). */
export interface KnowledgeRefItem { ref: string; title: string; fields?: string[]; current_version: number }

// ---- discussions (spec §8) ----

export type DiscussionContext = { kind: 'plan'; plan_id: string } | { kind: 'card'; card_id: number }
export type TurnWait = 'pending' | 'interrupted'
export interface DiscussionAttachment { kind: 'draft' | 'knowledge'; id: number; version?: number }
export interface DiscussionTurn {
  id: number; seq: number; role: 'user' | 'assistant'; body: string; created_at: string
  // user turns
  request_id?: string; attachment?: (DiscussionAttachment & { title?: string }) | null
  state?: TurnWait | null; user_input_id?: number | null
  // assistant turns
  status?: 'ok' | 'rejected' | 'error' | 'skipped'; reason?: string | null; refs?: string[]
  agent_run_id?: string | null; cutoff_at?: string | null; detail?: Record<string, unknown> | null
  knowledge_draft?: KnowledgeDraft | null
}
export interface Discussion {
  id: number; context_kind: 'plan' | 'card'; ticker: string; signal_date: string
  plan_id: string | null; card_id: number | null; created_at: string
  context?: {
    version_no?: number | null; generated_at?: string | null; cutoff_at?: string | null
    end_kind?: EndKind | null; end_session?: string | null
  } | null
  turns: DiscussionTurn[]
}

// ---- weekly review-7 `stats.learning` (spec §10) ----

export interface WeeklyLearning {
  discipline: { cards: number; chase: number; early_take: number; held_loser: number; unplanned: number; pending: number }
  cards: {
    card_id: number; ticker: string; end_kind: EndKind; end_text: string; decision_text: string; execution_text?: string | null
    actual_r: number | null; filled?: boolean; rule_r: number | null; agent_r: number | null; flags: string[]
    status: CardStatus; headline: string | null
  }[]
  counts: { total: number; reviewed: number; to_review: number; drafting: number; draft_failed: number }
  knowledge: { ref: string; title: string; new_outcomes: number; sample: KnowledgePerfBlock }[]
}

// =====================================================================================================
// texts (verbatim from the backend; the cross-language test of Task 5 pins them)
// =====================================================================================================

/** retro.END_TEXT (spec §4.1). */
export const END_TEXT: Record<string, string> = {
  position_closed: '平仓', stop: '止损', target: '到 T1', expired: '过期未成交', invalidated: '作废',
}
/** retro exit_basis texts, appended to a closed position as 「（按止损）」 etc. (spec §4.1). */
export const EXIT_BASIS_TEXT: Record<string, string> = { stop: '按止损', target: '到 T1 后', other: '自行卖出' }
/** retro.card_status texts (spec §4.6). */
export const CARD_STATUS_TEXT: Record<string, string> = {
  reviewed: '已审定', to_review: '待审定', draft_failed: '起草失败（可手动审定或重新起草）', drafting: '起草中',
}
/** retro.DECISION_TEXT (spec §4.3); `{n}` is the Agent version number. The backend sends the finished sentence
 *  (`decision_text`, `facts.decision.text`); this table is what Task 5 compares against retro.DECISION_TEXT. */
export const DECISION_TEXT = {
  accept_rule: '采纳（照规则计划）', accept_agent: '采纳（照 Agent 第 {n} 版）', accept_agent_legacy: '采纳（照 Agent agent-1）',
  accept_own: '自改价位', reject: '否决', downgrade: '降为观察', none: '未决定（计划外成交）',
  accept: '采纳',                                   // accepted, but the executed plan is unknown
} as const
/** retro.BASIS_TEXT: which Agent version a track follows (`facts.tracks.agent.version_basis` is the code). */
export const VERSION_BASIS_TEXT: Record<string, string> = { decision: '决定时看到的版本', first: '首版' }
/** retro.BASIS_TEXT_V2: tracks-2 adds `fill` (the version the buy trade was linked to) and `merged` (v2.9 D27). */
export const VERSION_BASIS_TEXT_V2: Record<string, string> = { ...VERSION_BASIS_TEXT, fill: '成交时关联的版本', merged: '并入其他链' }
/** The four discipline flags and 「待定」 (spec §4.3, §13). */
export const DISCIPLINE_TEXT: Record<string, string> = {
  chase: '追高', early_take: '过早止盈', held_loser: '死扛亏损', unplanned: '计划外', pending: '待定',
}
export const DISCIPLINE_FLAGS: DisciplineFlag[] = ['chase', 'early_take', 'held_loser', 'unplanned']
/** What an immature flag waits for (spec §4.3). */
export const PENDING_TEXT: Record<string, string> = {
  early_take: '待定（卖出后 20 个交易日才能判定）', held_loser: '待定（止损次日之后判定）',
}
export const FACT_KEYS = ['subject', 'plans', 'bars_after', 'shadow', 'tracks', 'decision', 'execution', 'holding', 'trades',
                          'discipline', 'reviews', 'knowledge'] as const
export const ROLE_TEXT: Record<string, string> = {
  reference: '参考计划', executed: '执行的计划', seen_at_decision: '决定时看到', first: '首版', head: '最新版',
}
/** Where in a plan version a knowledge entry was cited (knowledge_citations.field). */
export const CITED_FIELD_TEXT: Record<string, string> = {
  thesis: '论点', invalidation: '失效条件', changes: '变化说明', counter: '反证', risks: '其他风险', review: '复查结论',
}
export const KNOWLEDGE_ORIGIN_TEXT: Record<string, string> = { manual: '手写', review_card: '复盘卡', discussion: '讨论' }
export const KNOWLEDGE_FIELD_TEXT: Record<string, string> = {
  title: '标题', body: '正文', scope: '适用范围', counter_examples: '反例', concepts: '概念', tickers: '标的',
}
export const KNOWLEDGE_STATUS_TEXT: Record<string, string> = { active: '有效', archived: '已归档' }

/** The page polls a discussion every 2 s, for at most this long (spec §8.2 step 3). */
export const DISCUSS_POLL_MS = 600_000
export const DISCUSS_POLL_INTERVAL_MS = 2000
export const DISCUSS_TIMEOUT_TEXT = '回答仍在后台生成，稍后刷新查看'
export const DISCUSS_INTERRUPTED_TEXT = '没有收到回答（服务可能重启过），可以再问一次'
/** A redraft run is a retro run: poll as long as a draft may take (batch deadline is 25 min per stage). */
export const REDRAFT_POLL_MS = 300_000
export const REDRAFT_PENDING_TEXT = '仍在后台起草，稍后刷新查看'

// =====================================================================================================
// knowledge references
// =====================================================================================================

const KNOW_REF = /^know:([1-9][0-9]*)(?:@([1-9][0-9]*))?$/

export function parseKnowRef(ref: string): { id: number; version: number | null } | null {
  const m = KNOW_REF.exec(ref)
  return m ? { id: Number(m[1]), version: m[2] ? Number(m[2]) : null } : null
}
export const isKnowRef = (ref: string): boolean => KNOW_REF.test(ref)

/** `know:3@2` -> `#knowledge/mine/3@2` (the version page); anything else lands on the list. */
export function knowHref(ref: string): string {
  const parsed = parseKnowRef(ref)
  if (!parsed) return '#knowledge/mine'
  return `#knowledge/mine/${parsed.id}${parsed.version ? `@${parsed.version}` : ''}`
}

export type RefKind = 'call' | 'fact' | 'know' | 'concept' | 'user' | 'other'
export function refKind(ref: string): RefKind {
  if (ref.startsWith('call:')) return 'call'
  if (ref.startsWith('fact:')) return 'fact'
  if (isKnowRef(ref)) return 'know'
  if (ref.startsWith('concept:')) return 'concept'
  if (ref.startsWith('user:')) return 'user'
  return 'other'
}
/** `concept:plan.stop@1` or `plan.stop` -> `plan.stop`. */
export const conceptId = (ref: string): string => ref.replace(/^concept:/, '').split('@')[0]

/** 「平仓」 / 「平仓（按止损）」 / 「止损」 … The exit basis only describes a closed position. */
export function endText(kind: string, exitBasis?: string | null): string {
  const base = END_TEXT[kind] ?? kind
  if (kind !== 'position_closed' || !exitBasis) return base
  const basis = EXIT_BASIS_TEXT[exitBasis]
  return basis ? `${base}（${basis}）` : base
}

// =====================================================================================================
// uuid5: the user input a discussion turn was saved as (spec §11 补充说明)
// =====================================================================================================

const NAMESPACE_URL = '6ba7b811-9dad-11d1-80b4-00c04fd430c8'
const hex = (bytes: Uint8Array) => [...bytes].map(b => b.toString(16).padStart(2, '0')).join('')

/** user_inputs.request_id = uuid5(NAMESPACE_URL, 'discussion-turn:' + <the turn's request id>), the same algorithm as
 *  Python's uuid.uuid5 (SHA-1 of namespace bytes + name bytes, version and variant bits set). Async because it
 *  uses crypto.subtle. */
export async function userInputRequestId(turnRequestId: string): Promise<string> {
  const ns = Uint8Array.from(NAMESPACE_URL.replace(/-/g, '').match(/../g)!.map(h => parseInt(h, 16)))
  const name = new TextEncoder().encode(`discussion-turn:${turnRequestId}`)
  const data = new Uint8Array(ns.length + name.length)
  data.set(ns)
  data.set(name, ns.length)
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-1', data)).slice(0, 16)
  digest[6] = (digest[6] & 0x0f) | 0x50
  digest[8] = (digest[8] & 0x3f) | 0x80
  const h = hex(digest)
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

// =====================================================================================================
// knowledge form rules (spec §5.1)
// =====================================================================================================

const chars = (text: string) => [...text.trim()].length
const TICKER = /^[A-Z][A-Z0-9.\-]{0,9}$/
export const normalizeTicker = (text: string) => text.trim().toUpperCase()
export const isTickerLike = (text: string) => TICKER.test(text)

/** The first problem of a knowledge entry as the form would submit it, or null. Lengths count code points. */
export function knowledgeProblem(values: KnowledgeValues, options: { requireCounter?: boolean } = {}): string | null {
  const limit = (label: string, text: string, max: number, required = true): string | null => {
    const n = chars(text)
    if (n === 0) return required ? `${label}不能为空` : null
    return n > max ? `${label}最多 ${max} 字（现在 ${n} 字）` : null
  }
  const title = limit('标题', values.title, 60)
  if (title) return title
  const body = limit('正文', values.body, 4000)
  if (body) return body
  if (chars(values.scope) === 0) return '适用范围必填'
  const scope = limit('适用范围', values.scope, 500)
  if (scope) return scope
  if (options.requireCounter && chars(values.counter_examples) === 0) return '反例必填'
  const counter = limit('反例', values.counter_examples, 1000, false)
  if (counter) return counter
  const attached = values.concepts.length + values.tickers.length
  if (attached < 1 || attached > 10) return `挂靠（概念 + 标的）须为 1–10 项（现在 ${attached} 项）`
  return null
}

/** Which of the six fields differ between two versions, in the form's order. */
export function changedFields(before: KnowledgeValues, after: KnowledgeValues): string[] {
  return (Object.keys(KNOWLEDGE_FIELD_TEXT) as (keyof KnowledgeValues)[]).filter(key => {
    const a = before[key]
    const b = after[key]
    return Array.isArray(a) || Array.isArray(b) ? JSON.stringify(a ?? []) !== JSON.stringify(b ?? []) : (a ?? '') !== (b ?? '')
  }).map(key => KNOWLEDGE_FIELD_TEXT[key])
}

/** 「样本 n 个单元 · 有结果 m · 过期 k · 均值 … · 中位 …」 or the same with 「少于 5 个不给均值」 (spec §7). */
export function sampleLine(block: KnowledgePerfBlock, minSample: number, rText: (r: number | null) => string): string {
  const head = `样本 ${block.count} 个单元 · 有结果 ${block.determined} · 过期 ${block.expired}`
  return block.determined >= minSample && block.r_mean !== null
    ? `${head} · 均值 ${rText(block.r_mean)} · 中位 ${rText(block.r_median)}`
    : `${head} · 少于 ${minSample} 个不给均值`
}

export const truncate = (text: string, n: number) => [...text].slice(0, n).join('')

// =====================================================================================================
// writes: request ids and error texts
// =====================================================================================================

/** A request id that is reused while the payload stays the same (a retry after a failure replays the stored row
 *  instead of writing twice) and renewed when the payload changes or after a success (spec §12). */
export function idempotentRequests() {
  let current: { key: string; id: string } | null = null
  return {
    idFor(payload: unknown): string {
      const key = JSON.stringify(payload)
      if (!current || current.key !== key) current = { key, id: newRequestId() }
      return current.id
    },
    done() { current = null },
  }
}

/** Actual R of a card row: a number; a fill without an R is an unplanned trade; no fill at all is 未成交. */
export function actualRText(row: { actual_r: number | null; filled?: boolean }): string {
  if (row.actual_r !== null) return rText(row.actual_r)
  return row.filled ? '无 R（计划外）' : '未成交'
}

const CONFLICT_TEXT: Record<string, string> = {
  card_reviewed: '这张卡已经审定过了，要改经验请到「我的知识」改版本',
  knowledge_stale: '这条知识已更新，请刷新后再改',
  knowledge_archived: '这条知识已归档，先恢复才能改',
  status_unchanged: '状态没有变化',
  review_on_card: '这是复盘卡的草稿，请到复盘卡上审定',
  request_id_conflict: '同一个提交编号对应了不同内容，请刷新后重试',
  draft_decided: '这条草稿已经审定过了',
}
/** 409 bodies are 「code」 or 「code: sentence」; a sentence from the backend is shown as is. */
export function conflictText(message: string): string {
  const [code, ...rest] = message.split(':')
  const tail = rest.join(':').trim()
  if (code === 'agent_unavailable') return `Agent 不可用${tail ? `：${AGENT_REASON_TEXT[tail] ?? tail}` : ''}`
  if (tail && code in CONFLICT_TEXT) return tail
  return CONFLICT_TEXT[code] ?? AGENT_REASON_TEXT[code] ?? message
}
/** Page text of a failed growth-loop request. Migration 027 missing reads as exactly that sentence. */
export function growthError(error: unknown): string {
  if (error instanceof WorkbenchError) {
    if (error.status === 503) {
      return error.message.includes('迁移 027') || error.message.startsWith('migration_027_missing')
        ? AGENT_REASON_TEXT.migration_027_missing : `数据库未就绪：${error.message}`
    }
    if (error.status === 409) return conflictText(error.message)
    if (error.status === 400) return `输入有误：${error.message}`
    if (error.status === 404) return `不存在：${error.message}`
    return `请求失败：${error.message}`
  }
  return error instanceof Error ? error.message : String(error)
}
/** Replies are either the row itself or `{status, record}`. */
export function unwrapRecord<T>(reply: unknown): T {
  const r = reply as { record?: T } | null
  return (r && typeof r === 'object' && 'record' in r && r.record ? r.record : reply) as T
}
