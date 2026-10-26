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
  getDataFamilies: vi.fn(async () => ({
    session: '2026-10-22',
    evidence: '这里只展示采集事实。所有规则都未经验证（Phase 0 Gate HOLD）：数据完整不代表信号有效。',
    fetch_runs_ready: true,
    families: Object.entries({
      bars: '日线', sec_filings: 'SEC 申报', news: '资讯', atr: 'ATR', fred: 'FRED 利差', universe: '纳指 100 范围',
    }).map(([id, title]) => ({
      id, title, purpose: `用途-${id}`,
      kind: id === 'atr' ? 'derived' : id === 'universe' ? 'manual' : 'fetched',
      fetch_via: id === 'atr' ? 'bars' : null,
      per_ticker: ['bars', 'sec_filings', 'news'].includes(id),
      job: null, coverage: { targets: 10, covered: 10, lagging: [] },
      latest_at: '2026-10-22', last_run: null, last_success_at: null,
      evidence: '这里只展示采集事实。所有规则都未经验证（Phase 0 Gate HOLD）：数据完整不代表信号有效。', notes: [],
    })),
  })),
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

  it('keeps tools and settings under more, with data in primary navigation', async () => {
    location.hash = '#tools'
    const { getAllByText, getByRole, queryByText } = render(App)
    expect(getAllByText('工具').length).toBeGreaterThan(0)
    expect(getAllByText('设置').length).toBeGreaterThan(0)
    expect(getByRole('link', { name: /数据/ })).toHaveAttribute('href', '#data')
    expect(queryByText('策略')).toBeNull()
    expect(queryByText('交易')).toBeNull()
  })

  it('legacy data hash opens the data overview rather than today', async () => {
    location.hash = '#data/us-research'
    const { findByRole, getAllByRole, getByRole, queryByRole } = render(App)
    expect(await findByRole('heading', { name: '数据' })).toBeInTheDocument()
    expect(getAllByRole('article')).toHaveLength(6)
    expect(getByRole('link', { name: /数据/ })).toHaveAttribute('href', '#data')
    expect(queryByRole('heading', { name: '今日' })).toBeNull()
  })
})
