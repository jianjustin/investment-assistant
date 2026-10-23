import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import Today from './Today.svelte'
import { confirmResearchNavigation } from '../lib/navigation-guard'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const unit = (overrides: Record<string, unknown> = {}) => ({
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
  respond = async () => json({ session: '2026-10-22', units: [unit()] })
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
