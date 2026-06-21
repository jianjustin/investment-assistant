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

export type WatchlistItem = {
  ticker: string
  status?: 'active' | 'paused' | 'archived' | string
  thesis?: string | null
  tags?: string[]
  source?: string
  created_at?: string
  updated_at?: string
}

export type WatchlistPayload = {
  rows: WatchlistItem[]
  count: number
}

export type WatchlistMutationResult = {
  item?: WatchlistItem
  ticker?: string
  deleted?: boolean
  error?: string
}


export type TickerTrendSnapshot = {
  ticker: string
  signal_date?: string
  close?: string | number | null
  ma20?: string | number | null
  ma50?: string | number | null
  ma200?: string | number | null
  volume?: string | number | null
  volume_ratio?: string | number | null
  relative_strength_spy?: string | number | null
  relative_strength_qqq?: string | number | null
  trend_state: 'uptrend' | 'base' | 'downtrend' | 'volatile' | 'unknown' | string
  attention_level: 'high' | 'medium' | 'low' | string
  trigger_reason?: string[]
  source?: string
  error?: string | null
  run_id?: string | null
  created_at?: string
  updated_at?: string
}

export type TickerTrendsPayload = {
  rows: TickerTrendSnapshot[]
  count: number
}

export type TickerTrendScanResult = {
  run_id?: string
  requested?: { date: string; tickers: string[] }
  rows?: TickerTrendSnapshot[]
  count?: number
  failures?: TickerTrendSnapshot[]
  error?: string
}

export type TickerTrendHelpTopic = 'trend_state' | 'attention_level' | 'trigger_reason' | 'volume_ratio' | 'relative_strength'

export type StrategyScore = {
  ticker: string
  score_date?: string
  strategy: string
  score: number
  evidence?: string[]
  limits?: string[]
  source_snapshot_id?: number | null
  run_id?: string | null
  created_at?: string
  updated_at?: string
}

export type StrategyScoresPayload = {
  rows: StrategyScore[]
  count: number
}

export type StrategyScoreRunResult = {
  run_id?: string
  mode?: string
  rows?: StrategyScore[]
  count?: number
  failures?: Array<{ ticker?: string; error?: string }>
  error?: string
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

export type HermesCapability = {
  id: string
  label: string
  description: string
  status: 'ready' | 'planned' | string
  endpoint?: string | null
  inputs: string[]
  outputs: string[]
}

export type HermesAgent = {
  id: string
  name: string
  role: string
  description: string
  system_prompt: string
  data_sources: string[]
  tools: string[]
  enabled: boolean
  custom: boolean
  created_at: string
  updated_at: string
}

export type HermesIdea = {
  title: string
  description: string
  next_step: string
}

export type HermesPayload = {
  capabilities: HermesCapability[]
  agents: HermesAgent[]
  ideas: HermesIdea[]
}

export type HermesAgentSaveResult = {
  agent?: HermesAgent
  error?: string
}

export type HermesInterpretationSection = {
  title: string
  items: string[]
}

export type HermesMacroAnalysisPayload = {
  source: string
  agent_role?: string
  stage?: string
  artifact_type?: string
  macro_state?: "offense" | "cautious" | "defense" | string
  stance_label?: string
  macro_snapshot?: {
    stage?: string
    artifact_type?: string
    state?: string
    stance?: string
    watchlist?: string[]
    metrics?: Array<Record<string, unknown>>
  }
  key_changes?: string[]
  growth_implications?: string[]
  watchlist_implications?: string[]
  next_checks?: string[]
  window: number
  sample_size: number
  generated_at: string
  judgement: 'risk_on' | 'neutral' | 'risk_off' | string
  title: string
  summary: string
  metrics: {
    green_ratio?: number
    red_ratio?: number
    above_ma_ratio?: number
    avg_vix?: number
    latest_status?: string
    status_counts?: Record<string, number>
  }
  sections: HermesInterpretationSection[]
  actions: string[]
  risk_questions?: string[]
  llm?: {
    provider?: string
    mode?: string
    used?: boolean
    model?: string
    error?: string | null
  }
  llm_interpretation?: {
    summary?: string
    key_changes?: string[]
    growth_implications?: string[]
    watchlist_implications?: string[]
    next_checks?: string[]
    actions?: string[]
    risk_questions?: string[]
  } | null
}

export type HermesMacroLlmResult = {
  run_id?: string
  analysis?: HermesMacroAnalysisPayload
  error?: string
}

export type HermesMarketInterpretationPayload = HermesMacroAnalysisPayload

export type MarketFetchResult = {
  requested?: { from: string; to: string }
  rows?: MarketSignal[]
  failures?: Array<{ signal_date: string; error: string }>
  error?: string
}

export type RouteId = 'workbench' | 'watchlist-list' | 'ticker-trends' | 'strategy-scores' | 'strategy-runs' | 'hermes-overview' | 'hermes-agents' | 'hermes-ideas' | 'market-overview' | 'market-trend' | 'market-list' | 'market-fetch' | 'filings' | 'services' | 'operations' | 'raw'

export type RouteItem = {
  id: RouteId
  labelKey: CopyKey
  descriptionKey: CopyKey
  icon?: string
}

export type RouteParent = {
  id: string
  labelKey: CopyKey
  descriptionKey: CopyKey
  icon: string
  children: RouteItem[]
}

export type RouteEntry = RouteItem | RouteParent

export type RouteGroup = {
  labelKey: CopyKey
  children: RouteEntry[]
}

export type AppState = {
  loading: boolean
  error: string | null
  language: Language
  navOpen: boolean
  expandedMenus: string[]
  activeRoute: RouteId
  refreshedAt: Date | null
  status: StatusPayload | null
  services: ServicesPayload | null
  latestSignal: MarketSignal | null
  filings: FilingsPayload | null
  operations: OperationsPayload | null
  watchlist: WatchlistPayload | null
  watchlistSaving: boolean
  watchlistResult: WatchlistMutationResult | null
  tickerTrends: TickerTrendsPayload | null
  tickerTrendScanInFlight: boolean
  tickerTrendScanResult: TickerTrendScanResult | null
  tickerTrendHelpTopic: TickerTrendHelpTopic | null
  strategyScores: StrategyScoresPayload | null
  strategyScoreRunInFlight: boolean
  strategyScoreRunResult: StrategyScoreRunResult | null
  marketSignals: MarketSignalsPayload | null
  marketTrend: MarketTrendPayload | null
  marketFetchResult: MarketFetchResult | null
  marketFetchInFlight: boolean
  marketFetchRequest: string | null
  hermesMacroAnalysis: HermesMacroAnalysisPayload | null
  macroLlmInFlight: boolean
  macroLlmResult: HermesMacroLlmResult | null
  hermesMarketInterpretation: HermesMarketInterpretationPayload | null
  hermes: HermesPayload | null
  hermesAgentSaving: boolean
  hermesAgentResult: HermesAgentSaveResult | null
  raw: StatusPayload | null
}

import type { CopyKey } from '../i18n/messages'
