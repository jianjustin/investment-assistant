import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/svelte'
import App from './app.svelte'

// Mock all API calls
vi.mock('./lib/api', () => ({
  getStatus: vi.fn(async () => ({})),
  getRawStatus: vi.fn(async () => ({})),
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
  it('defaults to the today zone with workbench entries first and the rest under more', async () => {
    const { getAllByText, getByRole } = render(App)
    expect(getAllByText('今日').length).toBeGreaterThan(0)
    expect(getAllByText('标的').length).toBeGreaterThan(0)
    expect(getAllByText('复盘').length).toBeGreaterThan(0)
    expect(getByRole('button', { name: /更多/ })).toBeInTheDocument()
  })

  it('shows only tools and settings under more', async () => {
    location.hash = '#tools'
    const { getAllByText, queryByText } = render(App)
    expect(getAllByText('工具').length).toBeGreaterThan(0)
    expect(getAllByText('设置').length).toBeGreaterThan(0)
    expect(queryByText('数据')).toBeNull()
    expect(queryByText('策略')).toBeNull()
    expect(queryByText('交易')).toBeNull()
  })

  it('legacy data hash falls back to today', async () => {
    location.hash = '#data/us-research'
    const { getAllByText, queryByText } = render(App)
    expect(getAllByText('今日').length).toBeGreaterThan(0)
    expect(queryByText('数据')).toBeNull()
  })
})
