import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'
import Instrument from './Instrument.svelte'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const view = (ticker: string) => ({
  ticker, session: '2026-10-22', bars: [], closed: [],
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
