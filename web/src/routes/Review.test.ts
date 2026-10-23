import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import Review from './Review.svelte'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const trade = { id: 't1', ticker: 'NVDA', side: 'buy', quantity: 10, price: 101.5, fee: 1, executed_at: '2026-10-23T14:00:00Z',
                decision_id: null, note: null, recorded_at: '2026-10-23T15:00:00Z', voided_at: null, void_reason: null }

let calls: { url: string; init?: RequestInit }[]
let respond: (url: string, init?: RequestInit) => Promise<Response>

beforeEach(() => {
  calls = []
  respond = async (url, init) => {
    if (url.includes('/review/trades')) return json({ session: '2026-10-22', calc_version: 'review-1', closed: [],
      open: [{ ticker: 'NVDA', quantity: '10', avg_cost: 100.1, last_close: 105, as_of: '2026-10-22', unrealized_pnl: 49, unrealized_return: 0.049 }] })
    if (url === '/api/workbench/trades' && init?.method !== 'POST') return json({ trades: [trade] })
    if (url.includes('/review/shadow')) return json({ session: '2026-10-22', since: '2026-07-24', calc_version: 'review-1', units: [
      { id: 'd1', ticker: 'NVDA', signal_date: '2026-10-22', proposed_action: 'buy', final_action: 'ignore', decision: 'reject',
        reason: 'r', decided_at: '2026-10-23T01:00:00Z', supersedes_id: null, rule_ids: ['trend_reclaim'],
        outcome: { status: 'entered', entry_date: '2026-10-23', entry_price: 100, windows: {
          '5': { status: 'mature', return: 0.05, spy_return: 0.01, excess: 0.04 }, '10': { status: 'immature' }, '20': { status: 'immature' } } } }] })
    if (url.includes('/weekly-reviews')) return json({ reviews: [] })
    if (url.startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }] })
    return json({})
  }
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => { calls.push({ url: String(url), init }); return respond(String(url), init) }))
  vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'req-t') })
})
afterEach(() => vi.unstubAllGlobals())

it('records a trade with a timezone-aware time and a request id', async () => {
  render(Review, { sub: 'trades' })
  expect(await screen.findByText(/浮动盈亏/)).toBeInTheDocument()
  await fireEvent.input(screen.getByLabelText('代码'), { target: { value: 'nvda' } })
  await fireEvent.input(screen.getByLabelText('数量'), { target: { value: '5' } })
  await fireEvent.input(screen.getByLabelText('成交价'), { target: { value: '102' } })
  await fireEvent.input(screen.getByLabelText('成交时间'), { target: { value: '2026-10-23T10:15' } })
  await fireEvent.click(screen.getByRole('button', { name: '记录成交' }))
  const isPost = (c: { url: string; init?: RequestInit }) => c.url === '/api/workbench/trades' && c.init?.method === 'POST'
  await waitFor(() => expect(calls.some(isPost)).toBe(true))
  const body = JSON.parse(String(calls.find(isPost)!.init!.body))
  expect(body).toMatchObject({ request_id: 'req-t', ticker: 'NVDA', side: 'buy', quantity: '5', price: '102', fee: '0' })
  expect(body.executed_at).toMatch(/^2026-10-23T\d{2}:15:00(\.000)?Z$/)
})

it('voids a trade only with a reason', async () => {
  render(Review, { sub: 'trades' })
  await screen.findByText(/101.5/)
  await fireEvent.click(screen.getByRole('button', { name: '作废' }))
  expect(screen.getByRole('button', { name: '确认作废' })).toBeDisabled()
  await fireEvent.input(screen.getByLabelText('作废理由'), { target: { value: '价格录错' } })
  await fireEvent.click(screen.getByRole('button', { name: '确认作废' }))
  await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/trades/t1/void')).toBe(true))
})

it('shows shadow outcomes with immature windows marked', async () => {
  render(Review, { sub: 'shadow' })
  expect(await screen.findByText('+4.00%')).toBeInTheDocument()
  expect(screen.getAllByText('未成熟').length).toBe(2)
  expect(screen.getByText(/否决/)).toBeInTheDocument()
})

it('generates a weekly review for the chosen Monday', async () => {
  render(Review, { sub: 'weekly' })
  expect(await screen.findByText(/尚无周度复盘/)).toBeInTheDocument()
  await fireEvent.input(screen.getByLabelText('周一'), { target: { value: '2026-10-19' } })
  await fireEvent.input(screen.getByLabelText('复盘笔记'), { target: { value: '合成笔记' } })
  respond = async (url) => url.includes('/weekly-reviews') && calls.at(-1)?.init?.method === 'POST'
    ? json({ id: 'w1', week_start: '2026-10-19', calc_version: 'review-1', notes: '合成笔记', supersedes_id: null, created_at: 'x',
             stats: { units: { decided: 0, undecided: 0 }, by_rule: {}, by_decision: {}, execution: [], unsignaled_trades: [], note: '描述性统计' } })
    : json({ reviews: [] })
  await fireEvent.click(screen.getByRole('button', { name: '生成复盘' }))
  await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/weekly-reviews' && c.init?.method === 'POST')).toBe(true))
  const body = JSON.parse(String(calls.find(c => c.init?.method === 'POST')!.init!.body))
  expect(body).toEqual({ week_start: '2026-10-19', notes: '合成笔记', supersedes_id: null })
})

it('reports 503 instead of an empty review', async () => {
  respond = async (url) => url.startsWith('/api/watchlist') ? json({ rows: [] }) : json({ error: 'down' }, 503)
  render(Review, { sub: 'shadow' })
  expect(await screen.findByText(/数据库未就绪/)).toBeInTheDocument()
})


describe('monthly and account tabs', () => {
  const monthly = (stats: Record<string, unknown>) => ({
    id: 'm1', month: '2026-10-01', calc_version: 'monthly-1', stats, notes: '', supersedes_id: null,
    created_at: '2026-11-01T02:00:00Z',
  })
  const baseStats = { month: '2026-10-01', tier: null, spy: null, review_flag: 'insufficient',
                      sensitivity: { approximate: true, rows: [] }, discipline: {}, plans: {},
                      generated_at: '2026-11-01T02:00:00Z' }

  it('monthly tab shows missing snapshot message', async () => {
    respond = async (url) => url.includes('/monthly-reviews')
      ? json({ reviews: [monthly({ ...baseStats, return: { status: 'missing_snapshot', return: null } })] })
      : json({})
    render(Review, { sub: 'monthly' })
    expect(await screen.findByText(/缺资金快照，无法计算/)).toBeInTheDocument()
  })

  it('monthly tab shows tier and SPY', async () => {
    respond = async (url) => url.includes('/monthly-reviews')
      ? json({ reviews: [monthly({ ...baseStats, return: { status: 'ok', return: 0.12, net_flow: 5000 },
                                   tier: 'excellent', spy: { return: 0.04, excess: 0.08 } })] })
      : json({})
    render(Review, { sub: 'monthly' })
    expect(await screen.findByText(/优秀/)).toBeInTheDocument()
    expect(screen.getByText(/\+12\.00%/)).toBeInTheDocument()
    expect(screen.getByText(/SPY \+4\.00%/)).toBeInTheDocument()
    expect(screen.getByText(/超额 \+8\.00%/)).toBeInTheDocument()
  })

  it('account tab records a snapshot and a flow', async () => {
    respond = async (url, init) => {
      if (url.includes('/account/snapshots') && init?.method !== 'POST')
        return json({ snapshots: [], flows: [], params: { risk_pct: 0.01, single_cap: 0.25, total_cap: 1,
                                                          public_url: 'http://localhost:8787',
                                                          return_tiers: [0.2, 0.1, 0] } })
      if (url.includes('/account/flows') && init?.method === 'POST')
        return json({ status: 'created', record: { id: 'f1' } })
      if (url.includes('/account/snapshots'))
        return json({ status: 'created', record: { id: 's1' } })
      return json({})
    }
    render(Review, { sub: 'account' })
    expect(await screen.findByText(/单票上限 25%/)).toBeInTheDocument()
    await fireEvent.input(screen.getByLabelText('资金日期'), { target: { value: '2026-10-31' } })
    await fireEvent.input(screen.getByLabelText('总资金'), { target: { value: '112000' } })
    await fireEvent.click(screen.getByRole('button', { name: '录入资金快照' }))
    await fireEvent.input(screen.getByLabelText('出入金日期'), { target: { value: '2026-10-15' } })
    await fireEvent.input(screen.getByLabelText('金额'), { target: { value: '5000' } })
    await fireEvent.click(screen.getByRole('button', { name: '录入出入金' }))
    const snap = calls.find(c => c.url.includes('/account/snapshots') && c.init?.method === 'POST')!
    expect(JSON.parse(String(snap.init!.body))).toMatchObject({ as_of: '2026-10-31', equity: '112000' })
    const flow = calls.find(c => c.url.includes('/account/flows') && c.init?.method === 'POST')!
    expect(JSON.parse(String(flow.init!.body))).toMatchObject({ flow_date: '2026-10-15', amount: '5000' })
  })

  it('account tab voids a flow with a reason', async () => {
    respond = async (url) => url.includes('/account/snapshots')
      ? json({ snapshots: [], params: {}, flows: [{ id: 'f1', request_id: 'r', flow_date: '2026-10-15',
                                                    amount: 5000, note: null, recorded_at: '2026-10-15T12:00:00Z',
                                                    voided_at: null, void_reason: null }] })
      : json({})
    render(Review, { sub: 'account' })
    await screen.findByText(/5000/)
    await fireEvent.click(screen.getByRole('button', { name: '作废' }))
    await fireEvent.input(screen.getByLabelText('作废理由'), { target: { value: '录错' } })
    await fireEvent.click(screen.getByRole('button', { name: '确认作废' }))
    await waitFor(() => {
      const voided = calls.find(c => c.url.includes('/account/flows/f1/void'))
      expect(voided).toBeTruthy()
      expect(JSON.parse(String(voided!.init!.body))).toEqual({ reason: '录错' })
    })
  })

  it('weekly shows plan and discipline sections', async () => {
    respond = async (url) => url.includes('/weekly-reviews')
      ? json({ reviews: [{ id: 'w1', week_start: '2026-10-19', calc_version: 'review-2',
                           notes: '', supersedes_id: null, created_at: '2026-10-24T02:00:00Z',
                           stats: { week: { start: '2026-10-19', end: '2026-10-25' }, units: { decided: 1, undecided: 0 },
                                    plans: { rule: { count: 2, expired: 1, r_mean: 1.5, r_median: 1.5 } },
                                    discipline: { counts: { chase: 1, early_take: 0, held_loser: 0, unplanned: 0 },
                                                  planned_buys: 2, compliance_rate: 0.5 } } }] })
      : json({})
    render(Review, { sub: 'weekly' })
    expect(await screen.findByText(/计划影子/)).toBeInTheDocument()
    expect(screen.getByText(/已过期 1/)).toBeInTheDocument()
    expect(screen.getByText(/遵守率 50%/)).toBeInTheDocument()
    expect(screen.getByText(/追高 1/)).toBeInTheDocument()
  })
})
