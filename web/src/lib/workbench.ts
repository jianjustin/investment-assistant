/** US workbench API client and pure helpers (design 2026-10-23). */

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
export interface Unit {
  ticker: string; signal_date: string; proposed_action: Action; labels: string[]; candidate_ids: string[]
  rule_ids: string[]; entry_passed: boolean; market_status: string | null; holding: boolean
  candidates: Candidate[]; brief: Brief | null; filings: Filing[]; news: NewsItem[]; position: Position | null
}
export interface TodayView { session: string; units: Unit[] }
export interface Decision {
  id: string; ticker: string; signal_date: string; proposed_action: Action; final_action: FinalAction
  decision: Choice; reason: string; decided_at: string; supersedes_id: string | null
}
export interface Trade {
  id: string; ticker: string; side: 'buy' | 'sell'; quantity: number; price: number; fee: number
  executed_at: string; decision_id: string | null; note: string | null; recorded_at: string
  voided_at: string | null; void_reason: string | null
}
export interface InstrumentView {
  ticker: string; session: string; bars: any[]; filings: Filing[]; news: NewsItem[]; candidates: Candidate[]
  decisions: Decision[]; trades: Trade[]; position: Position | null; closed: any[]
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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

export function describeError(error: unknown): string {
  if (error instanceof WorkbenchError) {
    if (error.status === 503) return `数据库未就绪：${error.message}`
    if (error.status === 409) return `已有更新的记录，请刷新后基于最新记录操作（${error.message}）`
    if (error.status === 400) return `输入有误：${error.message}`
  }
  return `请求失败：${error instanceof Error ? error.message : String(error)}`
}

export const newRequestId = () => crypto.randomUUID()

export function finalAction(proposed: Action, choice: Choice): FinalAction {
  return choice === 'accept' ? proposed : choice === 'reject' ? 'ignore' : 'watch'
}

export function decisionPayload(unit: Unit, choice: Choice, reason: string, requestId: string) {
  return {
    request_id: requestId, ticker: unit.ticker, signal_date: unit.signal_date, candidate_ids: unit.candidate_ids,
    brief_id: unit.brief && unit.brief.status !== 'error' ? unit.brief.id : null,
    proposed_action: unit.proposed_action, final_action: finalAction(unit.proposed_action, choice),
    decision: choice, reason: reason.trim(),
  }
}

export const RULE_LABELS: Record<string, string> = {
  trend_reclaim: '趋势回踩修复', volume_breakout: '放量突破', earnings_gap_up: '财报跳空向上',
  trend_break: '跌破 MA50', earnings_gap_down: '财报跳空向下', position_drawdown: '持仓回撤',
  new_filing: '新财报', abnormal_move: '异常波动',
}
export const ACTION_LABELS: Record<string, string> = { buy: '买入', sell: '卖出', watch: '观察', ignore: '忽略' }
export const UNIT_LABELS: Record<string, string> = { conflict: '冲突', avoid: '回避' }
export const CHOICE_LABELS: Record<Choice, string> = { accept: '采纳', reject: '否决', downgrade: '降级为观察' }

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
