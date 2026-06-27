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
export const getFilings = () => get<unknown>('/api/filings')
export const getOperations = () => get<unknown>('/api/operations')
export const getMarketSignals = (limit = 90) => get<unknown>(`/api/market/signals?limit=${limit}`)
export const getMarketSignalsLatest = () => get<unknown>('/api/market/signals/latest')
export const getMarketSignalsTrend = (window = 30) => get<unknown>(`/api/market/signals/trend?window=${window}`)
export const fetchMarketSignals = (body: object) => post<unknown>('/api/market/signals/fetch', body)
export const getTickerTrends = () => get<unknown>('/api/tickers/trends')
export const scanTickerTrends = (body: object) => post<unknown>('/api/tickers/trends/scan', body)
export const getStrategyScores = () => get<unknown>('/api/strategies/scores')
export const runStrategyScores = (body: object) => post<unknown>('/api/strategies/scores/run', body)
export const getMacroAnalysis = (window = 30) => get<unknown>(`/api/hermes/macro-analysis?window=${window}`)
export const getHermes = () => get<unknown>('/api/hermes')
export const getHermesAgents = () => get<unknown>('/api/hermes/agents')
export const getWatchlist = () => get<unknown>('/api/watchlist')
export const addWatchlistItem = (body: object) => post<unknown>('/api/watchlist', body)
export const deleteWatchlistItem = (ticker: string) => del<unknown>(`/api/watchlist/${ticker}`)
export const runMacroLlm = (body: object) => post<{ run_id: string; status: string }>('/api/hermes/macro-analysis/run', body)
export const runDecisionEvidence = (body: object) => post<{ run_id: string; status: string }>('/api/hermes/decision-evidence/run', body)
export const getRun = (runId: string) => get<RunRecord>(`/api/runs/${runId}`)
