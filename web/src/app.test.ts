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
  getTickerOhlcv: vi.fn(async () => ({ ticker: '', bars: [], ma20: [], ma50: [], ma200: [] })),
  getStrategyScores: vi.fn(async () => ({ rows: [] })),
  getWatchlist: vi.fn(async () => ({ rows: [] })),
  getOperations: vi.fn(async () => ({ operations: [] })),
  getServices: vi.fn(async () => ({})),
  pollRun: vi.fn(async () => ({ status: 'done', result: {} })),
  getScheduledJobs: vi.fn(async () => ({ jobs: [], degraded: false })),
  getJobReports: vi.fn(async () => ({ reports: [], degraded: false })),
  runJob: vi.fn(async () => ({ run_id: 'x', status: 'pending' })),
  getFilingRecords: vi.fn(async () => ({ records: [], tickers: [], degraded: false })),
  getNotifySettings: vi.fn(async () => ({})),
  patchNotifySettings: vi.fn(async () => ({})),
  testNotifyChannel: vi.fn(async () => ({ ok: true })),
  getEnvStatus: vi.fn(async () => ({})),
  get: vi.fn(async () => ({})),
}))
vi.mock('./lib/workbench', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./lib/workbench')>()),
  getToday: vi.fn(async () => ({ session: '2026-10-22', units: [] })),
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
  it('defaults to the today zone with workbench entries first and legacy entries under more', async () => {
    const { getAllByText, getByRole } = render(App)
    expect(getAllByText('今日').length).toBeGreaterThan(0)
    expect(getAllByText('标的').length).toBeGreaterThan(0)
    expect(getAllByText('复盘').length).toBeGreaterThan(0)
    expect(getByRole('button', { name: /更多/ })).toBeInTheDocument()
  })

  it('shows legacy entries under more when a legacy zone is open', async () => {
    location.hash = '#tools'
    const { getAllByText } = render(App)
    expect(getAllByText('工具').length).toBeGreaterThan(0)
    expect(getAllByText('数据').length).toBeGreaterThan(0)
    expect(getAllByText('策略').length).toBeGreaterThan(0)
    expect(getAllByText('交易').length).toBeGreaterThan(0)
    expect(getAllByText('设置').length).toBeGreaterThan(0)
  })

  it('side nav has no A-share entry', async () => {
    location.hash = '#data/us-research'
    const { getAllByText, queryByText } = render(App)
    expect(getAllByText('美股研究数据').length).toBeGreaterThan(0)
    expect(queryByText('A 股研究数据')).toBeNull()
  })

  it('renders data zone on #data hash', async () => {
    location.hash = '#data'
    const { getAllByText } = render(App)
    expect(getAllByText('数据').length).toBeGreaterThan(0)
  })
})
