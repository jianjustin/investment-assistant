// Types and display rules for the Data menu (design 2026-10-26 §4/§8/§9).
// The backend's data_view owns the payload; these mirror its shapes verbatim.

export const KNOWN_FAMILIES = ['bars', 'sec_filings', 'news', 'atr', 'fred', 'universe'] as const
export type FamilyId = (typeof KNOWN_FAMILIES)[number]

export interface FamilyJob {
  name: string
  enabled: boolean
  next_run_at: string | null
}

export interface FamilyCoverage {
  targets: number
  covered: number
  lagging: string[]
}

export interface FetchFailure {
  target: string
  reason: string
}

/** The card's last_run: the row the backend trims to §8's display fields. */
export interface LastRun {
  status: string
  trigger: string
  scope: string
  ticker: string | null
  job: string                  // the task path this run actually went through
  reason: string | null        // skipped reason (detail.reason), shown as-is
  finished_at: string | null
  ok_count: number
  target_count: number
  failures: FetchFailure[]
}

export interface FamilyCard {
  id: FamilyId
  title: string
  purpose: string
  kind: 'fetched' | 'derived' | 'manual'
  fetch_via: string | null   // derived families fetch through another family
  per_ticker: boolean
  job: FamilyJob | null
  coverage: FamilyCoverage
  latest_at: string | null
  coverage_note: string      // one sentence on what this family's coverage counts
  last_run: LastRun | null
  last_success_at: string | null
  evidence: string
  notes: string[]
  current_error: string | null   // e.g. the universe file's current load error
  fetch_runs_ready: boolean
}

export interface DataOverview {
  session: string
  evidence: string
  fetch_runs_ready: boolean
  families: FamilyCard[]
}

export interface FetchRun {
  id: number
  created_at: string
  family: string
  job: string
  trigger: string
  run_id: string | null
  scope: string
  ticker: string | null
  session: string
  status: string
  target_count: number
  ok_count: number
  failures: FetchFailure[]
  detail: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
}

export interface DetailRow {
  target: string
  latest_at: string | null
  lagging: boolean
  last_failure: string | null
}

export interface FamilyDetail {
  card: FamilyCard
  runs: FetchRun[]
  rows: DetailRow[]
}

/** Raw values over each family's fixed browse window; the row shape varies per family. */
export interface BrowseResult {
  family: string
  key: string | null
  has_data: boolean
  rows: Record<string, unknown>[] | number
  note?: string
  filings?: Record<string, unknown>[]
  sec_8k?: Record<string, unknown>[]
  meta?: Record<string, unknown> | null
  notes?: string[]
  current_error?: string | null   // e.g. why the universe file cannot load right now
}

export function kindLabel(kind: string): string {
  const labels: Record<string, string> = { fetched: '采集', derived: '派生', manual: '手动维护' }
  return labels[kind] ?? kind
}

export function triggerLabel(trigger: string): string {
  const labels: Record<string, string> = {
    scheduled: '定时', manual_batch: '手动批处理', manual_family: '手动拉取',
  }
  return labels[trigger] ?? trigger
}

export function fetchButtonLabel(card: Pick<FamilyCard, 'id'>): string {
  if (card.id === 'atr') return '拉取日线'
  if (card.id === 'universe') return '重新加载'
  return '拉取'
}

/** Derived families are fetched through the family they are computed from. */
export function fetchTarget(card: Pick<FamilyCard, 'id' | 'fetch_via'>): string {
  return card.fetch_via ?? card.id
}

const NOTE_TEXT: Record<string, string> = {
  universe_stale: '范围文件超过 120 天未更新',
  no_filing_is_not_missing: '无申报 ≠ 缺数据',
  pool_empty: '关注列表中没有可用的池标的',
  pool_invalid: '观察池配置非法（超限或标签无效），无法确定目标清单',
  universe_unavailable: '范围文件不可读或非法',
}

export function noteText(note: string): string {
  return NOTE_TEXT[note] ?? note
}
