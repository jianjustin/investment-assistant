import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'
import Instrument from './Instrument.svelte'

// CandleChart 依赖 canvas，jsdom 下 mock 掉
vi.mock('../lib/charts/CandleChart.svelte', async () => {
  // @ts-ignore – stub has no declaration file; only used in tests
  const Stub = (await import('./__stub__.svelte')).default
  return { default: Stub }
})

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const chartBars = (ma: Partial<{ ma20: number | null; ma50: number | null; ma200: number | null }> = {}) =>
  ['2026-10-20', '2026-10-21', '2026-10-22'].map((date, i) => ({
    price_date: date, open: 100 + i, high: 101 + i, low: 99 + i, close: 100.5 + i, volume: 1000,
    ma20: ma.ma20 ?? 100, ma50: ma.ma50 ?? 99, ma200: ma.ma200 ?? 98,
  }))
const fundamentalsView = (ticker: string) => ({
  ticker, security_id: `US:stock:${ticker}`, currency: 'USD',
  financials: [{ period: '2026-04-01/2026-06-30', start: '2026-04-01', end: '2026-06-30', days: 91, metrics: {}, ttm: {}, warnings: [] }],
  market: { bars: [], benchmarks: { SPY: [], QQQ: [] }, quote: {}, performance: { windows: {} }, limitations: [] },
  valuation: {}, statuses: [], guidance: { records: [], comparisons: [], consensus: '未接入一致预期' }, filings: [], pit: {},
})
const view = (ticker: string, chart: { bars: unknown[]; adjustment: string } = { bars: chartBars(), adjustment: 'split_only' }) => ({
  ticker, session: '2026-10-22', bars: [], closed: [], chart,
  position: { quantity: 10, avg_cost: 100.1, opened_at: '2026-10-02T14:00:00Z' },
  filings: [{ id: 1, form: '8-K', filing_date: '2026-10-20', accepted_at: null, items: ['2.02'] }],
  news: [{ id: 2, source: 'yfinance', title: '合成新闻', url: 'https://news.example.com/2', publisher: 'W',
           published_at: '2026-10-21T12:00:00Z', fetched_at: '2026-10-21T13:00:00Z' }],
  candidates: [{ id: 'c', signal_date: '2026-10-22', action: 'buy', rule_id: 'trend_reclaim', created_at: '2026-10-22T22:30:00Z' }],
  decisions: [], trades: [],
})

let urls: string[]
beforeEach(() => {
  urls = []
  history.replaceState(null, '', '#instrument/NVDA')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    urls.push(String(url))
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }, { ticker: 'MU' }] })
    if (String(url).startsWith('/api/us-research/')) return json(fundamentalsView(String(url).split('/')[3].split('?')[0]))
    return json(view(String(url).split('/').pop()!))
  }))
})
afterEach(() => vi.unstubAllGlobals())

it('loads the ticker from the route and renders one timeline', async () => {
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByRole('heading', { name: /NVDA/ })).toBeInTheDocument()
  expect(screen.getByText(/受理时间未知/)).toBeInTheDocument()
  expect(screen.getByText(/趋势回踩修复/)).toBeInTheDocument()
  expect(screen.getByText(/持仓 10/)).toBeInTheDocument()
  expect(urls).toContain('/api/workbench/instruments/NVDA')
})

it('switches ticker through the picker and updates the hash', async () => {
  render(Instrument, { sub: 'NVDA' })
  await screen.findByRole('heading', { name: /NVDA/ })
  await fireEvent.change(screen.getByLabelText('标的'), { target: { value: 'MU' } })
  expect(await screen.findByRole('heading', { name: /MU/ })).toBeInTheDocument()
  expect(location.hash).toBe('#instrument/MU')
})

it('shows 503 as database unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).startsWith('/api/watchlist')
    ? json({ rows: [] }) : json({ error: 'down' }, 503)))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByText(/数据库未就绪/)).toBeInTheDocument()
})

it('skips invalid-identity watchlist rows when choosing the default ticker', async () => {
  history.replaceState(null, '', '#instrument')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    urls.push(String(url))
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [
      { ticker: '688008.SH', market: null, identity_error: '证券身份无效，请删除后使用完整有效代码重新添加' },  // invalid US code
      { ticker: 'MU', market: 'US' },
    ] })
    return json(view(String(url).split('/').pop()!))
  }))
  render(Instrument, {})
  expect(await screen.findByRole('heading', { name: /MU/ })).toBeInTheDocument()
  expect(urls.some(u => u.includes('/api/workbench/instruments/688008.SH'))).toBe(false)
  expect(screen.queryByRole('option', { name: '688008.SH' })).toBeNull()
})

it('renders the chart with three moving averages', async () => {
  render(Instrument, { sub: 'NVDA' })
  await screen.findByRole('heading', { name: /NVDA/ })
  expect(screen.getByTestId('instrument-chart')).toBeInTheDocument()
  expect(screen.getByText(/拆股调整、未分红调整/)).toBeInTheDocument()
})

it('renders candles without ma200 when history is short', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).startsWith('/api/watchlist')
    ? json({ rows: [{ ticker: 'NVDA' }] })
    : json(view(String(url).split('/').pop()!, { bars: chartBars({ ma200: null }), adjustment: 'split_only' }))))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByTestId('instrument-chart')).toBeInTheDocument()
})

it('shows an empty note without bars', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).startsWith('/api/watchlist')
    ? json({ rows: [{ ticker: 'NVDA' }] })
    : json(view(String(url).split('/').pop()!, { bars: [], adjustment: 'split_only' }))))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByText('暂无日线，等下一次批处理采集')).toBeInTheDocument()
  expect(urls.some(u => u.startsWith('/api/tickers/'))).toBe(false)
})

it('renders the fundamentals section', async () => {
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByText('未接入一致预期')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '基本面' })).toBeInTheDocument()
})

it('keeps the instrument page when fundamentals fail', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).startsWith('/api/watchlist')
    ? json({ rows: [{ ticker: 'NVDA' }] })
    : String(url).startsWith('/api/us-research/') ? json({ error: 'down' }, 500)
      : json(view(String(url).split('/').pop()!))))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByRole('heading', { name: /NVDA/ })).toBeInTheDocument()
  expect(screen.getByTestId('instrument-chart')).toBeInTheDocument()
  expect(screen.getByText(/趋势回踩修复/)).toBeInTheDocument()
  expect(await screen.findByText(/加载失败/)).toBeInTheDocument()
})
