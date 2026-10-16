export async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: 'application/json' }, cache: 'no-store' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
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
export const getMarketSignals = (limit = 90) => get<unknown>(`/api/market/signals?limit=${limit}`)
export const getMarketSignalsLatest = () => get<unknown>('/api/market/signals/latest')
export const getMarketSignalsTrend = (window = 30) => get<unknown>(`/api/market/signals/trend?window=${window}`)
export const getTickerTrends = () => get<unknown>('/api/tickers/trends')
export const scanTickerTrends = (body: object) => post<unknown>('/api/tickers/trends/scan', body)
export const getStrategyScores = () => get<unknown>('/api/strategies/scores')
export const runStrategyScores = (body: object) => post<unknown>('/api/strategies/scores/run', body)
export const getMacroAnalysis = (window = 30) => get<unknown>(`/api/hermes/macro-analysis?window=${window}`)
export const getHermes = () => get<unknown>('/api/hermes')
export const getHermesAgents = () => get<unknown>('/api/hermes/agents')
export const getWatchlist = (market?: 'CN' | 'US', enriched = false) => {
  const query = new URLSearchParams()
  if (market) query.set('market', market)
  if (enriched) query.set('enriched', 'true')
  return get<unknown>(`/api/watchlist${query.size ? '?' + query : ''}`)
}
export const addWatchlistItem = (body: object) => post<unknown>('/api/watchlist', body)
export const deleteWatchlistItem = (ticker: string) => del<unknown>(`/api/watchlist/${ticker}`)
export const runMacroLlm = (body: object) => post<{ run_id: string; status: string }>('/api/hermes/macro-analysis/run', body)
export const runDecisionEvidence = (body: object) => post<{ run_id: string; status: string }>('/api/hermes/decision-evidence/run', body)
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

// settings
export const getNotifySettings = () => get<any>('/api/settings/notify')
export const patchNotifySettings = (body: object) => patch<unknown>('/api/settings/notify', body)
export const testNotifyChannel = (body: object) =>
  post<{ ok: boolean; error?: string }>('/api/settings/notify/test', body)
export const getEnvStatus = () => get<Record<string, boolean>>('/api/settings/env')

// research
export const getEventStudyKinds = () => get<{ kinds: string[] }>('/api/research/event-study/kinds')
export const getEventStudy = (kind: string, since?: string, asof?: string) =>
  get<{ result: any; degraded: boolean; source: string }>(
    `/api/research/event-study?kind=${kind}${since ? `&since=${since}` : ''}${asof ? `&asof=${asof}` : ''}`,
  )

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

// ticker ohlcv
export interface Bar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}
export interface OhlcvResponse {
  ticker: string
  bars: Bar[]
  ma20: (number | null)[]
  ma50: (number | null)[]
  ma200: (number | null)[]
}
export const getTickerOhlcv = (ticker: string, days = 250) =>
  get<OhlcvResponse>(`/api/tickers/${ticker}/ohlcv?days=${days}`)

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
