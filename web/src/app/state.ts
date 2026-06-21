import { defaultLanguage, messages, type CopyKey } from '../i18n/messages'
import { defaultRoute, parentForRoute, routeFromHash } from './navigation'
import type { AppState, FilingsPayload, Language, HermesMarketInterpretationPayload, MarketFetchResult, MarketSignal, MarketSignalsPayload, MarketTrendPayload, OperationsPayload, ServicesPayload, StatusPayload } from './types'

export const state: AppState = {
  loading: true,
  error: null,
  language: defaultLanguage,
  navOpen: false,
  expandedMenus: ['market-signals'],
  activeRoute: routeFromHash(window.location.hash || `#/${defaultRoute}`),
  refreshedAt: null,
  status: null,
  services: null,
  latestSignal: null,
  filings: null,
  operations: null,
  marketSignals: null,
  marketTrend: null,
  marketFetchResult: null,
  marketFetchInFlight: false,
  marketFetchRequest: null,
  hermesMarketInterpretation: null,
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
    const [status, services, latestSignal, filings, operations, marketSignals, marketTrend, hermesMarketInterpretation, raw] = await Promise.all([
      fetchJson<StatusPayload>('/api/status'),
      fetchJson<ServicesPayload>('/api/services'),
      fetchJson<MarketSignal | null>('/api/market/signals/latest'),
      fetchJson<FilingsPayload>('/api/filings'),
      fetchJson<OperationsPayload>('/api/operations'),
      fetchJson<MarketSignalsPayload>('/api/market/signals?limit=90'),
      fetchJson<MarketTrendPayload>('/api/market/signals/trend?window=20'),
      fetchJson<HermesMarketInterpretationPayload>('/api/hermes/market-signals/interpretation?window=30'),
      fetchJson<StatusPayload>('/api/raw/status'),
    ])
    state.status = status
    state.services = services
    state.latestSignal = latestSignal
    state.filings = filings
    state.operations = operations
    state.marketSignals = marketSignals
    state.marketTrend = marketTrend
    state.hermesMarketInterpretation = hermesMarketInterpretation
    state.raw = raw
    state.refreshedAt = new Date()
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
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
