import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/svelte'
import Fundamentals from './Fundamentals.svelte'

const source = 'https://www.sec.gov/Archives/example'
const metric = (value: number | null, unit = 'USD') => ({ value, unit, basis: 'us-gaap:consolidated', method: 'reported', input_ids: [42], sources: [{ source_url: source, start: '2026-04-01', end: '2026-06-30', filed: '2026-08-01', concept: 'Revenues', source_locator: '/facts/1' }], missing_reason: value === null ? 'Missing compatible calculation input' : null })
const view = (ticker = 'MU') => ({ ticker, security_id: `US:stock:${ticker}`, currency: 'USD', financials: [{ period: '2026-04-01/2026-06-30', start: '2026-04-01', end: '2026-06-30', days: 91, metrics: { revenue: metric(100), cfo: metric(0), fcf: metric(null) }, ttm: {}, warnings: [] }], market: { bars: [], benchmarks: { SPY: [], QQQ: [] }, quote: { market_cap_verified: false }, performance: { windows: {} }, limitations: [] }, valuation: { ps_ttm: metric(null, 'multiple') }, statuses: [{ dataset: 'financials', status: 'failed', retained_old_values: true, succeeded_at: '2026-08-01', attempted_at: '2026-10-16', error: '来源失败', last_success_details: { identity: { name: '测试公司' } } }], guidance: { records: [], comparisons: [], consensus: '未接入一致预期' }, filings: [], pit: { strict: false } })

let urls: { url: string; init?: RequestInit }[] = []
let respond: (url: string, init?: RequestInit) => Promise<any> | Response
const json = (body: any, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  urls = []
  let drawn: string[] = []
  const context = new Proxy({ fillText: (text: string) => { drawn.push(String(text)) }, measureText: (text: string) => ({ width: text.length * 7 }), createLinearGradient: () => ({ addColorStop() { } }) }, { get: (target: any, key) => key in target ? target[key] : () => { } })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as any)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(320)
  respond = async (url) => url.includes('/api/us-research/sync') ? json({ run_id: 'run', status: 'pending' })
    : url === '/api/runs/run' ? json({ status: 'done', run_id: 'run', result: { status: 'success', summary: { errors: [], results: [] } } })
      : url.startsWith('/api/us-research/') ? json(view(url.split('/')[3].split('?')[0]))
        : json({ rows: [], records: [], tickers: [] })
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    urls.push({ url: String(url), init })
    return respond(String(url), init)
  }))
})
afterEach(() => vi.unstubAllGlobals())

it('loads the given ticker', async () => {
  render(Fundamentals, { ticker: 'MU' })
  await screen.findByText('未接入一致预期')
  expect(screen.getByRole('heading', { name: /基本面/ })).toBeInTheDocument()
  expect(screen.getByText('测试公司')).toBeInTheDocument()
  expect(urls.some(u => u.url === '/api/us-research/MU')).toBe(true)
})

it('reloads when ticker changes and drops the stale response', async () => {
  let finish: (v: any) => void = () => { }
  const initial = respond
  respond = (url, init) => url === '/api/us-research/MU' ? new Promise(resolve => { finish = resolve }) : initial(url, init)
  const mounted = render(Fundamentals, { ticker: 'MU' })
  await mounted.rerender({ ticker: 'NVDA' } as any)
  expect(await screen.findByText(/币种 USD/)).toBeInTheDocument()
  await act(async () => finish(json({ ...view('MU'), currency: 'STALE' })))
  expect(screen.queryByText(/币种 STALE/)).toBeNull()
  expect(screen.getByText(/币种 USD/)).toBeInTheDocument()
})

it('shows not-collected state', async () => {
  const initial = respond
  respond = (url, init) => url.startsWith('/api/us-research/') ? json({ ...view(), financials: [] }) : initial(url, init)
  render(Fundamentals, { ticker: 'MU' })
  expect(await screen.findByText(/尚未采集/)).toBeInTheDocument()
})

it('manual refresh posts sync for the ticker', async () => {
  render(Fundamentals, { ticker: 'MU' })
  await screen.findByText('未接入一致预期')
  await fireEvent.click(screen.getByRole('button', { name: '手动更新' }))
  const sync = urls.find(u => u.url === '/api/us-research/sync')
  expect(sync?.init?.body).toBe(JSON.stringify({ symbols: ['MU'], retry_failed: false }))
})

it('distinguishes a real zero from a missing cash flow and expands sources', async () => {
  render(Fundamentals, { ticker: 'MU' })
  await screen.findByText('未接入一致预期')
  expect(screen.getByText('显示旧值')).toBeInTheDocument()
  expect(screen.getAllByText('缺少可比计算输入').length).toBeGreaterThan(0)
  expect(screen.getByRole('row', { name: /经营现金流/ })).toHaveTextContent('0 USD')
  expect(screen.getByRole('row', { name: /标准自由现金流/ })).toHaveTextContent('—')
  await fireEvent.click(screen.getAllByText('计算与来源')[0])
  expect(screen.getAllByRole('link', { name: /原文/ })[0]).toHaveAttribute('href', source)
  expect(screen.getAllByText(/2026-04-01.*2026-06-30/).length).toBeGreaterThan(0)
})

it('displays the twelve latest actual quarters, percentages and a recent-year price window', async () => {
  const payload = view()
  payload.financials = [['2023-06-01', '2023-08-31'], ['2023-09-01', '2023-11-30'], ['2023-12-01', '2024-02-29'], ['2024-03-01', '2024-05-31'], ['2024-06-01', '2024-08-31'], ['2024-09-01', '2024-11-30'], ['2024-12-01', '2025-02-28'], ['2025-03-01', '2025-05-31'], ['2025-06-01', '2025-08-31'], ['2025-09-01', '2025-11-30'], ['2025-12-01', '2026-02-28'], ['2026-03-01', '2026-05-31'], ['2026-06-01', '2026-08-31']].map(([start, end]) => ({ period: `${start}/${end}`, start, end, days: 92, metrics: { revenue: metric(100), gross_margin: metric(0.25, 'ratio'), cfo: metric(0), fcf: metric(null) }, ttm: { revenue: metric(380) }, warnings: [] }))
  payload.market.bars = [{ date: '2024-10-15', close: 999, adjusted_close: 999, currency: 'USD' }, { date: '2025-10-16', close: 15, adjusted_close: 14, currency: 'USD' }, { date: '2026-10-15', close: 20, adjusted_close: 19, currency: 'USD' }] as any
  const initial = respond
  respond = (url, init) => url.startsWith('/api/us-research/') ? json(payload) : initial(url, init)
  render(Fundamentals, { ticker: 'MU' })
  await screen.findByText('未接入一致预期')
  expect(screen.getByText(/最近 12 个实际财季/)).toBeInTheDocument()
  expect(screen.queryByText('2023-08-31')).toBeNull()
  expect(screen.getAllByText('25%').length).toBe(12)
  await fireEvent.change(screen.getByLabelText('财务期间口径'), { target: { value: 'ttm' } })
  expect(screen.getAllByText('380 USD').length).toBe(12)
  await fireEvent.click(screen.getByText('价格原始记录与报价来源'))
  expect(screen.queryByRole('row', { name: /2024-10-15/ })).toBeNull()
  expect(screen.getByRole('row', { name: /2025-10-16/ })).toHaveTextContent('15 USD')
})

it('reports nested partial failures and reloads retained data after manual refresh', async () => {
  const initial = respond
  respond = (url, init) => init?.method === 'POST' ? json({ run_id: 'outer', status: 'pending' })
    : url === '/api/runs/outer' ? json({ status: 'done', run_id: 'outer', result: { status: 'error', summary: { errors: [{ dataset: 'financials' }], results: [] } } })
      : initial(url, init)
  render(Fundamentals, { ticker: 'MU' })
  await screen.findByText('未接入一致预期')
  await fireEvent.click(screen.getByRole('button', { name: '手动更新' }))
  await screen.findByText(/更新有缺失或失败/)
  expect(screen.queryByText('全部更新成功')).toBeNull()
})

it('notice is an alert', async () => {
  const initial = respond
  respond = (url, init) => url.startsWith('/api/us-research/') && !url.includes('/sync') ? json({ ...view(), financials: [] }) : initial(url, init)
  render(Fundamentals, { ticker: 'MU' })
  const notice = (await screen.findByText(/尚未采集：本机没有该股票的财季数据/)).closest('[data-slot="alert"]') as HTMLElement
  expect(notice).not.toBeNull()
  expect(notice.className).toMatch(/border-warn/)
  // an update that did not finish is a danger alert with the reason, and a finished one an info status
  respond = (url, init) => init?.method === 'POST' ? json({ error: 'down' }, 500) : initial(url, init)
  await screen.findByText('未接入一致预期')
  await fireEvent.click(screen.getByRole('button', { name: '手动更新' }))
  const failed = (await screen.findByText(/更新未完成/)).closest('[data-slot="alert"]') as HTMLElement
  expect(failed).toHaveAttribute('role', 'alert')
  expect(failed.className).toMatch(/border-destructive/)
})
