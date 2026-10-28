import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import Today from './Today.svelte'
import { confirmResearchNavigation } from '../lib/navigation-guard'
import * as api from '../lib/api'

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
afterEach(() => {
  vi.unstubAllGlobals(); vi.restoreAllMocks()
  try { localStorage.removeItem('workbench.today.layout') } catch { /* storage unavailable */ }
})

it('shows candidates, cited brief and undated news without inventing times', async () => {
  render(Today)
  expect(await screen.findByRole('heading', { name: /NVDA/ })).toBeInTheDocument()
  expect(screen.getByText('趋势回踩修复')).toBeInTheDocument()
  expect(screen.getByText('合成摘要')).toBeInTheDocument()
  expect(screen.getByText(/支持一/)).toHaveTextContent('news:2')
  expect(screen.getByText(/反证一/)).toBeInTheDocument()
  expect(screen.getByText(/发布时间未知/)).toBeInTheDocument()
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

describe('market context and extended pool', () => {
  const market = { id: 'r1', session: '2026-10-22', calc_version: 'regime-1', label: 'risk_off',
    breadth: { tickers: 40, eligible_50: 40, above_50: 12, pct_50: 0.3, eligible_200: 40, above_200: 10,
               pct_200: 0.25, eligible_52w: 38, new_highs: 3, new_lows: 5 },
    sectors: { SMH: { rs20: -0.12, rs60: -0.2, state: 'weak' } }, macro: { BAMLH0A0HYM2: null, T10Y2Y: null },
    inputs: {}, created_at: '2026-10-22T23:00:00Z' }
  const contextPlan = (overrides: Record<string, unknown> = {}) => plan({
    inputs: { context: { context_version: 'context-1', pool_tier: 'core',
                         regime: { id: 'r1', label: 'risk_off' },
                         sector: { etf: 'SMH', rs20: -0.12, rs60: -0.2, state: 'weak' },
                         next_earnings: '2026-11-20' } }, ...overrides,
  })

  it('market card shows label and breadth', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], extended_units: [], market })
    render(Today)
    expect(await screen.findByText('防守')).toBeTruthy()
    expect(screen.getByText(/站上 MA50 30\.0%/)).toBeTruthy()
    expect(screen.getByText(/新高 3 \/ 新低 5/)).toBeTruthy()
    expect(screen.getByText(/SMH/)).toBeTruthy()
  })
  it('market card shows FRED not configured', async () => {
    const unconfigured = { ...market, inputs: { macro_status: { BAMLH0A0HYM2: 'not_configured', T10Y2Y: 'not_configured' } } }
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], extended_units: [], market: unconfigured })
    render(Today)
    expect(await screen.findByText('FRED 未配置')).toBeTruthy()
  })
  it('market card tells a FRED failure apart from no key', async () => {
    const failed = { ...market, inputs: { macro_status: { BAMLH0A0HYM2: 'error', T10Y2Y: 'error' } } }
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], extended_units: [], market: failed })
    render(Today)
    expect(await screen.findByText(/FRED 采集失败/)).toBeTruthy()
    expect(screen.queryByText('FRED 未配置')).toBeNull()
  })
  it('market card without recorded FRED status says no data', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], extended_units: [], market })
    render(Today)
    expect(await screen.findByText('FRED 无数据')).toBeTruthy()
  })
  it('extended units show the plan status', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], market: null,
                                 extended_units: [
                                   { ticker: 'AMD', signal_date: '2026-10-22', proposed_action: 'buy',
                                     rule_ids: ['trend_reclaim'], plan: contextPlan({ status: 'invalid' }) },
                                   { ticker: 'ARM', signal_date: '2026-10-22', proposed_action: 'buy',
                                     rule_ids: ['trend_reclaim'], plan: contextPlan() }] })
    render(Today)
    await screen.findByText(/扩展池（只影子跟踪）/)
    const items = [...document.querySelectorAll('details li')].map(li => li.textContent ?? '')
    expect(items.find(t => t.includes('AMD'))).toContain('已作废')
    expect(items.find(t => t.includes('ARM'))).toContain('有效')
  })
  it('plan card shows regime, next earnings and sector', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: contextPlan() })], holdings: [],
                                 extended_units: [], market })
    render(Today)
    expect(await screen.findByText(/区制 防守 · 下次财报 2026-11-20 · 行业 SMH 弱/)).toBeTruthy()
  })
  it('plan card falls back to unknown context', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan() })], holdings: [], extended_units: [], market: null })
    render(Today)
    expect(await screen.findByText(/下次财报 未知 · 行业 未映射/)).toBeTruthy()
  })
  it('extended units are collapsed and have no decision controls', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], market: null,
                                 extended_units: [{ ticker: 'AMD', signal_date: '2026-10-22', proposed_action: 'buy',
                                                    rule_ids: ['trend_reclaim'], plan: contextPlan() }] })
    render(Today)
    expect(await screen.findByText(/扩展池（只影子跟踪）/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '提交决定' })).toBeNull()
    expect(screen.queryByLabelText('理由')).toBeNull()
    const details = document.querySelector('details')!
    expect(details.open).toBe(false)
    expect(details.textContent).toContain('AMD')
  })
})

describe('agent track', () => {
  const agentPlan = (overrides: Record<string, unknown> = {}) => ({
    id: 'ap1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'agent', plan_version: 'agent-1', status: 'ok',
    entry_low: 98.5, entry_high: 101.5, stop: 96, target1: 108, ref_price: 100, atr: 2,
    valid_from: '2026-10-23', valid_until: '2026-10-27',
    sizing: { status: 'sized', shares: 166, risk_amount: 1000, snapshot_as_of: '2026-10-20' },
    invalid_reasons: [], warnings: [], ...overrides,
  })

  const agentOk = (overrides: Record<string, unknown> = {}) => ({
    id: 'r1', status: 'ok', model: 'glm-5.3', agent_version: 'agent-1',
    output: { action: 'buy', summary: '回踩修复放量',
              levels: { entry_low: { value: '98.50', refs: ['call:1'] },
                        entry_high: { value: '101.50', refs: ['call:1'] },
                        stop: { value: '96.00', refs: ['call:1'] },
                        target1: { value: '108.00', refs: ['call:1'] } },
              thesis: [{ text: '放量突破 20 日线', refs: ['call:1'] }] },
    counter: { status: 'ok', risks: [{ text: '财报临近', refs: ['call:1'] }], dropped: 0 },
    plan: agentPlan(), input_tokens: 40, output_tokens: 20, created_at: '2026-10-22T23:00:00Z',
    ...overrides,
  })

  const agentRejected = {
    id: 'r2', status: 'rejected', reason: 'invalid_citation', created_at: '2026-10-22T23:00:00Z',
  }

  const toolCallDetail = () => ({
    ...agentOk(), tool_calls: [
      { seq: 1, phase: 'propose', tool: 'get_indicators', args: { ticker: 'NVDA' },
        result: { ref: 'call:1', data: { last_close: 100 } },
        result_sha256: 'abcd1234ef567890abcd1234ef567890abcd1234ef567890abcd1234ef567890',
        called_at: '2026-10-22T22:31:00Z' }],
  })

  const todayWith = (units: any[], extended: any[] = []) =>
    async () => json({ session: '2026-10-22', units, extended_units: extended, holdings: [] })

  it('agent block shows action, levels, thesis refs and counter', async () => {
    respond = todayWith([unit({ agent: agentOk() })])
    render(Today)
    expect(await screen.findByText('Agent 建议（glm-5.3 · agent-1）买入')).toBeInTheDocument()
    expect(screen.getByText('入场区间 98.50–101.50 · 止损 96.00 · T1 108.00')).toBeInTheDocument()
    expect(screen.getByText('建议 166 股')).toBeInTheDocument()
    expect(screen.getByText('回踩修复放量')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'call:1' }).length).toBeGreaterThan(0)
    expect(screen.getByText(/反方：/)).toBeInTheDocument()
    expect(screen.getByText(/财报临近/)).toBeInTheDocument()
  })

  it('clicking a ref opens the tool call', async () => {
    respond = async (url: string) =>
      url.includes('/agent-runs/r1') ? json(toolCallDetail()) : await todayWith([unit({ agent: agentOk() })])()
    render(Today)
    await fireEvent.click((await screen.findAllByRole('button', { name: 'call:1' }))[0])
    expect(await screen.findByText(/get_indicators/)).toBeInTheDocument()
    expect(screen.getByText(/abcd1234/)).toBeInTheDocument()          // 哈希前 8 位
    expect(screen.getByText(/ticker/)).toBeInTheDocument()            // 调用参数
    expect(screen.getByRole('button', { name: /关闭/ })).toBeInTheDocument()
  })

  it('rejected agent shows reason and rerun button', async () => {
    respond = todayWith([unit({ agent: agentRejected })])
    render(Today)
    expect(await screen.findByText('Agent 未给出计划：引用无效已作废')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新运行 Agent' })).toBeInTheDocument()
  })

  it('rerun posts and refreshes', async () => {
    respond = async (url: string, init?: RequestInit) => {
      if (url === '/api/workbench/agent-runs' && init?.method === 'POST')
        return json({ id: 'r3', status: 'ok', reason: null })
      return await todayWith([unit({ agent: agentRejected })])()
    }
    render(Today)
    await fireEvent.click(await screen.findByRole('button', { name: '重新运行 Agent' }))
    await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/agent-runs'
      && c.init?.method === 'POST')).toBe(true))
    const body = JSON.parse(String(calls.find(c => c.url === '/api/workbench/agent-runs')!.init!.body))
    expect(body).toEqual({ ticker: 'NVDA', signal_date: '2026-10-22' })
    await waitFor(() => expect(calls.filter(c => c.url === '/api/workbench/today').length).toBeGreaterThanOrEqual(2))
  })

  it('agent basis enabled only when agent plan ok', async () => {
    respond = todayWith([unit({ plan: plan(), agent: { id: 'r', status: 'pass', model: 'glm-5.3',
      output: { summary: '趋势不明' }, counter: null, plan: null, input_tokens: 5, output_tokens: 5,
      created_at: 'c' } })])
    const { unmount } = render(Today)
    expect((await screen.findByRole('radio', { name: /Agent 计划/ }) as HTMLInputElement).disabled).toBe(true)
    unmount()

    respond = todayWith([unit({ plan: plan(), agent: agentOk() })])
    render(Today)
    expect((await screen.findByRole('radio', { name: /Agent 计划/ }) as HTMLInputElement).disabled).toBe(false)
  })

  it('rule invalid and agent ok defaults basis to agent', async () => {
    respond = todayWith([unit({ plan: plan({ status: 'invalid', invalid_reasons: ['earnings_in_validity'] }),
                               agent: agentOk() })])
    render(Today)
    expect((await screen.findByRole('radio', { name: /Agent 计划/ }) as HTMLInputElement).checked).toBe(true)
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '按 Agent 建议执行' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => {
      const post = calls.find(c => c.url === '/api/workbench/decisions')
      expect(JSON.parse(String(post!.init!.body)).plan_id).toBe('ap1')
    })
  })

  it('missing rule plan and agent ok defaults basis to agent and locks rule', async () => {
    respond = todayWith([unit({ plan: null, agent: agentOk() })])
    render(Today)
    expect((await screen.findByRole('radio', { name: /Agent 计划/ }) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText(/规则计划/) as HTMLInputElement).disabled).toBe(true)
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '规则计划缺失，按 Agent 执行' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => {
      const post = calls.find(c => c.url === '/api/workbench/decisions')
      expect(JSON.parse(String(post!.init!.body)).plan_id).toBe('ap1')
    })
  })

  it('missing rule plan and void agent plan still offers own levels', async () => {
    respond = todayWith([unit({ plan: null, agent: agentOk({
      plan: agentPlan({ status: 'invalid', invalid_reasons: ['no_room'] }) }) })])
    render(Today)
    expect((await screen.findByLabelText(/自定价位/) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText(/规则计划/) as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByRole('radio', { name: /Agent 计划/ }) as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByLabelText('入场下限')).toBeInTheDocument()
  })

  it('level refs open their tool calls', async () => {
    const levels = { entry_low: { value: '98.50', refs: ['call:2'] }, entry_high: { value: '101.50', refs: ['call:2'] },
                     stop: { value: '96.00', refs: ['call:2'] }, target1: { value: '108.00', refs: ['call:2'] } }
    const agent = agentOk({ output: { ...agentOk().output, levels } })
    respond = async (url: string) => url.includes('/agent-runs/r1')
      ? json({ ...agent, tool_calls: [...toolCallDetail().tool_calls,
          { seq: 2, phase: 'propose', tool: 'get_price_bars', args: { ticker: 'NVDA', lookback: 20 },
            result: { ref: 'call:2', data: [] }, result_sha256: '99887766'.repeat(8), called_at: '2026-10-22T22:32:00Z' }] })
      : await todayWith([unit({ agent })])()
    render(Today)
    const line = await screen.findByText(/价位引用/)
    const buttons = Array.from(line.querySelectorAll('button')).filter(b => b.textContent === 'call:2')
    expect(buttons.length).toBe(4)
    await fireEvent.click(buttons[2])
    expect(await screen.findByText(/get_price_bars/)).toBeInTheDocument()
    expect(screen.getByText(/99887766/)).toBeInTheDocument()
  })

  it('extended list shows agent status', async () => {
    respond = todayWith([], [{ ticker: 'X01', signal_date: '2026-10-22', proposed_action: 'buy',
                               rule_ids: ['trend_reclaim'], plan: null, agent_status: 'skipped: disabled' }])
    render(Today)
    await fireEvent.click(await screen.findByText(/扩展池/))
    expect(await screen.findByText(/Agent skipped: disabled/)).toBeInTheDocument()
  })
})


// --- interpret briefs (P4 §7.5) ---

it('collapses an agent-1 brief to a pointer line', async () => {
  respond = async () => json({ session: '2026-10-22', units: [unit({
    brief: { id: 'b1', status: 'ok', prompt_version: 'agent-1', model: 'glm-5.3',
             output: { summary: '回踩修复后放量上行', support: [], contra: [], conflicts: [] } } })], holdings: [] })
  render(Today)
  expect(await screen.findByText('解读见 Agent 建议')).toBeInTheDocument()
  expect(screen.queryByText('回踩修复后放量上行')).not.toBeInTheDocument()
})

it('shows the model name on an interpret brief', async () => {
  respond = async () => json({ session: '2026-10-22', units: [unit({
    brief: { id: 'b1', status: 'ok', prompt_version: 'agent-brief-1', model: 'glm-5.3',
             output: { summary: '持仓回撤，趋势未坏', support: [], contra: [], conflicts: [] } } })], holdings: [] })
  render(Today)
  expect(await screen.findByText('持仓回撤，趋势未坏')).toBeInTheDocument()
  expect(screen.getByText(/glm-5.3/)).toBeInTheDocument()
})


describe('derivation expansion', () => {
  const planDerivation = (over: Record<string, unknown> = {}) => ({
    derivation_version: 'derivation-1',
    plan: { id: 'p1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'rule', plan_version: 'plan-1', status: 'ok' },
    trigger: { note: '触发段只复核候选冻结的取值是否满足阈值，不从原始日线重算均线。', candidates: [] },
    inputs: {}, steps: [], checks: [],
    consistency: { status: 'consistent', mismatches: [], missing: [] },
    evidence: '规则 v1 与 `plan-1` 都未经验证（Phase 0 Gate HOLD）。推导一致只说明算术正确，不说明规则有效。',
    run: { ready: true, run_id: 'run-9', stage: 'plan', status: 'success',
           derivation: { checked: 1, consistent: 1, mismatch: 0, incomplete: 0 } },
    ...over,
  })

  const agentWithPlan = () => ({
    id: 'r1', status: 'ok', model: 'glm-5.3', agent_version: 'agent-1',
    output: { action: 'buy', summary: '回踩修复放量',
              levels: { entry_low: { value: '98.50', refs: ['call:1'] },
                        entry_high: { value: '101.50', refs: ['call:1'] },
                        stop: { value: '96.00', refs: ['call:1'] },
                        target1: { value: '108.00', refs: ['call:1'] } },
              thesis: [] },
    counter: null,
    plan: { id: 'ap1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'agent', plan_version: 'agent-1', status: 'ok',
            entry_low: '98.50', entry_high: '101.50', stop: '96.00', target1: '108.00', ref_price: 100, atr: 0,
            valid_from: '2026-10-23', valid_until: '2026-10-27',
            sizing: { status: 'sized', shares: 166, risk_amount: 1000, snapshot_as_of: '2026-10-20' },
            invalid_reasons: [], warnings: [] },
    input_tokens: 1, output_tokens: 1, created_at: '2026-10-22T23:00:00Z',
  })

  it('rule plan has 展开推导 and fetches on click only', async () => {
    respond = async (url: string) => url.includes('/derivation')
      ? json(planDerivation())
      : json({ session: '2026-10-22', units: [unit({ plan: plan() })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(calls.filter(c => c.url.includes('derivation'))).toHaveLength(0)   // 点开前不请求
    await fireEvent.click(screen.getByRole('button', { name: '展开推导' }))
    await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/plans/p1/derivation')).toBe(true))
    expect(await screen.findByText('推导与重算一致')).toBeInTheDocument()
  })

  it('agent plan block has 展开推导', async () => {
    respond = async (url: string) => url.includes('/derivation')
      ? json(planDerivation({ plan: { id: 'ap1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'agent',
                                      plan_version: 'agent-1', status: 'ok' } }))
      : json({ session: '2026-10-22', units: [unit({ plan: null, agent: agentWithPlan() })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.click(screen.getByRole('button', { name: '展开推导' }))
    await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/plans/ap1/derivation')).toBe(true))
    expect(await screen.findByText('推导与重算一致')).toBeInTheDocument()
  })

  it('unit without plan shows 触发依据', async () => {
    respond = async (url: string) => url.includes('/derivation')
      ? json({ derivation_version: 'derivation-1',
               trigger: [{ candidate_id: 'c1', rule_id: 'trend_reclaim', rule_version: '1', action: 'buy',
                           clauses: [{ text: 'close > ma20', operands: { 'values.close': 110.75, 'values.ma20': 108.2 },
                                      result: 'holds' }] }],
               consistency: { status: 'consistent', mismatches: [], missing: [] },
               evidence: '规则 v1 与 `plan-1` 都未经验证（Phase 0 Gate HOLD）。推导一致只说明算术正确，不说明规则有效。',
               note: '触发段只复核候选冻结的取值是否满足阈值，不从原始日线重算均线。', plan_ids: [] })
      : json({ session: '2026-10-22', units: [unit()], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.click(screen.getByRole('button', { name: '触发依据' }))
    await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/units/NVDA/2026-10-22/derivation')).toBe(true))
    expect(await screen.findByText('触发段只复核候选冻结的取值是否满足阈值，不从原始日线重算均线。')).toBeInTheDocument()
    expect(screen.getByText('成立')).toBeInTheDocument()
  })
})

const screenReport = (over: Record<string, unknown> = {}) => ({
  session: '2026-10-22', calc_version: 'screen-1', status: 'success', error: null,
  universe: { name: 'nasdaq100', as_of: '2026-10-22', stale: false },
  counts: { universe: 100, data_skipped: 0, illiquid: 0, earnings_soon: 0, no_setup: 74,
            trigger: 2, setup: 12, selected: 14 },
  selected: ['T1', 'T2', ...Array.from({ length: 12 }, (_, i) => `S${i}`)],
  members: 20, cap: 40, evicted: [], removed: [], flags: [],
  triggers: [
    { ticker: 'T1', rule_ids: ['trend_reclaim'], rs: 0.12, review: 'plan',
      plan: { entry_low: 98.5, entry_high: 101.5, stop: 94, target1: 112, shares: 166,
              sizing_status: 'sized' }, invalid_reasons: [] },
    { ticker: 'T2', rule_ids: ['volume_breakout'], rs: 0.1, review: 'invalid', plan: null,
      invalid_reasons: ['earnings'] },
  ],
  setups: Array.from({ length: 10 }, (_, i) => ({ ticker: `S${i}`, rs: 0.05 - i * 0.001, atr_pct: 0.04, rank: 3 + i })),
  setups_more: 2, ...over,
})

describe('今日 · 筛选卡片', () => {
  it('renders the screen card', async () => {
    const twelve = Array.from({ length: 12 }, (_, i) => ({ ticker: `S${i}`, rs: 0.05 - i * 0.001, atr_pct: 0.04, rank: 3 + i }))
    respond = async (url) => json(url.includes('/api/workbench/today')
      ? { session: '2026-10-22', units: [], holdings: [], screen: screenReport() }
      : { report: screenReport({ setups: twelve, setups_more: 0 }) })
    render(Today)
    const card = await screen.findByRole('region', { name: '筛选' })
    expect(card).toHaveTextContent('范围 100 · 通过过滤 14')
    expect(card).toHaveTextContent('今日入选 14（触发 2 / 形态 12）')
    expect(card).toHaveTextContent('成员 20/40')
    expect(card).toHaveTextContent('T1')
    expect(card).toHaveTextContent('入场 98.5–101.5 · 止损 94 · T1 112 · 建议 166 股')
    expect(card).toHaveTextContent('作废 earnings')
    expect(card).toHaveTextContent('S0')
    expect(card).toHaveTextContent('另 2 只')
    expect(screen.queryByText(/S10/)).toBeNull()
    await fireEvent.click(screen.getByRole('button', { name: '展开全部' }))
    await waitFor(() => expect(calls.some(c => c.url.includes('/api/workbench/screen') && c.url.includes('full=1'))).toBe(true))
    expect(await screen.findByText(/S11/)).toBeInTheDocument()
  })

  it('screen trigger without an equity snapshot shows no null shares', async () => {
    const report = screenReport({ triggers: [
      { ticker: 'T1', rule_ids: ['trend_reclaim'], rs: 0.12, review: 'plan',
        plan: { entry_low: 98.5, entry_high: 101.5, stop: 94, target1: 112, shares: null,
                sizing_status: 'no_equity' }, invalid_reasons: [] }] })
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], screen: report })
    render(Today)
    const card = await screen.findByRole('region', { name: '筛选' })
    expect(card).toHaveTextContent('T1 112 · 缺资金快照，无法计算股数')
    expect(card).not.toHaveTextContent('null')
  })

  it('splits today\'s picks, not the groups that passed', async () => {
    // Real 2026-10-23 shape: 1 trigger + 20 setups passed, 20 picked -> 1 trigger + 19 setups picked.
    const setups = Array.from({ length: 20 }, (_, i) => `S${i}`)
    const report = screenReport({
      counts: { universe: 94, data_skipped: 2, illiquid: 0, earnings_soon: 30, no_setup: 41,
                trigger: 1, setup: 20, selected: 20 },
      selected: ['T1', ...setups.slice(0, 19)],
      triggers: [{ ticker: 'T1', rule_ids: ['trend_reclaim'], rs: 0.2, review: 'watch', plan: null,
                   invalid_reasons: [] }] })
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], screen: report })
    render(Today)
    const card = await screen.findByRole('region', { name: '筛选' })
    expect(card).toHaveTextContent('通过过滤 21')
    expect(card).toHaveTextContent('今日入选 20（触发 1 / 形态 19）')
  })

  it('screen units carry a badge', async () => {
    respond = async () => json({ session: '2026-10-22', units: [
      unit({ ticker: 'U00', source: 'screen' }), unit({ ticker: 'NVDA', source: 'watchlist' })],
      holdings: [], screen: null })
    render(Today)
    expect(await screen.findByRole('heading', { name: /U00/ })).toBeInTheDocument()
    expect(screen.getByTitle('筛选来源')).toHaveTextContent('筛选')
    expect(screen.getAllByTitle('筛选来源')).toHaveLength(1)
  })

  it('screen error is shown plainly', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [],
      screen: screenReport({ status: 'error', error: 'benchmark_missing', triggers: [], setups: [], setups_more: 0 }) })
    render(Today)
    expect(await screen.findByText('筛选未运行：benchmark_missing')).toBeInTheDocument()
    expect(screen.getByText(/沿用成员 20 只/)).toBeInTheDocument()
  })
})


// --- v2.5 agent-first Today (spec §10.1, §10.2, §11, §13) ---

it('collapses an agent-2 brief to a pointer line too', async () => {
  respond = async () => json({ session: '2026-10-22', units: [unit({
    brief: { id: 'b1', status: 'ok', prompt_version: 'agent-2', model: 'glm-5.3',
             output: { summary: '回踩修复后放量上行', support: [], contra: [{ text: '量能来自指数调仓', refs: ['call:5'] }],
                       conflicts: [] } } })], holdings: [] })
  render(Today)
  expect(await screen.findByText('解读见 Agent 建议')).toBeInTheDocument()
  expect(screen.queryByText('回踩修复后放量上行')).not.toBeInTheDocument()
  expect(screen.queryByText(/量能来自指数调仓/)).not.toBeInTheDocument()
})

describe('agent-first layout', () => {
  const agentPlan2 = (overrides: Record<string, unknown> = {}) => ({
    id: 'ap2', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'agent', plan_version: 'agent-2', status: 'ok',
    entry_low: '98.50', entry_high: '101.50', stop: '96.00', target1: '108.00', ref_price: '100.00', atr: '2.00',
    valid_from: '2026-10-23', valid_until: '2026-10-27',
    sizing: { status: 'sized', shares: 120, risk_amount: '1000.00', snapshot_as_of: '2026-10-20' },
    invalid_reasons: [], warnings: [], ...overrides,
  })
  const chain = (overrides: Record<string, unknown> = {}) => ({
    version_no: 1, head_plan_id: 'ap2', state: 'entry', mode: 'entry', basis: '尚未决定',
    latest_review: null, ...overrides,
  })
  const agent2 = (overrides: Record<string, unknown> = {}) => ({
    id: 'r2', status: 'ok', model: 'glm-5.3', agent_version: 'agent-2',
    output: { action: 'buy', summary: '回踩修复放量',
              levels: { entry_low: { value: '98.50', refs: ['call:1'] }, entry_high: { value: '101.50', refs: ['call:1'] },
                        stop: { value: '96.00', refs: ['call:1'] }, target1: { value: '108.00', refs: ['call:1'] } },
              thesis: [{ id: 'T1', text: '放量突破 20 日线', refs: ['call:1'] }],
              invalidation: [{ kind: 'close_below', params: { price: '95.00' }, text: '收盘跌破 95.00', refs: ['call:1'] }],
              review_when: [] },
    counter: { status: 'ok', counter: [], risks: [], dropped: 0, uncountered: [1] },
    plan: agentPlan2(), input_tokens: 40, output_tokens: 20, created_at: '2026-10-22T23:00:00Z',
    chain: chain(), ...overrides,
  })
  const today = (units: any[], extra: Record<string, unknown> = {}) =>
    async () => json({ session: '2026-10-22', units, extended_units: [], holdings: [], timeline_ready: true,
                       chains: [], ...extra })
  const agentBlock = () => screen.getByRole('region', { name: 'Agent 计划' })
  const baseline = () => screen.getByTestId('rule-baseline')
  const before = (a: Element, b: Element) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
  const FULL_RULE = /入场区间 98\.5–101\.5 · 止损 94 · T1 112/

  it('agent block renders before rule baseline', async () => {
    respond = today([unit({ plan: plan(), agent: agent2() })])
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(before(agentBlock(), baseline())).toBe(true)
    expect(agentBlock()).toHaveTextContent('Agent 计划 · 第 1 版')
  })

  it('agent block shows cutoff, host diff and per-condition judgments from the today view', async () => {
    const review = { id: 5, session: '2026-10-23', trigger: 'batch', outcome: 'maintain', decided_by: 'host',
      reason: '无新信号，复查条件未满足（下一交易日）', new_plan_id: null, revision_status: null,
      created_at: '2026-10-23T22:40:00Z',
      conditions: [{ list: 'invalidation', index: 0, kind: 'close_below', params: { price: '95.00' },
                     result: 'not_met', detail: '' }] }
    respond = today([unit({ plan: plan(), agent: agent2({
      output: { ...agent2().output, changes: [{ field: 'stop', text: '止损上移到前低', refs: ['call:1'] }] },
      chain: chain({ cutoff_at: '2026-10-23T14:30:00Z', diff: [{ field: 'stop', before: '95.00', after: '96.00' }],
                     latest_review: review }) }) })])
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(agentBlock()).toHaveTextContent('Agent 计划 · 第 1 版 · 生成于 2026-10-23 07:00:00 北京 · 截止 2026-10-23 22:30:00 北京')
    expect(screen.getByRole('list', { name: '失效条件' })).toHaveTextContent('收盘跌破 95.00 · 最近判定：未成立')
    const changes = screen.getByRole('region', { name: '相对第 0 版' })
    expect(changes).toHaveTextContent('止损 95.00 → 96.00')
    expect(changes).toHaveTextContent('止损上移到前低')
    expect(changes).not.toHaveTextContent('见计划页版本链')
  })

  it('rule baseline folded to one line and expands', async () => {
    respond = today([unit({ plan: plan(), agent: agent2() })])
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(baseline()).toHaveTextContent('规则基线 plan-1：入场 98.5–101.5 · 止损 94 · T1 112 · 建议 166 股（有效）')
    expect(screen.queryByText(FULL_RULE)).toBeNull()
    await fireEvent.click(screen.getByRole('button', { name: '展开' }))
    expect(screen.getByText(FULL_RULE)).toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: '收起' }))
    expect(screen.queryByText(FULL_RULE)).toBeNull()
  })

  it('baseline auto-expands when agent failed, passed or invalidated', async () => {
    const cases = [
      { id: 'r3', status: 'error', reason: 'model_error', created_at: '2026-10-22T23:00:00Z' },
      agent2({ status: 'pass', plan: null, output: { action: 'pass', summary: '趋势不明', levels: null, thesis: [] } }),
      agent2({ chain: chain({ state: 'invalidated', latest_review: { outcome: 'invalidate', decided_by: 'host',
        reason: '失效条件成立：收盘跌破 95.00', created_at: '2026-10-23T22:40:00Z', new_plan_id: null,
        revision_status: null } }) }),
    ]
    const texts = ['Agent 未给出计划：模型调用失败', 'Agent 不建议买入：趋势不明',
                   'Agent 已作废此计划（第 1 版）：失效条件成立：收盘跌破 95.00']
    for (const [i, agent] of cases.entries()) {
      respond = today([unit({ plan: plan(), agent })])
      const { unmount } = render(Today)
      expect(await screen.findByText(texts[i])).toBeInTheDocument()
      expect(screen.getByText(FULL_RULE)).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '展开' })).toBeNull()
      expect(screen.queryByRole('button', { name: '收起' })).toBeNull()
      unmount()
    }
  })

  it('layout toggle switches to legacy order and persists', async () => {
    respond = today([unit({ plan: plan(), agent: agent2() })])
    const first = render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(screen.getByRole('button', { name: 'Agent 优先' })).toHaveAttribute('aria-pressed', 'true')
    await fireEvent.click(screen.getByRole('button', { name: '规则优先（旧）' }))
    expect(before(baseline(), agentBlock())).toBe(true)
    expect(screen.getByText(FULL_RULE)).toBeInTheDocument()            // 旧布局都不折叠
    expect(screen.queryByRole('button', { name: '展开' })).toBeNull()
    expect(localStorage.getItem('workbench.today.layout')).toBe('legacy')
    first.unmount()

    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(screen.getByRole('button', { name: '规则优先（旧）' })).toHaveAttribute('aria-pressed', 'true')
    expect(before(baseline(), agentBlock())).toBe(true)
  })

  it('layout falls back to agent_first when localStorage throws', async () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') },
      removeItem: () => { throw new Error('denied') },
    })
    respond = today([unit({ plan: plan(), agent: agent2() })])
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(before(agentBlock(), baseline())).toBe(true)
    await fireEvent.click(screen.getByRole('button', { name: '规则优先（旧）' }))   // 写失败也照样切换
    expect(before(baseline(), agentBlock())).toBe(true)
  })

  it('basis defaults to agent and lists Agent 计划（第 n 版） first', async () => {
    respond = today([unit({ plan: plan(), agent: agent2() })])
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    const fieldset = screen.getByRole('group', { name: '执行依据' })
    const labels = [...fieldset.querySelectorAll('label')].map(l => l.textContent?.trim())
    expect(labels).toEqual(['Agent 计划（第 1 版）', '规则计划', '自定价位'])
    expect((screen.getByLabelText('Agent 计划（第 1 版）') as HTMLInputElement).checked).toBe(true)
  })

  it('decision payload carries agent_plan_id and review_view.baseline_expanded', async () => {
    respond = today([unit({ plan: plan(), agent: agent2() })])
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.click(screen.getByRole('button', { name: '展开' }))
    await fireEvent.click(screen.getByRole('button', { name: '收起' }))     // 展开过即记 true
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '按 Agent 计划' } })
    respond = async (url) => url.includes('/decisions')
      ? json({ status: 'created', record: { id: 'd1' } })
      : json({ session: '2026-10-22', units: [], holdings: [] })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => expect(calls.some(c => c.url.includes('/decisions'))).toBe(true))
    const body = JSON.parse(String(calls.find(c => c.url.includes('/decisions'))!.init!.body))
    expect(body.plan_id).toBe('ap2')
    expect(body.agent_plan_id).toBe('ap2')
    expect(body.review_view).toEqual({ layout: 'agent_first', baseline_expanded: true, agent_version_no: 1 })
  })

  it('reports baseline_expanded false when the folded baseline was never opened', async () => {
    respond = today([unit({ plan: plan(), agent: agent2() })])
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '按 Agent 计划' } })
    respond = async (url) => url.includes('/decisions')
      ? json({ status: 'created', record: { id: 'd1' } }) : json({ session: '2026-10-22', units: [], holdings: [] })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => expect(calls.some(c => c.url.includes('/decisions'))).toBe(true))
    const body = JSON.parse(String(calls.find(c => c.url.includes('/decisions'))!.init!.body))
    expect(body.review_view).toEqual({ layout: 'agent_first', baseline_expanded: false, agent_version_no: 1 })
  })

  it('omits agent_plan_id and review_view when migration 026 is missing', async () => {
    respond = today([unit({ plan: plan(), agent: agent2() })], { timeline_ready: false })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '按规则' } })
    respond = async (url) => url.includes('/decisions')
      ? json({ status: 'created', record: { id: 'd1' } }) : json({ session: '2026-10-22', units: [], holdings: [] })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => expect(calls.some(c => c.url.includes('/decisions'))).toBe(true))
    const body = JSON.parse(String(calls.find(c => c.url.includes('/decisions'))!.init!.body))
    expect('agent_plan_id' in body).toBe(false)
    expect('review_view' in body).toBe(false)
  })

  it('409 agent_plan_stale shows message and refresh', async () => {
    respond = today([unit({ plan: plan(), agent: agent2() })])
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '按 Agent 计划' } })
    respond = async (url) => url.includes('/decisions')
      ? json({ error: 'agent_plan_stale: Agent 计划已更新到第 2 版，请刷新后再决定' }, 409)
      : await today([unit({ plan: plan(), agent: agent2({ chain: chain({ version_no: 2, head_plan_id: 'ap3' }),
                                                          plan: agentPlan2({ id: 'ap3' }) }) })])()
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    expect(await screen.findByText('Agent 计划已更新到第 2 版，请刷新后再决定')).toBeInTheDocument()
    expect((screen.getByLabelText('理由') as HTMLTextAreaElement).value).toBe('按 Agent 计划')
    const before = calls.filter(c => c.url === '/api/workbench/today').length
    await fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    await waitFor(() => expect(calls.filter(c => c.url === '/api/workbench/today').length).toBe(before + 1))
    expect(await screen.findByText(/Agent 计划 · 第 2 版/)).toBeInTheDocument()
    expect((screen.getByLabelText('理由') as HTMLTextAreaElement).value).toBe('按 Agent 计划')
  })

  it('进行中的 Agent 计划 lists chains with recheck', async () => {
    const chains = [
      { ticker: 'AMD', signal_date: '2026-10-20', state: 'holding', mode: 'holding', basis: '持仓中', version_no: 2,
        head_plan_id: 'hp-amd', valid_until: '2026-10-27', pool: 'core',
        latest_review: { outcome: 'revise', decided_by: 'agent', created_at: '2026-10-21T22:40:00Z',
                         reason: '财报提前，止损上移' },
        signals_today: ['t1_touched', 'user_input'] },
      { ticker: 'ARM', signal_date: '2026-10-21', state: 'entry', mode: 'entry', basis: '已决定买入', version_no: 0,
        head_plan_id: 'hp-arm', valid_until: '2026-10-24', pool: 'core', latest_review: null, signals_today: [] },
    ]
    respond = async (url, init) => {
      if (url.endsWith('/recheck') && init?.method === 'POST')
        return url.includes('/ARM/') ? json({ error: 'review_in_progress' }, 409)
          : json({ run_id: 'plan_recheck-1', status: 'pending' })
      if (url.startsWith('/api/runs/')) return json({ run_id: 'plan_recheck-1', status: 'done',
                                                      result: { outcome: 'maintain', decided_by: 'agent' } })
      return await today([], { chains })()
    }
    render(Today)
    const section = await screen.findByRole('region', { name: '进行中的 Agent 计划' })
    const rows = section.querySelectorAll('li')
    expect(rows[0]).toHaveTextContent('AMD · 持仓期 · 第 2 版')
    expect(rows[0]).toHaveTextContent('修订 · Agent')
    expect(rows[0]).toHaveTextContent('财报提前，止损上移')
    expect(rows[0]).toHaveTextContent('触及 T1、新的用户输入')
    expect(rows[1]).toHaveTextContent('ARM · 入场期 · 第 0 版')
    expect(rows[1]).toHaveTextContent('尚未复查')
    expect(rows[0].querySelector('a')!.getAttribute('href')).toBe('#plan/hp-amd')
    const buttons = screen.getAllByRole('button', { name: '重新复查' })
    await fireEvent.click(buttons[0])
    expect(await screen.findByText('复查完成：维持')).toBeInTheDocument()
    expect(calls.some(c => c.url === '/api/workbench/chains/AMD/2026-10-20/recheck' && c.init?.method === 'POST')).toBe(true)
    await fireEvent.click(screen.getAllByRole('button', { name: '重新复查' })[1])
    expect(await screen.findByText('不能重新复查：正在复查')).toBeInTheDocument()
  })

  const activeChain = { ticker: 'AMD', signal_date: '2026-10-20', state: 'holding', mode: 'holding', basis: '持仓中',
                       version_no: 2, head_plan_id: 'hp-amd', valid_until: '2026-10-27', pool: 'core',
                       latest_review: null, signals_today: [] }

  it('active chain rows have DiscussButton', async () => {
    respond = async (url, init) => url === '/api/workbench/discussions' && init?.method === 'POST'
      ? json({ id: 5 }) : await today([], { chains: [activeChain] })()
    location.hash = ''
    render(Today)
    const section = await screen.findByRole('region', { name: '进行中的 Agent 计划' })
    await fireEvent.click(within(section).getByRole('button', { name: '就此计划讨论' }))
    await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/discussions' && c.init?.method === 'POST')).toBe(true))
    const post = calls.find(c => c.url === '/api/workbench/discussions')!
    expect(JSON.parse(String(post.init!.body))).toMatchObject({ context: { kind: 'plan', plan_id: 'hp-amd' } })
    await waitFor(() => expect(location.hash).toBe('#discuss/5'))
  })

  it('recheck polls up to 15 minutes and reports a poll timeout as still running', async () => {
    respond = async (url, init) => url.endsWith('/recheck') && init?.method === 'POST'
      ? json({ run_id: 'plan_recheck-1', status: 'pending' }) : await today([], { chains: [activeChain] })()
    const poll = vi.spyOn(api, 'pollRun').mockRejectedValue(new Error('run timeout'))
    render(Today)
    await fireEvent.click(await screen.findByRole('button', { name: '重新复查' }))
    expect(await screen.findByText('复查仍在后台进行，稍后刷新查看')).toBeInTheDocument()
    expect(poll).toHaveBeenCalledWith('plan_recheck-1', { timeoutMs: 900_000 })
    expect(screen.getByRole('button', { name: '重新复查' })).toBeDisabled()
    expect(screen.queryByText(/请求失败/)).toBeNull()
  })

  it('recheck finishing as skipped shows the reason', async () => {
    respond = async (url, init) => {
      if (url.endsWith('/recheck') && init?.method === 'POST') return json({ run_id: 'plan_recheck-2', status: 'pending' })
      if (url.startsWith('/api/runs/')) return json({ run_id: 'plan_recheck-2', status: 'done',
                                                      result: { outcome: 'skipped', reason: 'token_budget' } })
      return await today([], { chains: [activeChain] })()
    }
    render(Today)
    await fireEvent.click(await screen.findByRole('button', { name: '重新复查' }))
    expect(await screen.findByText('复查完成：跳过（超出 token 上限）')).toBeInTheDocument()
  })

  it('holding without chain shows note', async () => {
    respond = today([], { holdings: [holding({ has_chain: false }), holding({ ticker: 'AMD', has_chain: true })] })
    render(Today)
    await screen.findByText(/持仓止损/)
    const items = [...document.querySelectorAll('li')].map(li => li.textContent ?? '')
    expect(items.find(t => t.includes('NVDA'))).toContain('此持仓无 Agent 计划，不参与复查')
    expect(items.find(t => t.includes('AMD'))).not.toContain('此持仓无 Agent 计划')
  })

  it('holding whose agent plan was invalidated says so instead of the no-chain note', async () => {
    respond = today([], { holdings: [holding({ has_chain: true, chain_state: 'invalidated' }),
                                     holding({ ticker: 'AMD', has_chain: true, chain_state: 'holding' })] })
    render(Today)
    await screen.findByText(/持仓止损/)
    const items = [...document.querySelectorAll('li')].map(li => li.textContent ?? '')
    const nvda = items.find(t => t.includes('NVDA'))
    expect(nvda).toContain('Agent 计划已作废，不再复查')
    expect(nvda).not.toContain('此持仓无 Agent 计划')
    expect(items.find(t => t.includes('AMD'))).not.toContain('Agent 计划已作废')
  })

  it('hides review controls when migration 026 is missing', async () => {
    const chains = [{ ticker: 'AMD', signal_date: '2026-10-20', state: 'holding', mode: 'holding', basis: '持仓中',
                      version_no: 0, head_plan_id: 'hp', valid_until: '2026-10-27', pool: 'core',
                      latest_review: null, signals_today: [] }]
    respond = today([unit({ plan: plan() })], { timeline_ready: false, chains,
                                                holdings: [holding({ has_chain: false })] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(screen.queryByRole('region', { name: '进行中的 Agent 计划' })).toBeNull()
    expect(screen.queryByRole('button', { name: '重新复查' })).toBeNull()
    expect(screen.queryByText(/此持仓无 Agent 计划/)).toBeNull()
    expect(screen.getByText(FULL_RULE)).toBeInTheDocument()
  })
})


it('run overview is the first section', async () => {
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  const getRunOverview = vi.spyOn(api, 'getRunOverview').mockResolvedValue({
    session: '2026-10-22', ready: true, note: null, runs: [], selected_run_id: 'r1',
    headline: '定时运行 · 06:30 开始 · 用时 3 分 12 秒 · 8 个阶段：成功 8',
    stages: [{ id: 'collect', title: '数据采集', purpose: '', status: 'success', status_text: '成功', sentence: '采集 10/10 个目标',
               input_count: 10, output_count: 10, skips: [], failures: [], degradations: [], reason: null, reason_text: null,
               duration_ms: 1000, concepts: [] }],
  } as any)
  render(Today)
  await screen.findByRole('heading', { name: /NVDA/ })
  const overview = await screen.findByRole('region', { name: '运行一览' })
  expect(await within(overview).findByText('采集 10/10 个目标')).toBeInTheDocument()
  expect(getRunOverview).toHaveBeenCalledWith(undefined, undefined)
  // before 筛选, 市场环境 and the unit cards
  for (const name of ['筛选', '市场环境']) {
    const other = screen.getByRole('region', { name })
    expect(overview.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  }
  const card = screen.getByRole('heading', { name: /NVDA/ })
  expect(overview.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  // the overview does not depend on the batch view: today's request count is unchanged
  expect(calls.filter(c => c.url === '/api/workbench/today')).toHaveLength(1)
})
