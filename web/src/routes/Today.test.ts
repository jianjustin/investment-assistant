import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import Today from './Today.svelte'
import { confirmResearchNavigation } from '../lib/navigation-guard'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const plan = (overrides: Record<string, unknown> = {}) => ({
  id: 'p1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'rule', plan_version: 'plan-1', status: 'ok',
  entry_low: 98.5, entry_high: 101.5, stop: 94, target1: 112, ref_price: 100, atr: 2.11,
  valid_from: '2026-10-23', valid_until: '2026-10-27',
  sizing: { status: 'sized', shares: 166, risk_amount: 1000, snapshot_as_of: '2026-10-20' },
  invalid_reasons: [], warnings: [], ...overrides,
})

const holding = (overrides: Record<string, unknown> = {}) => ({
  ticker: 'NVDA', quantity: 10, avg_cost: 100, plan_id: 'p1', stop: 105, mode: 'trailing', t1_reached: true,
  target1: 112, last_close: 110, to_stop_pct: -0.045, to_target_pct: 0.018, next_earnings: null, ...overrides,
})

const unit = (overrides: Record<string, unknown> = {}) => ({
  plan: null,
  ticker: 'NVDA', signal_date: '2026-10-22', proposed_action: 'buy', labels: [], candidate_ids: ['c1'],
  rule_ids: ['trend_reclaim'], entry_passed: false, market_status: 'green', holding: false, position: null,
  candidates: [{ id: 'c1', signal_date: '2026-10-22', action: 'buy', rule_id: 'trend_reclaim',
                 inputs: { values: { close: 110.75, ma20: 108.1 } } }],
  brief: { id: 'b1', status: 'ok', output: { summary: '合成摘要', support: [{ text: '支持一', refs: ['news:2'] }],
                                             contra: [{ text: '反证一', refs: ['candidate:c1'] }], conflicts: [] } },
  filings: [],
  news: [{ id: 2, source: 'yfinance', title: '合成新闻', url: 'https://news.example.com/2', publisher: null,
           published_at: null, fetched_at: '2026-10-22T20:00:00Z' }],
  ...overrides,
})

let calls: { url: string; init?: RequestInit }[]
let respond: (url: string, init?: RequestInit) => Promise<Response>

beforeEach(() => {
  calls = []
  respond = async () => json({ session: '2026-10-22', units: [unit()], holdings: [] })
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => { calls.push({ url: String(url), init }); return respond(String(url), init) }))
  vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValueOnce('req-1').mockReturnValueOnce('req-2') })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('shows candidates, cited brief and undated news without inventing times', async () => {
  render(Today)
  expect(await screen.findByRole('heading', { name: /NVDA/ })).toBeInTheDocument()
  expect(screen.getByText('趋势回踩修复')).toBeInTheDocument()
  expect(screen.getByText('合成摘要')).toBeInTheDocument()
  expect(screen.getByText(/支持一/)).toHaveTextContent('news:2')
  expect(screen.getByText(/反证一/)).toBeInTheDocument()
  expect(screen.getByText(/发布时间未知/)).toBeInTheDocument()
  expect(screen.getByText(/大盘 green（仅背景）/)).toBeInTheDocument()
})

it('labels conflict, avoid, late entry and fallback or invalid briefs', async () => {
  respond = async () => json({ session: '2026-10-22', units: [
    unit({ ticker: 'MU', proposed_action: 'watch', labels: ['conflict'], entry_passed: true,
           brief: { id: 'b2', status: 'fallback', error: 'no key', output: { summary: '规则候选', support: [], contra: [], conflicts: [] } } }),
    unit({ ticker: 'RKLB', proposed_action: 'sell', labels: ['avoid'], brief: { id: 'b3', status: 'error', error: 'unknown refs: news:9' } }),
  ] })
  render(Today)
  await screen.findByRole('heading', { name: /MU/ })
  expect(screen.getByText('冲突')).toBeInTheDocument()
  expect(screen.getByText('回避')).toBeInTheDocument()
  expect(screen.getByText(/已过入场时点/)).toBeInTheDocument()
  expect(screen.getByText(/LLM 未参与/)).toBeInTheDocument()
  expect(screen.getByText(/解读无效，已隐藏/)).toHaveTextContent('unknown refs: news:9')
})

it('requires a reason, posts the decision with a stable request id and removes the unit', async () => {
  render(Today)
  await screen.findByRole('heading', { name: /NVDA/ })
  const submit = screen.getByRole('button', { name: '提交决定' })
  expect(submit).toBeDisabled()
  await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '合成理由' } })
  respond = async (url) => url.includes('/decisions') ? json({ status: 'created', record: { id: 'd1' } }) : json({ session: '2026-10-22', units: [] })
  await fireEvent.click(submit)
  await waitFor(() => expect(screen.getByText('今日没有待处理的信号')).toBeInTheDocument())
  const post = calls.find(c => c.url.includes('/decisions'))!
  expect(JSON.parse(String(post.init!.body))).toMatchObject({ request_id: 'req-1', decision: 'accept', final_action: 'buy',
                                                              reason: '合成理由', brief_id: 'b1' })
})

it('keeps the draft and the request id when the server reports a conflict', async () => {
  render(Today)
  await screen.findByRole('heading', { name: /NVDA/ })
  await fireEvent.click(screen.getByLabelText('否决'))
  await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '保留的草稿' } })
  respond = async (url) => url.includes('/decisions') ? json({ error: 'newer decision' }, 409) : json({ session: '2026-10-22', units: [unit()] })
  await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
  expect(await screen.findByText(/已有更新的记录/)).toBeInTheDocument()
  expect((screen.getByLabelText('理由') as HTMLTextAreaElement).value).toBe('保留的草稿')
  await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
  const ids = calls.filter(c => c.url.includes('/decisions')).map(c => JSON.parse(String(c.init!.body)).request_id)
  expect(ids).toEqual(['req-1', 'req-1'])
})

it('reports a missing database instead of an empty list', async () => {
  respond = async () => json({ error: '工作台数据表未就绪' }, 503)
  render(Today)
  expect(await screen.findByText(/数据库未就绪/)).toBeInTheDocument()
  expect(screen.queryByText('今日没有待处理的信号')).not.toBeInTheDocument()
})

it('guards unsent decision drafts on navigation', async () => {
  render(Today)
  await screen.findByRole('heading', { name: /NVDA/ })
  await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '未提交' } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  expect(confirmResearchNavigation()).toBe(false)
  expect(confirm).toHaveBeenCalled()
})


describe('trade plans', () => {
  it('renders plan levels and shares', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan() })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(screen.getByText(/入场区间 98\.5–101\.5/)).toBeInTheDocument()
    expect(screen.getByText(/止损 94/)).toBeInTheDocument()
    expect(screen.getByText(/T1 112/)).toBeInTheDocument()
    expect(screen.getByText(/建议 166 股/)).toBeInTheDocument()
    expect(screen.getByText(/证据：未验证/)).toBeInTheDocument()
  })

  it('shows the no_equity hint without inventing a size', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan(
      { sizing: { status: 'no_equity', shares: null, snapshot_as_of: null } }) })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(screen.getByText(/缺资金快照，无法计算/)).toBeInTheDocument()
  })

  it('only allows own levels when the rule plan is invalid', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan(
      { status: 'invalid', invalid_reasons: ['earnings_in_validity'] }) })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(screen.getByText(/作废：earnings_in_validity/)).toBeInTheDocument()
    expect(screen.getByLabelText('规则计划')).toBeDisabled()
    expect(screen.getByLabelText('自定价位')).toBeChecked()
  })

  it('blocks own levels with stop >= entry_low', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan({ status: 'invalid' }) })],
                                 holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '自定价位' } })
    await fireEvent.input(screen.getByLabelText('入场下限'), { target: { value: '99' } })
    await fireEvent.input(screen.getByLabelText('入场上限'), { target: { value: '101' } })
    await fireEvent.input(screen.getByLabelText('止损价'), { target: { value: '100' } })
    await fireEvent.input(screen.getByLabelText('T1 价'), { target: { value: '112' } })
    expect(screen.getByText(/价位需满足/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交决定' })).toBeDisabled()
  })

  it('accept sends plan_id for a healthy rule plan', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan() })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '按规则计划' } })
    respond = async (url) => url.includes('/decisions')
      ? json({ status: 'created', record: { id: 'd1' } })
      : json({ session: '2026-10-22', units: [], holdings: [] })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => expect(screen.getByText('今日没有待处理的信号')).toBeInTheDocument())
    const post = calls.find(c => c.url.includes('/decisions'))!
    const body = JSON.parse(String(post.init!.body))
    expect(body.plan_id).toBe('p1')
    expect(body.own_plan).toBeNull()
  })

  it('accept with own levels sends own_plan', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan() })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.click(screen.getByLabelText('自定价位'))
    await fireEvent.input(screen.getByLabelText('入场下限'), { target: { value: '97' } })
    await fireEvent.input(screen.getByLabelText('入场上限'), { target: { value: '101' } })
    await fireEvent.input(screen.getByLabelText('止损价'), { target: { value: '94' } })
    await fireEvent.input(screen.getByLabelText('T1 价'), { target: { value: '110' } })
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '自定' } })
    respond = async (url) => url.includes('/decisions')
      ? json({ status: 'created', record: { id: 'd2' } })
      : json({ session: '2026-10-22', units: [], holdings: [] })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => expect(screen.getByText('今日没有待处理的信号')).toBeInTheDocument())
    const body = JSON.parse(String(calls.find(c => c.url.includes('/decisions'))!.init!.body))
    expect(body.plan_id).toBeNull()
    expect(body.own_plan).toMatchObject({ entry_low: '97', entry_high: '101', stop: '94', target1: '110' })
    expect(body.own_plan.request_id).toBeTruthy()
  })

  it('holdings show stop and t1 state', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [holding()] })
    render(Today)
    expect(await screen.findByText(/持仓止损/)).toBeInTheDocument()
    expect(screen.getByText(/NVDA/)).toBeInTheDocument()
    expect(screen.getByText(/止损 105/)).toBeInTheDocument()
    expect(screen.getByText(/已触 T1/)).toBeInTheDocument()
  })

  it('repush button calls pushToday and shows the result', async () => {
    respond = async (url) => url.includes('/api/workbench/push')
      ? json({ session: '2026-10-22', sent: true, messages: 4 })
      : json({ session: '2026-10-22', units: [], holdings: [] })
    render(Today)
    await screen.findByText('今日没有待处理的信号')
    await fireEvent.click(screen.getByRole('button', { name: '重新推送今日计划' }))
    await waitFor(() => expect(screen.getByText(/已推送 4 条/)).toBeInTheDocument())
    const push = calls.find(c => c.url.includes('/api/workbench/push'))!
    expect(push.init?.method).toBe('POST')
  })
})
