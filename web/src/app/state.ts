import { defaultLanguage, messages, type CopyKey } from '../i18n/messages'
import { defaultRoute, parentForRoute, routeFromHash } from './navigation'
import type { AppState, FilingsPayload, Language, HermesAgentSaveResult, HermesMacroAnalysisPayload, HermesMacroLlmResult, HermesMarketInterpretationPayload, HermesPayload, MarketFetchResult, MarketSignal, MarketSignalsPayload, WatchlistMutationResult, WatchlistPayload, MarketTrendPayload, OperationsPayload, ServicesPayload, StatusPayload } from './types'

export const state: AppState = {
  loading: true,
  error: null,
  language: defaultLanguage,
  navOpen: false,
  expandedMenus: ['market-signals', 'hermes'],
  activeRoute: routeFromHash(window.location.hash || `#/${defaultRoute}`),
  refreshedAt: null,
  status: null,
  services: null,
  latestSignal: null,
  filings: null,
  operations: null,
  watchlist: null,
  watchlistSaving: false,
  watchlistResult: null,
  marketSignals: null,
  marketTrend: null,
  marketFetchResult: null,
  marketFetchInFlight: false,
  marketFetchRequest: null,
  hermesMacroAnalysis: null,
  macroLlmInFlight: false,
  macroLlmResult: null,
  hermesMarketInterpretation: null,
  hermes: null,
  hermesAgentSaving: false,
  hermesAgentResult: null,
  raw: null,
}

export function t(key: CopyKey): string {
  return messages[state.language][key]
}

export function toggleLanguage(): void {
  state.language = state.language === 'zh' ? 'en' : 'zh'
}

export function setLanguage(language: Language): void {
  state.language = language
}

export function setRouteFromHash(): void {
  state.activeRoute = routeFromHash(window.location.hash)
  const parent = parentForRoute(state.activeRoute)
  if (parent && !state.expandedMenus.includes(parent.id)) {
    state.expandedMenus = [...state.expandedMenus, parent.id]
  }
}

export function toggleExpandedMenu(menuId: string): void {
  state.expandedMenus = state.expandedMenus.includes(menuId)
    ? state.expandedMenus.filter((id) => id !== menuId)
    : [...state.expandedMenus, menuId]
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }
  return (await response.json()) as T
}

export async function reloadData(): Promise<void> {
  state.loading = true
  state.error = null

  try {
    const [status, services, latestSignal, filings, operations, watchlist, marketSignals, marketTrend, hermesMacroAnalysis, hermes, raw] = await Promise.all([
      fetchJson<StatusPayload>('/api/status'),
      fetchJson<ServicesPayload>('/api/services'),
      fetchJson<MarketSignal | null>('/api/market/signals/latest'),
      fetchJson<FilingsPayload>('/api/filings'),
      fetchJson<OperationsPayload>('/api/operations'),
      fetchJson<WatchlistPayload>('/api/watchlist'),
      fetchJson<MarketSignalsPayload>('/api/market/signals?limit=90'),
      fetchJson<MarketTrendPayload>('/api/market/signals/trend?window=20'),
      fetchJson<HermesMacroAnalysisPayload>('/api/hermes/macro-analysis?window=30'),
      fetchJson<HermesPayload>('/api/hermes'),
      fetchJson<StatusPayload>('/api/raw/status'),
    ])
    state.status = status
    state.services = services
    state.latestSignal = latestSignal
    state.filings = filings
    state.operations = operations
    state.watchlist = watchlist
    state.marketSignals = marketSignals
    state.marketTrend = marketTrend
    state.hermesMacroAnalysis = hermesMacroAnalysis
    state.hermesMarketInterpretation = hermesMacroAnalysis
    state.hermes = hermes
    state.raw = raw
    state.refreshedAt = new Date()
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.loading = false
  }
}

export async function runMacroAnalystLlm(payload: { window?: number; watchlist?: string[]; model?: string } = { window: 30 }): Promise<void> {
  state.macroLlmInFlight = true
  state.macroLlmResult = null
  state.error = null
  try {
    const response = await fetch('/api/hermes/macro-analysis/run', {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ window: 30, ...payload }),
    })
    const result = (await response.json()) as HermesMacroLlmResult
    state.macroLlmResult = result
    if (!response.ok) {
      throw new Error(result.error ?? `HTTP ${response.status}: ${response.statusText}`)
    }
    if (result.analysis) {
      state.hermesMacroAnalysis = result.analysis
      state.hermesMarketInterpretation = result.analysis
    }
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.macroLlmInFlight = false
    state.loading = false
  }
}

export async function addWatchlistItem(payload: { ticker: string; status?: string; thesis?: string; tags?: string[] }): Promise<void> {
  state.watchlistSaving = true
  state.watchlistResult = null
  state.error = null
  try {
    const response = await fetch('/api/watchlist', {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const result = (await response.json()) as WatchlistMutationResult
    state.watchlistResult = result
    if (!response.ok) {
      throw new Error(result.error ?? `HTTP ${response.status}: ${response.statusText}`)
    }
    await reloadData()
    state.watchlistResult = result
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.watchlistSaving = false
    state.loading = false
  }
}

export async function deleteWatchlistItem(ticker: string): Promise<void> {
  state.watchlistSaving = true
  state.watchlistResult = null
  state.error = null
  try {
    const response = await fetch(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: 'DELETE', headers: { Accept: 'application/json' } })
    const result = (await response.json()) as WatchlistMutationResult
    state.watchlistResult = result
    if (!response.ok) {
      throw new Error(result.error ?? `HTTP ${response.status}: ${response.statusText}`)
    }
    await reloadData()
    state.watchlistResult = result
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.watchlistSaving = false
    state.loading = false
  }
}

export async function fetchMarketSignals(payload: { date?: string; from?: string; to?: string }): Promise<void> {
  state.marketFetchInFlight = true
  state.marketFetchResult = null
  state.error = null
  try {
    const response = await fetch('/api/market/signals/fetch', {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const result = (await response.json()) as MarketFetchResult
    state.marketFetchResult = result
    if (!response.ok) {
      throw new Error(result.error ?? `HTTP ${response.status}: ${response.statusText}`)
    }
    await reloadData()
    state.marketFetchResult = result
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.marketFetchInFlight = false
    state.marketFetchRequest = null
    state.loading = false
  }
}


export async function saveHermesAgent(payload: { id: string; name: string; role?: string; description?: string; system_prompt?: string; data_sources?: string[]; tools?: string[]; enabled?: boolean }): Promise<void> {
  state.hermesAgentSaving = true
  state.hermesAgentResult = null
  state.error = null
  try {
    const response = await fetch('/api/hermes/agents', {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const result = (await response.json()) as HermesAgentSaveResult
    state.hermesAgentResult = result
    if (!response.ok) {
      throw new Error(result.error ?? `HTTP ${response.status}: ${response.statusText}`)
    }
    await reloadData()
    state.hermesAgentResult = result
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.hermesAgentSaving = false
    state.loading = false
  }
}
