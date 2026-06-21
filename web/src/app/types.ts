export type Language = 'zh' | 'en'

export type CommandStatus = {
  ok: boolean
  returncode?: number
  output?: string
}

export type MarketSignal = {
  signal_date?: string
  market_status?: string
  score?: number
  distribution_days?: number
  vix?: number
  index_above_ma?: boolean
  notes?: string
  created_at?: string
  spy_ticker?: string
  spy_close?: string | number
  spy_ma200?: string | number
  spy_above_200ma?: boolean
  vix_ticker?: string
  vix_close?: string | number
  source?: string
  run_id?: string
  details?: Record<string, unknown>
}

export type StatusPayload = {
  database?: {
    ok?: boolean
    error?: string
    latest_market_signal?: MarketSignal | null
  }
  filings?: FilingSummary
  system?: ServicesPayload
}

export type ServicesPayload = {
  postgres_service?: CommandStatus
  dashboard_service?: CommandStatus
  timer?: CommandStatus
}

export type FilingSummary = {
  path?: string
  exists?: boolean
  file_count?: number
}

export type FilingRow = {
  name?: string
  path?: string
  size?: number
  modified_at?: number
}

export type FilingsPayload = {
  summary?: FilingSummary
  files?: FilingRow[]
}

export type Operation = {
  id: string
  label: string
  description: string
  risk: 'low' | 'medium' | 'high' | string
  enabled: boolean
  requires_confirmation: boolean
  method: string
  endpoint: string
}

export type OperationsPayload = {
  operations: Operation[]
}

export type MarketSignalsPayload = {
  rows: MarketSignal[]
  count: number
}

export type MarketTrendPayload = {
  window: number
  sample_size: number
  latest_status: string
  status_counts: Record<string, number>
  green_ratio: number
  red_ratio: number
  judgement: 'risk_on' | 'neutral' | 'risk_off' | string
  summary: string
  rows: MarketSignal[]
}

export type MarketFetchResult = {
  requested?: { from: string; to: string }
  rows?: MarketSignal[]
  failures?: Array<{ signal_date: string; error: string }>
  error?: string
}

export type RouteId = 'workbench' | 'market' | 'filings' | 'services' | 'operations' | 'raw'

export type RouteItem = {
  id: RouteId
  labelKey: CopyKey
  descriptionKey: CopyKey
  icon: string
}

export type RouteGroup = {
  labelKey: CopyKey
  children: RouteItem[]
}

export type AppState = {
  loading: boolean
  error: string | null
  language: Language
  navOpen: boolean
  activeRoute: RouteId
  refreshedAt: Date | null
  status: StatusPayload | null
  services: ServicesPayload | null
  latestSignal: MarketSignal | null
  filings: FilingsPayload | null
  operations: OperationsPayload | null
  marketSignals: MarketSignalsPayload | null
  marketTrend: MarketTrendPayload | null
  marketFetchResult: MarketFetchResult | null
  raw: StatusPayload | null
}

import type { CopyKey } from '../i18n/messages'
