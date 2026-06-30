import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/svelte'
import App from './app.svelte'

// Mock all API calls
vi.mock('./lib/api', () => ({
  getStatus: vi.fn(async () => ({})),
  getRawStatus: vi.fn(async () => ({})),
  getMarketSignals: vi.fn(async () => ({ rows: [], count: 0 })),
  getMarketSignalsTrend: vi.fn(async () => ({ window: 30 })),
  getMarketSignalsLatest: vi.fn(async () => ({})),
  getMacroAnalysis: vi.fn(async () => ({ macro_state: 'offense', stance_label: '进攻' })),
  getHermes: vi.fn(async () => ({})),
  getHermesAgents: vi.fn(async () => ({ agents: [] })),
  getTickerTrends: vi.fn(async () => ({ rows: [] })),
  getStrategyScores: vi.fn(async () => ({ rows: [] })),
  getWatchlist: vi.fn(async () => ({ rows: [] })),
  getFilings: vi.fn(async () => ({})),
  getOperations: vi.fn(async () => ({ operations: [] })),
  getServices: vi.fn(async () => ({})),
  pollRun: vi.fn(async () => ({ status: 'done', result: {} })),
  getScheduledJobs: vi.fn(async () => ({ jobs: [], degraded: false })),
  getJobReports: vi.fn(async () => ({ reports: [], degraded: false })),
  getJobMetrics: vi.fn(async () => ({ metrics: [], degraded: false })),
  runJob: vi.fn(async () => ({ run_id: 'x', status: 'pending' })),
  fetchMarketSignals: vi.fn(async () => ({})),
  getNotifySettings: vi.fn(async () => ({})),
  patchNotifySettings: vi.fn(async () => ({})),
  testNotifyChannel: vi.fn(async () => ({ ok: true })),
  getEnvStatus: vi.fn(async () => ({})),
}))

// Mock EventSource for SSE
class FakeEventSource {
  onerror: (() => void) | null = null
  addEventListener(_: string, __: () => void) {}
  close() {}
}
vi.stubGlobal('EventSource', FakeEventSource)

beforeEach(() => { location.hash = '' })
afterEach(() => cleanup())

describe('app routing', () => {
  it('defaults to tools zone and renders 5-layer nav', async () => {
    const { getAllByText } = render(App)
    expect(getAllByText('工具').length).toBeGreaterThan(0)
    expect(getAllByText('数据').length).toBeGreaterThan(0)
    expect(getAllByText('策略').length).toBeGreaterThan(0)
    expect(getAllByText('交易').length).toBeGreaterThan(0)
    expect(getAllByText('设置').length).toBeGreaterThan(0)
  })

  it('renders data zone on #data hash', async () => {
    location.hash = '#data'
    const { getAllByText } = render(App)
    expect(getAllByText('数据').length).toBeGreaterThan(0)
  })
})
