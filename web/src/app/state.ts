import { defaultLanguage, messages, type CopyKey } from '../i18n/messages'
import { defaultRoute, routeFromHash } from './navigation'
import type { AppState, FilingsPayload, Language, MarketSignal, OperationsPayload, ServicesPayload, StatusPayload } from './types'

export const state: AppState = {
  loading: true,
  error: null,
  language: defaultLanguage,
  navOpen: false,
  activeRoute: routeFromHash(window.location.hash || `#/${defaultRoute}`),
  refreshedAt: null,
  status: null,
  services: null,
  latestSignal: null,
  filings: null,
  operations: null,
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
    const [status, services, latestSignal, filings, operations, raw] = await Promise.all([
      fetchJson<StatusPayload>('/api/status'),
      fetchJson<ServicesPayload>('/api/services'),
      fetchJson<MarketSignal | null>('/api/market/signals/latest'),
      fetchJson<FilingsPayload>('/api/filings'),
      fetchJson<OperationsPayload>('/api/operations'),
      fetchJson<StatusPayload>('/api/raw/status'),
    ])
    state.status = status
    state.services = services
    state.latestSignal = latestSignal
    state.filings = filings
    state.operations = operations
    state.raw = raw
    state.refreshedAt = new Date()
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.loading = false
  }
}
