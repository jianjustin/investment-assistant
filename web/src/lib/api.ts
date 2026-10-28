import type * as df from './data-families'
import type { Derivation, UnitDerivation } from './derivation'
import type { Chain, PlanReview, TickerChain, UserInput, UserInputBody } from './timeline'
import type { ConceptCard, ConceptsView, PrinciplesView, ReasoningView, RunOverviewView } from './knowledge'
import { request as workbenchRequest } from './workbench'
export async function get<T>(path: string, options: { errorDetails?: boolean } = {}): Promise<T> {
  const r = await fetch(path, { headers: { Accept: 'application/json' }, cache: 'no-store' })
  if (!r.ok) {
    let message = `HTTP ${r.status}`
    // Opt in per endpoint so existing GET callers keep their error contract.
    if (options.errorDetails) {
      const data = await r.json().catch(() => null)
      const detail = [data?.error, data?.message, data?.detail].find(
        value => typeof value === 'string' && value.trim(),
      )
      if (detail) message = detail
    }
    throw new Error(message)
  }
  return r.json() as Promise<T>
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json()
  if (!r.ok) throw new Error(data?.error ?? `HTTP ${r.status}`)
  return data as T
}

export async function del<T>(path: string): Promise<T> {
  const r = await fetch(path, { method: 'DELETE', headers: { Accept: 'application/json' } })
  const data = await r.json()
  if (!r.ok) throw new Error(data?.error ?? `HTTP ${r.status}`)
  return data as T
}

export async function patch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json()
  if (!r.ok) throw new Error(data?.error ?? `HTTP ${r.status}`)
  return data as T
}

export async function put<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const data = await r.json()
  if (!r.ok) throw new Error(data?.error ?? `HTTP ${r.status}`)
  return data as T
}

export interface RunRecord {
  run_id: string
  status: 'pending' | 'done' | 'error'
  result?: unknown
  error?: string
}

export async function pollRun(
  runId: string,
  opts: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<RunRecord> {
  const interval = opts.intervalMs ?? 1500
  const deadline = Date.now() + (opts.timeoutMs ?? 120_000)
  for (;;) {
    const rec = await get<RunRecord>(`/api/runs/${runId}`)
    if (rec.status !== 'pending') return rec
    if (Date.now() > deadline) throw new Error('run timeout')
    await new Promise((res) => setTimeout(res, interval))
  }
}

// Convenience wrappers
export const getStatus = () => get<unknown>('/api/status')
export const getRawStatus = () => get<unknown>('/api/raw/status')
export const getHealth = () => get<unknown>('/api/health')
export const getServices = () => get<unknown>('/api/services')
export const getOperations = () => get<unknown>('/api/operations')
export const getWatchlist = (enriched = false) =>
  get<unknown>(`/api/watchlist${enriched ? '?enriched=true' : ''}`)
export const addWatchlistItem = (body: object) => post<unknown>('/api/watchlist', body)
export const deleteWatchlistItem = (ticker: string) => del<unknown>(`/api/watchlist/${ticker}`)
export const getRun = (runId: string) => get<RunRecord>(`/api/runs/${runId}`)

// jobs
export interface SchedulerStatus {
  status: 'up' | 'degraded' | 'down'
  detail: string
  meta: {
    enabled: boolean
    last_tick_at: string | null
    tick_in_progress?: boolean
    tick_started_at?: string | null
    last_tick_failed?: boolean | null
  }
}

export const getScheduledJobs = () =>
  get<{ jobs: any[]; degraded: boolean; scheduler?: SchedulerStatus }>('/api/jobs/scheduled')
export const getJobReports = (task?: string, limit = 50) =>
  get<{ reports: any[]; degraded: boolean }>(
    `/api/jobs/reports?limit=${limit}${task ? `&task=${task}` : ''}`,
  )
export const runJob = (name: string, body: object = {}) =>
  post<{ run_id: string; status: string }>(`/api/jobs/${name}/run`, body)
export const patchScheduledJob = (name: string, body: object) =>
  patch<unknown>(`/api/jobs/scheduled/${name}`, body)

// data families (the Data menu; 503 details opt in so migration notices surface verbatim)
export const getDataFamilies = () =>
  get<df.DataOverview>('/api/data/families', { errorDetails: true })
export const getDataFamily = (id: string) =>
  get<df.FamilyDetail>(`/api/data/families/${encodeURIComponent(id)}`, { errorDetails: true })
export const fetchDataFamily = (id: string, ticker?: string) =>
  post<{ run_id: string; status: string }>(
    `/api/data/families/${encodeURIComponent(id)}/fetch`, ticker ? { ticker } : {})
export const browseData = (id: string, params: { ticker?: string; series?: string } = {}) => {
  const q = new URLSearchParams()
  if (params.ticker) q.set('ticker', params.ticker)
  if (params.series) q.set('series', params.series)
  return get<df.BrowseResult>(
    `/api/data/browse/${encodeURIComponent(id)}?${q.toString()}`, { errorDetails: true })
}

// settings
export const getNotifySettings = () => get<any>('/api/settings/notify')
export const patchNotifySettings = (body: object) => patch<unknown>('/api/settings/notify', body)
export const testNotifyChannel = (body: object) =>
  post<{ ok: boolean; error?: string }>('/api/settings/notify/test', body)
export const getEnvStatus = () => get<Record<string, boolean>>('/api/settings/env')

// filings
export interface FilingRecord {
  id: number
  ticker: string
  form: string
  filing_date: string
  accession_number: string
  primary_document: string
  file_path: string
  downloaded_at: string
  created_at: string
}
export const getFilingRecords = (
  params: { ticker?: string; form?: string; from?: string; to?: string; limit?: number } = {},
) => {
  const q = new URLSearchParams()
  if (params.ticker) q.set('ticker', params.ticker)
  if (params.form) q.set('form', params.form)
  if (params.from) q.set('from', params.from)
  if (params.to) q.set('to', params.to)
  q.set('limit', String(params.limit ?? 100))
  return get<{ records: FilingRecord[]; tickers: string[]; degraded: boolean }>(
    `/api/filings/records?${q.toString()}`,
  )
}
export const filingDownloadUrl = (id: number) => `/api/filings/records/${id}/download`

// ticker bars (chart payload shapes reuse these fields)
export interface Bar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}
// US research values preserve explicit null, source versions and accounting basis.
export interface ResearchSource { source_url?:string; source_locator?:string; source_hash?:string; concept?:string; accession?:string; filed?:string; start?:string; end?:string; [key:string]:unknown }
export interface ResearchMetric { value:number|null; unit:string|null; basis:string|null; method:string; input_ids:(number|string)[]; sources:ResearchSource[]; missing_reason:string|null; [key:string]:any }
export interface FiscalRow { period:string; start:string; end:string; days:number; metrics:Record<string,ResearchMetric>; ttm:Record<string,ResearchMetric>; warnings:string[] }
export interface GuidanceRecord { id:number; metric:string; target_start:string; target_end:string; basis:string; unit:string; low:number; high:number; issued_at:string; source_url:string; source_locator:string; note:string; supersedes_id?:number|null; revision?:number; first_seen_at?:string }
export type GuidanceInput = Omit<GuidanceRecord,'id'|'revision'|'first_seen_at'>
export interface GuidanceComparison { guidance_id:number; metric?:string; target_start?:string; target_end?:string; basis?:string; unit?:string; actual:number|null; status:string; reason:string|null; input_ids?:(number|string)[] }
export interface USResearchView {
 security_id:string; ticker:string; currency:string|null; financials:FiscalRow[];
 market:{bars:any[]; benchmarks:Record<string,any[]>; quote:any; performance:{windows:Record<string,any>;basis?:string;limitations?:string[]};limitations:string[]};
 valuation:Record<string,ResearchMetric>; statuses:any[]; template:{id?:string;question:string;value:null;status:string}[];
 card:any; guidance:{records:GuidanceRecord[];comparisons:GuidanceComparison[];consensus:string;status?:string};filings:any[];
 pit:{strict:boolean;as_of?:string|null;limitation?:string;metadata_scope?:string}
}
export const getUSResearch = (ticker:string,asOf?:string) => get<USResearchView>(`/api/us-research/${encodeURIComponent(ticker)}${asOf?'?'+new URLSearchParams({as_of:asOf}):''}`)
export const syncUSResearch = (ticker:string,retry=false) => post<{run_id:string;status:string}>('/api/us-research/sync',{symbols:[ticker],retry_failed:retry})
export const appendUSGuidance = (ticker:string,body:GuidanceInput) => post<{record:GuidanceRecord}>(`/api/us-research/${encodeURIComponent(ticker)}/guidance`,body)

// derivation views (v2.4): 503 details opt in so the backend reason surfaces verbatim
export const getPlanDerivation = (planId: string) =>
  get<Derivation>(`/api/workbench/plans/${encodeURIComponent(planId)}/derivation`, { errorDetails: true })
export const getUnitDerivation = (ticker: string, signalDate: string) =>
  get<UnitDerivation>(
    `/api/workbench/units/${encodeURIComponent(ticker)}/${encodeURIComponent(signalDate)}/derivation`,
    { errorDetails: true })

// plan timeline (v2.5 §12): workbench errors keep the HTTP status (409 / 503 reasons surface verbatim)
const seg = encodeURIComponent
export const getChain = (ticker: string, signalDate: string) =>
  workbenchRequest<Chain>(`/api/workbench/chains/${seg(ticker)}/${seg(signalDate)}`)
export const getTickerChains = (ticker: string) =>
  workbenchRequest<{ ticker: string; chains: TickerChain[] }>(`/api/workbench/chains?ticker=${seg(ticker)}`)
export const getPlanReviews = (session: string) =>
  workbenchRequest<{ session: string; reviews: PlanReview[] }>(`/api/workbench/plan-reviews?session=${seg(session)}`)
export const recheckChain = (ticker: string, signalDate: string) =>
  workbenchRequest<{ run_id: string; status: 'pending' }>(
    `/api/workbench/chains/${seg(ticker)}/${seg(signalDate)}/recheck`, { method: 'POST' })
export const getUserInputs = (ticker: string, signalDate?: string) =>
  workbenchRequest<{ inputs: UserInput[] }>(
    `/api/workbench/user-inputs?ticker=${seg(ticker)}${signalDate ? `&signal_date=${seg(signalDate)}` : ''}`)
export const postUserInput = (body: UserInputBody) =>
  workbenchRequest<{ status: 'created' | 'replayed'; record: UserInput }>(
    '/api/workbench/user-inputs', { method: 'POST', body: JSON.stringify(body) })

// knowledge layer (v2.6): the knowledge endpoints never touch the database; a 503 carries the card problems
export class KnowledgeError extends Error {
  constructor(message: string, public status: number, public problems: string[] = []) { super(message) }
}
async function knowledgeRequest<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: 'application/json' }, cache: 'no-store' })
  const data = await r.json().catch(() => null)
  if (!r.ok) {
    throw new KnowledgeError(
      typeof data?.error === 'string' && data.error ? data.error : `HTTP ${r.status}`, r.status,
      Array.isArray(data?.problems) ? data.problems.map(String) : [])
  }
  return data as T
}
export const getConcepts = () => knowledgeRequest<ConceptsView>('/api/knowledge/concepts')
export const getConcept = (ref: string) => knowledgeRequest<ConceptCard>(`/api/knowledge/concepts/${seg(ref)}`)
export const getPrinciples = () => knowledgeRequest<PrinciplesView>('/api/knowledge/principles')

// run overview and the Agent reasoning view (v2.6 §7, §8): read-only workbench endpoints
export const getRunOverview = (session?: string, runId?: string) => {
  const q = new URLSearchParams()
  if (session) q.set('session', session)
  if (runId) q.set('run_id', runId)
  const query = q.toString()
  return workbenchRequest<RunOverviewView>(`/api/workbench/run-overview${query ? `?${query}` : ''}`)
}
export const getReasoning = (runId: string) =>
  workbenchRequest<ReasoningView>(`/api/workbench/agent-runs/${seg(runId)}/reasoning`)
