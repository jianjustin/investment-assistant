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
  it('defaults to Dashboard zone', async () => {
    const { getByText } = render(App)
    expect(getByText(/总览|dashboard/i)).toBeTruthy()
  })

  it('renders Market zone on #market hash', async () => {
    location.hash = '#market'
    const { getByText } = render(App)
    expect(getByText(/市场|market/i)).toBeTruthy()
  })
})
